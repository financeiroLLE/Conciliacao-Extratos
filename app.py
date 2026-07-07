"""App Streamlit — Conciliação Bancária Grupo LLE.

Layout: fundo azul institucional, sidebar amarela, cards executivos.
Fluxo: Upload → tela única de Resultado com cards, painel de bancos
e abas internas por status / subabas por tipo.
"""

from __future__ import annotations

import base64
import io
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.auditoria import (
    listar_execucoes,
    novo_id_execucao,
    registrar_execucao,
    salvar_snapshot,
)
from src.classificacao import TIPOS_PRINCIPAIS
from src.parsers import (
    carregar_extrato_banco,
    carregar_pendencias_anteriores,
    carregar_relatorio_sistema,
)
from src.parsers.adquirente import (
    carregar_extrato_adquirente,
    resumo_por_categoria,
)
from src.pipeline import ResultadoConciliacao, executar_pipeline
from src.reports import (
    gerar_csvs_zip,
    gerar_relatorio_excel,
    gerar_relatorio_excel_de_conta,
)


# ============================================================
# Identidade visual — Grupo LLE
# ============================================================
CORES = {
    "azul_escuro": "#041747",
    "azul_escuro_2": "#0A1F4D",
    "azul": "#0071FE",
    "amarelo": "#FAC318",
    "amarelo_2": "#E5AD0A",
    "verde": "#0F8C3B",
    "vermelho": "#D63031",
    "branco": "#FFFFFF",
    "texto_muted": "#A8B3CC",
    "card_bg": "#0E2456",
    "card_borda": "#1B3266",
}

ASSETS = Path(__file__).parent / "assets"


@st.cache_data
def _logo_data_uri() -> str:
    """Retorna a logo PNG (com fundo transparente) como data URI."""
    # Preferir a versão transparente; cair para a com fundo se a transparente não existir
    for nome in ("logo-grupo-lle-transparente.png", "logo-grupo-lle-branco.png"):
        arq = ASSETS / nome
        if arq.exists():
            b64 = base64.b64encode(arq.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    return ""


# ============================================================
# v5.35: Identificador da conta a partir do Sankhya
# ------------------------------------------------------------
# O match banco × Sankhya casa pela STRING exata do nome da conta. Para a
# usuária não precisar digitar (e errar espaço/underline/maiúscula), lemos os
# nomes de conta de dentro do próprio Sankhya e oferecemos numa lista — assim a
# string é sempre idêntica à que o matcher usa. A pré-seleção usa o nome do
# arquivo/banco só para já marcar o item certo; quem casa é o nome do Sankhya.
# ============================================================
_OPCAO_DIGITAR = "✏️  Digitar outro nome…"


def _norm_conta(s: str) -> str:
    """Normaliza nome de conta para comparar (espaço/underline/maiúscula iguais)."""
    s = str(s).lower().strip()
    s = re.sub(r"[_\-./]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


_STOP_CONTA = {
    "banco", "extrato", "mensal", "conta", "corrente", "cc", "c", "ag", "agencia",
    "do", "da", "de", "dos", "das", "e", "no", "na", "movimento", "conciliacao",
    "relatorio",
}


def _tokens_conta(s: str) -> set[str]:
    """Tokens distintivos de um nome de conta (sem palavras genéricas/números)."""
    return {
        t for t in _norm_conta(s).split()
        if t not in _STOP_CONTA and not t.isdigit() and len(t) >= 3
    }


def _melhor_match_conta(candidato: str, opcoes: list[str]) -> int | None:
    """Índice da conta do Sankhya que melhor casa com o nome do arquivo/banco.

    Retorna None quando não há um match claro (uma conta nova, p.ex.) — aí a UI
    pré-seleciona 'Digitar outro nome…'. Nunca chuta com ambiguidade.
    """
    nc = _norm_conta(candidato)
    if not nc:
        return None
    # 1) match exato (normalizado)
    for i, o in enumerate(opcoes):
        if _norm_conta(o) == nc:
            return i
    # 2) um contém o outro, e só uma conta bate
    contidos = [
        i for i, o in enumerate(opcoes)
        if nc in _norm_conta(o) or _norm_conta(o) in nc
    ]
    if len(contidos) == 1:
        return contidos[0]
    # 3) token distintivo (KING, INOV, PISA...) — casa quando uma conta tem o
    #    MAIOR overlap de tokens e esse máximo é único (sem empate = sem chute).
    tk = _tokens_conta(candidato)
    if tk:
        scores = sorted(
            ((len(_tokens_conta(o) & tk), i) for i, o in enumerate(opcoes)),
            reverse=True,
        )
        if scores and scores[0][0] > 0 and (len(scores) == 1 or scores[0][0] > scores[1][0]):
            return scores[0][1]
    return None


@st.cache_data(show_spinner=False)
def _contas_no_sankhya(payload: tuple, coluna_conta: str) -> list[str]:
    """Nomes de conta presentes no(s) relatório(s) do Sankhya.

    `payload` é uma tupla de (nome_arquivo, bytes) — hashável, então o resultado
    fica em cache e o Sankhya (que pode ter 69k linhas) só é lido uma vez por
    arquivo. As strings retornadas são IDÊNTICAS às que o pipeline usa na conta.
    """
    nomes: set[str] = set()
    for _nome_arq, conteudo in payload:
        try:
            # v5.39: sem o nome do arquivo, o leitor não sabe que é .xls e cai no
            # engine errado (openpyxl → BadZipFile), o except engolia e a lista de
            # contas voltava vazia — por isso o dropdown não aparecia pra .xls.
            bio = io.BytesIO(conteudo)
            bio.name = _nome_arq
            df = carregar_relatorio_sistema(
                bio, coluna_conta=coluna_conta or None
            )
            nomes.update(
                c for c in df["conta"].astype(str).unique() if c and c != "—"
            )
        except Exception:
            continue
    return sorted(nomes)


def _ler_contas_sankhya_da_sessao() -> list[str]:
    """Lê os nomes de conta do Sankhya já enviado (via session_state).

    A coluna 1 (banco) é renderizada ANTES da coluna 2 (Sankhya) no mesmo run,
    então pegamos o arquivo do Sankhya do run anterior pelo session_state.
    """
    arquivos = st.session_state.get("sistema") or []
    if arquivos and not isinstance(arquivos, list):
        arquivos = [arquivos]
    if not arquivos:
        return []
    coluna = st.session_state.get("coluna_conta_sistema", "") or ""
    try:
        payload = tuple((f.name, f.getvalue()) for f in arquivos)
    except Exception:
        return []
    return _contas_no_sankhya(payload, coluna)


@st.cache_data(show_spinner=False)
def _parse_adquirentes(payload: tuple) -> pd.DataFrame:
    """Lê todos os arquivos de adquirente (GetNet/PagBank) e junta num só df,
    no esquema comum de src.parsers.adquirente. payload = ((nome, bytes), ...)."""
    import io as _io

    from src.parsers.adquirente import COLUNAS_SAIDA

    frames = []
    _vistos = set()
    for nome, conteudo in payload:
        try:
            import hashlib as _hl

            _h = _hl.md5(conteudo).hexdigest()
            if _h in _vistos:
                continue  # v5.42: ignora arquivo idêntico subido em duplicata
            _vistos.add(_h)
            bio = _io.BytesIO(conteudo)
            bio.name = nome
            df = carregar_extrato_adquirente(bio)
            if df is not None and not df.empty:
                df = df.copy()
                df["arquivo"] = nome
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=COLUNAS_SAIDA + ["arquivo"])
    return pd.concat(frames, ignore_index=True)


def _adquirentes_da_sessao() -> pd.DataFrame:
    """DataFrame combinado dos extratos de adquirente enviados (ou vazio)."""
    from src.parsers.adquirente import COLUNAS_SAIDA

    arquivos = st.session_state.get("adquirente") or []
    if arquivos and not isinstance(arquivos, list):
        arquivos = [arquivos]
    if not arquivos:
        return pd.DataFrame(columns=COLUNAS_SAIDA + ["arquivo"])
    try:
        payload = tuple((f.name, f.getvalue()) for f in arquivos)
    except Exception:
        return pd.DataFrame(columns=COLUNAS_SAIDA + ["arquivo"])
    return _parse_adquirentes(payload)


def _relatorio_auditoria_da_sessao() -> tuple:
    """Monta o relatório da Auditoria de Cartões a partir dos extratos de
    adquirente JÁ enviados na conciliação (guardados em 'adquirente_bytes').

    Só o extrato CRU da GETNET tem venda + valor bruto + taxa aplicada, então
    é o único auditável por venda. PagBank é recebimento (não traz taxa por
    venda) e é ignorado aqui — informamos quais foram ignorados, sem inventar.
    Retorna (relatorio_df, nomes_ignorados).
    """
    import io as _io

    from src.cartao import eh_extrato_getnet_cru, carregar_extrato_getnet_cru

    itens = st.session_state.get("adquirente_bytes") or []
    frames, ignorados = [], []
    for nome, conteudo in itens:
        try:
            if eh_extrato_getnet_cru(_io.BytesIO(conteudo)):
                rel = carregar_extrato_getnet_cru(_io.BytesIO(conteudo))
                if rel is not None and not rel.empty:
                    frames.append(rel)
                else:
                    ignorados.append(nome)
            else:
                ignorados.append(nome)
        except Exception:
            ignorados.append(nome)
    relatorio = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return relatorio, ignorados


# ============================================================
# Configuração da página
# ============================================================
st.set_page_config(
    page_title="Conciliação Bancária · Grupo LLE",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Estado de sessão
# ============================================================
if "pagina" not in st.session_state:
    st.session_state.pagina = "Conciliação"
if "resultado" not in st.session_state:
    st.session_state.resultado = None
if "pendencias_anteriores" not in st.session_state:
    st.session_state.pendencias_anteriores = pd.DataFrame()
if "id_execucao_atual" not in st.session_state:
    st.session_state.id_execucao_atual = None
if "banco_conta_selecionada" not in st.session_state:
    st.session_state.banco_conta_selecionada = None
if "fluxo_etapa" not in st.session_state:
    st.session_state.fluxo_etapa = "upload"  # upload | resultado
if "subtab_conciliacao" not in st.session_state:
    st.session_state.subtab_conciliacao = "Todos"


def ir_para(pagina: str):
    st.session_state.pagina = pagina


def selecionar_banco(conta: str):
    st.session_state.banco_conta_selecionada = conta


def voltar_upload():
    st.session_state.fluxo_etapa = "upload"
    st.session_state.banco_conta_selecionada = None


# ============================================================
# CSS global
# ============================================================
LOGO_URI = _logo_data_uri()

st.html(
    f"""
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.19.0/dist/tabler-icons.min.css" rel="stylesheet">
<style>
/* ===== Tipografia e fundo ===== */
html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {{
    font-family: 'Montserrat', sans-serif !important;
}}
.stApp {{
    background: linear-gradient(180deg, {CORES["azul_escuro"]} 0%, #061B57 100%) !important;
    color: {CORES["branco"]};
}}

/* ===== v3: ESCONDER faixa branca do topo do Streamlit =====
   v5.8: mantemos o header vis\u00edvel (mas transparente) porque \u00e9 onde fica
   o bot\u00e3o de reabrir sidebar. Com 'display: none' o bot\u00e3o sumia. */
header[data-testid="stHeader"] {{
    background-color: transparent !important;
}}
[data-testid="stToolbar"] {{
    background-color: transparent !important;
}}
#MainMenu {{ visibility: hidden; }}
.stDeployButton,
.stAppDeployButton,
[data-testid="stDeployButton"],
[data-testid="stAppDeployButton"],
[data-testid="stToolbarActions"],
[data-testid="stStatusWidget"] {{
    display: none !important;
    visibility: hidden !important;
}}
footer {{ visibility: hidden; }}

.block-container {{
    padding-top: 0.8rem !important;
    padding-bottom: 4rem;
    max-width: 1500px;
}}
h1, h2, h3, h4, h5, h6, p, span, div, label {{ color: {CORES["branco"]}; }}

/* ===== Sidebar AMARELA — v3 com bordas arredondadas e tom uniforme ===== */
[data-testid="stSidebar"] {{
    background-color: {CORES["amarelo"]} !important;
    border-right: none;
}}
[data-testid="stSidebar"] * {{ color: {CORES["azul_escuro"]} !important; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(4,23,71,0.18) !important; }}

/* Logo: bloco azul com bordas inferiores arredondadas e transição suave */
.lle-sidebar-logo {{
    background: linear-gradient(180deg, {CORES["azul_escuro"]} 0%, #061B57 100%);
    padding: 24px 14px 22px 14px;
    margin: 8px 4px 22px 4px;
    border-radius: 18px;
    text-align: center;
    box-shadow: 0 6px 18px rgba(4,23,71,0.22);
}}
.lle-sidebar-logo img {{
    height: 78px;
    width: auto;
    display: inline-block;
}}
.lle-sidebar-tagline {{
    text-align: center;
    color: {CORES["amarelo"]} !important;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    margin-top: 10px;
}}

/* v5.8: bot\u00e3o de reabrir sidebar quando ela est\u00e1 fechada.
   Por padr\u00e3o o Streamlit deixa quase invis\u00edvel no canto. */
[data-testid="stExpandSidebarButton"] {{
    background-color: {CORES["amarelo"]} !important;
    border-radius: 8px !important;
    padding: 6px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.35) !important;
    transition: all 0.18s ease !important;
}}
[data-testid="stExpandSidebarButton"]:hover {{
    box-shadow: 0 4px 12px rgba(0,0,0,0.5) !important;
    transform: scale(1.05);
    background-color: {CORES["amarelo"]} !important;
}}
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stExpandSidebarButton"] *,
[data-testid="stExpandSidebarButton"] button {{
    color: {CORES["azul_escuro"]} !important;
    fill: {CORES["azul_escuro"]} !important;
}}

/* Sidebar buttons — TODOS com mesmo tom, ícones verdes ao lado */
[data-testid="stSidebar"] .stButton > button {{
    background-color: rgba(4,23,71,0.06) !important;
    color: {CORES["azul_escuro"]} !important;
    border: 1px solid rgba(4,23,71,0.22) !important;
    border-radius: 10px !important;
    padding: 12px 16px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    text-align: left !important;
    width: 100% !important;
    transition: all 0.18s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background-color: {CORES["azul_escuro"]} !important;
    color: {CORES["amarelo"]} !important;
    border-color: {CORES["azul_escuro"]} !important;
    transform: translateX(2px);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background-color: rgba(4,23,71,0.92) !important;
    border-color: {CORES["azul_escuro"]} !important;
}}
/* Texto do botão ativo amarelo */
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[kind="primary"] * {{
    color: {CORES["amarelo"]} !important;
}}

/* v5.7: força texto amarelo no bot\u00e3o ativo da sidebar com especificidade alta.
   Sem isso, a regra geral '[kind="primary"] *' (texto azul) sobrescrevia,
   ficando azul sobre azul (invis\u00edvel). */
[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
[data-testid="stSidebar"] .stButton > button[kind="primary"] div,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] span,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] div,
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{
    color: {CORES["amarelo"]} !important;
    -webkit-text-fill-color: {CORES["amarelo"]} !important;
}}

/* ===== Header escuro com logo ===== */
.lle-header {{
    background: linear-gradient(135deg, {CORES["azul_escuro"]} 0%, {CORES["azul_escuro_2"]} 100%);
    border-radius: 16px;
    padding: 22px 30px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 24px;
    border: 1px solid {CORES["card_borda"]};
}}
.lle-header img {{ height: 56px; width: auto; }}
.lle-header .lle-title {{
    font-size: 26px;
    font-weight: 800;
    color: {CORES["branco"]};
    line-height: 1.1;
    margin: 0;
    letter-spacing: -0.5px;
}}
.lle-header .lle-subtitle {{
    font-size: 13px;
    color: {CORES["amarelo"]};
    margin-top: 4px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}

/* ===== Cards executivos ===== */
.lle-kpi-row {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
    margin-bottom: 18px;
}}
.lle-kpi {{
    background: linear-gradient(145deg, {CORES["card_bg"]} 0%, #0B1E48 100%);
    border: 1px solid {CORES["card_borda"]};
    border-radius: 16px;
    padding: 20px 22px;
    position: relative;
    overflow: hidden;
    transition: all 0.22s ease;
    box-shadow: 0 4px 14px rgba(0,0,0,0.18);
}}
.lle-kpi:hover {{
    border-color: {CORES["amarelo"]};
    transform: translateY(-2px);
    box-shadow: 0 8px 22px rgba(0,0,0,0.28);
}}
.lle-kpi::before {{
    content: "";
    position: absolute;
    top: 0; left: 0;
    width: 4px; height: 100%;
    background: linear-gradient(180deg, {CORES["amarelo"]} 0%, {CORES["amarelo_2"]} 100%);
}}
.lle-kpi-label {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.2px;
    text-transform: uppercase;
    color: {CORES["texto_muted"]} !important;
    margin-bottom: 8px;
}}
.lle-kpi-value {{
    font-size: 26px;
    font-weight: 800;
    color: {CORES["branco"]} !important;
    line-height: 1.1;
}}
.lle-kpi-value.destaque-amarelo {{ color: {CORES["amarelo"]} !important; }}
.lle-kpi-value.destaque-verde {{ color: {CORES["verde"]} !important; }}
.lle-kpi-value.destaque-vermelho {{ color: {CORES["vermelho"]} !important; }}
.lle-kpi-suffix {{
    font-size: 12px;
    font-weight: 500;
    color: {CORES["texto_muted"]} !important;
    margin-top: 4px;
}}

/* v3: sub-stack para Falta Conciliar (vertical) e Investimentos */
.lle-kpi-sub-stack {{
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
}}
.lle-kpi-sub-label {{
    font-size: 11px;
    font-weight: 600;
    color: {CORES["branco"]} !important;
    letter-spacing: 0.2px;
    margin-top: 4px;
}}
.lle-kpi-sub-valor {{
    font-size: 14px;
    font-weight: 700;
    color: {CORES["branco"]} !important;
    line-height: 1.2;
}}
.lle-kpi-sub-valor.vermelho {{ color: {CORES["vermelho"]} !important; }}
.lle-kpi-sub-valor.verde {{ color: {CORES["verde"]} !important; }}

/* ===== Painel de bancos (botões) ===== */
.lle-banco-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 12px;
}}
.stButton > button.lle-banco-btn {{
    background-color: {CORES["azul_escuro_2"]};
    color: {CORES["branco"]};
    border: 2px solid {CORES["card_borda"]};
    border-radius: 12px;
    padding: 18px 16px;
    font-weight: 700;
    font-size: 14px;
    width: 100%;
    text-align: left;
    transition: all 0.18s ease;
}}

/* Botões primários e gerais — cobre stButton E stDownloadButton */
.stButton > button,
[data-testid="stDownloadButton"] > button,
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-primary"] {{
    background-color: {CORES["azul"]} !important;
    color: {CORES["branco"]} !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    padding: 8px 14px !important;
    min-height: 38px !important;
    font-size: 13.5px !important;
    transition: all 0.18s ease !important;
    box-shadow: 0 2px 6px rgba(0,0,0,0.18) !important;
}}
.stButton > button *,
[data-testid="stDownloadButton"] > button *,
[data-testid="stBaseButton-secondary"] *,
[data-testid="stBaseButton-primary"] * {{
    color: {CORES["branco"]} !important;
}}
.stButton > button:hover,
[data-testid="stDownloadButton"] > button:hover {{
    background-color: {CORES["amarelo"]} !important;
    box-shadow: 0 4px 10px rgba(0,0,0,0.24) !important;
}}
.stButton > button:hover *,
[data-testid="stDownloadButton"] > button:hover * {{
    color: {CORES["azul_escuro"]} !important;
}}
/* Primary = amarelo institucional com texto azul escuro */
.stButton > button[kind="primary"],
[data-testid="stDownloadButton"] > button[kind="primary"],
[data-testid="stBaseButton-primary"] {{
    background-color: {CORES["amarelo"]} !important;
}}
.stButton > button[kind="primary"] *,
[data-testid="stDownloadButton"] > button[kind="primary"] *,
[data-testid="stBaseButton-primary"] * {{
    color: {CORES["azul_escuro"]} !important;
}}
/* Primary HOVER = AZUL com texto branco (item 17) */
.stButton > button[kind="primary"]:hover,
[data-testid="stDownloadButton"] > button[kind="primary"]:hover {{
    background-color: {CORES["azul"]} !important;
}}
.stButton > button[kind="primary"]:hover *,
[data-testid="stDownloadButton"] > button[kind="primary"]:hover * {{
    color: {CORES["branco"]} !important;
}}

/* ===== Inputs e file uploader ===== */
input, textarea, select, [data-baseweb="select"] > div {{
    background-color: {CORES["azul_escuro_2"]} !important;
    color: {CORES["branco"]} !important;
    border-color: {CORES["card_borda"]} !important;
}}
/* v5.35: menu ABERTO do selectbox (popover do BaseWeb). Antes herdava o texto
   branco do tema, mas o popover tem fundo claro → texto branco-no-branco,
   invisível. Força fundo escuro + texto branco, com destaque no hover/selecionado.
   Corrige também o antigo submenu de Tipo (mesmo problema). */
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [data-baseweb="menu"],
[data-baseweb="popover"] ul {{
    background-color: {CORES["azul_escuro_2"]} !important;
}}
[data-baseweb="popover"] [role="option"],
[data-baseweb="popover"] li {{
    background-color: {CORES["azul_escuro_2"]} !important;
    color: {CORES["branco"]} !important;
}}
[data-baseweb="popover"] [role="option"] * {{
    color: {CORES["branco"]} !important;
}}
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [role="option"][aria-selected="true"] {{
    background-color: {CORES["card_bg"]} !important;
    color: {CORES["amarelo"]} !important;
}}
[data-baseweb="popover"] [role="option"]:hover *,
[data-baseweb="popover"] [role="option"][aria-selected="true"] * {{
    color: {CORES["amarelo"]} !important;
}}
.stTextInput input, .stDateInput input {{
    background-color: {CORES["azul_escuro_2"]} !important;
    color: {CORES["branco"]} !important;
    border: 1px solid {CORES["card_borda"]} !important;
}}
[data-testid="stFileUploaderDropzone"] {{
    background-color: {CORES["azul_escuro_2"]} !important;
    border: 2px dashed {CORES["card_borda"]} !important;
}}
[data-testid="stFileUploaderDropzone"]:hover {{
    border-color: {CORES["amarelo"]} !important;
}}
/* v5.37: ANTES pintava TUDO de branco (inclusive o nome do arquivo, que fica
   numa caixa branca → sumia). Agora só as INSTRUÇÕES ("arraste", "200MB") ficam
   brancas; o nome do arquivo mantém a cor escura padrão e aparece na caixa. */
[data-testid="stFileUploaderDropzoneInstructions"],
[data-testid="stFileUploaderDropzoneInstructions"] * {{ color: {CORES["branco"]} !important; }}

/* v5.37/v5.38: menu da coluna do st.dataframe (Sort/filtro) e menus em geral —
   vinham claro-no-claro (texto branco em fundo branco). Cobre vários tipos. */
[data-testid="stDataFrameColumnMenu"],
[data-baseweb="menu"],
[data-baseweb="popover"] [role="menu"],
[role="menu"] {{
    background-color: {CORES["azul_escuro_2"]} !important;
    border: 1px solid {CORES["card_borda"]} !important;
}}
[data-testid="stDataFrameColumnMenu"] *,
[data-baseweb="menu"] *,
[data-baseweb="menu"] [role="option"],
[role="menu"] *,
[role="menuitem"],
[role="menuitem"] * {{
    color: {CORES["branco"]} !important;
}}
[data-testid="stDataFrameColumnMenu"] input,
[data-baseweb="menu"] input,
[role="menu"] input {{
    color: {CORES["branco"]} !important;
    background-color: {CORES["azul_escuro_2"]} !important;
    border: 1px solid {CORES["card_borda"]} !important;
}}

/* v3.4: tooltip do help (?) — texto PRETO em qualquer lugar (sidebar amarela ou main) */
[data-testid="stTooltipContent"],
[data-testid="stTooltipContent"] *,
[role="tooltip"],
[role="tooltip"] * {{
    color: {CORES["azul_escuro"]} !important;
    background-color: #FFFFFF !important;
}}
[data-testid="stTooltipContent"] {{
    border: 1px solid {CORES["azul_escuro"]} !important;
    border-radius: 8px !important;
}}

/* v5.6: o input do number_input estava com texto invisível na sidebar (texto
   escuro sobre fundo escuro). Força cor branca com seletores específicos. */
[data-testid="stNumberInput"] input,
[data-testid="stNumberInputContainer"] input,
input[type="number"] {{
    background-color: {CORES["azul_escuro_2"]} !important;
    color: {CORES["branco"]} !important;
    -webkit-text-fill-color: {CORES["branco"]} !important;
}}

/* v5.6: checkbox da sidebar — o "check" estava invisível */
[data-testid="stCheckbox"] svg {{
    color: {CORES["branco"]} !important;
    fill: {CORES["branco"]} !important;
}}

/* v3.4: botões + / - do number_input — texto BRANCO sobre fundo azul.
   No sidebar amarela, esses botões herdavam azul-escuro do '*' geral. */
[data-testid="stNumberInputContainer"] button,
[data-testid="stNumberInput"] button {{
    background-color: {CORES["azul"]} !important;
    color: {CORES["branco"]} !important;
    border-color: {CORES["azul"]} !important;
}}
[data-testid="stNumberInputContainer"] button *,
[data-testid="stNumberInput"] button *,
[data-testid="stNumberInputContainer"] button svg,
[data-testid="stNumberInput"] button svg {{
    color: {CORES["branco"]} !important;
    fill: {CORES["branco"]} !important;
}}
[data-testid="stNumberInputContainer"] button:hover,
[data-testid="stNumberInput"] button:hover {{
    background-color: {CORES["azul_escuro"]} !important;
}}

/* Radio horizontal */
[role="radiogroup"] label {{ color: {CORES["branco"]} !important; }}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    background-color: {CORES["azul_escuro_2"]};
    padding: 6px;
    border-radius: 12px;
    border: 1px solid {CORES["card_borda"]};
}}
.stTabs [data-baseweb="tab"] {{
    font-weight: 600;
    color: {CORES["texto_muted"]} !important;
    background-color: transparent;
    border-radius: 8px;
    padding: 8px 16px;
}}
.stTabs [aria-selected="true"] {{
    color: {CORES["azul_escuro"]} !important;
    background-color: {CORES["amarelo"]} !important;
}}

/* Dataframes */
[data-testid="stDataFrame"] {{
    background-color: {CORES["card_bg"]};
    border: 1px solid {CORES["card_borda"]};
    border-radius: 10px;
    padding: 4px;
}}

/* Alerts */
.stAlert {{ background-color: {CORES["azul_escuro_2"]} !important; border: 1px solid {CORES["card_borda"]}; }}
.stAlert * {{ color: {CORES["branco"]} !important; }}

/* Divider */
hr {{ border-color: {CORES["card_borda"]} !important; }}

/* Expander */
.streamlit-expanderHeader {{
    background-color: {CORES["azul_escuro_2"]} !important;
    color: {CORES["branco"]} !important;
    border: 1px solid {CORES["card_borda"]} !important;
}}

/* Caption */
.stCaption, [data-testid="stCaptionContainer"] {{ color: {CORES["texto_muted"]} !important; }}

/* Subheader chips */
.lle-section-title {{
    display: inline-block;
    background-color: {CORES["amarelo"]};
    color: {CORES["azul_escuro"]} !important;
    padding: 6px 14px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 14px;
}}

/* Footer */
.lle-footer {{
    margin-top: 56px;
    padding: 18px 24px;
    text-align: center;
    font-size: 12px;
    color: {CORES["texto_muted"]} !important;
    border-top: 1px solid {CORES["card_borda"]};
}}
.lle-footer a {{ color: {CORES["amarelo"]} !important; text-decoration: none; }}

/* Tabela de detalhamento — cabeçalho mais legível */
table {{ color: {CORES["branco"]}; }}

/* Status badges */
.lle-badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}
.lle-badge.verde {{ background: {CORES["verde"]}; color: {CORES["branco"]}; }}
.lle-badge.amarelo {{ background: {CORES["amarelo"]}; color: {CORES["azul_escuro"]}; }}
.lle-badge.vermelho {{ background: {CORES["vermelho"]}; color: {CORES["branco"]}; }}
.lle-badge.azul {{ background: {CORES["azul"]}; color: {CORES["branco"]}; }}

/* ============================================================
   v5.12 — Estilo EDITORIAL (Fase 1: Resumo Executivo)
   Componentes novos com prefixo .editorial-*. Convivem com o CSS antigo.
   Princípios: tipografia leve (300/400/500), sem cards, divisores finos,
   cor cirúrgica.
   ============================================================ */

/* Header do resumo (kicker + título + data) */
.editorial-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
}}
.editorial-kicker {{
    color: {CORES["amarelo"]};
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 3px;
    text-transform: uppercase;
}}
.editorial-title {{
    color: {CORES["branco"]};
    font-size: 22px;
    font-weight: 300;
    margin-top: 6px;
    letter-spacing: -0.3px;
}}
.editorial-meta {{
    color: #6B88B5;
    font-size: 11px;
    font-weight: 400;
    letter-spacing: 0.5px;
    text-align: right;
}}
.editorial-meta + .editorial-meta {{ margin-top: 2px; }}

/* Divisor temático com fade dourado */
.editorial-divisor-fade {{
    height: 1px;
    background: linear-gradient(90deg,
        rgba(250,195,24,0.4) 0%,
        rgba(250,195,24,0.05) 40%,
        transparent 100%);
    margin: 20px 0 36px;
}}

/* Bloco do KPI âncora (% + valor) */
.editorial-destaque-row {{
    display: flex;
    align-items: flex-end;
    gap: 28px;
    margin-bottom: 8px;
}}
.editorial-destaque-col {{ flex: 1; }}
.editorial-destaque-col.bigger {{
    flex: 1.4;
    padding-left: 28px;
    border-left: 1px solid rgba(255,255,255,0.08);
}}
.editorial-label {{
    color: #6B88B5;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2.5px;
    text-transform: uppercase;
}}
.editorial-valor-hero {{
    color: {CORES["branco"]};
    font-size: 52px;
    font-weight: 300;
    letter-spacing: -1.5px;
    line-height: 1;
    margin-top: 10px;
}}
.editorial-valor-hero .unit {{
    color: #6B88B5;
    font-size: 28px;
    font-weight: 300;
}}
.editorial-valor-grande {{
    color: {CORES["branco"]};
    font-size: 38px;
    font-weight: 300;
    letter-spacing: -1px;
    margin-top: 10px;
    line-height: 1;
}}
.editorial-valor-grande .destaque {{ font-weight: 400; }}
.editorial-valor-grande .centavos {{ color: #6B88B5; }}
.editorial-sub-text {{
    color: #6B88B5;
    font-size: 12px;
    margin-top: 8px;
}}
.editorial-status-pill {{
    font-size: 12px;
    font-weight: 500;
    padding-bottom: 6px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}}
.editorial-status-pill.verde {{ color: #7DD87D; }}
.editorial-status-pill.amarelo {{ color: {CORES["amarelo"]}; }}
.editorial-status-pill.vermelho {{ color: #FF8A8A; }}

/* Barra de progresso editorial */
.editorial-progresso-wrap {{ margin: 36px 0; }}
.editorial-progresso-track {{
    height: 6px;
    background: rgba(255,255,255,0.04);
    border-radius: 3px;
    position: relative;
    overflow: hidden;
}}
.editorial-progresso-fill {{
    position: absolute;
    left: 0;
    top: 0;
    height: 100%;
    background: linear-gradient(90deg, {CORES["amarelo"]} 0%, {CORES["amarelo_2"]} 100%);
    border-radius: 3px;
}}
.editorial-progresso-legend {{
    display: flex;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 10px;
    color: #6B88B5;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}

/* Linha de métricas em colunas com divisor */
.editorial-cols {{
    display: grid;
    grid-template-columns: repeat(var(--cols, 4), 1fr);
    gap: 0;
    margin: 48px 0 36px;
}}
.editorial-cols .col {{
    padding: 0 20px;
    border-right: 1px solid rgba(255,255,255,0.08);
}}
.editorial-cols .col:first-child {{ padding-left: 0; }}
.editorial-cols .col:last-child {{
    padding-right: 0;
    border-right: none;
}}
.editorial-cols .label {{
    color: #6B88B5;
    font-size: 9px;
    font-weight: 500;
    letter-spacing: 2px;
    text-transform: uppercase;
}}
.editorial-cols .valor {{
    color: {CORES["branco"]};
    font-size: 24px;
    font-weight: 300;
    margin-top: 8px;
    letter-spacing: -0.5px;
}}
.editorial-cols .valor.verde {{ color: #7DD87D; }}
.editorial-cols .valor.amarelo {{ color: {CORES["amarelo"]}; }}
.editorial-cols .valor.vermelho {{ color: #FF8A8A; }}
.editorial-cols .valor.atencao {{ color: #FFD6A0; }}
.editorial-cols .valor .centavos {{ color: #6B88B5; font-size: 14px; }}
.editorial-cols .sub {{
    color: #6B88B5;
    font-size: 10px;
    margin-top: 10px;
}}
.editorial-cols .sub .verde {{ color: #7DD87D; }}
.editorial-cols .sub .vermelho {{ color: #FF8A8A; }}
.editorial-cols .sub .inline {{ margin-right: 10px; }}

/* Faixa horizontal de contagens (entre divisores horizontais) */
.editorial-faixa {{
    display: flex;
    align-items: center;
    gap: 20px;
    padding: 18px 0;
    border-top: 1px solid rgba(255,255,255,0.06);
    border-bottom: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 36px;
}}
.editorial-faixa .item {{
    flex: 1;
    text-align: center;
}}
.editorial-faixa .item .valor {{
    color: {CORES["branco"]};
    font-size: 18px;
    font-weight: 300;
}}
.editorial-faixa .item .valor.verde {{ color: #7DD87D; }}
.editorial-faixa .item .valor.amarelo {{ color: {CORES["amarelo"]}; }}
.editorial-faixa .item .label {{
    color: #6B88B5;
    font-size: 9px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-top: 2px;
}}
.editorial-faixa .sep {{
    width: 1px;
    height: 24px;
    background: rgba(255,255,255,0.08);
}}

/* Cabeçalho de seção editorial (com linha que se esvai) */
.editorial-secao-head {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 18px;
}}
.editorial-secao-head .titulo {{
    color: {CORES["amarelo"]};
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 2.5px;
    text-transform: uppercase;
}}
.editorial-secao-head .linha {{
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(250,195,24,0.2) 0%, transparent 100%);
}}
.editorial-secao-head .contagem {{
    color: #6B88B5;
    font-size: 10px;
}}

/* Lista de exceções (sem cards) */
.editorial-lista {{
    display: flex;
    flex-direction: column;
    gap: 14px;
}}
.editorial-lista-item {{
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 6px 0;
}}
.editorial-lista-item.muted {{ opacity: 0.5; }}
.editorial-lista-divisor {{
    height: 1px;
    background: rgba(255,255,255,0.04);
}}
.editorial-lista-icone {{
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: 1px solid rgba(107,136,181,0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: #6B88B5;
}}
.editorial-lista-icone.verde {{
    border-color: rgba(125,216,125,0.3);
    color: #7DD87D;
}}
.editorial-lista-icone.amarelo {{
    border-color: rgba(250,195,24,0.3);
    color: {CORES["amarelo"]};
}}
.editorial-lista-corpo {{ flex: 1; }}
.editorial-lista-titulo {{
    color: {CORES["branco"]};
    font-size: 13px;
    font-weight: 400;
}}
.editorial-lista-titulo .light {{ color: #6B88B5; font-weight: 300; }}
.editorial-lista-sub {{
    color: #6B88B5;
    font-size: 11px;
    margin-top: 2px;
}}
.editorial-lista-direita {{ text-align: right; }}
.editorial-lista-valor {{
    color: {CORES["branco"]};
    font-size: 15px;
    font-weight: 300;
}}
.editorial-lista-valor.muted {{ color: #6B88B5; }}
.editorial-lista-status {{
    font-size: 9px;
    font-weight: 500;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-top: 2px;
}}
.editorial-lista-status.verde {{ color: #7DD87D; }}
.editorial-lista-status.amarelo {{ color: {CORES["amarelo"]}; }}

/* ============================================================
   v5.13 — Estilo OPÇÃO A (cards generosos)
   Cards modernos com hierarquia visual, gradientes sutis,
   bordas superiores semânticas, donut SVG pro %.
   ============================================================ */

/* Grid principal: 3 colunas com proporção 1.4 / 1 / 1 (card âncora maior) */
.opa-grid-hero {{
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr;
    gap: 16px;
    margin-bottom: 16px;
}}
.opa-grid-secundario {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
}}
@media (max-width: 900px) {{
    .opa-grid-hero, .opa-grid-secundario {{
        grid-template-columns: 1fr;
    }}
}}

/* Card âncora (gradiente + glow sutil no canto) */
.opa-card-ancora {{
    background: linear-gradient(135deg, #16335F 0%, #0F2548 100%);
    padding: 24px 22px;
    border-radius: 18px;
    position: relative;
    overflow: hidden;
}}
.opa-card-ancora::before {{
    content: "";
    position: absolute;
    top: 0;
    right: 0;
    width: 140px;
    height: 140px;
    background: radial-gradient(circle, rgba(250,195,24,0.08) 0%, transparent 70%);
    pointer-events: none;
}}
.opa-card-ancora-label {{
    color: #8BA3C7;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}
.opa-card-ancora-valor {{
    color: {CORES["branco"]};
    font-size: 30px;
    font-weight: 500;
    margin-top: 14px;
    letter-spacing: -0.5px;
}}
.opa-rec-desp-row {{
    display: flex;
    gap: 28px;
    margin-top: 18px;
    padding-top: 14px;
    border-top: 1px solid rgba(255,255,255,0.08);
}}
.opa-rec-desp-item .marker {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 500;
}}
.opa-rec-desp-item .marker.verde {{ color: #7DD87D; }}
.opa-rec-desp-item .marker.vermelho {{ color: #FF8A8A; }}
.opa-rec-desp-item .marker .dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
}}
.opa-rec-desp-item .marker.verde .dot {{ background: #7DD87D; }}
.opa-rec-desp-item .marker.vermelho .dot {{ background: #FF8A8A; }}
.opa-rec-desp-item .valor {{
    color: {CORES["branco"]};
    font-size: 15px;
    font-weight: 500;
    margin-top: 4px;
}}

/* Card verde translúcido (Conciliado) */
.opa-card-conciliado {{
    background: linear-gradient(135deg, rgba(125,216,125,0.12) 0%, rgba(125,216,125,0.04) 100%);
    padding: 24px 22px;
    border-radius: 18px;
    border: 1px solid rgba(125,216,125,0.18);
}}
.opa-card-conciliado-label {{
    color: #A8D8A8;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}
.opa-card-conciliado-valor {{
    color: #7DD87D;
    font-size: 30px;
    font-weight: 500;
    margin-top: 14px;
    letter-spacing: -0.5px;
}}
.opa-card-conciliado-sub {{
    color: #8BA3C7;
    font-size: 12px;
    margin-top: 14px;
    padding-top: 14px;
    border-top: 1px solid rgba(255,255,255,0.06);
}}
.opa-card-conciliado-sub i {{
    color: #7DD87D;
    vertical-align: -2px;
    margin-right: 4px;
}}

/* Card donut (percentual) */
.opa-card-donut {{
    background: #0F2548;
    padding: 24px 22px;
    border-radius: 18px;
    border: 1px solid rgba(250,195,24,0.2);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
    min-height: 160px;
}}
.opa-card-donut svg {{
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
}}
.opa-card-donut-text {{
    position: relative;
    z-index: 1;
    text-align: center;
}}
.opa-card-donut-pct {{
    color: {CORES["amarelo"]};
    font-size: 30px;
    font-weight: 500;
    letter-spacing: -0.5px;
}}
.opa-card-donut-label {{
    color: #8BA3C7;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    margin-top: 2px;
}}

/* Cards secundários (Falta, Divergência, Contas) */
.opa-card-secundario {{
    background: #0F2548;
    padding: 18px 20px;
    border-radius: 14px;
    border-top: 2px solid #888;
}}
.opa-card-secundario.vermelho {{ border-top-color: #FF6B6B; }}
.opa-card-secundario.amarelo {{ border-top-color: {CORES["amarelo"]}; }}
.opa-card-secundario.verde {{ border-top-color: #7DD87D; }}

.opa-card-sec-head {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}}
.opa-card-sec-label {{
    color: #8BA3C7;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}}
.opa-card-sec-valor {{
    color: {CORES["branco"]};
    font-size: 24px;
    font-weight: 500;
    margin-top: 8px;
    letter-spacing: -0.3px;
}}
.opa-card-sec-valor.vermelho {{ color: #FF8A8A; }}
.opa-card-sec-valor.amarelo {{ color: {CORES["amarelo"]}; }}
.opa-card-sec-valor.verde {{ color: #7DD87D; }}

.opa-card-sec-icon {{
    padding: 6px;
    border-radius: 8px;
}}
.opa-card-sec-icon.vermelho {{ background: rgba(255,107,107,0.12); color: #FF8A8A; }}
.opa-card-sec-icon.amarelo {{ background: rgba(250,195,24,0.12); color: {CORES["amarelo"]}; }}
.opa-card-sec-icon.verde {{ background: rgba(125,216,125,0.12); color: #7DD87D; }}
.opa-card-sec-icon i {{ font-size: 14px; }}

.opa-card-sec-sub {{
    font-size: 11px;
    color: #8BA3C7;
    margin-top: 14px;
}}
.opa-card-sec-sub .label {{ color: #8BA3C7; }}
.opa-card-sec-sub .verde-text {{ color: #7DD87D; }}
.opa-card-sec-sub .vermelho-text {{ color: #FF8A8A; }}
.opa-card-sec-sub .item {{ display: inline-block; margin-right: 14px; }}

/* Seção Exceções (chips horizontais leves) */
.opa-excecoes-head {{
    display: flex;
    gap: 10px;
    align-items: center;
    margin: 28px 0 14px;
    padding-top: 20px;
    border-top: 1px dashed rgba(255,255,255,0.08);
}}
.opa-excecoes-head-label {{
    color: #8BA3C7;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.8px;
    text-transform: uppercase;
}}
.opa-excecoes-head-line {{
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.06);
}}

.opa-excecoes-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
}}

.opa-chip {{
    display: flex;
    gap: 12px;
    align-items: center;
    padding: 12px 14px;
    border-radius: 12px;
    background: rgba(139,163,199,0.06);
}}
.opa-chip.verde {{ background: rgba(125,216,125,0.06); }}
.opa-chip.amarelo {{ background: rgba(250,195,24,0.06); }}
.opa-chip-icon {{
    width: 34px;
    height: 34px;
    border-radius: 50%;
    background: rgba(139,163,199,0.15);
    color: #8BA3C7;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}}
.opa-chip-icon.verde {{ background: rgba(125,216,125,0.15); color: #7DD87D; }}
.opa-chip-icon.amarelo {{ background: rgba(250,195,24,0.15); color: {CORES["amarelo"]}; }}
.opa-chip-icon i {{ font-size: 16px; }}
.opa-chip-label {{
    color: #8BA3C7;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}}
.opa-chip-valor {{
    color: {CORES["branco"]};
    font-size: 16px;
    font-weight: 500;
    margin-top: 2px;
}}
.opa-chip-valor .light {{
    color: #8BA3C7;
    font-size: 11px;
    font-weight: 400;
}}

</style>
"""
)


# ============================================================
# Sidebar — navegação
# ============================================================
with st.sidebar:
    if LOGO_URI:
        st.html(
            f"""
            <div class="lle-sidebar-logo">
                <img src="{LOGO_URI}" alt="Grupo LLE" />
                <div class="lle-sidebar-tagline">CONCILIAÇÃO BANCÁRIA</div>
            </div>
            """
        )

    # Páginas principais (lista simples)
    paginas_top = [
        ("📊 Dashboard", "Dashboard"),
        ("✅ Conciliação", "Conciliação"),
    ]
    for label, key in paginas_top:
        is_atual = st.session_state.pagina == key
        st.button(
            label,
            key=f"nav_{key}",
            on_click=ir_para,
            args=(key,),
            type="primary" if is_atual else "secondary",
            use_container_width=True,
        )

    # v5.4: Conta 70 logo após Conciliação (antes do CARTÃO)
    conta70_atual = st.session_state.pagina == "Conta 70"
    st.button(
        "📒 Conta 70",
        key="nav_Conta 70",
        on_click=ir_para,
        args=("Conta 70",),
        type="primary" if conta70_atual else "secondary",
        use_container_width=True,
    )

    # v5.5: Auditoria volta pra dentro do submenu CARTÃO
    cartao_atual = st.session_state.pagina in ("Cadastro de Taxas", "Auditoria de Taxas")
    with st.expander("💳 CARTÃO", expanded=cartao_atual):
        submenus_cartao = [
            ("🏦 Cadastro de Taxas", "Cadastro de Taxas"),
            ("💳 Auditoria de Cartões", "Auditoria de Taxas"),
        ]
        for label, key in submenus_cartao:
            is_atual = st.session_state.pagina == key
            st.button(
                label,
                key=f"nav_{key}",
                on_click=ir_para,
                args=(key,),
                type="primary" if is_atual else "secondary",
                use_container_width=True,
            )

    # Restante das páginas principais
    paginas_bot = [
        ("📂 Histórico", "Histórico"),
        ("🟢 Sobre", "Sobre"),
    ]
    for label, key in paginas_bot:
        is_atual = st.session_state.pagina == key
        st.button(
            label,
            key=f"nav_{key}",
            on_click=ir_para,
            args=(key,),
            type="primary" if is_atual else "secondary",
            use_container_width=True,
        )

    st.divider()

    with st.expander("⚙️ Configurações"):
        rodar_fuzzy = st.checkbox(
            "Gerar sugestões fuzzy",
            value=True,
            help="Aba complementar de revisão manual. Não entra na conciliação automática.",
        )
        tolerancia = st.number_input(
            "Tolerância de data (dias)",
            min_value=0, max_value=10, value=2, step=1,
            help="Aceita diferença de até N dias entre o lançamento no banco e no sistema (fim de semana / feriado).",
        )


# ============================================================
# Header (sempre presente)
# ============================================================
PAGE_INFO = {
    "Dashboard": ("Dashboard", "Visão executiva da última conciliação"),
    "Conciliação": ("Conciliação", "Upload, processamento e detalhamento"),
    "Cadastro de Taxas": ("Cadastro de Taxas", "Contratos com adquirentes de cartão"),
    "Auditoria de Taxas": ("Auditoria de Cartões", "Comparação entre taxa contratada e aplicada"),
    "Conta 70": ("Conta 70", "Controle provisório de créditos bancários não identificados"),
    "Histórico": ("Histórico", "Execuções e reprocessamentos"),
    "Sobre": ("Sobre o sistema", "Como funciona e regras de negócio"),
}
titulo, subtitulo = PAGE_INFO.get(st.session_state.pagina, ("Conciliação", ""))

st.html(
    f"""
    <div class="lle-header">
        {'<img src="' + LOGO_URI + '" alt="Grupo LLE"/>' if LOGO_URI else ''}
        <div>
            <div class="lle-title">{titulo}</div>
            <div class="lle-subtitle">{subtitulo}</div>
        </div>
    </div>
    """
)


# ============================================================
# Helpers de formatação
# ============================================================
def fmt_brl(v: float) -> str:
    if v is None or pd.isna(v):
        return "R$ 0,00"
    sinal = "-" if v < 0 else ""
    return f"{sinal}R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int(v) -> str:
    if v is None or pd.isna(v):
        return "0"
    return f"{int(v):,}".replace(",", ".")


def fmt_pct(v: float) -> str:
    if v is None or pd.isna(v):
        return "0,0%"
    return f"{v:.1f}%".replace(".", ",")


def card_kpi(label: str, valor: str, suffix: str = "", classe: str = "") -> str:
    return f"""
    <div class="lle-kpi">
        <div class="lle-kpi-label">{label}</div>
        <div class="lle-kpi-value {classe}">{valor}</div>
        {f'<div class="lle-kpi-suffix">{suffix}</div>' if suffix else ''}
    </div>
    """


def card_kpi_html(label: str, valor: str, suffix_html: str = "", classe: str = "") -> str:
    """Versão de card_kpi onde o suffix é HTML literal (pra blocos verticais)."""
    return f"""
    <div class="lle-kpi">
        <div class="lle-kpi-label">{label}</div>
        <div class="lle-kpi-value {classe}">{valor}</div>
        {suffix_html}
    </div>
    """


def _card_falta_conciliar_vertical(receitas: float, despesas: float) -> str:
    """v3: Falta Conciliar com receitas e despesas EMPILHADAS, ambos em vermelho."""
    return f"""
    <div class="lle-kpi-sub-stack">
        <div class="lle-kpi-sub-label">Receitas:</div>
        <div class="lle-kpi-sub-valor vermelho">{fmt_brl(receitas)}</div>
        <div class="lle-kpi-sub-label">Despesas:</div>
        <div class="lle-kpi-sub-valor vermelho">{fmt_brl(despesas)}</div>
    </div>
    """


def _card_total_com_rec_desp(receitas: float, despesas: float) -> str:
    """v3.1: bloco com Receitas (verde) e Despesas (vermelho) empilhadas embaixo do valor total.
    Usado em 'Total Movimentado no Banco' e 'Total Extrato Sankhya'."""
    return f"""
    <div class="lle-kpi-sub-stack">
        <div class="lle-kpi-sub-label">Receitas:</div>
        <div class="lle-kpi-sub-valor verde">{fmt_brl(receitas)}</div>
        <div class="lle-kpi-sub-label">Despesas:</div>
        <div class="lle-kpi-sub-valor vermelho">{fmt_brl(despesas)}</div>
    </div>
    """


def _card_investimentos(resultado: ResultadoConciliacao) -> str:
    """Card único de Investimentos (Aplicações + Resgates) — substitui 2 cards separados."""
    return _card_investimentos_de_df(resultado.aplicacoes_resgates)


def _card_investimentos_da_conta(resultado: ResultadoConciliacao, conta: str) -> str:
    """Versão filtrada por conta."""
    return _card_investimentos_de_df(resultado.aplicacoes_resgates_da_conta(conta))


def _card_investimentos_de_df(df: pd.DataFrame) -> str:
    """v5.27: card Investimentos simplificado, mesmo tamanho dos outros cards.

    Mudanças desta versão:
    - Card mostra saldo líquido + 2 linhas (Aplicações e Resgates).
    - Rendimentos e alerta de descasamento vão pra dentro da aba 'Aplicações e
      Resgates' — não poluem o card principal.

    DEDUP banco × sankhya: prefere Sankhya quando ambos existem.
    """
    if df.empty:
        return card_kpi("Investimentos", "—", "sem aplicações/resgates")

    df = df.copy()

    # Filtro defensivo: SALDO não é aplicação nem resgate
    if "historico" in df.columns:
        mask_saldo = df["historico"].astype(str).str.upper().str.contains("SALDO", na=False)
        df = df[~mask_saldo]

    if df.empty:
        return card_kpi("Investimentos", "—", "sem aplicações/resgates")

    # DEDUP banco × sankhya: preferir Sankhya quando ambos existem
    cols_chave = [c for c in ["data", "valor", "conta", "tipo_aplicacao"] if c in df.columns]
    if cols_chave and "origem" in df.columns:
        df["_ord_origem"] = df["origem"].apply(lambda x: 0 if "Sankhya" in str(x) else 1)
        df = df.sort_values("_ord_origem").drop_duplicates(subset=cols_chave, keep="first")
        df = df.drop(columns=["_ord_origem"])

    aplic = df[df["tipo_aplicacao"] == "Aplicação"] if "tipo_aplicacao" in df.columns else pd.DataFrame()
    resg = df[df["tipo_aplicacao"] == "Resgate"] if "tipo_aplicacao" in df.columns else pd.DataFrame()

    qtd_a = len(aplic)
    val_a = float(aplic["valor"].abs().sum()) if not aplic.empty else 0.0
    qtd_r = len(resg)
    val_r = float(resg["valor"].abs().sum()) if not resg.empty else 0.0

    # Saldo líquido = Resgates - Aplicações (faz sentido contábil)
    saldo_liquido = val_r - val_a

    # v5.45: card enxuto — o "por que não é prejuízo" já está em "Entenda seus
    # cards"; aqui fica só o fato curto + um lembrete apontando pro detalhamento.
    if saldo_liquido < -0.005:
        _status = "Aplicou " + fmt_brl(abs(saldo_liquido)) + " a mais que resgatou"
    elif saldo_liquido > 0.005:
        _status = "Resgatou " + fmt_brl(saldo_liquido) + " a mais que aplicou no mês"
    else:
        _status = "Aplicações e resgates se equilibraram no mês"

    sub = f"""
    <div class="lle-kpi-sub-stack">
        <div class="lle-kpi-sub-label">Aplicações:</div>
        <div class="lle-kpi-sub-valor">{fmt_int(qtd_a)} mov. · {fmt_brl(val_a)}</div>
        <div class="lle-kpi-sub-label">Resgates:</div>
        <div class="lle-kpi-sub-valor">{fmt_int(qtd_r)} mov. · {fmt_brl(val_r)}</div>
        <div class="lle-kpi-sub-label" style="margin-top:6px;">{_status}</div>
        <div class="lle-kpi-sub-label" style="margin-top:2px; opacity:.65;">ℹ️ O que significa? veja em “Entenda seus cards”.</div>
    </div>
    """
    return card_kpi_html("Investimentos", fmt_brl(saldo_liquido), sub, classe="destaque-amarelo")


def render_cards(cards: list[str]):
    html = '<div class="lle-kpi-row">' + "".join(cards) + "</div>"
    st.html(html)


def section_title(texto: str):
    st.html(f'<div class="lle-section-title">{texto}</div>')


def render_secao_excecoes_regras(resultado, kpis: dict, conta: str | None = None):
    """v5.12: Seção 'EXCEÇÕES E REGRAS APLICADAS' — agrupa os cards de tratamento
    especial (Estornos, Cartão TOP 1722, Investimentos) que antes poluíam o Resumo
    Executivo. Só renderiza se houver pelo menos uma exceção com dados.

    Args:
        resultado: ResultadoConciliacao
        kpis: dict de KPIs (globais ou da conta)
        conta: se informado, filtra Investimentos pela conta
    """
    qtd_est_anu = kpis.get("qtd_estornos_anulados", 0)
    qtd_est_par = kpis.get("qtd_estornos_parciais", 0)
    qtd_top1722 = kpis.get("qtd_top1722_grupos", 0)
    qtd_top1702 = kpis.get("qtd_top1702_grupos", 0)

    # Investimentos: pega global ou por conta
    if conta:
        df_inv = resultado.aplicacoes_resgates_da_conta(conta)
    else:
        df_inv = resultado.aplicacoes_resgates
    tem_invest = not df_inv.empty

    # Só renderiza a seção se houver pelo menos uma exceção
    if not (qtd_est_anu > 0 or qtd_est_par > 0 or qtd_top1722 > 0 or qtd_top1702 > 0 or tem_invest):
        return

    section_title("EXCEÇÕES E REGRAS APLICADAS")
    st.caption(
        "Tratamentos especiais aplicados pelo sistema durante a conciliação — "
        "estes valores já foram considerados nos totais do Resumo Executivo."
    )

    cards = []
    if qtd_est_anu > 0:
        cards.append(card_kpi(
            "♻️ Anulados por Estorno", fmt_int(qtd_est_anu),
            f"valor bruto: {fmt_brl(kpis.get('valor_estornos_anulados', 0.0))}",
            classe="destaque-verde",
        ))
    if qtd_est_par > 0:
        cards.append(card_kpi(
            "⚖️ Estornos Parciais", fmt_int(qtd_est_par),
            f"saldo restante: {fmt_brl(kpis.get('saldo_estornos_parciais', 0.0))}",
            classe="destaque-amarelo",
        ))
    if qtd_top1722 > 0:
        cards.append(card_kpi(
            "🃏 Cartão TOP 1722", fmt_int(qtd_top1722),
            f"valor: {fmt_brl(kpis.get('valor_top1722_conciliado', 0.0))}",
            classe="destaque-verde",
        ))
    if qtd_top1702 > 0:
        _dif1702 = getattr(resultado, "top1702_diferencas", pd.DataFrame())
        _difv = float(_dif1702["diferenca"].sum()) if (not _dif1702.empty and "diferenca" in _dif1702.columns) else 0.0
        _sub = f"valor: {fmt_brl(kpis.get('valor_top1702_conciliado', 0.0))}"
        if abs(_difv) >= 0.005:
            _sub += f" · dif {fmt_brl(_difv)}"
        cards.append(card_kpi(
            "🎫 Boleto TOP 1702", fmt_int(qtd_top1702),
            _sub,
            classe="destaque-amarelo" if abs(_difv) >= 0.005 else "destaque-verde",
        ))
    if tem_invest:
        cards.append(_card_investimentos_de_df(df_inv))

    # Completa com cards vazios pra manter grid de 4
    while len(cards) % 4 != 0:
        cards.append(card_kpi("", "", ""))

    render_cards(cards)
    st.divider()


# ============================================================
# v5.12 — Componentes EDITORIAIS (Fase 1: Resumo Executivo)
# Convivem com os helpers antigos. Outras telas continuam usando os antigos.
# ============================================================

def _split_centavos(valor: float) -> tuple[str, str]:
    """Quebra 874388.20 em ('R$ 874.388', ',20'). Usado pros valores com centavos
    em cinza no estilo editorial."""
    s = fmt_brl(valor)  # 'R$ 874.388,20'
    if "," in s:
        inteiro, cents = s.rsplit(",", 1)
        return inteiro, f",{cents}"
    return s, ""


def editorial_header(kicker: str, titulo: str, meta_esquerda: str = "", meta_direita: str = ""):
    """Cabeçalho editorial: kicker em amarelo + título grande + meta à direita."""
    meta_html = ""
    if meta_esquerda or meta_direita:
        m1 = f'<div class="editorial-meta">{meta_esquerda}</div>' if meta_esquerda else ""
        m2 = f'<div class="editorial-meta">{meta_direita}</div>' if meta_direita else ""
        meta_html = f'<div>{m1}{m2}</div>'
    st.html(
        f"""
        <div class="editorial-header">
            <div>
                <div class="editorial-kicker">{kicker}</div>
                <div class="editorial-title">{titulo}</div>
            </div>
            {meta_html}
        </div>
        <div class="editorial-divisor-fade"></div>
        """
    )


def editorial_kpi_destaque(
    percentual: float,
    valor_conciliado: float,
    valor_total: float,
    label_pct: str = "Conciliado",
    label_valor: str = "Valor conciliado",
    status_text: str | None = None,
    status_cor: str = "verde",  # 'verde' | 'amarelo' | 'vermelho'
):
    """KPI âncora gigante: percentual (52px) + valor (38px) lado a lado."""
    pct_str = f"{percentual:.1f}".replace(".", ",")
    inteiro, cents = _split_centavos(valor_conciliado)

    status_html = ""
    if status_text:
        status_html = (
            f'<div class="editorial-status-pill {status_cor}">'
            f'<i class="ti ti-trending-up"></i> {status_text}'
            f'</div>'
        )

    st.html(
        f"""
        <div class="editorial-destaque-row">
            <div class="editorial-destaque-col">
                <div class="editorial-label">{label_pct}</div>
                <div style="display:flex; align-items:baseline; gap:14px; margin-top:10px;">
                    <div class="editorial-valor-hero">{pct_str}<span class="unit">%</span></div>
                    {status_html}
                </div>
            </div>
            <div class="editorial-destaque-col bigger">
                <div class="editorial-label">{label_valor}</div>
                <div class="editorial-valor-grande">
                    R$ <span class="destaque">{inteiro.replace('R$ ', '')}</span><span class="centavos">{cents}</span>
                </div>
                <div class="editorial-sub-text">de {fmt_brl(valor_total)} movimentados</div>
            </div>
        </div>
        """
    )


def editorial_barra_progresso(percentual: float, label_esq: str = "", label_dir: str = ""):
    """Barra de progresso fina, dourada, com legendas opcionais embaixo."""
    pct_clamped = max(0.0, min(100.0, percentual))
    st.html(
        f"""
        <div class="editorial-progresso-wrap">
            <div class="editorial-progresso-track">
                <div class="editorial-progresso-fill" style="width:{pct_clamped}%;"></div>
            </div>
            <div class="editorial-progresso-legend">
                <span>{label_esq}</span>
                <span>{label_dir}</span>
            </div>
        </div>
        """
    )


def editorial_linha_metricas(metricas: list[dict]):
    """Linha de colunas separadas por divisores verticais.
    Cada métrica: {'label': str, 'valor': str, 'centavos': str?, 'cor': str?, 'sub_html': str?}
    cor: '' (branco) | 'verde' | 'amarelo' | 'vermelho' | 'atencao'
    """
    cols_html = []
    for m in metricas:
        cor_class = m.get("cor", "")
        centavos = m.get("centavos", "")
        sub = m.get("sub_html", "")
        sub_html = f'<div class="sub">{sub}</div>' if sub else ""
        cols_html.append(
            f"""
            <div class="col">
                <div class="label">{m['label']}</div>
                <div class="valor {cor_class}">{m['valor']}<span class="centavos">{centavos}</span></div>
                {sub_html}
            </div>
            """
        )
    cols_count = len(metricas)
    st.html(
        f'<div class="editorial-cols" style="--cols:{cols_count};">{"".join(cols_html)}</div>'
    )


def editorial_faixa_contagens(itens: list[dict]):
    """Faixa horizontal entre dois divisores. Cada item: {'label', 'valor', 'cor'?}"""
    parts = []
    for i, item in enumerate(itens):
        if i > 0:
            parts.append('<div class="sep"></div>')
        cor = item.get("cor", "")
        parts.append(
            f"""
            <div class="item">
                <div class="valor {cor}">{item['valor']}</div>
                <div class="label">{item['label']}</div>
            </div>
            """
        )
    st.html(f'<div class="editorial-faixa">{"".join(parts)}</div>')


def editorial_secao_head(titulo: str, contagem_text: str = ""):
    """Cabeçalho de seção: título amarelo + linha que esmaece + contagem opcional à direita."""
    contagem_html = f'<span class="contagem">{contagem_text}</span>' if contagem_text else ""
    st.html(
        f"""
        <div class="editorial-secao-head">
            <span class="titulo">{titulo}</span>
            <span class="linha"></span>
            {contagem_html}
        </div>
        """
    )


def editorial_lista_excecoes(itens: list[dict]):
    """Lista de exceções (não cards). Cada item:
        {'icone': 'ti-credit-card', 'titulo': str, 'sub': str,
         'valor': str, 'status': str?, 'cor': 'verde'|'amarelo'|'',
         'muted': bool?}
    """
    parts = []
    for i, item in enumerate(itens):
        if i > 0:
            parts.append('<div class="editorial-lista-divisor"></div>')
        cor = item.get("cor", "")
        muted = "muted" if item.get("muted") else ""
        status = item.get("status", "")
        status_html = (
            f'<div class="editorial-lista-status {cor}">{status}</div>' if status else ""
        )
        valor_class = "muted" if item.get("muted") else ""
        # Parte "light" (cinza) no título: separar por travessão
        titulo = item["titulo"]
        if " — " in titulo:
            principal, light = titulo.split(" — ", 1)
            titulo_html = f'{principal} <span class="light">— {light}</span>'
        else:
            titulo_html = titulo
        parts.append(
            f"""
            <div class="editorial-lista-item {muted}">
                <div class="editorial-lista-icone {cor}">
                    <i class="ti {item['icone']}"></i>
                </div>
                <div class="editorial-lista-corpo">
                    <div class="editorial-lista-titulo">{titulo_html}</div>
                    <div class="editorial-lista-sub">{item['sub']}</div>
                </div>
                <div class="editorial-lista-direita">
                    <div class="editorial-lista-valor {valor_class}">{item['valor']}</div>
                    {status_html}
                </div>
            </div>
            """
        )
    st.html(f'<div class="editorial-lista">{"".join(parts)}</div>')


def render_resumo_executivo_editorial(resultado: ResultadoConciliacao, kpis: dict):
    """v5.12 Fase 1: Resumo Executivo no estilo editorial.
    Substitui os 8-11 cards retangulares por um layout em camadas:
    1) Header (kicker + título + data)
    2) KPI âncora (% + valor conciliado, lado a lado)
    3) Barra de progresso
    4) Linha de 4 colunas com divisores (Banco | Sankhya | Falta | Divergência)
    5) Faixa de contagens (Banco · Sankhya · Pares · Conta)
    6) Seção de exceções (lista, não cards)
    """
    # 1) Header
    data_ref = resultado.data_referencia.strftime("%d de %B · %Y")
    # tradução curta dos meses pra PT-BR (cobre EN-US default e variações de locale)
    meses_pt = {
        "January": "janeiro", "February": "fevereiro", "March": "março",
        "April": "abril", "May": "maio", "June": "junho",
        "July": "julho", "August": "agosto", "September": "setembro",
        "October": "outubro", "November": "novembro", "December": "dezembro",
    }
    for en, pt in meses_pt.items():
        data_ref = data_ref.replace(en, pt).replace(en.lower(), pt)

    n_contas = len(resultado.contas_processadas)
    titulo_subtitulo = (
        "Conciliação consolidada"
        if n_contas != 1
        else f"Conciliação · {resultado.contas_processadas[0]}"
    )

    editorial_header(
        kicker="Resumo executivo",
        titulo=titulo_subtitulo,
        meta_esquerda=data_ref,
        meta_direita=f"{n_contas} conta{'s' if n_contas != 1 else ''} processada{'s' if n_contas != 1 else ''}",
    )

    # 2) KPI âncora
    pct = float(kpis["percentual_conciliado"])
    if pct >= 95:
        status_text, status_cor = "dentro da meta", "verde"
    elif pct >= 80:
        status_text, status_cor = "próximo da meta", "amarelo"
    else:
        status_text, status_cor = "abaixo da meta", "vermelho"

    editorial_kpi_destaque(
        percentual=pct,
        valor_conciliado=float(kpis["total_conciliado"]),
        valor_total=float(kpis["total_movimentado_banco"]),
        status_text=status_text,
        status_cor=status_cor,
    )

    # 3) Barra de progresso
    falta = float(kpis["falta_conciliar"])
    diverg = float(kpis["divergencia_sankhya_banco"])
    label_dir = []
    if falta > 0:
        label_dir.append(f"{fmt_brl(falta)} falta")
    if diverg > 0:
        label_dir.append(f"{fmt_brl(diverg)} divergência")
    editorial_barra_progresso(
        percentual=pct,
        label_esq=f"{fmt_brl(float(kpis['total_conciliado']))} conciliado",
        label_dir=" · ".join(label_dir) if label_dir else "—",
    )

    # 4) Linha de 4 colunas: Banco | Sankhya | Falta | Divergência
    inteiro_b, cents_b = _split_centavos(float(kpis["total_movimentado_banco"]))
    inteiro_s, cents_s = _split_centavos(float(kpis["total_extrato_sistema"]))
    inteiro_f, cents_f = _split_centavos(falta)
    inteiro_d, cents_d = _split_centavos(diverg)

    # Subs: receitas/despesas resumidos
    rec_b = float(kpis["receitas_banco"])
    desp_b = float(kpis["despesas_banco"])
    rec_s = float(kpis["receitas_sistema"])
    desp_s = float(kpis["despesas_sistema"])

    sub_banco = (
        f'<span class="inline"><span class="verde">↑ {fmt_brl(rec_b).replace("R$ ", "")}</span></span>'
        f'<span class="vermelho">↓ {fmt_brl(desp_b).replace("R$ ", "")}</span>'
    )
    sub_sankhya = (
        f'<span class="inline"><span class="verde">↑ {fmt_brl(rec_s).replace("R$ ", "")}</span></span>'
        f'<span class="vermelho">↓ {fmt_brl(desp_s).replace("R$ ", "")}</span>'
    )

    # Sub de "Falta": indicar se é só despesas, só receitas ou ambos
    fr = float(kpis["falta_conciliar_receitas"])
    fd = float(kpis["falta_conciliar_despesas"])
    if fr > 0 and fd > 0:
        sub_falta = "receitas e despesas"
    elif fd > 0:
        sub_falta = "apenas em despesas"
    elif fr > 0:
        sub_falta = "apenas em receitas"
    else:
        sub_falta = "—"

    qtd_div = int(kpis.get("qtd_divergencia_sankhya_banco", 0))
    sub_div = f"{qtd_div} lançamento{'s' if qtd_div != 1 else ''}" if qtd_div else "—"

    # Remover "R$ " dos inteiros pra mostrar só o número (R$ já está embutido no contexto)
    editorial_linha_metricas([
        {
            "label": "Banco",
            "valor": inteiro_b.replace("R$ ", ""),
            "centavos": cents_b,
            "sub_html": sub_banco,
        },
        {
            "label": "Sankhya",
            "valor": inteiro_s.replace("R$ ", ""),
            "centavos": cents_s,
            "sub_html": sub_sankhya,
        },
        {
            "label": "Falta conciliar",
            "valor": inteiro_f.replace("R$ ", ""),
            "centavos": cents_f,
            "cor": "vermelho" if falta > 0 else "",
            "sub_html": sub_falta,
        },
        {
            "label": "Divergência",
            "valor": inteiro_d.replace("R$ ", ""),
            "centavos": cents_d,
            "cor": "atencao" if diverg > 0 else "",
            "sub_html": sub_div,
        },
    ])

    # 5) Faixa de contagens
    editorial_faixa_contagens([
        {"label": "Banco", "valor": fmt_int(kpis["qtd_registros_banco"])},
        {"label": "Sankhya", "valor": fmt_int(kpis["qtd_registros_sistema"])},
        {"label": "Pares", "valor": fmt_int(kpis["qtd_conciliados"]), "cor": "verde"},
        {"label": "Conta" if n_contas == 1 else "Contas", "valor": fmt_int(n_contas), "cor": "amarelo"},
    ])

    # 6) Seção de exceções (lista editorial)
    _render_excecoes_editorial(resultado, kpis)


def _render_excecoes_editorial(resultado: ResultadoConciliacao, kpis: dict):
    """Lista de exceções no estilo editorial — substitui a versão de cards."""
    qtd_est_anu = kpis.get("qtd_estornos_anulados", 0)
    qtd_est_par = kpis.get("qtd_estornos_parciais", 0)
    qtd_top1722 = kpis.get("qtd_top1722_grupos", 0)
    qtd_top1702 = kpis.get("qtd_top1702_grupos", 0)
    df_inv = resultado.aplicacoes_resgates
    tem_invest = not df_inv.empty

    # Se nenhuma das regras se aplica, mostra seção minimalista com "nenhuma exceção"
    if not (qtd_est_anu > 0 or qtd_est_par > 0 or qtd_top1722 > 0 or qtd_top1702 > 0 or tem_invest):
        editorial_secao_head("Exceções aplicadas", "nenhuma neste período")
        return

    total_regras = sum(1 for x in [qtd_est_anu > 0, qtd_est_par > 0, qtd_top1722 > 0, qtd_top1702 > 0, tem_invest] if x)
    editorial_secao_head("Exceções aplicadas", f"{total_regras} regra{'s' if total_regras != 1 else ''} ativa{'s' if total_regras != 1 else ''}")

    itens = []

    # TOP 1722
    if qtd_top1722 > 0:
        valor_top = float(kpis.get("valor_top1722_conciliado", 0.0))
        # Detalhamento de qtd banco × sankhya, se possível
        linhas_b = getattr(resultado, "top1722_linhas_banco", pd.DataFrame())
        linhas_s = getattr(resultado, "top1722_linhas", pd.DataFrame())
        qtd_b = len(linhas_b) if not linhas_b.empty else 0
        qtd_s = len(linhas_s) if not linhas_s.empty else 0
        sub = (
            f"{qtd_b} créditos banco × {qtd_s} vendas Sankhya · diferença R$ 0,00"
            if qtd_b and qtd_s
            else f"{qtd_top1722} agrupamento{'s' if qtd_top1722 != 1 else ''}"
        )
        itens.append({
            "icone": "ti-credit-card",
            "titulo": "Cartão TOP 1722 — agrupamento por soma total",
            "sub": sub,
            "valor": fmt_brl(valor_top),
            "status": "Conciliado",
            "cor": "verde",
        })

    # TOP 1702 (boleto)
    if qtd_top1702 > 0:
        valor_bol = float(kpis.get("valor_top1702_conciliado", 0.0))
        lb = getattr(resultado, "top1702_linhas_banco", pd.DataFrame())
        ls = getattr(resultado, "top1702_linhas", pd.DataFrame())
        dif1702 = getattr(resultado, "top1702_diferencas", pd.DataFrame())
        qb = len(lb) if not lb.empty else 0
        qs = len(ls) if not ls.empty else 0
        dif_val = float(dif1702["diferenca"].sum()) if (not dif1702.empty and "diferenca" in dif1702.columns) else 0.0
        com_dif = abs(dif_val) >= 0.005
        sub = (
            f"{qb} créditos cobrança banco × {qs} boletos Sankhya · "
            + (f"diferença {fmt_brl(dif_val)} (a investigar)" if com_dif else "diferença R$ 0,00")
        )
        itens.append({
            "icone": "ti-barcode",
            "titulo": "Boleto TOP 1702 — agrupamento por soma total",
            "sub": sub,
            "valor": fmt_brl(valor_bol),
            "status": "Conciliado (c/ diferença)" if com_dif else "Conciliado",
            "cor": "amarelo" if com_dif else "verde",
        })

    # Investimentos
    if tem_invest:
        aplic = df_inv[df_inv["tipo_aplicacao"] == "Aplicação"] if "tipo_aplicacao" in df_inv.columns else pd.DataFrame()
        resg = df_inv[df_inv["tipo_aplicacao"] == "Resgate"] if "tipo_aplicacao" in df_inv.columns else pd.DataFrame()
        qtd_a = len(aplic)
        qtd_r = len(resg)
        val_total = float(df_inv["valor"].abs().sum())
        itens.append({
            "icone": "ti-trending-up",
            "titulo": "Investimentos — aplicações e resgates",
            "sub": f"{qtd_a} aplicaç{'ão' if qtd_a == 1 else 'ões'} · {qtd_r} resgate{'s' if qtd_r != 1 else ''}",
            "valor": fmt_brl(val_total),
            "status": "Excluído da divergência",
            "cor": "amarelo",
        })

    # Estornos anulados
    if qtd_est_anu > 0:
        itens.append({
            "icone": "ti-refresh",
            "titulo": "Estornos anulados — débito e crédito se cancelam",
            "sub": f"{qtd_est_anu} ocorrência{'s' if qtd_est_anu != 1 else ''}",
            "valor": fmt_brl(float(kpis.get("valor_estornos_anulados", 0.0))),
            "status": "Removidos do resumo",
            "cor": "verde",
        })

    # Estornos parciais
    if qtd_est_par > 0:
        itens.append({
            "icone": "ti-scale",
            "titulo": "Estornos parciais — débito reduz crédito",
            "sub": f"{qtd_est_par} ocorrência{'s' if qtd_est_par != 1 else ''}",
            "valor": fmt_brl(float(kpis.get("saldo_estornos_parciais", 0.0))),
            "status": "Saldo restante",
            "cor": "amarelo",
        })

    editorial_lista_excecoes(itens)


# ============================================================
# v5.13 — Componentes OPÇÃO A (cards generosos)
# Layout moderno com hierarquia: card âncora grande + secundários
# com borda superior semântica + chips de exceção.
# ============================================================

def _formata_valor_curto(valor: float) -> str:
    """Formata sem o 'R$ ' (usado em sub-textos do card âncora)."""
    return fmt_brl(valor).replace("R$ ", "")


def opa_card_ancora(label: str, valor: float, receitas: float, despesas: float) -> str:
    """Card âncora (maior, com gradiente): Total Movimentado, com receitas/despesas."""
    return f"""
    <div class="opa-card-ancora">
        <div class="opa-card-ancora-label">{label}</div>
        <div class="opa-card-ancora-valor">{fmt_brl(valor)}</div>
        <div class="opa-rec-desp-row">
            <div class="opa-rec-desp-item">
                <div class="marker verde">
                    <span class="dot"></span>
                    Receitas
                </div>
                <div class="valor">{fmt_brl(receitas)}</div>
            </div>
            <div class="opa-rec-desp-item">
                <div class="marker vermelho">
                    <span class="dot"></span>
                    Despesas
                </div>
                <div class="valor">{fmt_brl(despesas)}</div>
            </div>
        </div>
    </div>
    """


def opa_card_conciliado(valor: float, sub_texto: str = "Match Banco × Sankhya") -> str:
    """Card verde translúcido (Total Conciliado)."""
    return f"""
    <div class="opa-card-conciliado">
        <div class="opa-card-conciliado-label">Total conciliado</div>
        <div class="opa-card-conciliado-valor">{fmt_brl(valor)}</div>
        <div class="opa-card-conciliado-sub">
            <i class="ti ti-check"></i>{sub_texto}
        </div>
    </div>
    """


def opa_card_donut(percentual: float) -> str:
    """Card com donut SVG do percentual conciliado.
    Círculo de raio 50, perímetro = 2*pi*50 ≈ 314.16.
    O 'offset' faz a parte amarela = percentual%.
    """
    raio = 50
    perimetro = 2 * 3.14159265 * raio  # ≈ 314.16
    pct_clamped = max(0.0, min(100.0, percentual))
    # dashoffset: 0 = círculo cheio. perimetro = vazio.
    dash_offset = perimetro * (1 - pct_clamped / 100)
    pct_str = f"{percentual:.1f}".replace(".", ",")
    return f"""
    <div class="opa-card-donut">
        <svg width="140" height="140" viewBox="0 0 120 120">
            <circle cx="60" cy="60" r="{raio}" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="6"/>
            <circle cx="60" cy="60" r="{raio}" fill="none" stroke="{CORES['amarelo']}" stroke-width="6"
                stroke-linecap="round" stroke-dasharray="{perimetro:.2f}"
                stroke-dashoffset="{dash_offset:.2f}"
                transform="rotate(-90 60 60)"/>
        </svg>
        <div class="opa-card-donut-text">
            <div class="opa-card-donut-pct">{pct_str}%</div>
            <div class="opa-card-donut-label">Conciliado</div>
        </div>
    </div>
    """


def opa_card_secundario(
    label: str,
    valor: str,
    sub_html: str = "",
    cor: str = "",
    icone_tabler: str = "",
) -> str:
    """Card secundário com borda superior semântica + ícone em pílula.
    cor: '' | 'vermelho' | 'amarelo' | 'verde'
    """
    icone_html = ""
    if icone_tabler:
        icone_html = f"""
        <div class="opa-card-sec-icon {cor}">
            <i class="ti {icone_tabler}"></i>
        </div>
        """
    sub = f'<div class="opa-card-sec-sub">{sub_html}</div>' if sub_html else ""
    return f"""
    <div class="opa-card-secundario {cor}">
        <div class="opa-card-sec-head">
            <div>
                <div class="opa-card-sec-label">{label}</div>
                <div class="opa-card-sec-valor {cor}">{valor}</div>
            </div>
            {icone_html}
        </div>
        {sub}
    </div>
    """


def opa_render_chip_excecao(icone: str, label: str, valor_principal: str, valor_sub: str = "", cor: str = "") -> str:
    """Chip horizontal pra Exceções (ícone redondo + label + valor inline)."""
    sub_html = f'<span class="light">· {valor_sub}</span>' if valor_sub else ""
    return f"""
    <div class="opa-chip {cor}">
        <div class="opa-chip-icon {cor}">
            <i class="ti {icone}"></i>
        </div>
        <div>
            <div class="opa-chip-label">{label}</div>
            <div class="opa-chip-valor">{valor_principal} {sub_html}</div>
        </div>
    </div>
    """


def render_resumo_executivo_opcao_a(resultado: ResultadoConciliacao, kpis: dict):
    """v5.13: Resumo Executivo no estilo Opção A.
    Layout em camadas:
    1) Section title clássico
    2) Linha hero: Card âncora (1.4fr) + Conciliado (1fr) + Donut % (1fr)
    3) Linha secundária: Falta + Divergência + Contas (3 cards iguais)
    4) Seção Exceções e Regras Aplicadas (chips horizontais)
    """
    section_title("RESUMO EXECUTIVO")

    # Linha 1: hero (3 cards com proporção 1.4 / 1 / 1)
    card_ancora = opa_card_ancora(
        label="Total movimentado · banco",
        valor=float(kpis["total_movimentado_banco"]),
        receitas=float(kpis["receitas_banco"]),
        despesas=float(kpis["despesas_banco"]),
    )
    card_conc = opa_card_conciliado(
        valor=float(kpis["total_conciliado"]),
        sub_texto="Match Banco × Sankhya",
    )
    card_donut = opa_card_donut(float(kpis["percentual_conciliado"]))

    st.html(
        f'<div class="opa-grid-hero">{card_ancora}{card_conc}{card_donut}</div>'
    )

    # Linha 2: secundários (3 cards iguais)
    falta = float(kpis["falta_conciliar"])
    falta_r = float(kpis["falta_conciliar_receitas"])
    falta_d = float(kpis["falta_conciliar_despesas"])
    diverg = float(kpis["divergencia_sankhya_banco"])
    qtd_div = int(kpis.get("qtd_divergencia_sankhya_banco", 0))
    n_contas = len(resultado.contas_processadas)

    sub_falta = (
        f'<span class="item"><span class="label">Receitas:</span> '
        f'<span class="{"vermelho-text" if falta_r > 0 else ""}">{fmt_brl(falta_r)}</span></span>'
        f'<span class="item"><span class="label">Despesas:</span> '
        f'<span class="{"vermelho-text" if falta_d > 0 else ""}">{fmt_brl(falta_d)}</span></span>'
    )

    sub_div = f"Sankhya × Banco · {qtd_div} lançamento{'s' if qtd_div != 1 else ''}"

    # Conta(s)
    nome_contas = ", ".join(resultado.contas_processadas[:2])
    if n_contas > 2:
        nome_contas += f" + {n_contas - 2}"
    sub_contas = nome_contas if n_contas > 0 else "—"

    card_falta = opa_card_secundario(
        label="Falta conciliar",
        valor=fmt_brl(falta),
        sub_html=sub_falta,
        cor="vermelho" if falta > 0 else "",
        icone_tabler="ti-alert-triangle",
    )
    card_diverg = opa_card_secundario(
        label="Divergência",
        valor=fmt_brl(diverg),
        sub_html=sub_div,
        cor="vermelho" if diverg > 0 else "",
        icone_tabler="ti-git-compare",
    )
    card_contas = opa_card_secundario(
        label="Contas processadas",
        valor=str(n_contas),
        sub_html=sub_contas,
        cor="amarelo",
        icone_tabler="ti-building-bank",
    )

    st.html(
        f'<div class="opa-grid-secundario">{card_falta}{card_diverg}{card_contas}</div>'
    )

    # Linha 3: contagens (mantém o estilo antigo dos cards, mas com cards menores e arejados)
    cards_contagem = [
        card_kpi("Registros Banco", fmt_int(kpis["qtd_registros_banco"]),
                 f"{fmt_int(kpis['qtd_movimentacoes_banco'])} movimentações"),
        card_kpi("Registros Sistema", fmt_int(kpis["qtd_registros_sistema"]),
                 f"{fmt_int(kpis['qtd_movimentacoes_sistema'])} movimentações"),
        card_kpi("Conciliados", fmt_int(kpis["qtd_conciliados"]),
                 "pares Banco × Sankhya", classe="destaque-verde"),
        card_kpi("", "", ""),
    ]
    st.write("")  # respiro
    render_cards(cards_contagem)

    # Seção Exceções
    _render_excecoes_opcao_a(resultado, kpis)


def _render_excecoes_opcao_a(resultado: ResultadoConciliacao, kpis: dict):
    """Exceções no estilo Opção A — chips horizontais leves (não cards)."""
    qtd_est_anu = kpis.get("qtd_estornos_anulados", 0)
    qtd_est_par = kpis.get("qtd_estornos_parciais", 0)
    qtd_top1722 = kpis.get("qtd_top1722_grupos", 0)
    qtd_top1702 = kpis.get("qtd_top1702_grupos", 0)
    df_inv = resultado.aplicacoes_resgates
    tem_invest = not df_inv.empty

    # Se nenhuma exceção, esconde a seção (não polui)
    if not (qtd_est_anu > 0 or qtd_est_par > 0 or qtd_top1722 > 0 or qtd_top1702 > 0 or tem_invest):
        return

    # Header da seção
    st.html(
        """
        <div class="opa-excecoes-head">
            <span class="opa-excecoes-head-label">Exceções e regras aplicadas</span>
            <span class="opa-excecoes-head-line"></span>
        </div>
        """
    )

    chips = []

    # TOP 1722
    if qtd_top1722 > 0:
        valor_top = float(kpis.get("valor_top1722_conciliado", 0.0))
        chips.append(opa_render_chip_excecao(
            icone="ti-credit-card",
            label="Cartão TOP 1722",
            valor_principal=str(qtd_top1722),
            valor_sub=fmt_brl(valor_top),
            cor="verde",
        ))

    # TOP 1702 (boleto)
    if qtd_top1702 > 0:
        _dif1702 = getattr(resultado, "top1702_diferencas", pd.DataFrame())
        _difv = float(_dif1702["diferenca"].sum()) if (not _dif1702.empty and "diferenca" in _dif1702.columns) else 0.0
        _com_dif = abs(_difv) >= 0.005
        chips.append(opa_render_chip_excecao(
            icone="ti-barcode",
            label="Boleto TOP 1702",
            valor_principal=str(qtd_top1702),
            valor_sub=fmt_brl(float(kpis.get("valor_top1702_conciliado", 0.0)))
            + (f" · dif {fmt_brl(_difv)}" if _com_dif else ""),
            cor="amarelo" if _com_dif else "verde",
        ))

    # Investimentos
    if tem_invest:
        val_total = float(df_inv["valor"].abs().sum())
        chips.append(opa_render_chip_excecao(
            icone="ti-trending-up",
            label="Investimentos",
            valor_principal=str(len(df_inv)),
            valor_sub=fmt_brl(val_total),
            cor="amarelo",
        ))

    # Anulados por Estorno
    if qtd_est_anu > 0:
        chips.append(opa_render_chip_excecao(
            icone="ti-refresh",
            label="Anulados por estorno",
            valor_principal=str(qtd_est_anu),
            valor_sub=fmt_brl(float(kpis.get("valor_estornos_anulados", 0.0))),
            cor="verde",
        ))

    # Estornos Parciais
    if qtd_est_par > 0:
        chips.append(opa_render_chip_excecao(
            icone="ti-scale",
            label="Estornos parciais",
            valor_principal=str(qtd_est_par),
            valor_sub=fmt_brl(float(kpis.get("saldo_estornos_parciais", 0.0))),
            cor="amarelo",
        ))

    st.html(f'<div class="opa-excecoes-grid">{"".join(chips)}</div>')


# ============================================================
# Validações
# ============================================================
NOMES_PROIBIDOS = {"data", "valor", "histórico", "historico", "conta", "—", ""}


def validar_nome_conta(nome: str) -> str | None:
    """Retorna mensagem de erro ou None se válido."""
    if not nome or not nome.strip():
        return "Identificador da conta não pode ser vazio."
    n = nome.lower().strip()
    if n in NOMES_PROIBIDOS:
        return f"Identificador '{nome}' é genérico demais. Use algo como 'Bradesco-12345'."
    if len(nome.strip()) < 3:
        return f"Identificador '{nome}' tem menos de 3 caracteres."
    return None


# ============================================================
# Página: Dashboard
# ============================================================
def pagina_dashboard():
    resultado: ResultadoConciliacao | None = st.session_state.resultado
    if resultado is None:
        st.info(
            "👋 Nenhuma conciliação foi rodada ainda nesta sessão. "
            "Acesse a página **Conciliação** para começar."
        )
        if st.button("➡️ Ir para Conciliação", type="primary"):
            ir_para("Conciliação")
            st.rerun()
        return

    kpis = resultado.kpis_globais()

    section_title("INDICADORES EXECUTIVOS")

    # Linha 1: principais
    sub_banco = _card_total_com_rec_desp(kpis["receitas_banco"], kpis["despesas_banco"])
    sub_sankhya = _card_total_com_rec_desp(kpis["receitas_sistema"], kpis["despesas_sistema"])
    cards1 = [
        card_kpi_html("Total Movimentado no Banco", fmt_brl(kpis["total_movimentado_banco"]),
                      sub_banco),
        card_kpi_html("Total Extrato Sankhya", fmt_brl(kpis["total_extrato_sistema"]),
                      sub_sankhya),
        _card_investimentos(resultado),
        card_kpi("Percentual Conciliado", fmt_pct(kpis["percentual_conciliado"]),
                 classe="destaque-amarelo"),
    ]
    render_cards(cards1)

    # Linha 2: Falta Conciliar vertical + Divergência + Qtd + Contas
    sub_falta_conciliar = _card_falta_conciliar_vertical(
        kpis["falta_conciliar_receitas"],
        kpis["falta_conciliar_despesas"],
    )

    cards2 = [
        card_kpi_html("Falta Conciliar", fmt_brl(kpis["falta_conciliar"]),
                      sub_falta_conciliar, classe="destaque-vermelho"),
        card_kpi_html("Divergência (Sankhya × Banco)",
                      fmt_brl(kpis["divergencia_sankhya_banco"]),
                      _card_falta_conciliar_vertical(
                          kpis["divergencia_sankhya_banco_receitas"],
                          kpis["divergencia_sankhya_banco_despesas"],
                      ),
                      classe="destaque-vermelho"),
        card_kpi("Qtd Divergências", fmt_int(kpis["qtd_divergencia_sankhya_banco"]),
                 "lançamentos do Sankhya sem par no banco",
                 classe="destaque-amarelo" if kpis["qtd_divergencia_sankhya_banco"] > 0 else ""),
        card_kpi("Contas processadas", fmt_int(len(resultado.contas_processadas))),
    ]
    render_cards(cards2)

    # Linha 3: contagens
    cards3 = [
        card_kpi("Registros Processados", fmt_int(kpis["qtd_registros_banco"] + kpis["qtd_registros_sistema"])),
        card_kpi("Conciliados", fmt_int(kpis["qtd_conciliados"]), classe="destaque-verde"),
        card_kpi("Movimentações Banco", fmt_int(kpis["qtd_movimentacoes_banco"])),
        card_kpi("Movimentações Sistema", fmt_int(kpis["qtd_movimentacoes_sistema"])),
    ]
    render_cards(cards3)

    st.divider()

    # v5.14: Seção "Exceções e Regras Aplicadas" removida.
    # TOP 1722 e Estornos seguem funcionando; aparecem dentro do detalhamento da conta.

    # v3.10: Dashboard é visão gerencial — cards das contas são só informativos.
    # Drill-down (Ver detalhamento) só acontece na aba Conciliação.
    section_title("CONTAS PROCESSADAS")
    render_painel_bancos(resultado, mostrar_botao=False)


# ============================================================
# Painel de botões por banco
# ============================================================
def render_painel_bancos(resultado: ResultadoConciliacao, mostrar_botao: bool = True):
    """v6: painel de contas ordenado por atenção, com SELO DE ALERTA.

    - Cards em tom NEUTRO. O vermelho/âmbar aparece só num selo (badge),
      nunca como cor do card.
    - Contas ORDENADAS POR ATENÇÃO: quem tem mais itens a resolver vem no topo.
    - Mostra movimento da conta e quanto há "a resolver".

    `mostrar_botao=False` no Dashboard (cards só informativos).
    """
    contas = resultado.contas_processadas
    if not contas:
        st.warning("Nenhuma conta foi processada.")
        return

    kpis_pb = resultado.kpis_por_banco()

    def _itens_a_resolver(conta: str, k: dict) -> tuple[int, float]:
        """Itens que precisam de análise nesta conta e quanto em R$.

        'Precisa de você' = banco sem explicação + Sankhya sem confirmação +
        lançamentos que não pertencem à conta (espelha a triagem do detalhamento).
        """
        try:
            qtd_nao_pertence = len(resultado.nao_pertence_da_conta(conta))
        except Exception:
            qtd_nao_pertence = 0
        qtd = (
            int(k.get("qtd_pendentes_banco", 0))
            + int(k.get("qtd_divergencia_sankhya_banco", 0))
            + qtd_nao_pertence
        )
        valor = abs(float(k.get("falta_conciliar", 0.0))) + abs(
            float(k.get("divergencia_sankhya_banco", 0.0))
        )
        return qtd, valor

    # Ordena por atenção: mais itens primeiro; empate desempata por R$ a resolver.
    contas_ordenadas = sorted(
        contas,
        key=lambda c: _itens_a_resolver(c, kpis_pb[c]),
        reverse=True,
    )

    def _metricas(conta: str):
        k = kpis_pb[conta]
        mov = float(k.get("total_movimentado_banco", 0.0))
        falta = float(k.get("falta_conciliar", 0.0))
        explic = 100.0 * (mov - falta) / mov if mov > 0 else 0.0
        tot_sis = float(k.get("total_extrato_sistema", 0.0))
        div = float(k.get("divergencia_sankhya_banco", 0.0))
        confirm = 100.0 * (tot_sis - div) / tot_sis if tot_sis > 0 else 0.0
        pct_pares = float(k.get("percentual_conciliado", 0.0))
        qtd, valor = _itens_a_resolver(conta, k)
        return mov, explic, confirm, pct_pares, qtd, valor

    # ---- UMA conta: mantém o card de hoje (a tabela é só pra múltiplas contas) ----
    if len(contas_ordenadas) == 1:
        conta = contas_ordenadas[0]
        mov_conta, pct, _confirm, pct_pares, qtd_itens, valor_resolver = _metricas(conta)
        if qtd_itens == 0:
            badge_classe, badge_texto = "verde", "ok"
        elif qtd_itens <= 2:
            badge_classe = "amarelo"
            badge_texto = f"{qtd_itens} item" if qtd_itens == 1 else f"{qtd_itens} itens"
        else:
            badge_classe, badge_texto = "vermelho", f"{qtd_itens} itens"
        cor_barra = "#46d18a" if qtd_itens == 0 else "#9fb0d0"
        pct_barra = max(0.0, min(100.0, float(pct)))
        if qtd_itens == 0:
            linha_resolver = '<div class="lle-kpi-suffix">nada pendente</div>'
        else:
            cor_txt = "#ff8a8a" if badge_classe == "vermelho" else "#cdbf7a"
            linha_resolver = (
                f'<div class="lle-kpi-suffix" style="color:{cor_txt};">'
                f"{fmt_brl(valor_resolver)} a resolver</div>"
            )
        st.html(
            f"""
            <div class="lle-kpi">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
                    <div class="lle-kpi-label">{conta}</div>
                    <span class="lle-badge {badge_classe}">{badge_texto}</span>
                </div>
                <div class="lle-kpi-value" style="font-size:22px;">{fmt_pct(pct)}</div>
                <div style="height:6px; background:#1a2a52; border-radius:999px; overflow:hidden; margin:8px 0;">
                    <div style="width:{pct_barra}%; height:100%; background:{cor_barra};"></div>
                </div>
                <div class="lle-kpi-suffix">mov. {fmt_brl(mov_conta)}</div>
                <div class="lle-kpi-suffix" style="opacity:.7;">{fmt_pct(pct_pares)} em pares</div>
                {linha_resolver}
            </div>
            """
        )
        if mostrar_botao:
            st.button(
                "Ver detalhamento →", key=f"banco_btn_{conta}",
                on_click=selecionar_banco, args=(conta,), use_container_width=True,
            )
        return

    # ---- VÁRIAS contas: card único (Opção 2) — tabela organizada + selo do banco ----
    # v5.45: tudo dentro de UM card (st.container border), fonte padronizada, selo
    # colorido por banco na 1ª coluna, separadores entre linhas e GRUPO como rodapé
    # no mesmo card. O botão "Ver →" continua NATIVO por linha (botão do Streamlit
    # não entra dentro de HTML), então não voltou a virar fileira embaixo.
    _ratios = [3.4, 1.05, 1.05, 0.8, 1.6, 1.15]

    def _cel(html, align="left", cor="#dfe8fb", peso="400", size="14px"):
        return (f'<div style="text-align:{align}; color:{cor}; font-weight:{peso}; '
                f'font-size:{size}; line-height:1.9;">{html}</div>')

    def _cor_banco(nome: str) -> str:
        u = nome.upper()
        if "SICREDI" in u:
            return "#3FA110"
        if "ITAU" in u or "ITAÚ" in u:
            return "#EC7000"
        if "BRADESCO" in u:
            return "#CC092F"
        if "CAIXA" in u:
            return "#0070AF"
        if "SANTANDER" in u:
            return "#EC0000"
        return "#5B6B8C"

    def _selo(nome: str) -> str:
        cor = _cor_banco(nome)
        return (
            '<span style="display:inline-flex;align-items:center;gap:9px;">'
            f'<span style="width:22px;height:22px;border-radius:6px;background:{cor};'
            'display:inline-flex;align-items:center;justify-content:center;font-size:12px;">'
            '🏦</span>'
            f'<span style="color:#fff;font-weight:600;">{nome}</span></span>'
        )

    _sep = '<div style="border-top:1px solid #16305d; margin:0;"></div>'

    with st.container(border=True):
        st.markdown(
            '<div style="color:#fff; font-size:15px; font-weight:600; margin-bottom:6px;">'
            'Contas processadas</div>', unsafe_allow_html=True)

        # Cabeçalho
        hc = st.columns(_ratios)
        for _col, _txt, _al in zip(
            hc, ["CONTA", "EXPLICADO", "CONFIRMADO", "ITENS", "A RESOLVER", ""],
            ["left", "center", "center", "center", "right", "left"],
        ):
            _col.markdown(_cel(_txt, _al, "#8BA3C7", size="11px"), unsafe_allow_html=True)

        total_itens = 0
        total_resolver = 0.0
        fechadas = 0
        for conta in contas_ordenadas:
            _mov, explic, confirm, _pp, qtd, valor = _metricas(conta)
            total_itens += qtd
            total_resolver += valor
            if qtd == 0:
                fechadas += 1
                itens_cell = '<span style="background:#0F8C3B; color:#fff; font-size:11px; padding:3px 9px; border-radius:20px;">ok</span>'
                resolver_cell = '<span style="color:#46d18a;">—</span>'
            else:
                cor_badge = "#9a7b12" if qtd <= 2 else "#D63031"
                itens_cell = f'<span style="background:{cor_badge}; color:#fff; font-size:11px; padding:3px 9px; border-radius:20px;">{qtd}</span>'
                resolver_cell = f'<span style="color:#ff8a8a; font-weight:500;">{fmt_brl(valor)}</span>'

            st.markdown(_sep, unsafe_allow_html=True)
            rc = st.columns(_ratios)
            rc[0].markdown(_cel(_selo(conta)), unsafe_allow_html=True)
            rc[1].markdown(_cel(fmt_pct(explic), "center"), unsafe_allow_html=True)
            rc[2].markdown(_cel(fmt_pct(confirm), "center"), unsafe_allow_html=True)
            rc[3].markdown(_cel(itens_cell, "center"), unsafe_allow_html=True)
            rc[4].markdown(_cel(resolver_cell, "right"), unsafe_allow_html=True)
            if mostrar_botao:
                rc[5].button("Ver →", key=f"banco_btn_{conta}",
                             on_click=selecionar_banco, args=(conta,),
                             use_container_width=True)

        # Rodapé GRUPO (no mesmo card)
        st.markdown('<div style="border-top:1px solid #24427e; margin:0;"></div>', unsafe_allow_html=True)
        gc = st.columns(_ratios)
        gc[0].markdown(
            _cel(f'GRUPO &middot; {fechadas} de {len(contas_ordenadas)} fechadas', "left", "#f4c430", "500"),
            unsafe_allow_html=True)
        gc[1].markdown(_cel("&mdash;", "center", "#6f86ad"), unsafe_allow_html=True)
        gc[2].markdown(_cel("&mdash;", "center", "#6f86ad"), unsafe_allow_html=True)
        gc[3].markdown(_cel(str(total_itens), "center", "#fff", "500"), unsafe_allow_html=True)
        gc[4].markdown(_cel(fmt_brl(total_resolver), "right", "#ff8a8a", "500"), unsafe_allow_html=True)

    st.markdown(
        '<div style="color:#6f86ad; font-size:11px; margin-top:8px;">As % do grupo ficam vazias '
        'de propósito — média de contas diferentes engana. Cada conta tem seu botão "Ver →" à direita.</div>',
        unsafe_allow_html=True)




# ============================================================
# Resumo com termômetros (% explicado) — v7
# ============================================================
def render_resumo_termometros(resultado: ResultadoConciliacao, kpis: dict):
    """v7: cabeçalho do resumo com dois termômetros.

    % explicado = (movimentado - falta conciliar) / movimentado  → conta o cartão
    (explicado pelo agrupamento TOP 1722), não só os pares 1-a-1. Mostra a
    composição (pares × regra de cartão) pra continuar auditável.
    """
    total_banco = float(kpis.get("total_movimentado_banco", 0.0))
    falta = float(kpis.get("falta_conciliar", 0.0))
    total_sis = float(kpis.get("total_extrato_sistema", 0.0))
    diverg = float(kpis.get("divergencia_sankhya_banco", 0.0))

    explicado = 100.0 * (total_banco - falta) / total_banco if total_banco > 0 else 0.0
    pares = float(kpis.get("percentual_conciliado", 0.0))
    regra = max(0.0, explicado - pares)
    sankhya_conf = 100.0 * (total_sis - diverg) / total_sis if total_sis > 0 else 0.0

    qtd_div = int(kpis.get("qtd_divergencia_sankhya_banco", 0))
    qtd_pend = int(kpis.get("qtd_pendentes_banco", 0))
    precisa = qtd_div + qtd_pend

    cor_banco = "#0F8C3B" if explicado >= 99.95 else ("#FAC318" if explicado >= 80 else "#D63031")
    cor_sis = "#0F8C3B" if sankhya_conf >= 99.95 else ("#FAC318" if sankhya_conf >= 80 else "#D63031")

    section_title("RESUMO EXECUTIVO")

    # Selo de veredito
    if precisa == 0 and explicado >= 99.95 and sankhya_conf >= 99.95:
        st.html(
            '<div style="background:rgba(15,140,59,0.12); border:1px solid rgba(15,140,59,0.5); '
            'border-radius:12px; padding:12px 16px; margin-bottom:16px;">'
            '<span style="background:#0F8C3B; color:#fff; font-size:13px; font-weight:600; '
            'padding:4px 12px; border-radius:999px;">&#10003; Conciliação fechada</span>'
            '<span style="color:#7DD87D; font-size:13px; margin-left:10px;">'
            '100% do banco explicado &middot; R$ 0,00 sem explicação</span></div>'
        )
    else:
        st.html(
            '<div style="background:rgba(214,48,49,0.10); border:1px solid rgba(214,48,49,0.4); '
            'border-radius:12px; padding:12px 16px; margin-bottom:16px;">'
            '<span style="color:#FF8A8A; font-size:13px;">&#9888; ' + str(precisa) + ' '
            + ("item precisa" if precisa == 1 else "itens precisam") + ' da sua análise</span></div>'
        )

    def _termo(label, pct, cor, sub):
        return (
            '<div class="lle-kpi">'
            '<div class="lle-kpi-label">' + label + '</div>'
            '<div class="lle-kpi-value" style="color:' + cor + ';">' + fmt_pct(pct) + '</div>'
            '<div style="height:9px; background:rgba(255,255,255,0.06); border-radius:999px; '
            'overflow:hidden; margin:10px 0 0;">'
            '<div style="width:' + str(max(0.0, min(100.0, pct))) + '%; height:100%; background:' + cor + ';"></div></div>'
            '<div class="lle-kpi-suffix">' + sub + '</div></div>'
        )

    # v5.35: nomeia a regra que DE FATO explicou (boleto/cartão), em vez de cravar
    # "cartão". Se não houve agrupamento, mostra só os pares diretos.
    _regras_nomes = []
    if int(kpis.get("qtd_top1702_grupos", 0)) > 0:
        _regras_nomes.append("boleto")
    if int(kpis.get("qtd_top1722_grupos", 0)) > 0:
        _regras_nomes.append("cartão")
    if regra > 0.05:
        _rot = ("por agrupamento de " + " e ".join(_regras_nomes)) if _regras_nomes else "por agrupamento"
        sub_banco = fmt_pct(pares) + " em pares diretos &middot; " + fmt_pct(regra) + " " + _rot
    else:
        sub_banco = fmt_pct(pares) + " em pares diretos"
    sub_sis = (str(qtd_div) + " lançamento" + ("s" if qtd_div != 1 else "") + " sem confirmação"
               if qtd_div else "0 lançamentos sem confirmação no banco")
    st.html(
        '<div style="display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:14px;">'
        + _termo("Banco explicado pelo ERP", explicado, cor_banco, sub_banco)
        + _termo("Sankhya confirmado no banco", sankhya_conf, cor_sis, sub_sis)
        + '</div>'
    )

    # Cards: Precisa de você + 2 volumes + Investimentos
    if precisa == 0:
        precisa_card = card_kpi("Precisa de você", "0 itens",
                                "nada pendente de decisão", classe="destaque-verde")
    else:
        precisa_card = card_kpi("Precisa de você",
                                str(precisa) + (" item" if precisa == 1 else " itens"),
                                fmt_brl(falta + diverg) + " a resolver", classe="destaque-vermelho")
    # v5.35: a diferença vai no card do lado que movimentou MAIS, e só cita "cartão"
    # quando a conta tem cartão. Sem cartão, fala a verdade: "a analisar".
    diff_assinado = round(total_banco - total_sis, 2)
    abs_diff = abs(diff_assinado)
    nota_diff = ""
    if abs_diff >= 0.01:
        _tem_cartao = int(kpis.get("qtd_top1722_grupos", 0)) > 0
        _lado = ("Banco movimentou " + fmt_brl(abs_diff) + " a mais que o Sankhya"
                 if diff_assinado > 0
                 else "Sankhya movimentou " + fmt_brl(abs_diff) + " a mais que o banco")
        nota_diff = _lado + (" — pode incluir taxa de cartão lançada 2x; o restante a analisar."
                             if _tem_cartao else " — a analisar.")
    if diff_assinado > 0:
        banco_card = card_kpi("Movimentado no Banco", fmt_brl(total_banco), nota_diff)
        sankhya_card = card_kpi("Movimentado no Sankhya", fmt_brl(total_sis))
    elif diff_assinado < 0:
        banco_card = card_kpi("Movimentado no Banco", fmt_brl(total_banco))
        sankhya_card = card_kpi("Movimentado no Sankhya", fmt_brl(total_sis), nota_diff)
    else:
        banco_card = card_kpi("Movimentado no Banco", fmt_brl(total_banco))
        sankhya_card = card_kpi("Movimentado no Sankhya", fmt_brl(total_sis))
    render_cards([precisa_card, banco_card, sankhya_card, _card_investimentos(resultado)])


# ============================================================
# Página: Conciliação
# ============================================================
def pagina_conciliacao():
    if st.session_state.fluxo_etapa == "resultado" and st.session_state.resultado is not None:
        tela_resultado()
    else:
        tela_upload()


def tela_upload():
    section_title("CONFIGURAR EXECUÇÃO")

    col_modo, col_data = st.columns([2, 1])
    with col_modo:
        modo = st.radio(
            "Modo de execução",
            ["1 conta por vez", "Várias contas de uma vez"],
            horizontal=True,
        )
    with col_data:
        # v5.10: período opcional — ignora lançamentos fora da janela (ex.: extrato
        # baixado até 02/07, mas você quer analisar só junho). Banco e Sankhya usam
        # a mesma data efetiva, então o filtro simples resolve.
        usar_periodo = st.checkbox(
            "Filtrar por período",
            value=False,
            help="Ignora lançamentos fora da janela, no extrato e no Sankhya. "
            "Útil quando o extrato baixa acumulando dias.",
        )
        if usar_periodo:
            cini, cfim = st.columns(2)
            periodo_ini = cini.date_input("Início", value=date.today().replace(day=1), format="DD/MM/YYYY")
            periodo_fim = cfim.date_input("Fim", value=date.today(), format="DD/MM/YYYY")
            data_ref = periodo_fim
        else:
            periodo_ini = periodo_fim = None
            data_ref = st.date_input(
                "Data de referência",
                value=date.today(),
                format="DD/MM/YYYY",
            )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        section_title("EXTRATO BANCÁRIO")
        st.caption("Formato padronizado: Data, Histórico, Documento, Valor (R$). Aceita XLS, XLSX ou PDF do extrato bancário (Itaú, Sicredi, Bradesco, Caixa, Santander).")
        if modo == "1 conta por vez":
            arquivo_banco = st.file_uploader(
                "Arraste o extrato",
                type=["xlsx", "xls", "pdf"],
                key="banco_single",
            )
            # v5.8: auto-preenche o nome da conta a partir do nome do arquivo.
            # v5.9: e, quando dá, LÊ a conta do cabeçalho do próprio extrato
            # (banco + agência + conta), pra não depender do nome do arquivo.
            nome_default = ""
            conta_det = None
            if arquivo_banco is not None:
                nome_default = arquivo_banco.name.rsplit(".", 1)[0].strip()
                try:
                    import io as _io_det
                    from src.parsers.deteccao_conta import detectar_conta_extrato
                    _b = _io_det.BytesIO(arquivo_banco.getvalue())
                    _b.name = arquivo_banco.name
                    conta_det = detectar_conta_extrato(_b)
                    _cores_banco = {
                        "Bradesco": "#CC092F", "Santander": "#EC0000", "Sicredi": "#3FA110",
                        "Caixa": "#005CA9", "Itaú": "#EC7000",
                    }
                    if conta_det.confianca == "alta":
                        _cor = _cores_banco.get(conta_det.banco, "#6f88b8")
                        _emp = f" · {conta_det.empresa}" if conta_det.empresa else ""
                        st.markdown(
                            f'<div style="display:flex;align-items:center;gap:12px;background:#0b2560;'
                            f'border-radius:10px;border-left:6px solid {_cor};padding:9px 13px;margin:2px 0 8px;">'
                            f'<span style="background:{_cor};color:#fff;font-size:11px;font-weight:700;'
                            f'letter-spacing:.03em;padding:3px 11px;border-radius:6px;">{conta_det.banco.upper()}</span>'
                            f'<span style="color:#eaf0fb;font-size:12.5px;">agência {conta_det.agencia} · '
                            f'conta {conta_det.conta}{_emp}</span></div>',
                            unsafe_allow_html=True,
                        )
                        if conta_det.identificador:
                            nome_default = conta_det.identificador
                    else:
                        st.markdown(
                            '<div style="display:flex;align-items:center;gap:12px;background:#0b2560;'
                            'border-radius:10px;border-left:6px solid #6f88b8;padding:9px 13px;margin:2px 0 8px;">'
                            '<span style="background:#6f88b8;color:#041747;font-size:11px;font-weight:700;'
                            'letter-spacing:.03em;padding:3px 11px;border-radius:6px;">NÃO IDENTIFICADO</span>'
                            '<span style="color:#9fb3d6;font-size:12.5px;">não consegui ler a conta do cabeçalho '
                            '— confirme na lista abaixo</span></div>',
                            unsafe_allow_html=True,
                        )
                except Exception:
                    conta_det = None

            # v5.35: se o Sankhya já foi enviado, oferece os nomes de conta dele
            # numa lista (string idêntica à que o matcher usa), em vez de um campo
            # de texto onde o nome entra com underline/espaço/maiúscula errados.
            contas_sankhya = _ler_contas_sankhya_da_sessao()
            if contas_sankhya:
                opcoes = contas_sankhya + [_OPCAO_DIGITAR]
                idx_match = _melhor_match_conta(nome_default, contas_sankhya)
                # v5.9: se lemos o número da conta no extrato, ele é o critério
                # mais forte — casa com a conta do Sankhya que contém esse número.
                if conta_det is not None and getattr(conta_det, "conta_digitos", ""):
                    import re as _re_conta
                    alvo = conta_det.conta_digitos
                    for _j, _opt in enumerate(contas_sankhya):
                        if alvo and alvo in _re_conta.sub(r"\D", "", str(_opt)):
                            idx_match = _j
                            break
                idx_default = idx_match if idx_match is not None else len(opcoes) - 1
                escolha = st.selectbox(
                    "Extrato Bancário (identificador da conta)",
                    opcoes,
                    index=idx_default,
                    key="conta_single_sel",
                    help="Nomes lidos do Sankhya. Escolha o da conta deste extrato "
                    "— assim casa sem erro de digitação.",
                )
                if escolha == _OPCAO_DIGITAR:
                    nome_conta = st.text_input(
                        "Nome da conta (nova — ainda não está no Sankhya)",
                        value=nome_default,
                        key="conta_single_novo",
                    ).strip()
                else:
                    nome_conta = escolha
            else:
                st.caption(
                    "Suba o relatório do Sankhya ao lado para escolher a conta "
                    "numa lista. Por enquanto, digite o identificador."
                )
                nome_conta = st.text_input(
                    "Extrato Bancário (identificador da conta)",
                    value=nome_default,
                    placeholder="ex: Bradesco-CC-12345",
                    key="conta_single",
                    help="Rótulo único da conta. Mínimo 3 caracteres.",
                ).strip()
            arquivos_banco = (
                [(nome_conta, arquivo_banco)]
                if arquivo_banco and nome_conta
                else []
            )
        else:
            contas_sankhya = _ler_contas_sankhya_da_sessao()
            arquivos_multi = st.file_uploader(
                "Arraste os extratos (um por conta)",
                type=["xlsx", "xls", "pdf"],
                accept_multiple_files=True,
                key="banco_multi",
            )
            if not (arquivos_multi or []):
                st.caption(
                    "Suba os extratos e o Sankhya — depois escolha a conta de "
                    "cada arquivo numa lista."
                )
            arquivos_banco = []
            for f in (arquivos_multi or []):
                base = f.name.rsplit(".", 1)[0].strip()
                if contas_sankhya:
                    opcoes = contas_sankhya + [_OPCAO_DIGITAR]
                    idx_match = _melhor_match_conta(base, contas_sankhya)
                    idx_default = (
                        idx_match if idx_match is not None else len(opcoes) - 1
                    )
                    escolha = st.selectbox(
                        f"Conta de “{f.name}”",
                        opcoes,
                        index=idx_default,
                        key=f"conta_multi_sel_{f.name}",
                        help="Nome da conta como aparece no Sankhya.",
                    )
                    if escolha == _OPCAO_DIGITAR:
                        nome_arq = st.text_input(
                            f"Nome da conta (nova) para “{f.name}”",
                            value=base,
                            key=f"conta_multi_novo_{f.name}",
                        ).strip()
                    else:
                        nome_arq = escolha
                else:
                    nome_arq = base
                if nome_arq:
                    arquivos_banco.append((nome_arq, f))

    with col2:
        section_title("EXTRATO SANKHYA CONCILIAÇÃO")
        st.caption("Relatório de Conciliação Bancária exportado do ERP.")
        arquivo_sistema = st.file_uploader(
            "Arraste o(s) relatório(s) do sistema",
            type=["xlsx", "xls"],
            key="sistema",
            accept_multiple_files=True,
            help="Pode subir mais de um (ex.: um relatório do Sankhya por conta/banco). O app junta todos antes de conciliar.",
        )
        coluna_conta_sistema = st.text_input(
            "Extrato Sankhya Conciliação — coluna da conta",
            value="",
            placeholder="(deixe vazio para auto-detectar)",
            key="coluna_conta_sistema",
            help="Nome exato da coluna do ERP que identifica a conta. Se vazio, tenta detectar.",
        )

    st.divider()
    section_title("EXTRATO DA ADQUIRENTE (OPCIONAL)")
    st.caption(
        "Só pra contas que recebem cartão. Aceita GetNet (Recebíveis) e PagBank/PagSeguro. "
        "Pode subir vários. Conta sem cartão não precisa subir nada — tudo funciona igual."
    )
    arquivos_adquirente = st.file_uploader(
        "Arraste o extrato da adquirente (GetNet / PagBank)",
        type=["xlsx", "xls", "csv"],
        key="adquirente",
        accept_multiple_files=True,
        help="Usado pra dar NOME à diferença de cartão (aluguel, tarifa, estorno) na conciliação "
        "e pra alimentar a Auditoria de Cartões (taxa cobrada × taxa de contrato).",
    )

    st.divider()
    section_title("PENDÊNCIAS DE DIAS ANTERIORES (OPCIONAL)")
    arquivo_pendencias = st.file_uploader(
        "Relatório anterior (lê a aba 'Pendências Consolidadas')",
        type=["xlsx"],
        key="pendencias",
    )

    st.divider()

    # Validações
    erros_validacao: list[str] = []
    for nome, _ in arquivos_banco:
        erro = validar_nome_conta(nome)
        if erro:
            erros_validacao.append(erro)

    pode_executar = (
        bool(arquivos_banco) and bool(arquivo_sistema) and not erros_validacao
    )

    # v5.35: rede de segurança — nome do banco quase-igual a uma conta do Sankhya
    # (só muda espaço/underline/maiúscula). Avisa ANTES de conciliar e corrige
    # num clique, em vez de separar calado em duas contas.
    if contas_sankhya and arquivos_banco:
        norm_sankhya = {_norm_conta(c): c for c in contas_sankhya}
        for _nome, _f in arquivos_banco:
            if _nome in contas_sankhya:
                continue
            _alvo = norm_sankhya.get(_norm_conta(_nome))
            if _alvo and _alvo != _nome:
                _c1, _c2 = st.columns([4, 1])
                with _c1:
                    st.warning(
                        f"⚠️ “{_nome}” parece ser a mesma conta que "
                        f"**{_alvo}** no Sankhya (só muda espaço, underline ou "
                        f"maiúscula). Com nomes diferentes elas viram duas contas "
                        f"e não conciliam."
                    )
                with _c2:
                    if st.button(f"Usar “{_alvo}”", key=f"fix_conta_{_f.name}"):
                        if modo == "1 conta por vez":
                            st.session_state["conta_single_sel"] = _alvo
                        else:
                            st.session_state[f"conta_multi_sel_{_f.name}"] = _alvo
                        st.rerun()

    # v5.8: mensagem espec\u00edfica em vez do gen\u00e9rico "Aguardando upload"
    if not pode_executar:
        faltando: list[str] = []
        # No modo "1 conta por vez": pode faltar o nome da conta mesmo com arquivo
        if modo == "1 conta por vez":
            tem_arquivo_banco = bool(locals().get("arquivo_banco"))
            tem_nome_conta = bool(locals().get("nome_conta", "").strip())
            if not tem_arquivo_banco:
                faltando.append("**Extrato Bancário** (.xlsx ou .xls)")
            elif not tem_nome_conta:
                faltando.append("**Identificador da conta** (campo de texto abaixo do extrato banc\u00e1rio)")
        else:
            if not arquivos_banco:
                faltando.append("**Extratos Banc\u00e1rios** (.xlsx ou .xls)")
        if not arquivo_sistema:
            faltando.append("**Relat\u00f3rio Sankhya** (.xlsx ou .xls)")

        if faltando and not erros_validacao:
            if len(faltando) == 1:
                st.warning(f"⏳ Falta: {faltando[0]}")
            else:
                lista = "\n".join(f"- {f}" for f in faltando)
                st.warning(f"⏳ Para executar a conciliação ainda falta:\n\n{lista}")
        elif erros_validacao:
            for e in erros_validacao:
                st.error(f"❌ {e}")

    # Para sidebar — recupera config
    rodar_fuzzy = st.session_state.get("rodar_fuzzy", True)
    tolerancia = int(st.session_state.get("tolerancia", 2))

    if st.button(
        "▶️ Executar conciliação",
        type="primary",
        disabled=not pode_executar,
        use_container_width=True,
    ):
        with st.spinner("Processando... isso pode levar alguns segundos."):
            try:
                dfs_banco = []
                for nome_conta, arq in arquivos_banco:
                    df = carregar_extrato_banco(
                        arq, conta=nome_conta, ano_referencia=data_ref.year
                    )
                    dfs_banco.append(df)
                banco = pd.concat(dfs_banco, ignore_index=True) if dfs_banco else pd.DataFrame()

                # v3.6: força tipos consistentes após concat de múltiplos extratos.
                # Sem isso, se um extrato vier com 'data' como string e outro como datetime,
                # o merge no pipeline quebra com 'merge on object and datetime64 columns'.
                if not banco.empty:
                    if "data" in banco.columns:
                        banco["data"] = pd.to_datetime(banco["data"], errors="coerce")
                    if "valor" in banco.columns:
                        banco["valor"] = pd.to_numeric(banco["valor"], errors="coerce").fillna(0.0)
                    # Remove linhas com data inválida (NaT) — não dá pra conciliar sem data
                    linhas_antes = len(banco)
                    banco = banco.dropna(subset=["data"]).reset_index(drop=True)
                    linhas_descartadas = linhas_antes - len(banco)
                    if linhas_descartadas > 0:
                        st.warning(
                            f"⚠️ {linhas_descartadas} linha(s) do extrato bancário "
                            f"foram descartadas por terem data inválida ou vazia."
                        )

                # Múltiplos relatórios do Sankhya: carrega cada um e junta tudo.
                _lista_sistema = arquivo_sistema if isinstance(arquivo_sistema, list) else [arquivo_sistema]
                _dfs_sistema = []
                for _arq_sis in _lista_sistema:
                    _dfs_sistema.append(
                        carregar_relatorio_sistema(
                            _arq_sis,
                            coluna_conta=coluna_conta_sistema or None,
                        )
                    )
                sistema = (
                    pd.concat(_dfs_sistema, ignore_index=True)
                    if _dfs_sistema else pd.DataFrame()
                )

                # v3.6: mesmo tratamento para o sistema
                if not sistema.empty:
                    if "data" in sistema.columns:
                        sistema["data"] = pd.to_datetime(sistema["data"], errors="coerce")
                    if "valor" in sistema.columns:
                        sistema["valor"] = pd.to_numeric(sistema["valor"], errors="coerce").fillna(0.0)
                    sistema = sistema.dropna(subset=["data"]).reset_index(drop=True)

                # v5.10: aplica o filtro de período (quando ligado) — ignora tudo
                # fora da janela, no extrato E no Sankhya. Como os dois usam a mesma
                # data efetiva, o corte simples fecha certo (feriado empurra p/ o
                # próximo período nos dois lados). O saldo se reajusta às bordas
                # porque saldo_final_da_conta pega a 1ª/última linha de saldo por data.
                if usar_periodo and periodo_ini and periodo_fim:
                    _ini = pd.Timestamp(periodo_ini).normalize()
                    _fim = pd.Timestamp(periodo_fim).normalize()
                    _ab, _as = len(banco), len(sistema)
                    if not banco.empty and "data" in banco.columns:
                        _dn = banco["data"].dt.normalize()
                        banco = banco[(_dn >= _ini) & (_dn <= _fim)].reset_index(drop=True)
                    if not sistema.empty and "data" in sistema.columns:
                        _dn = sistema["data"].dt.normalize()
                        sistema = sistema[(_dn >= _ini) & (_dn <= _fim)].reset_index(drop=True)
                    st.info(
                        f"📅 Período {periodo_ini.strftime('%d/%m/%Y')}–{periodo_fim.strftime('%d/%m/%Y')}: "
                        f"extrato {_ab}→{len(banco)} linha(s) · Sankhya {_as}→{len(sistema)} linha(s). "
                        "Lançamentos fora da janela foram ignorados."
                    )

                if modo == "1 conta por vez" and not sistema.empty and (sistema["conta"] == "—").all():
                    sistema["conta"] = arquivos_banco[0][0]
                    st.info(
                        f"ℹ️ Relatório do sistema sem coluna de conta — atribuído a '{arquivos_banco[0][0]}'."
                    )
                elif modo != "1 conta por vez" and not sistema.empty:
                    # Modo várias contas: avisar se há contas no Sankhya que não existem no banco
                    contas_banco = {nome for nome, _ in arquivos_banco}
                    contas_sis = set(sistema["conta"].unique()) - {"—"}
                    if contas_sis and not (contas_sis & contas_banco):
                        st.warning(
                            f"⚠️ As contas no Sankhya **{sorted(contas_sis)}** não "
                            f"coincidem com nenhum dos identificadores dos extratos "
                            f"bancários enviados **{sorted(contas_banco)}**. Resultado "
                            f"será 0% conciliado. Verifique se o identificador da conta "
                            f"informado para cada extrato bancário corresponde ao valor "
                            f"da coluna de conta no relatório do Sankhya."
                        )
                    elif (sistema["conta"] == "—").any():
                        qtd = int((sistema["conta"] == "—").sum())
                        msg = (
                            f"⚠️ {qtd} linha(s) do Sankhya estão sem identificador de "
                            f"conta."
                        )
                        if coluna_conta_sistema:
                            msg += (
                                f" Você informou que a coluna da conta no Sankhya é "
                                f"**'{coluna_conta_sistema}'** mas ela não foi encontrada "
                                f"no arquivo ou veio vazia. Verifique o nome exato da "
                                f"coluna no Sankhya (atenção a maiúsculas e acentos)."
                            )
                        else:
                            msg += (
                                " Inclua uma coluna 'Conta' na planilha do Sankhya antes "
                                "de subir, ou informe o nome dela no campo "
                                "'Extrato Sankhya — coluna da conta', ou troque para o "
                                "modo '1 conta por vez'."
                            )
                        st.warning(msg)

                pendencias = carregar_pendencias_anteriores(arquivo_pendencias)

                # Detecta reprocessamento (já existe execução anterior nesta sessão)
                exec_anterior = st.session_state.id_execucao_atual
                versao = 1
                id_origem = None
                if exec_anterior:
                    versao = 2  # versionamento simples
                    id_origem = exec_anterior

                resultado = executar_pipeline(
                    banco, sistema,
                    data_referencia=datetime.combine(data_ref, datetime.min.time()),
                    tolerancia_dias=tolerancia,
                    rodar_fuzzy=rodar_fuzzy,
                )

                # Fase 1: rede de segurança — avisa se banco e Sankhya cobrem períodos
                # diferentes (descasamento infla a 'Falta Conciliar', como no susto do PDF).
                st.session_state.aviso_periodo = _checar_periodo(banco, sistema)

                id_exec = novo_id_execucao()

                # v5.34: NÃO gera o Excel aqui. Em volume alto (ex.: Santander, 12k+69k)
                # a geração levava ~3 min e segurava a tela em "Processando...". O Excel
                # passa a ser gerado sob demanda, quando o usuário clica em "Gerar Excel".

                # Snapshot append-only
                try:
                    salvar_snapshot(
                        id_exec, banco, sistema,
                        parametros={
                            "data_referencia": resultado.data_referencia,
                            "tolerancia_dias": tolerancia,
                            "rodar_fuzzy": rodar_fuzzy,
                            "modo": modo,
                            "contas": resultado.contas_processadas,
                            "versao": versao,
                            "id_origem": id_origem,
                        },
                        relatorio_xlsx=None,
                    )
                    registrar_execucao(
                        id_exec=id_exec,
                        data_referencia=resultado.data_referencia,
                        contas=resultado.contas_processadas,
                        tolerancia_dias=tolerancia,
                        kpis=resultado.kpis_globais(),
                        arquivos_inputs=[n for n, _ in arquivos_banco] + ["sistema.xlsx"],
                        status="reprocessado" if versao > 1 else "processado",
                        versao=versao,
                        id_origem=id_origem,
                    )
                except Exception as e:
                    st.warning(f"⚠️ Auditoria não pôde ser salva no disco: {e}. "
                               "Os resultados estão disponíveis para download mesmo assim.")

                st.session_state.resultado = resultado
                st.session_state.adquirente_df = _adquirentes_da_sessao()
                # v5.43: guarda os BYTES crus dos extratos de adquirente numa chave
                # própria (não some ao trocar de página) pra a Auditoria de Cartões
                # reaproveitar sem exigir novo upload.
                _adq_files = st.session_state.get("adquirente") or []
                if _adq_files and not isinstance(_adq_files, list):
                    _adq_files = [_adq_files]
                try:
                    st.session_state.adquirente_bytes = [
                        (f.name, f.getvalue()) for f in _adq_files
                    ]
                except Exception:
                    st.session_state.adquirente_bytes = []
                st.session_state.pendencias_anteriores = pendencias
                st.session_state.id_execucao_atual = id_exec
                st.session_state.xlsx_atual = None  # v5.34: gera sob demanda (volume)
                st.session_state.csvs_zip_atual = None  # força regerar quando precisar
                st.session_state.fluxo_etapa = "resultado"
                st.rerun()

            except Exception as e:
                st.error(f"❌ Erro durante o processamento:\n\n```\n{e}\n```")
                import traceback
                with st.expander("Stack trace completo"):
                    st.code(traceback.format_exc())


# ============================================================
# Tela de RESULTADO (única, pós-upload)
# ============================================================
def _checar_periodo(banco: pd.DataFrame, sistema: pd.DataFrame) -> str | None:
    """Compara o intervalo de datas do banco e do Sankhya; retorna um aviso se
    cobrirem períodos diferentes (causa comum de 'Falta Conciliar' inflada)."""
    try:
        if "data" not in banco.columns or "data" not in sistema.columns:
            return None
        bmin, bmax = banco["data"].min(), banco["data"].max()
        smin, smax = sistema["data"].min(), sistema["data"].max()
        if pd.isna(bmin) or pd.isna(bmax) or pd.isna(smin) or pd.isna(smax):
            return None
        if abs((bmax - smax).days) > 3 or abs((bmin - smin).days) > 3:
            return (
                f"⚠️ **Períodos diferentes.** O extrato do banco vai de "
                f"{bmin:%d/%m/%Y} a {bmax:%d/%m/%Y} e o Sankhya de "
                f"{smin:%d/%m/%Y} a {smax:%d/%m/%Y}. Quando os dois não cobrem o "
                f"mesmo período, sobram lançamentos sem par e a 'Falta Conciliar' "
                f"sobe. Confira se os arquivos são do mesmo mês."
            )
    except Exception:
        return None
    return None


def tela_resultado():
    resultado: ResultadoConciliacao = st.session_state.resultado
    kpis = resultado.kpis_globais()

    aviso_periodo = st.session_state.get("aviso_periodo")
    if aviso_periodo:
        st.warning(aviso_periodo)

    # Topo: botão voltar (menor) + ações principais (em destaque, amarelas)
    col_top1, col_top2, col_top3 = st.columns([1, 2, 2])
    with col_top1:
        st.button(
            "← Nova conciliação",
            on_click=voltar_upload,
            use_container_width=True,
            key="btn_voltar_topo",
        )
    with col_top2:
        nome = f"conciliacao_{resultado.data_referencia.strftime('%Y%m%d')}.xlsx"
        if st.session_state.get("xlsx_atual"):
            st.download_button(
                "⬇️ Excel (todas as abas)",
                data=st.session_state.xlsx_atual,
                file_name=nome,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )
        elif st.button("⬇️ Gerar Excel", type="primary", use_container_width=True,
                       key="btn_gerar_xlsx"):
            with st.spinner("Gerando Excel… em volume grande pode levar alguns minutos."):
                st.session_state.xlsx_atual = gerar_relatorio_excel(
                    resultado,
                    pendencias_anteriores=st.session_state.pendencias_anteriores,
                )
            st.rerun()
    with col_top3:
        nome_zip = f"conciliacao_{resultado.data_referencia.strftime('%Y%m%d')}_csvs.zip"
        if st.session_state.get("csvs_zip_atual"):
            st.download_button(
                "⬇️ CSVs (zip)",
                data=st.session_state.csvs_zip_atual,
                file_name=nome_zip,
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )
        elif st.button("⬇️ Gerar CSVs (zip)", type="primary", use_container_width=True,
                       key="btn_gerar_csvs"):
            with st.spinner("Gerando CSVs…"):
                st.session_state.csvs_zip_atual = gerar_csvs_zip(resultado)
            st.rerun()

    st.divider()

    # v3.9: RESUMO EXECUTIVO global só aparece quando NENHUMA conta está selecionada.
    # Quando o usuário entra no detalhamento de uma conta específica, mostra direto
    # o detalhe da conta — evita confundir KPIs globais com KPIs da conta selecionada.
    if not st.session_state.banco_conta_selecionada:
        render_resumo_termometros(resultado, kpis)

        # v5.14: Removida a seção "Exceções e Regras Aplicadas" (estornos + TOP 1722).
        # A lógica continua rodando — mas o resumo não exibe mais esses cards.
        # TOP 1722 aparece na aba dedicada dentro do detalhamento da conta.

    # Painel de bancos OU detalhe do banco selecionado
    if st.session_state.banco_conta_selecionada:
        tela_detalhamento_banco(resultado, st.session_state.banco_conta_selecionada)
    else:
        section_title("CONTAS PROCESSADAS — CLIQUE PARA DETALHAR")
        render_painel_bancos(resultado)
        # v5.14: Removida "CONCILIAÇÃO POR TIPO DE LANÇAMENTO" do resumo.
        # Os mesmos dados aparecem dentro do detalhamento de cada conta (sem duplicar).


# ============================================================
# Detalhamento por banco — cards + abas internas
# ============================================================
def _diferenca_bxs_por_dia(resultado: "ResultadoConciliacao", conta: str) -> list[tuple]:
    """Diferença |banco| − |Sankhya| por dia, com o MESMO filtro do KPI de
    'movimentado' (exclui saldo/aplicação/resgate/rendimento). Retorna lista de
    (data, dif) só com os dias que divergem (|dif| >= 0,01), ordenada do maior
    para o menor em módulo. Serve pra apontar no alerta EM QUE DIA está a
    diferença — num extrato de 30 dias, isso leva direto ao ponto."""
    _excl = ("saldo", "aplicacao", "resgate", "rendimento")

    def _abs_por_dia(df):
        if df is None or getattr(df, "empty", True):
            return pd.Series(dtype=float)
        d = df
        if "conta" in d.columns:
            d = d[d["conta"] == conta]
        if "categoria_mov" in d.columns:
            d = d[~d["categoria_mov"].isin(_excl)]
        if d.empty:
            return pd.Series(dtype=float)
        dia = pd.to_datetime(d["data"], errors="coerce").dt.normalize()
        return d["valor"].abs().groupby(dia).sum()

    gb = _abs_por_dia(resultado.banco_completo)
    gs = _abs_por_dia(resultado.sistema_completo)
    dias = sorted(set(gb.index) | set(gs.index))
    out = []
    for dia in dias:
        dif = round(float(gb.get(dia, 0.0)) - float(gs.get(dia, 0.0)), 2)
        if abs(dif) >= 0.01:
            out.append((dia, dif))
    out.sort(key=lambda x: abs(x[1]), reverse=True)
    return out


def _explicar_diferenca_cartao(resultado, conta: str, adq: pd.DataFrame):
    """Tenta explicar a diferença de volume de cada dia pela adquirente.

    Mecanismo confirmado: tarifa/aluguel do GetNet entram 2× no volume (o Sankhya
    lança a tarifa como despesa E dentro do bruto; o banco já vem líquido). Então
    se a diferença do dia == 2 × (aluguel+tarifa GetNet daquele dia), está EXPLICADA.
    Só marca 'explicado' quando bate EXATO — nunca crava.

    Retorna (partes, todos_explicados):
      partes = [(data, dif_assinada, texto_ou_None), ...]  (ordenada por |dif|)
    """
    dias = _diferenca_bxs_por_dia(resultado, conta)
    if not dias:
        return [], True
    tem_adq = adq is not None and not adq.empty
    adq_dt = (
        pd.to_datetime(adq["data"], errors="coerce").dt.normalize() if tem_adq else None
    )
    partes = []
    todos = True
    for d, v in dias:
        alvo = round(abs(v), 2)
        expl = None
        if tem_adq:
            gn = adq[
                (adq_dt == pd.Timestamp(d))
                & (adq["adquirente"] == "GetNet")
                & (adq["categoria"].isin(["aluguel", "tarifa"]))
            ]
            soma = round(float(gn["valor"].abs().sum()), 2)
            if soma > 0 and round(2 * soma, 2) == alvo:
                itens = "; ".join(
                    f"{desc} ({fmt_brl(abs(val))})"
                    for desc, val in zip(gn["descricao"], gn["valor"])
                )
                expl = (
                    itens
                    + " — a adquirente descontou essa taxa <b>dentro de um repasse do dia</b>: "
                    "entrou o valor cheio e saiu a taxa (uma entrada e uma saída do mesmo valor). "
                    "O Sankhya registra as duas pontas; o banco já recebe líquido — por isso conta 2× no volume."
                )
        if expl is None:
            todos = False
        partes.append((d, v, expl))
    return partes, todos


_ROTULOS_CARTAO = {
    "estorno": "Estorno / Cancelamento",
    "aluguel": "Aluguel de maquininha",
    "tarifa": "Tarifa / Excedentes",
    "repasse": "Repasse (cai no banco)",
    "venda": "Vendas",
    "saldo": "Saldo",
    "outros": "Outros",
}


def render_tab_diferenca_cartao(adq: pd.DataFrame, resultado, conta: str):
    """Aba 'Diferença de Cartão': usa o extrato da adquirente pra dar NOME às
    tarifas/aluguéis/estornos e amarrar isso à diferença de volume por dia.
    Só mostra o que está no arquivo — nada é cravado."""
    st.caption(
        "Extrato da adquirente (GetNet/PagBank) — dá nome às tarifas, aluguéis e "
        "estornos de cartão e amarra à diferença de volume. Nada é cravado sem estar no arquivo."
    )
    if adq is None or adq.empty:
        st.info(
            "Nenhum extrato de adquirente foi enviado nesta execução. Suba o GetNet "
            "(Recebíveis) e/ou PagBank na tela de upload — é opcional — pra ver o mapa de cartão aqui."
        )
        return

    # Mapa por ADQUIRENTE + categoria. O PagBank/PagSeguro é extrato de RECEBIMENTO:
    # não detalha vendas de forma confiável, então não exibimos 'venda'/'saldo' dele.
    g = (
        adq.assign(_abs=adq["valor"].abs())
        .groupby(["adquirente", "categoria"])
        .agg(qtd=("valor", "size"), total=("_abs", "sum"))
        .reset_index()
    )
    g = g[~((g["adquirente"] == "PagBank") & (g["categoria"].isin(["venda", "saldo"])))]
    g = g.sort_values(["adquirente", "total"], ascending=[True, False])
    mapa = pd.DataFrame(
        {
            "Adquirente": g["adquirente"].values,
            "Categoria": [_ROTULOS_CARTAO.get(c, c) for c in g["categoria"]],
            "Qtd": g["qtd"].astype(int).values,
            "Total": [fmt_brl(v) for v in g["total"]],
        }
    )
    st.markdown("**Mapa de cartão — por adquirente e categoria (valores do extrato)**")
    st.dataframe(mapa, hide_index=True, use_container_width=True)

    # Amarra a diferença de volume (por dia) ao que a adquirente mostra naquele dia.
    dias = _diferenca_bxs_por_dia(resultado, conta)
    if dias:
        adq_dt = pd.to_datetime(adq["data"], errors="coerce").dt.normalize()
        linhas = []
        for d, v in dias[:12]:
            no_dia = adq[
                (adq_dt == pd.Timestamp(d))
                & (adq["categoria"].isin(["aluguel", "tarifa", "estorno"]))
            ]
            if not no_dia.empty:
                no_dia = no_dia.reindex(
                    no_dia["valor"].abs().sort_values(ascending=False).index
                )
                expl = "; ".join(
                    f"{_ROTULOS_CARTAO.get(c, c)}: {fmt_brl(abs(val))} ({desc})"
                    for c, val, desc in zip(
                        no_dia["categoria"], no_dia["valor"], no_dia["descricao"]
                    )
                )
            else:
                expl = "— (não há tarifa/estorno da adquirente neste dia)"
            linhas.append(
                {"Dia": d.strftime("%d/%m"), "Diferença de volume": fmt_brl(abs(v)), "O que a adquirente mostra": expl}
            )
        st.markdown("**Diferença de volume Banco × Sankhya, dia a dia — explicada pela adquirente**")
        st.caption(
            "Tarifa/aluguel entram 2× no volume (o Sankhya lança a tarifa e o bruto; "
            "o banco já vem líquido), por isso a diferença costuma ser ~2× o valor da tarifa."
        )
        st.dataframe(pd.DataFrame(linhas), hide_index=True, use_container_width=True)

    # Detalhe das tarifas/aluguéis/estornos
    custos = adq[adq["categoria"].isin(["estorno", "aluguel", "tarifa"])].copy()
    if not custos.empty:
        custos = custos.sort_values("data")
        det = pd.DataFrame(
            {
                "Dia": pd.to_datetime(custos["data"]).dt.strftime("%d/%m"),
                "Adquirente": custos["adquirente"].values,
                "Bandeira": custos["bandeira"].values,
                "Lançamento": custos["descricao"].values,
                "Categoria": [_ROTULOS_CARTAO.get(c, c) for c in custos["categoria"]],
                "Valor": [fmt_brl(v) for v in custos["valor"]],
            }
        )
        st.markdown("**Tarifas, aluguéis e estornos (detalhe)**")
        st.dataframe(det, hide_index=True, use_container_width=True)


def tela_detalhamento_banco(resultado: ResultadoConciliacao, conta: str):
    col_back, _ = st.columns([1, 5])
    with col_back:
        if st.button("← Voltar ao painel"):
            st.session_state.banco_conta_selecionada = None
            st.rerun()

    section_title(f"DETALHAMENTO · {conta}")

    k = resultado.kpis_da_conta(conta)
    sub_banco_c = _card_total_com_rec_desp(k["receitas_banco"], k["despesas_banco"])
    sub_sankhya_c = _card_total_com_rec_desp(k["receitas_sistema"], k["despesas_sistema"])
    cards = [
        card_kpi_html("Total movimentado · banco", fmt_brl(k["total_movimentado_banco"]),
                      sub_banco_c),
        card_kpi_html("Total lançado no Sankhya", fmt_brl(k["total_extrato_sistema"]),
                      sub_sankhya_c),
        _card_investimentos_da_conta(resultado, conta),
        card_kpi("% conferido em pares", fmt_pct(k["percentual_conciliado"]), classe="destaque-amarelo"),
    ]
    render_cards(cards)

    # Card Falta Conciliar vertical + Falta Lançar + Divergência + Investimentos da conta
    sub_fc = _card_falta_conciliar_vertical(
        k["falta_conciliar_receitas"],
        k["falta_conciliar_despesas"],
    )
    fonte_fl = ("via Sankhya 'Conciliado=Não'"
                if k["fonte_falta_lancar"] == "sankhya_conciliado_nao"
                else "pendência do sistema")
    falta_c = float(k["falta_conciliar"])
    div_c = float(k["divergencia_sankhya_banco"])
    qtd_div_c = int(k["qtd_divergencia_sankhya_banco"])

    # Banco sem explicação (verde quando zero, vermelho quando há)
    if falta_c == 0:
        card_banco_sem_exp = card_kpi(
            "Banco sem explicação", "R$ 0,00",
            "movimento do banco que o ERP não justifica", classe="destaque-verde")
    else:
        card_banco_sem_exp = card_kpi_html(
            "Banco sem explicação", fmt_brl(falta_c), sub_fc, classe="destaque-vermelho")

    # Sankhya sem confirmação: junta valor + contagem num card só
    cor_div = "destaque-verde" if (div_c == 0 and qtd_div_c == 0) else "destaque-vermelho"
    qtd_txt = (fmt_int(qtd_div_c) + " item") if qtd_div_c == 1 else (fmt_int(qtd_div_c) + " itens")
    valor_div_html = (fmt_brl(div_c)
                      + ' <span style="font-size:14px; color:#8BA3C7; font-weight:400;">&middot; '
                      + qtd_txt + '</span>')
    card_sankhya_sem_conf = card_kpi_html(
        "Sankhya sem confirmação", valor_div_html,
        '<div class="lle-kpi-suffix">lançamentos do ERP que o banco não confirmou</div>',
        classe=cor_div)

    cards2 = [
        card_banco_sem_exp,
        card_sankhya_sem_conf,
        card_kpi("Valor conferido", fmt_brl(k["total_conciliado"]),
                 "soma dos lançamentos que casaram em pares", classe="destaque-verde"),
    ]
    render_cards(cards2)

    # v5.38: ALERTA da diferença Banco × Sankhya — antes ela só aparecia no texto do
    # explainer e nas abas, então passava batido. Agora grita num banner sempre que
    # existir, apontando pra onde investigar.
    dif_bs = round(float(k["total_movimentado_banco"]) - float(k["total_extrato_sistema"]), 2)
    if abs(dif_bs) >= 0.01:
        _lado = "banco" if dif_bs > 0 else "Sankhya"
        _adq_alert = st.session_state.get("adquirente_df")
        _partes, _todos = _explicar_diferenca_cartao(resultado, conta, _adq_alert)
        _dias_conferir = [d.strftime("%d/%m") for d, v, e in _partes if e is None]
        _val = fmt_brl(abs(dif_bs))

        def _banner(cor, borda, icone, status, texto):
            st.html(
                '<div style="background:' + cor + '; border-left:4px solid ' + borda + '; '
                'border-radius:8px; padding:10px 14px; margin:10px 0 2px 0; color:#e9eef7; '
                'font-size:14px; line-height:1.5;">' + icone
                + ' <b>Diferença Banco &times; Sankhya: ' + _val + '</b> &middot; <b>' + status
                + '</b> &middot; ' + texto + '</div>'
            )

        if _partes and _todos:
            # OK — a adquirente identifica 100% da diferença.
            _banner(
                "#0c2b1a", "#0F8C3B", "&#9989;", "identificada 100% pela adquirente",
                'taxa descontada no repasse (não é erro de conciliação). Detalhe na aba '
                '&ldquo;Diferença de Cartão&rdquo;.',
            )
        elif _partes and _dias_conferir:
            # Parte identificada, parte a conferir.
            _banner(
                "#2a1d10", "#FAC318", "&#9888;&#65039;", "parte a conferir",
                'a conferir em: ' + "; ".join(_dias_conferir[:6])
                + '. Veja a aba &ldquo;Diferença de Cartão&rdquo;.',
            )
        else:
            # Precisa de análise (sem adquirente ou sem detalhe por dia).
            _banner(
                "#2a1d10", "#FAC318", "&#9888;&#65039;", "precisa da sua análise",
                'suba o extrato da adquirente pra identificar, ou veja as abas '
                '&ldquo;Diferença de Cartão&rdquo; e &ldquo;Sem baixa no Sankhya&rdquo;.',
            )
    info_saldo = resultado.saldo_final_da_conta(conta)
    if info_saldo is not None:
        render_card_saldo_final(info_saldo)

    # Notas recolhíveis — explicam os cards acima, sem poluir
    _mov_c = float(k["total_movimentado_banco"])
    _falta_c2 = float(k["falta_conciliar"])
    _explic = 100.0 * (_mov_c - _falta_c2) / _mov_c if _mov_c > 0 else 0.0
    _pares = float(k["percentual_conciliado"])
    _regra = max(0.0, _explic - _pares)
    _diff = abs(float(k["total_extrato_sistema"]) - _mov_c)
    # v5.35: só fala "cartão" se a conta TEM cartão; nomeia a regra real.
    _tem_cartao = int(k.get("qtd_top1722_grupos", 0)) > 0
    _tem_boleto = int(k.get("qtd_top1702_grupos", 0)) > 0
    _nomes = []
    if _tem_boleto:
        _nomes.append("boleto (TOP 1702)")
    if _tem_cartao:
        _nomes.append("cartão (TOP 1722)")
    _rotulo = " e ".join(_nomes) if _nomes else "agrupamento por soma"
    with st.expander("Entenda os cards acima"):
        if _regra > 0.01:
            st.markdown(
                "**% conferido em pares (" + fmt_pct(_pares) + "):** casou em pares diretos (1 a 1). "
                "Os " + fmt_pct(_regra) + " restantes são **" + _rotulo + "**, que casa pela soma "
                "total — também explicado. Somando, o banco está **" + fmt_pct(_explic)
                + " explicado** (é o número que aparece no resumo)."
            )
        else:
            st.markdown(
                "**% conferido em pares (" + fmt_pct(_pares) + "):** casou em pares diretos (1 a 1). "
                "O banco está **" + fmt_pct(_explic) + " explicado** (é o número do resumo)."
            )
        _inv = resultado.aplicacoes_resgates_da_conta(conta).copy()
        if not _inv.empty:
            if "historico" in _inv.columns:
                _inv = _inv[~_inv["historico"].astype(str).str.upper().str.contains("SALDO", na=False)]
            _cols = [c for c in ["data", "valor", "conta", "tipo_aplicacao"] if c in _inv.columns]
            if _cols and "origem" in _inv.columns:
                _inv["_o"] = _inv["origem"].apply(lambda x: 0 if "Sankhya" in str(x) else 1)
                _inv = _inv.sort_values("_o").drop_duplicates(subset=_cols, keep="first")
            _ap = float(_inv[_inv["tipo_aplicacao"] == "Aplicação"]["valor"].abs().sum()) if "tipo_aplicacao" in _inv.columns else 0.0
            _rg = float(_inv[_inv["tipo_aplicacao"] == "Resgate"]["valor"].abs().sum()) if "tipo_aplicacao" in _inv.columns else 0.0
            _liq = _rg - _ap
            _frase_liq = (
                "Aplicou mais do que resgatou — **não é prejuízo**, o dinheiro ficou guardado "
                "em aplicação e continua sendo da empresa." if _liq < 0
                else "Resgatou mais do que aplicou no mês."
            )
            _msg_inv = (
                "**Investimentos no período:** líquido de **" + fmt_brl(_liq) + "** "
                "(resgatado " + fmt_brl(_rg) + " − aplicado " + fmt_brl(_ap) + "). " + _frase_liq
            )
            # v5.38: escapa o cifrão pra o Streamlit NÃO interpretar R$...R$ como LaTeX.
            st.markdown(_msg_inv.replace("$", "\\$"))
        if _diff > 0.01:
            if _tem_cartao:
                st.markdown((
                    "**Diferença entre Banco e Sankhya (" + fmt_brl(_diff) + "):** pode incluir a "
                    "taxa de cartão lançada **duas vezes** no Sankhya (uma no valor bruto, outra como "
                    "despesa). O restante precisa ser analisado."
                ).replace("$", "\\$"))
            else:
                st.markdown((
                    "**Diferença entre Banco e Sankhya (" + fmt_brl(_diff) + "):** precisa ser "
                    "analisada. O app **não crava** a causa — pode ser cartão de adquirente "
                    "(Cielo/Stone/Getnet) que não fechou no agrupamento, lançamento a mais/"
                    "duplicado no Sankhya, tarifa, ou item a conciliar."
                ).replace("$", "\\$"))

    # Download específico desse banco — v5.35: SOB DEMANDA.
    # Antes, o Excel da conta era gerado ao ABRIR o detalhamento; numa conta de
    # alto volume (ex.: Santander, 55k linhas) isso levava ~3,4 min e a tela
    # parecia travada ("Ver detalhamento" não respondia). Agora só gera ao clicar
    # — o detalhamento abre na hora, igual ao Excel global.
    excel_conta_key = (
        f"xlsx_conta_{st.session_state.get('id_execucao_atual', 'novo')}_{conta}"
    )
    nome_xls_conta = (
        f"conciliacao_{conta}_{resultado.data_referencia.strftime('%Y%m%d')}.xlsx"
    )
    if st.session_state.get(excel_conta_key):
        st.download_button(
            f"⬇️ Baixar relatório de {conta}",
            data=st.session_state[excel_conta_key],
            file_name=nome_xls_conta,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    elif st.button(f"⬇️ Gerar Excel de {conta}", type="primary",
                   use_container_width=True, key=f"btn_xls_conta_{conta}"):
        with st.spinner("Gerando Excel desta conta… em volume grande pode levar alguns minutos."):
            try:
                st.session_state[excel_conta_key] = gerar_relatorio_excel_de_conta(
                    resultado, conta
                )
            except Exception as e:
                st.warning(f"Não foi possível gerar o Excel deste banco: {e}")
        st.rerun()

    st.divider()

    # Abas internas — agora com Excesso no Sankhya
    div_conta = resultado.divergencias_da_conta(conta)
    aplic_conta = resultado.aplicacoes_resgates_da_conta(conta)
    poss_dup_conta = resultado.possiveis_duplicidades_da_conta(conta)
    excesso_conta = resultado.excesso_sankhya_da_conta(conta)
    diverg_consolidada = resultado.divergencias_sankhya_banco(conta)

    # v5.0/v5.1: filtra estornos e TOP 1722 pela conta.
    # `getattr` com fallback pra DataFrame vazio garante compatibilidade quando o objeto
    # `resultado` em sessão veio de uma versão anterior do código (sem esses campos).
    def _filtrar_conta_seguro(attr_name: str) -> pd.DataFrame:
        df = getattr(resultado, attr_name, None)
        if df is None or df.empty or "conta" not in df.columns:
            return pd.DataFrame()
        return df[df["conta"] == conta]

    estornos_anu_conta = _filtrar_conta_seguro("estornos_anulados")
    estornos_par_conta = _filtrar_conta_seguro("estornos_parciais")
    top1722_grupos_conta = _filtrar_conta_seguro("top1722_grupos")
    top1722_diff_conta = _filtrar_conta_seguro("top1722_diferencas")

    tabs_nomes = ["✅ Conciliadas", "⏳ Sem baixa no Sankhya",
                  "⚠️ Divergências (Sankhya × Banco)",
                  "🏦 Não Pertence à Conta"]
    if not div_conta.empty:
        tabs_nomes.append("💲 Diferença de Valor")
    if not poss_dup_conta.empty:
        tabs_nomes.append("🔍 Possíveis Duplicidades")
    if not excesso_conta.empty:
        tabs_nomes.append("📥 Excesso no Sankhya")
    if not aplic_conta.empty:
        tabs_nomes.append("💰 Aplicações e Resgates")
    # v5.0: abas novas
    if not estornos_anu_conta.empty:
        tabs_nomes.append(f"♻️ Estornos · pares anulados ({len(estornos_anu_conta)})")
    if not estornos_par_conta.empty:
        tabs_nomes.append(f"⚖️ Estornos Parciais ({len(estornos_par_conta)})")
    if not top1722_grupos_conta.empty:
        tabs_nomes.append(f"🃏 Cartão TOP 1722 ({len(top1722_grupos_conta)})")
    if not top1722_diff_conta.empty:
        tabs_nomes.append(f"⚠️ TOP 1722 Diferença ({len(top1722_diff_conta)})")

    # v5.41: aba "Diferença de Cartão" — só quando há extrato de adquirente enviado.
    _adq_df = st.session_state.get("adquirente_df")
    _tem_adq = _adq_df is not None and not _adq_df.empty
    if _tem_adq:
        tabs_nomes.append("💳 Diferença de Cartão")

    tabs = st.tabs(tabs_nomes)
    idx = 0
    with tabs[idx]:
        render_tab_conciliadas(resultado.conciliados_da_conta(conta), conta)
    idx += 1
    with tabs[idx]:
        render_tab_pendentes(resultado, conta)
    idx += 1
    with tabs[idx]:
        render_tab_divergencia_consolidada(diverg_consolidada, conta)
    idx += 1
    with tabs[idx]:
        render_tab_nao_pertence(resultado.nao_pertence_da_conta(conta), conta)
    if not div_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_divergencias(div_conta, conta)
    if not poss_dup_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_possiveis_duplicidades(poss_dup_conta, conta)
    if not excesso_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_excesso_sankhya(excesso_conta, conta)
    if not aplic_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_aplicacoes(aplic_conta, conta)
    # v5.0: abas novas — render
    if not estornos_anu_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_estornos_anulados(estornos_anu_conta, conta)
    if not estornos_par_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_estornos_parciais(estornos_par_conta, conta)
    if not top1722_grupos_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_top1722_grupos(
                top1722_grupos_conta,
                getattr(resultado, "top1722_linhas", pd.DataFrame()),
                conta,
                getattr(resultado, "top1722_linhas_banco", pd.DataFrame()),
            )
    if not top1722_diff_conta.empty:
        idx += 1
        with tabs[idx]:
            render_tab_top1722_diferenca(top1722_diff_conta, conta)
    if _tem_adq:
        idx += 1
        with tabs[idx]:
            render_tab_diferenca_cartao(_adq_df, resultado, conta)

    # v3.8: nova seção "POR TIPO DE LANÇAMENTO" filtrada por conta
    st.write("")
    st.divider()
    section_title(f"POR TIPO DE LANÇAMENTO · {conta}")
    st.caption(
        "Mesma análise mostrada no resumo geral, mas filtrada apenas para esta conta. "
        "Lançamentos do banco e do Sankhya agrupados por categoria, com status (conciliado / pendente)."
    )
    render_subabas_tipo(resultado, conta=conta)


def render_card_saldo_final(info: dict):
    """Card destacado de saldo final quando a conta está 100% conciliada."""
    saldo_final = info.get("saldo_final")
    saldo_inicial = info.get("saldo_inicial")
    mov_liq = info.get("movimentacao_liquida", 0.0)
    periodo_de = info.get("periodo_de")
    periodo_ate = info.get("periodo_ate")
    conta = info.get("conta", "")
    de_str = periodo_de.strftime("%d/%m/%Y") if periodo_de is not None else "—"
    ate_str = periodo_ate.strftime("%d/%m/%Y") if periodo_ate is not None else "—"

    if info.get("tem_saldo_no_extrato"):
        valor_destaque = fmt_brl(saldo_final)
        legenda = (
            f"Saldo inicial: {fmt_brl(saldo_inicial)} · "
            f"Movimentação líquida: {fmt_brl(mov_liq)}"
        )
    else:
        valor_destaque = fmt_brl(mov_liq)
        legenda = (
            "Movimentação líquida do período "
            "(saldo final não está no extrato — informe manualmente se necessário)"
        )

    st.html(f"""
        <div class="lle-kpi" style="border-left-color:{CORES['verde']}; padding:24px 28px; margin-top:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; gap:24px;">
                <div>
                    <div class="lle-kpi-label" style="color:{CORES['verde']} !important; font-size:13px;">
                        ✓ CONCILIAÇÃO 100% · SALDO FINAL DA CONTA
                    </div>
                    <div style="font-size:32px; font-weight:800; color:{CORES['verde']} !important; margin-top:6px;">
                        {valor_destaque}
                    </div>
                    <div style="font-size:12px; color:{CORES['texto_muted']} !important; margin-top:8px;">
                        {legenda}
                    </div>
                </div>
                <div style="text-align:right;">
                    <span class="lle-badge verde" style="font-size:12px;">100,0% conciliado</span>
                    <div style="font-size:11px; color:{CORES['texto_muted']} !important; margin-top:10px;">
                        Conta: <strong style="color:{CORES['amarelo']};">{conta}</strong><br>
                        Período: {de_str} a {ate_str}
                    </div>
                </div>
            </div>
        </div>
    """)


def _exibir_df(df: pd.DataFrame, nome_arquivo: str, msg_vazio: str = "Nenhum registro nesta categoria."):
    if df.empty:
        st.success(f"🎉 {msg_vazio}")
        return
    df_show = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
    st.dataframe(df_show, use_container_width=True, height=420)
    n_linhas = len(df_show)
    col_xls, col_csv = st.columns(2)
    with col_xls:
        # v5.35: Excel da tabela SOB DEMANDA. Em abas grandes (dezenas de milhares
        # de linhas) montar o xlsx a cada render deixava o detalhamento lento — e
        # st.tabs roda o código de TODAS as abas a cada clique. O CSV continua na
        # hora (é instantâneo, vetorizado).
        xls_key = f"tblxls_{nome_arquivo}_{n_linhas}"
        if st.session_state.get(xls_key):
            st.download_button(
                f"⬇️ Baixar Excel ({n_linhas} linhas)",
                data=st.session_state[xls_key],
                file_name=f"{nome_arquivo}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
                key=f"dl_{xls_key}",
            )
        elif st.button(
            f"⬇️ Gerar Excel ({n_linhas} linhas)",
            use_container_width=True,
            key=f"gen_{xls_key}",
        ):
            with st.spinner("Gerando Excel…"):
                st.session_state[xls_key] = _df_to_xlsx_bytes(df_show, nome_arquivo)
            st.rerun()
    with col_csv:
        csv_str = df_show.to_csv(index=False, sep=";", encoding="utf-8-sig", decimal=",")
        st.download_button(
            f"⬇️ Baixar CSV ({n_linhas} linhas)",
            data=csv_str.encode("utf-8-sig"),
            file_name=f"{nome_arquivo}.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"dlcsv_{nome_arquivo}_{n_linhas}",
        )


def _df_to_xlsx_bytes(df: pd.DataFrame, sheet_name: str = "Dados") -> bytes:
    import io
    import re
    from openpyxl import Workbook
    buf = io.BytesIO()
    wb = Workbook()
    ws = wb.active
    # Excel proíbe : \ / ? * [ ] no nome da aba, e limita a 31 chars
    nome_aba = re.sub(r"[:\\/\?\*\[\]]", "_", sheet_name)[:31] or "Dados"
    ws.title = nome_aba
    # header
    ws.append([str(c) for c in df.columns])
    for _, row in df.iterrows():
        ws.append([
            v.to_pydatetime() if isinstance(v, pd.Timestamp)
            else (None if pd.isna(v) else v)
            for v in row
        ])
    wb.save(buf)
    return buf.getvalue()


def render_tab_conciliadas(df: pd.DataFrame, conta: str):
    if df.empty:
        st.success("🎉 Nenhuma linha conciliada nesta conta.")
        return
    cols_preferidas = [
        "banco_data", "banco_historico", "banco_documento", "banco_valor",
        "sistema_data", "sistema_historico", "sistema_documento", "sistema_valor",
        "dias_diferenca", "status", "motivo",
    ]
    cols_existentes = [c for c in cols_preferidas if c in df.columns]
    out = df[cols_existentes].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"conciliadas_{conta}", "Tudo certo — nenhum item nesta aba.")


def render_tab_pendentes(resultado: ResultadoConciliacao, conta: str):
    pb = (
        resultado.pendentes_banco[resultado.pendentes_banco["conta"] == conta].copy()
        if not resultado.pendentes_banco.empty else pd.DataFrame()
    )
    # v5.32: esta aba ("Sem baixa no Sankhya") mostra SÓ o lado do banco — movimento
    # que entrou no banco e ainda não tem baixa no Sankhya (pendentes_banco). O lado
    # oposto (Sankhya sem confirmação = pendentes_sistema) já aparece na aba
    # "Divergências (Sankhya × Banco)"; mostrá-lo aqui também duplicava a mesma linha.
    if not pb.empty:
        pb["origem"] = "Banco (falta baixar no Sankhya)"
    df = pb
    if df.empty:
        st.success("🎉 Nada sem baixa no Sankhya nesta conta.")
        return

    # v5.35: somatório total da coluna (igual ao "Resumo por origem" do Divergência),
    # pra dar o total e permitir comparar.
    _total_pb = float(df["valor"].abs().sum()) if "valor" in df.columns else 0.0
    _qtd_pb = len(df)
    _un_pb = "item" if _qtd_pb == 1 else "itens"
    st.markdown(f"**Total sem baixa no Sankhya:** {fmt_brl(_total_pb)} · {fmt_int(_qtd_pb)} {_un_pb}")

    # v5.11: editor inline pra trocar o Tipo de uma linha pendente
    st.info(
        "💡 Voc\u00ea pode **editar a coluna Tipo** clicando na c\u00e9lula. "
        "Use isso quando o sistema classificou errado (ex.: 'GETNET' como 'Outros'). "
        "Mudan\u00e7as ficam salvas s\u00f3 nesta sess\u00e3o do navegador."
    )

    from src.classificacao import TIPOS_PRINCIPAIS

    cols = ["origem", "data", "historico", "documento", "valor", "tipo", "natureza"]
    cols = [c for c in cols if c in df.columns]
    df_visu = df[cols].copy()

    # Aplica edi\u00e7\u00f5es pr\u00e9vias salvas em session_state
    chave_edicoes = f"edicoes_tipo_pendentes_{conta}"
    edicoes = st.session_state.get(chave_edicoes, {})
    if edicoes and "tipo" in df_visu.columns:
        for chave, novo_tipo in edicoes.items():
            # chave = (data, historico, valor)
            try:
                data_chave, hist_chave, val_chave = chave
                mask = (
                    (df_visu["data"].astype(str) == str(data_chave))
                    & (df_visu["historico"].astype(str) == str(hist_chave))
                    & (df_visu["valor"].round(2) == round(float(val_chave), 2))
                )
                df_visu.loc[mask, "tipo"] = novo_tipo
            except Exception:
                pass

    # Op\u00e7\u00f5es do dropdown
    opcoes_tipo = sorted(set(TIPOS_PRINCIPAIS + ["Outros", "Salário/Folha", "Imposto", "Transferência"]))

    edited = st.data_editor(
        df_visu,
        column_config={
            "origem": st.column_config.TextColumn("Origem", disabled=True),
            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", disabled=True),
            "historico": st.column_config.TextColumn("Hist\u00f3rico", disabled=True),
            "documento": st.column_config.TextColumn("Documento", disabled=True),
            "valor": st.column_config.NumberColumn("Valor (R$)", format="%.2f", disabled=True),
            "tipo": st.column_config.SelectboxColumn(
                "Tipo (edit\u00e1vel)",
                options=opcoes_tipo,
                required=False,
                help="Clique para mudar a classifica\u00e7\u00e3o desta linha.",
            ),
            "natureza": st.column_config.TextColumn("Natureza", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        key=f"editor_pendentes_{conta}",
    )

    # Salva edi\u00e7\u00f5es no session_state se mudou
    if not edited.equals(df_visu):
        novas_edicoes = dict(edicoes)
        for i, row in edited.iterrows():
            if i < len(df_visu):
                orig = df_visu.iloc[i]
                if row["tipo"] != orig["tipo"]:
                    chave = (str(orig["data"]), str(orig["historico"]), round(float(orig["valor"]), 2))
                    novas_edicoes[chave] = row["tipo"]
        st.session_state[chave_edicoes] = novas_edicoes
        if len(novas_edicoes) > len(edicoes):
            st.toast(f"✅ {len(novas_edicoes) - len(edicoes)} classificações atualizadas", icon="✅")

    # Bot\u00e3o pra resetar edi\u00e7\u00f5es
    if edicoes:
        col_a, col_b = st.columns([3, 1])
        with col_b:
            if st.button(f"🔄 Resetar edições ({len(edicoes)})",
                         key=f"reset_edicoes_{conta}", use_container_width=True):
                st.session_state[chave_edicoes] = {}
                st.rerun()


def render_tab_nao_pertence(df: pd.DataFrame, conta: str):
    if df.empty:
        st.success("🎉 Nenhum lançamento parece estar na conta errada.")
        return
    out = df.copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"nao_pertence_{conta}")


def render_tab_divergencias(df: pd.DataFrame, conta: str):
    if df.empty:
        st.success("🎉 Sem divergências de valor nesta conta.")
        return
    cols = ["data", "historico_banco", "valor_banco", "historico_sistema",
            "valor_sistema", "diferenca", "documento_banco", "documento_sistema",
            "motivo"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"divergencias_{conta}")


def render_tab_aplicacoes(df: pd.DataFrame, conta: str):
    """Aplicações e Resgates da conta."""
    if df.empty:
        st.info("Nenhuma aplicação ou resgate identificado para esta conta.")
        return
    st.info(
        "💡 Estas linhas **não entram** no Total do Extrato Bancário (são movimentações "
        "entre conta corrente e investimento). Use esta lista para identificar "
        "lançamentos faltantes e confirmar manualmente quando necessário."
    )
    cols = ["origem", "tipo_aplicacao", "data", "historico",
            "documento", "valor", "categoria_mov"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"aplicacoes_resgates_{conta}")


# v5.0: renderizadores das abas novas
def render_tab_estornos_anulados(df: pd.DataFrame, conta: str):
    """v5.0: pares pagamento/recebimento + estorno com saldo zero."""
    if df.empty:
        st.info("Nenhum par anulado por estorno nesta conta.")
        return
    st.info(
        "♻️ **Pares anulados.** Estes lançamentos têm um par correspondente (recebimento + "
        "estorno OU pagamento + reversão) com saldo líquido **R$ 0,00**. "
        "Eles **não aparecem** em Pendentes, Falta Conciliar, Conta 70 ou Divergências."
    )
    out = df.copy()
    if "data_original" in out.columns:
        out["data_original"] = pd.to_datetime(out["data_original"]).dt.strftime("%d/%m/%Y")
    if "data_estorno" in out.columns:
        out["data_estorno"] = pd.to_datetime(out["data_estorno"]).dt.strftime("%d/%m/%Y")
    if "valor_original" in out.columns:
        out["valor_original"] = out["valor_original"].apply(fmt_brl)
    if "valor_estornado" in out.columns:
        out["valor_estornado"] = out["valor_estornado"].apply(fmt_brl)
    if "saldo_liquido" in out.columns:
        out["saldo_liquido"] = out["saldo_liquido"].apply(fmt_brl)
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"estornos_anulados_{conta}")


def render_tab_estornos_parciais(df: pd.DataFrame, conta: str):
    """v5.0: estornos parciais (saldo ≠ zero) — a diferença volta pra análise."""
    if df.empty:
        st.info("Nenhum estorno parcial nesta conta.")
        return
    st.warning(
        "⚖️ **Estornos parciais.** Aqui o estorno **não anulou totalmente** o lançamento "
        "original. A diferença foi mantida no fluxo como linha sintética para análise "
        "(marcada com **`[ESTORNO PARCIAL]`** no histórico)."
    )
    out = df.copy()
    if "data_original" in out.columns:
        out["data_original"] = pd.to_datetime(out["data_original"]).dt.strftime("%d/%m/%Y")
    if "data_estorno" in out.columns:
        out["data_estorno"] = pd.to_datetime(out["data_estorno"]).dt.strftime("%d/%m/%Y")
    for c in ("valor_original", "valor_estornado", "saldo_liquido"):
        if c in out.columns:
            out[c] = out[c].apply(fmt_brl)
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"estornos_parciais_{conta}")


def render_tab_top1722_grupos(grupos: pd.DataFrame, todas_linhas: pd.DataFrame, conta: str,
                                linhas_banco: pd.DataFrame = None):
    """v5.2: agrupamento TOP 1722 por SOMA TOTAL por conta.
    Cada linha = 1 conta agrupada (não mais 1 crédito banco)."""
    if grupos.empty:
        st.info("Nenhum agrupamento TOP 1722 nesta conta.")
        return

    grupo = grupos.iloc[0]
    qtd_creditos = int(grupo.get("qtd_creditos_banco", 0))
    valor_banco = float(grupo.get("valor_banco_total", 0))
    qtd_sankhya = int(grupo.get("qtd_linhas_sankhya", 0))
    valor_sankhya = float(grupo.get("valor_sankhya_total", 0))
    diferenca = float(grupo.get("diferenca", 0))

    st.success(
        f"🃏 **Conciliação por Agrupamento — Cartão TOP 1722** · {conta}\n\n"
        f"O sistema somou todos os **créditos de cartão no banco** ({qtd_creditos} lançamentos = "
        f"**{fmt_brl(valor_banco)}**) e todas as **vendas TOP 1722 no Sankhya** ({qtd_sankhya} lançamentos = "
        f"**{fmt_brl(valor_sankhya)}**). Diferença: **{fmt_brl(diferenca)}**. "
        f"Como bateu, todas as linhas foram tiradas de Pendentes/Divergência."
    )

    # Card-resumo do agrupamento
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Créditos no Banco", fmt_int(qtd_creditos), fmt_brl(valor_banco))
    with col2:
        st.metric("Vendas TOP 1722 Sankhya", fmt_int(qtd_sankhya), fmt_brl(valor_sankhya))
    with col3:
        st.metric("Diferença", fmt_brl(diferenca), "R$ 0,00" if diferenca == 0 else None)

    # Detalhamento
    if linhas_banco is not None and not linhas_banco.empty:
        with st.expander(f"🔍 Ver composição — créditos do banco ({qtd_creditos} linhas)"):
            lb = linhas_banco[linhas_banco["conta"] == conta].copy()
            if "data" in lb.columns:
                lb["data"] = pd.to_datetime(lb["data"]).dt.strftime("%d/%m/%Y")
            if "valor" in lb.columns:
                lb["valor"] = lb["valor"].apply(fmt_brl)
            cols = [c for c in ("data", "historico", "documento", "valor") if c in lb.columns]
            lb = lb[cols]
            lb.columns = [c.replace("_", " ").title() for c in lb.columns]
            st.dataframe(lb, use_container_width=True, hide_index=True)

    if not todas_linhas.empty:
        with st.expander(f"🔍 Ver composição — vendas no Sankhya ({qtd_sankhya} linhas)"):
            ls = todas_linhas[todas_linhas["conta"] == conta].copy()
            if "data" in ls.columns:
                ls["data"] = pd.to_datetime(ls["data"]).dt.strftime("%d/%m/%Y")
            if "valor" in ls.columns:
                ls["valor"] = ls["valor"].apply(fmt_brl)
            cols = [c for c in ("data", "historico", "documento", "valor") if c in ls.columns]
            ls = ls[cols]
            ls.columns = [c.replace("_", " ").title() for c in ls.columns]
            _exibir_df(ls, f"top1722_sankhya_{conta}")


def render_tab_top1722_diferenca(df: pd.DataFrame, conta: str):
    """v5.2: agrupamento com diferença (taxa) OU diferença grande não-agrupada."""
    if df.empty:
        st.info("Sem diferenças TOP 1722 nesta conta.")
        return

    linha = df.iloc[0]
    valor_banco = float(linha.get("valor_banco_total", 0))
    valor_sankhya = float(linha.get("valor_sankhya_total", 0))
    diferenca = float(linha.get("diferenca", 0))
    pct = float(linha.get("percentual_diferenca", 0))
    status = str(linha.get("status", ""))
    motivo = str(linha.get("motivo", ""))

    if "provável taxa" in status.lower() or "Diferença" in status and "NÃO" not in status:
        st.warning(
            f"⚠️ **TOP 1722 com Diferença** · {conta}\n\n"
            f"A diferença de **{fmt_brl(diferenca)}** ({pct:.2f}%) entre Sankhya e Banco "
            f"foi tratada como **provável taxa de cartão** e o agrupamento foi feito. "
            f"As linhas foram tiradas de Pendentes. Confira se a taxa faz sentido pra você."
        )
    else:
        st.error(
            f"❌ **TOP 1722 NÃO Agrupado** · {conta}\n\n"
            f"A diferença de **{fmt_brl(abs(diferenca))}** ({pct:.2f}%) é grande demais "
            f"para ser taxa de cartão. As linhas continuam em Pendentes/Divergência "
            f"para análise manual."
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Banco", fmt_brl(valor_banco), f"{int(linha.get('qtd_creditos_banco',0))} créditos")
    with col2:
        st.metric("Sankhya TOP 1722", fmt_brl(valor_sankhya), f"{int(linha.get('qtd_linhas_sankhya',0))} linhas")
    with col3:
        st.metric("Diferença", fmt_brl(diferenca), f"{pct:.2f}%")

    if motivo:
        st.caption(f"💡 {motivo}")


def render_tab_possiveis_duplicidades(df: pd.DataFrame, conta: str):
    """Possíveis duplicidades (3 de 4 campos batendo)."""
    if df.empty:
        st.success("🎉 Nenhuma possível duplicidade detectada.")
        return
    st.warning(
        "⚠️ **REVISAR MANUALMENTE.** Estes lançamentos têm 3 de 4 campos iguais "
        "(data, histórico, valor, documento). Não é certeza de duplicidade — "
        "pode ser apenas coincidência (ex: pagamentos similares de clientes diferentes)."
    )
    cols = ["origem", "data", "historico", "documento", "valor", "motivo"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"possiveis_duplicidades_{conta}")


def render_tab_excesso_sankhya(df: pd.DataFrame, conta: str):
    """Excesso no Sankhya: lançamentos do Sankhya sem contrapartida no banco (v3)."""
    if df.empty:
        st.success("🎉 Sankhya não tem lançamentos excedentes em relação ao banco.")
        return
    st.warning(
        "⚠️ **A BASE DA VERDADE É O EXTRATO BANCÁRIO.** "
        "Estes lançamentos aparecem MAIS vezes no Sankhya do que no extrato bancário "
        "para o mesmo perfil (data + valor + histórico + conta). "
        "Possível lançamento duplicado no ERP — revisar."
    )
    cols = ["data", "historico", "documento", "valor",
            "qtd_sankhya", "qtd_banco", "excedente_total", "motivo"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"excesso_sankhya_{conta}")


def render_tab_divergencia_consolidada(df: pd.DataFrame, conta: str):
    """v3.4: Aba 'Divergências (Sankhya × Banco)' — visão consolidada."""
    st.info(
        "📌 **DIVERGÊNCIA = tudo o que o Sankhya tem a mais que o extrato bancário.** "
        "O banco é a base da verdade. Inclui 3 origens:\n\n"
        "- **Sem par no banco**: lançamentos do Sankhya que o app não conseguiu casar com "
        "nenhuma linha do banco (decisão da comparação banco × Sankhya — não depende mais da "
        "flag `Conciliado` do ERP).\n"
        "- **Excesso no Sankhya**: mesma data+valor+conta aparece mais vezes no Sankhya do que no banco.\n"
        "- **Valor diferente**: mesma chave (data+histórico+conta) com valor diferente entre Sankhya e Banco."
    )
    if df.empty:
        st.success("🎉 Sem divergências — Sankhya está alinhado com o banco!")
        return

    # Resumo por origem
    if "origem_divergencia" in df.columns:
        # v5.37: soma COM SINAL (líquido). Antes somava o valor absoluto, então
        # +13,06 e −9,33 davam R$ 22,39 (sem sentido) em vez de R$ 3,73.
        resumo = df.groupby("origem_divergencia").agg(
            quantidade=("valor", "count"),
            total=("valor", "sum"),
        ).reset_index()
        resumo.columns = ["Origem da Divergência", "Quantidade", "Valor Total (líquido)"]
        resumo["Valor Total (líquido)"] = resumo["Valor Total (líquido)"].apply(fmt_brl)
        st.markdown("**Resumo por origem:**")
        st.dataframe(resumo, use_container_width=True, hide_index=True)
        st.write("")

    cols = ["origem_divergencia", "origem", "data", "historico", "documento", "valor", "conta"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"divergencias_sankhya_banco_{conta}")


# Mantido por retrocompat: redireciona para a nova visão consolidada
def render_tab_falta_lancar(df: pd.DataFrame, conta: str, fonte: str):
    """[DEPRECATED v3.4] Substituído por render_tab_divergencia_consolidada."""
    if df.empty:
        st.success("🎉 Nada para lançar — tudo conciliado!")
        return
    cols = ["data", "historico", "documento", "valor", "tipo", "natureza", "conciliado"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    _exibir_df(out, f"falta_lancar_{conta}")


# ============================================================
# Subabas por TIPO de lançamento (Boleto, Pix, Tarifa...)
# ============================================================
def render_subabas_tipo(resultado: ResultadoConciliacao, conta: str | None = None):
    """v3.3: Subabas por tipo mostram pares conciliados + pendentes (banco e sankhya)
    juntos, todos com coluna Status. O tipo dos pares conciliados vem do lado banco
    (histórico mais padronizado). Aba 'Outros' = sem categoria reconhecida.

    v3.8: Se `conta` for fornecido, filtra apenas registros daquela conta.
    """
    _tipos_base = [t for t in TIPOS_PRINCIPAIS if t not in ("Pagamentos", "Recebimentos", "Outros")]
    tipos_disponiveis = ["Todos"] + _tipos_base + ["Pagamentos", "Recebimentos", "Outros"]
    tabs = st.tabs(tipos_disponiveis)

    # v3.10: visão unificada é cara (concat de 3 DataFrames). Cache no session_state.
    # Chave inclui id_execucao_atual pra invalidar quando o resultado muda.
    # v5.15: adicionada versão na chave pra invalidar cache antigo após deploy do filtro
    # de aplicações/resgates.
    cache_key = f"visao_unificada_v515_{st.session_state.get('id_execucao_atual', 'novo')}"
    df_unif = st.session_state.get(cache_key)
    if df_unif is None:
        df_unif = _montar_visao_unificada(resultado)
        st.session_state[cache_key] = df_unif

    if conta is not None and not df_unif.empty and "conta" in df_unif.columns:
        df_unif = df_unif[df_unif["conta"] == conta].copy()

    for _itab, (tab, tipo) in enumerate(zip(tabs, tipos_disponiveis)):
        with tab:
            if tipo == "Todos":
                df = df_unif.copy()
            elif tipo == "Pagamentos":
                df = df_unif[df_unif["natureza"] == "Pagamento"].copy()
            elif tipo == "Recebimentos":
                df = df_unif[df_unif["natureza"] == "Recebimento"].copy()
            else:
                df = df_unif[df_unif["tipo"] == tipo].copy()

            # v5.12: Aba Cartão — quando regra TOP 1722 esvazia tudo, mostra a visão
            # banco × sankhya do agrupamento (mesmas linhas que sumiram de Pendentes/Diverg).
            mostrar_top1722_aqui = (tipo == "Cartão")

            if df.empty and not mostrar_top1722_aqui:
                if tipo == "Outros":
                    st.info(
                        "🎉 Nenhum lançamento sem categoria. "
                        "Esta aba mostra lançamentos cujo histórico não bateu com "
                        "nenhuma das categorias conhecidas (Pix, Boleto, Tarifa, TED/DOC, "
                        "Débito Automático, Cartão, Salário/Folha, Imposto, Transferência)."
                    )
                else:
                    st.info(f"Nenhum lançamento do tipo **{tipo}**.")
                continue

            # KPIs do tipo (só se houver lançamentos regulares)
            if not df.empty:
                qtd = len(df)
                valor_total = float(df["valor"].abs().sum())
                receitas = float(df[df["valor"] > 0]["valor"].sum())
                despesas = float(df[df["valor"] < 0]["valor"].abs().sum())

                sub_rec_desp = _card_total_com_rec_desp(receitas, despesas)

                # Contagens por status
                qtd_conciliado = int((df["status"] == "Conciliado").sum())
                qtd_pend_b = int((df["status"] == "Pendente Banco").sum())
                qtd_pend_s = int((df["status"] == "Pendente Sankhya").sum())

                label_qtd = f"Lançamentos {tipo}" if tipo not in ("Todos", "Outros") else f"Lançamentos {tipo.lower()}"
                cards = [
                    card_kpi(label_qtd, fmt_int(qtd),
                             f"Conciliados: {qtd_conciliado} · Pend. Banco: {qtd_pend_b} · Pend. Sankhya: {qtd_pend_s}"),
                    card_kpi_html("Valor total (absoluto)", fmt_brl(valor_total),
                                  sub_rec_desp, classe="destaque-amarelo"),
                    card_kpi("Contas envolvidas",
                             fmt_int(df["conta"].nunique())),
                ]
                render_cards(cards)

                # Tabela: status + origem + dados padronizados
                if tipo == "Recebimentos":
                    st.caption(
                        "💡 **Recebimentos** = qualquer entrada na conta (TED/DOC de cliente, "
                        "transferência recebida, depósito, crédito de cartão, devolução, etc.). "
                        "Use os tipos específicos (Pix, Boleto, Cartão, TED/DOC) pra ver "
                        "categorias isoladas."
                    )
                elif tipo == "Outros":
                    st.caption(
                        "📌 Lançamentos cujo histórico não bateu com nenhuma categoria conhecida. "
                        "Use esta lista para identificar termos que valem regras novas."
                    )

                cols_show = ["status", "origem", "data", "conta", "historico",
                             "documento", "valor", "tipo", "natureza"]
                cols_show = [c for c in cols_show if c in df.columns]
                out = df[cols_show].copy()
                out.columns = [c.title() for c in out.columns]
                _exibir_df(out, f"tipo{_itab}_{tipo.lower().replace(' ', '_').replace('/', '_')}")

            # v5.12: Bloco TOP 1722 (banco × sankhya) — aparece na aba Cartão
            if mostrar_top1722_aqui:
                _render_bloco_top1722_banco_sankhya(resultado, conta, mostrou_acima=(not df.empty))


def _render_bloco_top1722_banco_sankhya(
    resultado: ResultadoConciliacao,
    conta: str | None,
    mostrou_acima: bool,
):
    """v5.12: Mostra os lançamentos do agrupamento TOP 1722 em visão banco × sankhya
    (lado a lado). Esses lançamentos foram removidos de Pendentes/Divergências pela
    regra de agrupamento, então a aba Cartão ficaria vazia sem este bloco.
    """
    linhas_banco = getattr(resultado, "top1722_linhas_banco", pd.DataFrame())
    linhas_sank = getattr(resultado, "top1722_linhas", pd.DataFrame())

    # Filtra por conta se informado
    if conta is not None:
        if not linhas_banco.empty and "conta" in linhas_banco.columns:
            linhas_banco = linhas_banco[linhas_banco["conta"] == conta]
        if not linhas_sank.empty and "conta" in linhas_sank.columns:
            linhas_sank = linhas_sank[linhas_sank["conta"] == conta]

    if linhas_banco.empty and linhas_sank.empty:
        if not mostrou_acima:
            st.info(
                "Nenhum lançamento do tipo **Cartão**. "
                "Se houver crédito de cartão no banco, ele aparece aqui "
                "(agrupado com vendas TOP 1722 do Sankhya)."
            )
        return

    if mostrou_acima:
        st.divider()

    qtd_b = len(linhas_banco)
    qtd_s = len(linhas_sank)
    val_b = float(linhas_banco["valor"].abs().sum()) if not linhas_banco.empty and "valor" in linhas_banco.columns else 0.0
    val_s = float(linhas_sank["valor"].abs().sum()) if not linhas_sank.empty and "valor" in linhas_sank.columns else 0.0
    diff = val_b - val_s

    st.success(
        f"🃏 **Cartão TOP 1722 — Agrupamento Banco × Sankhya**\n\n"
        f"Esses lançamentos foram conciliados por **soma agrupada** (não 1-pra-1): "
        f"{qtd_b} créditos no banco ({fmt_brl(val_b)}) × {qtd_s} vendas TOP 1722 no Sankhya "
        f"({fmt_brl(val_s)}). Diferença: **{fmt_brl(diff)}**."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Créditos no Banco", fmt_int(qtd_b), fmt_brl(val_b))
    with col2:
        st.metric("Vendas TOP 1722 Sankhya", fmt_int(qtd_s), fmt_brl(val_s))
    with col3:
        st.metric("Diferença", fmt_brl(diff), "R$ 0,00" if diff == 0 else None)

    # Tabelas lado a lado
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**🏦 Banco — Créditos de Cartão**")
        if linhas_banco.empty:
            st.info("Sem créditos no banco para o filtro atual.")
        else:
            lb = linhas_banco.copy()
            if "data" in lb.columns:
                lb["data"] = pd.to_datetime(lb["data"], errors="coerce").dt.strftime("%d/%m/%Y")
            if "valor" in lb.columns:
                lb["valor"] = lb["valor"].apply(fmt_brl)
            cols_b = [c for c in ("data", "conta", "historico", "documento", "valor") if c in lb.columns]
            lb = lb[cols_b]
            lb.columns = [c.replace("_", " ").title() for c in lb.columns]
            st.dataframe(lb, use_container_width=True, hide_index=True)

    with col_b:
        st.markdown("**📋 Sankhya — Vendas TOP 1722**")
        if linhas_sank.empty:
            st.info("Sem vendas TOP 1722 no Sankhya para o filtro atual.")
        else:
            ls = linhas_sank.copy()
            if "data" in ls.columns:
                ls["data"] = pd.to_datetime(ls["data"], errors="coerce").dt.strftime("%d/%m/%Y")
            if "valor" in ls.columns:
                ls["valor"] = ls["valor"].apply(fmt_brl)
            cols_s = [c for c in ("data", "conta", "historico", "documento", "valor") if c in ls.columns]
            ls = ls[cols_s]
            ls.columns = [c.replace("_", " ").title() for c in ls.columns]
            st.dataframe(ls, use_container_width=True, hide_index=True)


def _montar_visao_unificada(resultado: ResultadoConciliacao) -> pd.DataFrame:
    """Une conciliados (lado banco) + pendentes banco + pendentes sankhya em um único
    DataFrame com coluna 'status' e 'origem'.

    Para pares conciliados, usa o tipo/natureza do lado BANCO (histórico padronizado).

    v5.15: Exclui aplicações/resgates/SALDO da visão genérica — esses lançamentos
    são tratamento especial e aparecem só no card de Investimentos. Antes apareciam
    duplicados em 'Recebimentos' (Por Tipo de Lançamento).
    """
    frames = []

    # Pares conciliados — pega o lado banco
    if not resultado.conciliados.empty:
        c = resultado.conciliados.copy()
        # Renomeia banco_* → colunas canônicas
        renomeio = {
            "banco_data": "data",
            "banco_historico": "historico",
            "banco_documento": "documento",
            "banco_valor": "valor",
            "banco_conta": "conta",
            "banco_tipo": "tipo",
            "banco_natureza": "natureza",
        }
        cols_pegar = [k for k in renomeio if k in c.columns]
        d = c[cols_pegar].rename(columns=renomeio).copy()
        d["status"] = "Conciliado"
        d["origem"] = "Banco (conciliado)"
        frames.append(d)

    # Pendentes do banco
    if not resultado.pendentes_banco.empty:
        d = resultado.pendentes_banco.copy()
        d["status"] = "Pendente Banco"
        d["origem"] = "Banco"
        cols_keep = [c for c in ["data","historico","documento","valor","conta","tipo","natureza"]
                     if c in d.columns]
        d = d[cols_keep + ["status", "origem"]]
        frames.append(d)

    # Pendentes do sankhya
    if not resultado.pendentes_sistema.empty:
        d = resultado.pendentes_sistema.copy()
        d["status"] = "Pendente Sankhya"
        d["origem"] = "Sankhya"
        cols_keep = [c for c in ["data","historico","documento","valor","conta","tipo","natureza"]
                     if c in d.columns]
        d = d[cols_keep + ["status", "origem"]]
        frames.append(d)

    if not frames:
        return pd.DataFrame(columns=["status","origem","data","conta","historico",
                                      "documento","valor","tipo","natureza"])

    out = pd.concat(frames, ignore_index=True)

    # v5.15: filtra aplicações/resgates/rendimentos/SALDO da visão genérica
    # (esses lançamentos pertencem ao card de Investimentos, não a Recebimentos)
    if "historico" in out.columns:
        h = out["historico"].astype(str).str.upper()
        mask_invest = (
            h.str.contains("APLIC", na=False)
            | h.str.contains("RESG", na=False)
            | h.str.contains("REND PAGO", na=False)
            | h.str.contains("SALDO APLIC", na=False)
            | h.str.contains("AUT MAIS", na=False)
        )
        out = out[~mask_invest].reset_index(drop=True)

    return out


def _filtrar_por(resultado: ResultadoConciliacao, filtro_fn) -> pd.DataFrame:
    """Aplica filtro_fn nos dois lados (banco + sistema) e marca origem."""
    frames = []
    if not resultado.banco_completo.empty:
        d = filtro_fn(resultado.banco_completo).copy()
        if not d.empty:
            d["origem"] = "Banco"
            frames.append(d)
    if not resultado.sistema_completo.empty:
        d = filtro_fn(resultado.sistema_completo).copy()
        if not d.empty:
            d["origem"] = "Sistema"
            frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ============================================================
# Página: Histórico (execuções e reprocessamentos)
# ============================================================
def pagina_historico():
    execucoes = listar_execucoes()
    if not execucoes:
        st.info(
            "📂 Nenhuma execução registrada ainda. "
            "Cada conciliação processada gera uma entrada aqui, com snapshot dos arquivos "
            "e do relatório (auditoria append-only)."
        )
        return

    section_title(f"{len(execucoes)} EXECUÇÃO(ÕES) REGISTRADAS")

    busca = st.text_input(
        "🔍 Buscar por conta, data ou ID",
        placeholder="ex: Bradesco ou 20260515",
        label_visibility="collapsed",
    )

    filtradas = execucoes
    if busca:
        b = busca.lower().strip()
        filtradas = [
            e for e in execucoes
            if b in " ".join(e.get("contas", [])).lower()
            or b in e.get("id", "").lower()
            or b in e.get("data_referencia", "").lower()
        ]

    if not filtradas:
        st.warning("Nenhuma execução encontrada para essa busca.")
        return

    for exec_data in filtradas:
        with st.container():
            kpis = exec_data.get("kpis", {})
            contas = exec_data.get("contas", [])
            contas_str = ", ".join(contas[:3]) + (f" +{len(contas)-3}" if len(contas) > 3 else "")
            data_ref = exec_data.get("data_referencia", "")[:10]
            try:
                data_ref_fmt = pd.to_datetime(data_ref).strftime("%d/%m/%Y")
            except Exception:
                data_ref_fmt = data_ref
            ts_fmt = exec_data.get("timestamp", "")[:19].replace("T", " ")
            pct = kpis.get("percentual_conciliado", 0)
            classe_pct = "verde" if pct >= 95 else ("amarelo" if pct >= 70 else "vermelho")
            status = exec_data.get("status", "processado")
            versao = exec_data.get("versao", 1)

            st.html(
                f"""
                <div class="lle-kpi" style="margin-bottom:8px;">
                    <div style="display:flex; align-items:center; gap:14px; flex-wrap:wrap;">
                        <span class="lle-badge azul">{exec_data.get("id","")}</span>
                        <strong style="color:{CORES['amarelo']}; font-size:14px;">
                            {data_ref_fmt}
                        </strong>
                        <span style="color:{CORES['texto_muted']};">·</span>
                        <span style="font-weight:600;">{contas_str}</span>
                        <span class="lle-badge {classe_pct}">{fmt_pct(pct)} conciliado</span>
                        <span class="lle-badge azul">v{versao} · {status}</span>
                        <span style="color:{CORES['texto_muted']}; margin-left:auto; font-size:12px;">
                            {ts_fmt}
                        </span>
                    </div>
                    <div style="margin-top:10px; font-size:12px; color:{CORES['texto_muted']};">
                        Conciliados: {fmt_int(kpis.get('qtd_conciliados', 0))} ·
                        Pendentes banco: {fmt_int(kpis.get('qtd_pendentes_banco', 0))} ·
                        Pendentes sistema: {fmt_int(kpis.get('qtd_pendentes_sistema', 0))} ·
                        Total processado: {fmt_brl(kpis.get('total_extrato_bancario', 0))}
                    </div>
                </div>
                """
            )

            # Botão de baixar snapshot
            from src.auditoria import carregar_snapshot_relatorio
            xlsx_snap = carregar_snapshot_relatorio(exec_data.get("id", ""))
            if xlsx_snap:
                st.download_button(
                    f"⬇️ Baixar snapshot desta execução",
                    data=xlsx_snap,
                    file_name=f"snapshot_{exec_data.get('id','')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"snap_{exec_data.get('id','')}",
                )


# ============================================================
# Página: Sobre — explicação das regras
# ============================================================
def pagina_sobre():
    tab1, tab2, tab3 = st.tabs(["Como funciona", "Regras de negócio", "Identidade visual"])

    with tab1:
        st.markdown(f"""
### 🏦 Conciliação Bancária — Grupo LLE

Sistema que bate diariamente o **extrato bancário** com o **extrato do sistema Sankhya**,
identificando conciliações, pendências, divergências e lançamentos na conta errada.

#### Fluxo
1. **Upload** dos extratos (1 ou várias contas) + relatório do ERP.
2. Processamento automático com as regras definidas pela equipe financeira.
3. **Tela única de resultado** com cards executivos, painel por banco e detalhamento por tipo.
4. **Download** em Excel (multi-aba) e CSV (zip) — globalmente ou por banco.
5. Auditoria de execuções fica em `data/outputs/auditoria.jsonl` (append-only — nada é sobrescrito).

#### Persistência sem banco
- O **Excel gerado é o "estado"**. Suba o do dia anterior em "Pendências de dias anteriores"
  para acompanhar há quantos dias cada pendência está aberta.
- Cada execução também salva um **snapshot completo** em `data/outputs/execucoes/{{id}}/`
  com os inputs, parâmetros e resultado, permitindo **reprocessamento** sem perder histórico.
        """)

    with tab2:
        st.markdown(f"""
### Regras determinantes da conciliação

**Match exato (conciliação automática):**
- Valor: precisa ser **exatamente igual** — sem tolerância de centavos.
- Conta: precisa ser **igual**.
- Data: tolerância de **±N dias corridos** (default 2 — cobre fim de semana e feriado curto).
- Match é **1-pra-1**. Cada lançamento do banco casa com no máximo um do sistema.

**Total Extrato Bancário (v2):**
- Soma absoluta SOMENTE de movimentações reais.
- **Exclui linhas de SALDO, APLICAÇÃO, RESGATE, INVESTIMENTO**, compra/venda de CDB/RDB/LCI/LCA/Tesouro etc.
- Essas linhas aparecem em aba dedicada ("Aplicações e Resgates"), mas não contam no total.

**Falta Conciliar:**
- Total que existe no extrato bancário mas não no Sankhya.
- Separado em **Receitas** e **Despesas** (despesas exibidas positivas).

**Falta Lançar — fonte automática:**
- Se o Sankhya tem a coluna **Conciliado** preenchida, usa as linhas com `Conciliado=Não`.
- Senão usa pendentes pós-match. O card mostra a fonte usada.

**Divergência de valor:**
- Mesma data + histórico exato (após normalização) + conta, mas valores diferentes.

**Duplicidade (estrita):**
- 4 de 4 campos iguais (data, histórico, valor, documento).
- 5 boletos legítimos com docs diferentes NÃO viram duplicidade.

**Possíveis Duplicidades (NOVO):**
- 3 de 4 campos batendo — aba própria, marcadas como "REVISAR MANUALMENTE".

**Não Pertence à Conta:**
- Pendência com candidato perfeito em outra conta (mesmo valor + data próxima).

**Receitas e Despesas Absolutas:**
- Separadas, sem compensação. Despesas em valor positivo no resumo.

**Saldo Final (NOVO):**
- Aparece quando a conta está 100% conciliada.
- Usa SALDO INICIAL/FINAL do extrato; senão usa movimentação líquida com aviso.

**Sugestões Fuzzy:**
- Aba complementar para revisão manual. Não entra na conciliação automática.
        """)

    with tab3:
        st.markdown(f"""
### Identidade Visual — Grupo LLE

Seguindo o Manual da Marca (Fev/2026):

| Cor | Hex | Uso |
|-----|-----|-----|
| Azul institucional escuro | `#041747` | Fundo principal |
| Azul primário | `#0071FE` | Botões e destaques |
| Amarelo | `#FAC318` | Sidebar e elementos de destaque |
| Verde | `#0F8C3B` | Indicadores positivos |
| Branco | `#FFFFFF` | Textos sobre fundo escuro |

**Fonte:** Montserrat (Google Fonts).

**Logo:** versão texto branco sobre fundo escuro (não distorcer, não mudar cor do símbolo).

📩 Dúvidas de identidade visual: marketing@grupolle.com.br
        """)


# ============================================================
# Página: Cadastro de Taxas (v4.0 — módulo CARTÃO)
# ============================================================
def pagina_cadastro_taxas():
    from src.cartao import carregar_cadastro_taxas, MODALIDADES_VALIDAS

    section_title("CADASTRO DE TAXAS — CONTRATOS COM ADQUIRENTES")

    st.markdown(
        "Esta tela mostra as taxas contratadas com as adquirentes (Stone, Cielo, Rede, etc) "
        "que servem de base para a **Auditoria de Taxas**. "
        "As taxas ficam num arquivo `taxas.xlsx` que você gerencia. "
        "Suba ele aqui sempre que houver alteração contratual."
    )

    st.write("")
    arq = st.file_uploader(
        "Suba o arquivo de taxas (.xlsx, .xls ou .csv)",
        type=["xlsx", "xls", "csv"],
        key="upload_taxas",
        help=(
            "Colunas obrigatórias: adquirente, modalidade, parcelas, taxa_mdr. "
            "Colunas opcionais: taxa_antecipacao, prazo_dias, vigencia_inicio, vigencia_fim."
        ),
    )

    if arq is not None:
        try:
            cadastro = carregar_cadastro_taxas(arq)
            st.session_state["cadastro_taxas"] = cadastro
            st.success(f"✅ Cadastro carregado com {len(cadastro)} taxas.")
        except Exception as e:
            st.error(f"❌ Erro ao ler taxas.xlsx: {e}")

    cadastro = st.session_state.get("cadastro_taxas")

    if cadastro is None or cadastro.empty:
        st.info(
            "🙋 Nenhum cadastro carregado. Suba o arquivo `taxas.xlsx` acima.\n\n"
            "**Formato esperado**: uma planilha Excel com as colunas\n"
            "- `adquirente` (Stone, Cielo, Rede, Getnet, …)\n"
            f"- `modalidade` ({', '.join(MODALIDADES_VALIDAS)})\n"
            "- `parcelas` (número inteiro: 1 para débito/à vista, 2-12 para parcelado)\n"
            "- `taxa_mdr` (`1,39%` ou `0.0139`)\n"
            "- `taxa_antecipacao` (opcional)\n"
            "- `prazo_dias` (opcional: D+N)\n"
            "- `vigencia_inicio` / `vigencia_fim` (opcional; deixe vazio se ainda vigente)\n\n"
            "💡 Há um arquivo de exemplo em `data/samples/taxas_exemplo.xlsx`."
        )
        return

    # Resumo
    section_title("RESUMO DO CADASTRO")
    qtd_adq = cadastro["adquirente"].nunique()
    qtd_mod = cadastro["modalidade"].nunique()
    cards = [
        card_kpi("Adquirentes cadastradas", fmt_int(qtd_adq)),
        card_kpi("Modalidades distintas", fmt_int(qtd_mod)),
        card_kpi("Total de regras", fmt_int(len(cadastro))),
        card_kpi("Taxa MDR média (débito)",
                 fmt_pct(cadastro[cadastro["modalidade"] == "Débito"]["taxa_mdr"].mean() * 100)
                 if (cadastro["modalidade"] == "Débito").any() else "—"),
    ]
    render_cards(cards)

    st.write("")
    section_title("CADASTRO DETALHADO")

    visu = cadastro.copy()
    visu["taxa_mdr"] = (visu["taxa_mdr"] * 100).round(4).astype(str) + "%"
    visu["taxa_antecipacao"] = (visu["taxa_antecipacao"] * 100).round(4).astype(str) + "%"
    visu["prazo_dias"] = "D+" + visu["prazo_dias"].astype(str)
    visu["vigencia_inicio"] = visu["vigencia_inicio"].dt.strftime("%d/%m/%Y").fillna("—")
    visu["vigencia_fim"] = visu["vigencia_fim"].dt.strftime("%d/%m/%Y").fillna("(vigente)")
    visu.columns = [c.replace("_", " ").title() for c in visu.columns]
    st.dataframe(visu, use_container_width=True, hide_index=True)

    st.caption(
        "💡 Para editar: abra o `taxas.xlsx` no Excel, faça as alterações e suba novamente. "
        "Histórico de alterações fica preservado no Excel via versionamento manual."
    )


# ============================================================
# Página: Auditoria de Taxas (v4.0 — módulo CARTÃO)
# ============================================================
def pagina_auditoria_taxas():
    from src.cartao import (
        carregar_relatorio_adquirente,
        auditar_taxas,
        consolidar_historico,
        eh_extrato_getnet_cru,
        carregar_extrato_getnet_cru,
        resumir_extrato_getnet,
    )
    from io import BytesIO

    section_title("AUDITORIA DE CARTÕES — ADQUIRENTES")

    cadastro = st.session_state.get("cadastro_taxas")
    if cadastro is None or cadastro.empty:
        st.warning(
            "⚠️ Você precisa carregar o **Cadastro de Taxas** primeiro. "
            "Vá em `💳 CARTÃO → 🏦 Cadastro de Taxas` e suba o `taxas.xlsx`."
        )
        return

    st.markdown(
        "Suba aqui o **relatório padronizado das adquirentes** do período que quer auditar. "
        "O sistema compara a taxa que a adquirente cobrou contra a taxa contratada no cadastro "
        "e marca cada lançamento como **OK**, **Arredondamento**, **Discrepância** ou **Sem contrato**."
    )

    # v4.1: bloco de histórico acumulado
    with st.expander("📁 Subir auditorias anteriores (opcional)", expanded=False):
        st.markdown(
            "Suba aqui Excels de auditorias **anteriores** (gerados pelo próprio sistema) "
            "para que os KPIs e tabelas acumulem o período completo. "
            "Útil pra ver o impacto financeiro de várias auditorias somadas."
        )
        arqs_hist = st.file_uploader(
            "Arquivos de auditorias anteriores (vários permitidos)",
            type=["xlsx"],
            key="upload_historico_auditorias",
            accept_multiple_files=True,
            help=(
                "Sobe os arquivos baixados por 'Baixar auditoria completa' em sessões "
                "anteriores. O sistema agrega tudo num único resultado consolidado."
            ),
        )
        historico_df = pd.DataFrame()
        if arqs_hist:
            historico_df, avisos = consolidar_historico(arqs_hist)
            if historico_df.empty:
                st.warning(
                    "Nenhum dos arquivos enviados pôde ser lido como auditoria. "
                    "Confira se são Excels gerados pelo botão 'Baixar auditoria completa'."
                )
            else:
                st.success(
                    f"✅ {len(historico_df)} lançamentos de {len(arqs_hist)} arquivo(s) "
                    f"de histórico carregados."
                )
                for av in avisos:
                    st.warning(av)

    st.write("")

    col_data, col_arq = st.columns([1, 2])
    with col_data:
        from datetime import date, timedelta
        data_ate = st.date_input(
            "Data a auditar",
            value=date.today() - timedelta(days=1),
            format="DD/MM/YYYY",
            help="Padrão: ontem (modelo D-1). Mude para auditar outro período.",
        )
    with col_arq:
        arq = st.file_uploader(
            "Relatório da adquirente (.xlsx, .xls ou .csv)",
            type=["xlsx", "xls", "csv"],
            key="upload_relatorio_adq",
            help=(
                "Aceita 2 formatos:\n\n"
                "1) **Extrato CRU da GETNET** — o XLSX baixado direto do portal "
                "(Recebíveis > Completos > Detalhado). O sistema detecta e converte sozinho.\n\n"
                "2) **Relatório padronizado** — XLSX com colunas: data_venda, adquirente, "
                "modalidade, parcelas, valor_bruto, taxa_aplicada, valor_liquido (opcional)."
            ),
        )

    # Recupera histórico do session_state (carregado no expander acima)
    historico_df = locals().get("historico_df", pd.DataFrame())

    # v5.43: reaproveita os extratos de adquirente já enviados na conciliação.
    # Só o GetNet cru é auditável por venda; PagBank (recebimento) é ignorado aqui.
    relatorio_sessao, adq_ignorados = _relatorio_auditoria_da_sessao()
    usar_sessao = False
    if arq is None and not relatorio_sessao.empty:
        st.success(
            f"🟩 Encontrei **{len(relatorio_sessao)} venda(s) de GetNet** que você já subiu "
            "na conciliação. Não precisa subir de novo."
        )
        usar_sessao = st.checkbox(
            "Auditar os extratos que já enviei na conciliação",
            value=True,
            help="Usa os mesmos arquivos de adquirente da tela de conciliação. "
            "Se preferir auditar outro período, suba um arquivo ao lado.",
        )
        if adq_ignorados:
            st.caption(
                "Obs.: estes não entram na auditoria por venda (não trazem taxa por "
                "venda, ex.: PagBank é recebimento): " + ", ".join(adq_ignorados)
            )

    if arq is None and not usar_sessao and (historico_df is None or historico_df.empty):
        st.info(
            "🙋 Suba o relatório da adquirente para iniciar a auditoria "
            "(ou suba o extrato da adquirente na conciliação — ele aparece aqui automaticamente).\n\n"
            "**Formato 1 — Extrato CRU da GETNET (recomendado):**\n"
            "- Baixe direto do portal GETNET: *Recebíveis > Completos > Detalhado*\n"
            "- Suba o XLSX como veio, o sistema converte sozinho\n\n"
            "**Formato 2 — Relatório padronizado:**\n"
            "- Planilha Excel/CSV com colunas: `data_venda`, `adquirente`, `modalidade`, "
            "`parcelas`, `valor_bruto`, `taxa_aplicada`, `valor_liquido` (opcional)\n"
            "- Exemplo em `data/samples/relatorio_adquirente_exemplo.xlsx`"
        )
        return

    # Carrega relatório atual (se subiu) — detecta formato automaticamente
    if arq is not None:
        try:
            # v5.16: detecta se é extrato CRU da GETNET e converte automaticamente
            if eh_extrato_getnet_cru(arq):
                relatorio = carregar_extrato_getnet_cru(arq)
                # Resumo informativo do que foi lido do extrato GETNET
                resumo_getnet = resumir_extrato_getnet(relatorio)
                periodo_str = ""
                if resumo_getnet["data_min"] and resumo_getnet["data_max"]:
                    periodo_str = (
                        f" · Período: {resumo_getnet['data_min'].strftime('%d/%m/%Y')} → "
                        f"{resumo_getnet['data_max'].strftime('%d/%m/%Y')}"
                    )
                st.success(
                    f"🟧 **Extrato GETNET detectado e convertido automaticamente.** "
                    f"{resumo_getnet['qtd']} vendas · "
                    f"Bruto: {fmt_brl(resumo_getnet['bruto_total'])} · "
                    f"Líquido: {fmt_brl(resumo_getnet['liquido_total'])} · "
                    f"Taxa média real: {fmt_pct(resumo_getnet['taxa_media']*100)}"
                    f"{periodo_str}"
                )
                # Mostra taxa real por bandeira/modalidade num expander (pra você conferir
                # antes de cadastrar o contrato)
                if not resumo_getnet["por_modalidade"].empty:
                    with st.expander("📊 Taxa real cobrada por bandeira/modalidade (informativo)", expanded=False):
                        st.caption(
                            "Esta é a taxa que a GETNET **efetivamente cobrou** em cada bandeira/modalidade neste período. "
                            "Use como referência para cadastrar a taxa contratada no `taxas.xlsx`."
                        )
                        visu_mod = resumo_getnet["por_modalidade"].copy()
                        visu_mod["bruto"] = visu_mod["bruto"].apply(fmt_brl)
                        visu_mod["liquido"] = visu_mod["liquido"].apply(fmt_brl)
                        visu_mod["taxa_real"] = (visu_mod["taxa_real"] * 100).round(4).astype(str) + "%"
                        visu_mod.columns = [c.replace("_", " ").title() for c in visu_mod.columns]
                        st.dataframe(visu_mod, use_container_width=True, hide_index=True)
            else:
                # Formato padronizado clássico
                relatorio = carregar_relatorio_adquirente(arq)
        except Exception as e:
            st.error(f"❌ Erro ao ler o relatório: {e}")
            return
        if relatorio.empty:
            st.warning("⚠️ O relatório está vazio ou não tem linhas válidas.")
            relatorio = pd.DataFrame()
    elif usar_sessao and not relatorio_sessao.empty:
        relatorio = relatorio_sessao
        resumo_getnet = resumir_extrato_getnet(relatorio)
        periodo_str = ""
        if resumo_getnet["data_min"] and resumo_getnet["data_max"]:
            periodo_str = (
                f" · Período: {resumo_getnet['data_min'].strftime('%d/%m/%Y')} → "
                f"{resumo_getnet['data_max'].strftime('%d/%m/%Y')}"
            )
        st.success(
            f"🟧 **Auditando os extratos da conciliação.** "
            f"{resumo_getnet['qtd']} vendas · "
            f"Bruto: {fmt_brl(resumo_getnet['bruto_total'])} · "
            f"Líquido: {fmt_brl(resumo_getnet['liquido_total'])} · "
            f"Taxa média real: {fmt_pct(resumo_getnet['taxa_media']*100)}"
            f"{periodo_str}"
        )
    else:
        relatorio = pd.DataFrame()

    # Filtra pelo período escolhido (padrão: data exata = data_ate)
    if not relatorio.empty:
        col_p1, _ = st.columns(2)
        with col_p1:
            usar_filtro = st.checkbox("Filtrar por data específica", value=False,
                                      help="Marque para auditar apenas a data selecionada acima.")
        if usar_filtro:
            relatorio = relatorio[
                relatorio["data_venda"].dt.date == data_ate
            ]
            if relatorio.empty:
                st.warning(f"⚠️ Nenhuma transação encontrada para {data_ate.strftime('%d/%m/%Y')}.")
                return

    # v4.1: roda auditoria com histórico opcional
    res = auditar_taxas(
        relatorio,
        cadastro,
        historico=historico_df if not historico_df.empty else None,
    )
    k = res.kpis

    if not historico_df.empty:
        st.info(
            f"📈 Auditoria **consolidada**: {len(relatorio)} lançamento(s) atual(is) + "
            f"{len(historico_df)} do histórico = **{len(res.detalhado)} total**."
        )

    st.write("")
    section_title("INDICADORES")

    cards1 = [
        card_kpi("Volume Bruto de Vendas", fmt_brl(k["volume_bruto"]),
                 f"{fmt_int(k['qtd_total'])} transações"),
        card_kpi("Valor Líquido Recebido", fmt_brl(k["valor_liquido"]),
                 classe="destaque-verde"),
        card_kpi("Total de Taxas Pagas", fmt_brl(k["taxas_pagas"])),
        card_kpi("Taxa Média Efetiva", fmt_pct(k["taxa_media_efetiva"] * 100),
                 classe="destaque-amarelo"),
    ]
    render_cards(cards1)

    cards2 = [
        card_kpi("OK", fmt_int(k["qtd_ok"]),
                 "conforme contrato", classe="destaque-verde"),
        card_kpi("Arredondamento", fmt_int(k.get("qtd_arredondamento", 0)),
                 "centavo da adquirente"),
        card_kpi("Discrepâncias", fmt_int(k["qtd_divergencias"]),
                 "diferença real de taxa",
                 classe="destaque-vermelho" if k["qtd_divergencias"] > 0 else ""),
        card_kpi("Sem Contrato", fmt_int(k["qtd_sem_contrato"]),
                 "modalidade não cadastrada",
                 classe="destaque-amarelo" if k["qtd_sem_contrato"] > 0 else ""),
    ]
    render_cards(cards2)

    cards3 = [
        card_kpi("Você pagou a mais", fmt_brl(k.get("impacto_pagou_mais", 0.0)),
                 "só discrepâncias",
                 classe="destaque-vermelho" if k.get("impacto_pagou_mais", 0.0) > 0 else ""),
        card_kpi("Você pagou a menos", fmt_brl(abs(k.get("impacto_pagou_menos", 0.0))),
                 "só discrepâncias (a seu favor)"),
        card_kpi("Arredondamento (total)", fmt_brl(k.get("arredondamento_total", 0.0)),
                 "não é cobrança indevida"),
    ]
    render_cards(cards3)

    st.divider()

    # Tabela com abas: OK / arredondamento / discrepância / sem contrato / tudo
    tabs = st.tabs([
        f"✅ OK ({k['qtd_ok']})",
        f"🔧 Arredondamento ({k.get('qtd_arredondamento', 0)})",
        f"⚠️ Discrepância ({k['qtd_divergencias']})",
        f"❓ Sem contrato ({k['qtd_sem_contrato']})",
        "📋 Tudo",
    ])

    # v5.18: 'bandeira' incluída pra facilitar identificar a origem da divergência
    # (Visa, Mastercard, Elo, etc — vem do parser GETNET).
    cols_show = [
        "data_venda", "adquirente", "bandeira", "modalidade", "parcelas",
        "valor_bruto", "taxa_aplicada", "taxa_esperada",
        "diferenca_pp", "diferenca_rs", "status", "motivo",
    ]
    cols_show = [c for c in cols_show if c in res.detalhado.columns]

    def _formatar_visualizacao(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        out = df[cols_show].copy()
        if "taxa_aplicada" in out.columns:
            out["taxa_aplicada"] = (out["taxa_aplicada"] * 100).round(4).astype(str) + "%"
        if "taxa_esperada" in out.columns:
            out["taxa_esperada"] = out["taxa_esperada"].apply(
                lambda x: f"{float(x) * 100:.4f}%" if pd.notna(x) else "—"
            )
        if "diferenca_pp" in out.columns:
            out["diferenca_pp"] = out["diferenca_pp"].apply(
                lambda x: f"{x:+.4f} p.p." if pd.notna(x) else "—"
            )
        if "diferenca_rs" in out.columns:
            out["diferenca_rs"] = out["diferenca_rs"].apply(
                lambda x: fmt_brl(x) if pd.notna(x) else "—"
            )
        if "valor_bruto" in out.columns:
            out["valor_bruto"] = out["valor_bruto"].apply(fmt_brl)
        if "data_venda" in out.columns:
            out["data_venda"] = out["data_venda"].dt.strftime("%d/%m/%Y")
        out.columns = [c.replace("_", " ").title() for c in out.columns]
        return out

    with tabs[0]:
        ok = res.detalhado[res.detalhado["status"] == "OK"]
        if ok.empty:
            st.info("Nenhuma transação OK neste período.")
        else:
            st.success(f"✅ **{len(ok)} transações conforme contrato.**")
            st.dataframe(_formatar_visualizacao(ok), use_container_width=True, hide_index=True)

    with tabs[1]:
        arr = res.detalhado[res.detalhado["status"] == "Arredondamento"]
        if arr.empty:
            st.success("✅ Nenhum arredondamento a destacar.")
        else:
            st.info(
                f"🔧 **{len(arr)} lançamentos com arredondamento da adquirente** "
                "(diferença de taxa até 0,02 pp). Total "
                f"**{fmt_brl(k.get('arredondamento_total', 0.0))}** — não é cobrança indevida, "
                "é o centavo que a adquirente arredonda por transação."
            )
            st.dataframe(_formatar_visualizacao(arr), use_container_width=True, hide_index=True)

    with tabs[2]:
        if res.divergentes.empty:
            st.success("🎉 Nenhuma discrepância de taxa. Tudo dentro do contrato (fora arredondamento).")
        else:
            _mais = k.get("impacto_pagou_mais", 0.0)
            _menos = abs(k.get("impacto_pagou_menos", 0.0))
            st.warning(
                f"⚠️ **{len(res.divergentes)} discrepâncias de taxa** (acima de 0,02 pp). "
                f"Você pagou a mais **{fmt_brl(_mais)}** e a menos **{fmt_brl(_menos)}**."
            )
            visu = _formatar_visualizacao(res.divergentes)
            st.dataframe(visu, use_container_width=True, hide_index=True)

            # Download das discrepâncias
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                _formatar_visualizacao(res.divergentes).to_excel(
                    writer, sheet_name="Discrepancias", index=False
                )
                # Aba "Bruto" com dados originais (sem formatação) pra reanálise
                res.divergentes[cols_show].to_excel(
                    writer, sheet_name="Bruto", index=False
                )
            buf.seek(0)
            st.download_button(
                "⬇️ Baixar Excel com discrepâncias",
                data=buf.getvalue(),
                file_name=f"discrepancias_taxas_{data_ate.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )

    with tabs[3]:
        sc = res.detalhado[res.detalhado["status"] == "Sem contrato"]
        if sc.empty:
            st.success("✅ Todas as transações têm taxa cadastrada.")
        else:
            st.warning(
                f"❓ **{len(sc)} transações sem contrato cadastrado.** "
                f"Cadastre a taxa correspondente em `🏦 Cadastro de Taxas` para que entrem na auditoria."
            )
            st.dataframe(_formatar_visualizacao(sc), use_container_width=True, hide_index=True)

    with tabs[4]:
        st.dataframe(_formatar_visualizacao(res.detalhado),
                     use_container_width=True, hide_index=True)

        # Resumo por adquirente (só discrepâncias)
        if not res.divergentes.empty:
            st.write("")
            st.markdown("**Discrepâncias por adquirente:**")
            por_adq = res.divergentes_por_adquirente()
            por_adq["impacto"] = por_adq["impacto"].apply(fmt_brl)
            por_adq.columns = ["Adquirente", "Quantidade", "Impacto (R$)"]
            st.dataframe(por_adq, use_container_width=True, hide_index=True)

    # v4.1: download da auditoria COMPLETA (pra usar como histórico no próximo dia)
    st.write("")
    st.divider()
    section_title("EXPORTAR AUDITORIA COMPLETA")
    st.caption(
        "💡 Baixe esse arquivo e guarde. Na próxima auditoria, suba-o em "
        "**'📁 Subir auditorias anteriores'** acima pra ver os números acumulados."
    )
    buf_completo = BytesIO()
    with pd.ExcelWriter(buf_completo, engine="openpyxl") as writer:
        # Dados brutos (com tipos preservados) — esse é o arquivo que o sistema relê
        res.detalhado.to_excel(writer, sheet_name="Auditoria", index=False)
        # Aba formatada pra leitura humana
        _formatar_visualizacao(res.detalhado).to_excel(
            writer, sheet_name="Visualização", index=False
        )
    buf_completo.seek(0)
    from datetime import date as _date
    nome_arquivo = f"auditoria_taxas_{_date.today().strftime('%Y%m%d')}.xlsx"
    st.download_button(
        "⬇️ Baixar auditoria completa (.xlsx)",
        data=buf_completo.getvalue(),
        file_name=nome_arquivo,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )


# ============================================================
# Página: Conta 70 (v5.0 — módulo de controle provisório)
# ============================================================
@st.cache_data(show_spinner="Processando a Conta 70 (uma vez)…")
def _c70_processar(capa_bytes, capa_name, sk_bytes, sk_name):
    """Parte pesada (ler Capa + Sankhya + atrelar) em cache: roda uma vez por
    arquivo, então marcar caixinhas e navegar fica instantâneo."""
    import io as _io
    from src.conta70.casamento import carregar_movimento, atrelar

    def _n(b, nome):
        x = _io.BytesIO(b)
        x.name = nome
        return x

    capa = carregar_movimento(_n(capa_bytes, capa_name))
    sk = carregar_movimento(_n(sk_bytes, sk_name))
    ult = int(pd.to_numeric(capa["numero"], errors="coerce").max() or 0)
    res = atrelar(sk, capa, ultimo_numero=ult)
    # acumulado da Capa inteira (conta 70): receita, despesa e diferença
    _rd = capa["receita_despesa"].astype(str).str.upper()
    acum_rec = float(capa[_rd.str.contains("RECEITA", na=False)]["valor"].abs().sum())
    acum_desp = float(capa[_rd.str.contains("DESPESA", na=False)]["valor"].abs().sum())
    return res.detalhado, dict(res.kpis), int(res.proximo_numero), ult, acum_rec, acum_desp


@st.cache_data(show_spinner=False)
def _c70_faturamento(fat_bytes, fat_name):
    import io as _io
    from src.conta70.casamento import carregar_faturamento
    x = _io.BytesIO(fat_bytes)
    x.name = fat_name
    return carregar_faturamento(x)


def _render_conta70_casamento_numeracao():
    """v5.7 — Atrelamento, numeração e esteira da Conta 70.

    Três uploads: Capa consolidada (só leitura), movimentação do Sankhya e notas
    emitidas não baixadas (com CNPJ). A Capa original nunca é alterada — a "capa
    atualizada" sai como arquivo novo, completo/acumulado.
    """
    import io as _io
    from datetime import date as _date
    from src.conta70.casamento import diagnosticar, sugerir_atrelamentos_cnpj, gerar_capa_acumulada

    def _money(v):
        try:
            return ("R$ " + f"{float(v):,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "R$ 0,00"

    section_title("ATRELAMENTO E NUMERAÇÃO — CONTA 70")
    st.markdown(
        "Suba a **Capa** (consolidada, somente leitura), a **movimentação da Conta 70 do Sankhya** "
        "e, quando tiver, as **notas emitidas não baixadas** (com CNPJ). O app atrela pela identidade "
        "do histórico (CNPJ/CPF/dados bancários), numera em sequência e organiza o que está aberto "
        "numa esteira com diagnóstico e ação. Sua capa original nunca é alterada."
    )

    c1, c2, c3 = st.columns(3)
    up_capa = c1.file_uploader("📄 Capa da Conta 70 (consolidada · só leitura)", type=["xlsx", "xls", "xlsm", "csv"], key="c70_capa")
    up_sk = c2.file_uploader("📄 Movimentação Conta 70 (Sankhya)", type=["xlsx", "xls", "xlsm", "csv"], key="c70_sk")
    up_fat = c3.file_uploader("📄 Notas emitidas não baixadas (com CNPJ)", type=["xlsx", "xls", "xlsm", "csv"], key="c70_fat")

    if up_capa is None or up_sk is None:
        st.caption("Suba pelo menos a Capa e a movimentação do Sankhya. As notas emitidas são opcionais (habilitam os atrelamentos sugeridos por CNPJ).")
        return

    # ---- parte pesada em cache: instantâneo nos cliques seguintes ----
    try:
        d, k, prox, ultimo, acum_rec, acum_desp = _c70_processar(up_capa.getvalue(), up_capa.name, up_sk.getvalue(), up_sk.name)
        d = d.copy()
    except Exception as e:
        st.error(f"Não consegui ler um dos arquivos: {e}")
        return

    pend = d[d["situacao"].isin(["Aguardando baixa", "A conferir"])]
    esteira = diagnosticar(pend)
    n_ident = k["ja_identificado"] + k["herdado"]
    acum_dif = acum_rec - acum_desp

    # cards do acumulado da Capa inteira (conta 70) — em cima
    render_cards([
        card_kpi("Receita acumulada", _money(acum_rec), "toda a Capa · Conta 70", classe="destaque-verde"),
        card_kpi("Despesa acumulada", _money(acum_desp), "toda a Capa · Conta 70", classe="destaque-vermelho"),
        card_kpi("Diferença acumulada", _money(acum_dif), "receita − despesa"),
    ])
    # cards de progresso do período — embaixo
    render_cards([
        card_kpi("Identificado", fmt_int(n_ident), "já com número na capa", classe="destaque-verde" if n_ident > 0 else ""),
        card_kpi("Atrelado agora", fmt_int(k["numerado_agora"]), "números novos", classe="destaque-amarelo" if k["numerado_agora"] > 0 else ""),
        card_kpi("Na esteira", fmt_int(len(pend)), "abertos a resolver"),
        card_kpi("Último número usado", fmt_int(ultimo), "na capa"),
    ])

    numeros_confirmados = {}   # índice original em d -> número atribuído
    seq = prox

    # ---- 2) Atrelamentos sugeridos (faturamento por CNPJ) ----
    st.markdown("##### 🔗 Atrelamentos sugeridos")
    st.caption("Quando o CNPJ da nota bate com o histórico do recebimento, o app sugere aqui. "
               "Confirmar = “esse recebimento é o pagamento dessa nota”. Ao confirmar, ele ganha um número e entra na capa.")
    if up_fat is None:
        st.caption("Suba as notas emitidas (com CNPJ) para o app sugerir atrelamentos pelo CNPJ do histórico.")
    else:
        fat = None
        try:
            fat = _c70_faturamento(up_fat.getvalue(), up_fat.name)
        except Exception as e:
            st.warning(f"Não consegui ler o faturamento: {e}")
        if fat is not None:
            if int((fat["cnpj"] != "").sum()) == 0:
                st.info("O faturamento veio **sem CNPJ preenchido**. Exporte com a coluna CNPJ/CPF para habilitar as sugestões.")
            else:
                sug = sugerir_atrelamentos_cnpj(esteira, fat)
                if sug.empty:
                    st.caption("Nenhum CNPJ do faturamento bateu com as entradas abertas.")
                else:
                    # dedup: uma linha por (recebimento, nota, valor recebido)
                    sug = sug.drop_duplicates(subset=["idx", "nota", "valor_recebido"]).reset_index(drop=True)
                    _rds = sug["receita_despesa"].astype(str).str.upper()
                    _rd_lbl = _rds.map(lambda x: "Despesa" if "DESPESA" in x else "Receita")
                    _sinal = _rds.map(lambda x: -1 if "DESPESA" in x else 1)
                    vis = pd.DataFrame({
                        "Confirmar": False,
                        "R/D": _rd_lbl.values,
                        "CNPJ": sug["cnpj"].values,
                        "Cliente": sug["nome"].astype(str).str.slice(0, 28).values,
                        "Nota": sug["nota"].astype(str).values,
                        "Recebido": (sug["valor_recebido"].astype(float) * _sinal).values,
                        "Valor da nota": pd.to_numeric(sug["valor_nota"], errors="coerce").values,
                        "Confere": sug["valor_fecha"].map(lambda b: "✅ bate" if b else "⚠️ conferir valor").values,
                    })
                    ed = st.data_editor(
                        vis, hide_index=True, use_container_width=True, key="c70_sug_ed",
                        column_config={
                            "Confirmar": st.column_config.CheckboxColumn("Confirmar", help="Marque para atrelar e numerar"),
                            "Recebido": st.column_config.NumberColumn("Recebido", format="%.2f"),
                            "Valor da nota": st.column_config.NumberColumn("Valor da nota", format="%.2f"),
                        },
                        disabled=["R/D", "CNPJ", "Cliente", "Nota", "Recebido", "Valor da nota", "Confere"],
                    )
                    for pos, marc in enumerate(ed["Confirmar"].tolist()):
                        if marc:
                            idx = int(sug.iloc[pos]["idx"])
                            if idx not in numeros_confirmados:
                                numeros_confirmados[idx] = seq
                                seq += 1

    # ---- 3) Esteira — todos os pendentes, com submenu de contadores + filtros ----
    st.markdown("##### 📋 Esteira — pendências abertas")
    st.caption("São os lançamentos da Conta 70 ainda **sem número/baixa** (recebimentos parados + os que precisam de conferência). "
               "Valor negativo = despesa (saída); positivo = receita (entrada).")
    est = esteira.copy()
    if est.empty:
        st.caption("Nenhuma pendência aberta no momento. 🎉")
    else:
        # submenu: quebra por diagnóstico com a quantidade de cada
        contagem = est["diagnostico"].value_counts()
        chips = " &nbsp;·&nbsp; ".join(f"**{nome}:** {qtd}" for nome, qtd in contagem.items())
        st.markdown(f"<div style='color:#9fb3d6;font-size:13px;margin:2px 0 8px'>{chips}</div>", unsafe_allow_html=True)

        fc1, fc2, fc3, fc4 = st.columns([1.2, 1.5, 1.2, 2.0])
        f_prio = fc1.selectbox("Prioridade", ["todas", "Alta", "Média", "Baixa"], key="c70_fprio")
        f_diag = fc2.selectbox("Tipo de pendência", ["todos"] + sorted(est["diagnostico"].dropna().unique().tolist()), key="c70_fdiag")
        f_banco = fc3.selectbox("Banco", ["todos"] + sorted(est["banco"].dropna().unique().tolist()), key="c70_fbanco")
        busca = fc4.text_input("Buscar (CNPJ, valor, histórico)", key="c70_busca")

        view = est
        if f_prio != "todas":
            view = view[view["prioridade"] == f_prio]
        if f_diag != "todos":
            view = view[view["diagnostico"] == f_diag]
        if f_banco != "todos":
            view = view[view["banco"] == f_banco]
        if busca.strip():
            b = busca.strip().lower()
            m = (view["historico"].astype(str).str.lower().str.contains(b, na=False)
                 | view["valor"].abs().round(2).astype(str).str.contains(b, na=False))
            view = view[m]
        st.caption(f"{len(view)} de {len(est)} pendentes")

        # valor com sinal: despesa negativa, receita positiva
        _rdv = view["receita_despesa"].astype(str).str.upper()
        valor_sinal = view["valor"].abs() * _rdv.map(lambda x: -1 if "DESPESA" in x else 1)

        vis2 = pd.DataFrame({
            "Atrelar": False,
            "Data": pd.to_datetime(view["data"], errors="coerce"),
            "Banco": view["banco"].values,
            "R/D": _rdv.map(lambda x: "Despesa" if "DESPESA" in x else "Receita").values,
            "Histórico": view["historico"].astype(str).str.slice(0, 44).values,
            "Valor": valor_sinal.values,
            "Dias": view["dias"].values,
            "Diagnóstico": view["diagnostico"].values,
            "Ação": view["acao"].values,
        }, index=view.index)
        ed2 = st.data_editor(
            vis2, hide_index=True, use_container_width=True, key="c70_est_ed",
            column_config={
                "Atrelar": st.column_config.CheckboxColumn("Atrelar", help="Marque quando localizar o par e quiser numerar"),
                "Valor": st.column_config.NumberColumn("Valor", format="%.2f"),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Dias": st.column_config.NumberColumn("Dias", format="%d"),
            },
            disabled=[c for c in vis2.columns if c != "Atrelar"],
        )
        for idx, marc in zip(vis2.index.tolist(), ed2["Atrelar"].tolist()):
            if marc and idx not in numeros_confirmados:
                numeros_confirmados[idx] = seq
                seq += 1

    # ---- 4) Gerar capa atualizada — INDEPENDENTE da seleção ----
    st.markdown("##### ⬇️ Gerar capa atualizada")
    n_sel = len(numeros_confirmados)
    st.caption(
        "Gera a **capa completa e acumulada** com os números **automáticos** já aplicados. "
        "Marcar atrelamentos acima é **opcional** — se marcar, eles entram também; se não marcar, "
        "a capa sai só com o que o app numerou sozinho. "
        + (f"Marcados agora: **{n_sel}**." if n_sel else "Nada marcado no momento.")
    )
    if st.button("Gerar capa atualizada", key="c70_gerar", type="primary"):
        for idx, num in numeros_confirmados.items():
            if idx in d.index:
                d.at[idx, "numero_final"] = num
                d.at[idx, "situacao"] = "Atrelado (confirmado)"
        try:
            capa_out, preenchidos, n_novos = gerar_capa_acumulada(
                _io.BytesIO(up_capa.getvalue()), d, ultimo,
            )
            buf = _io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                capa_out.to_excel(w, sheet_name="Capa Conta 70", index=False)
            st.session_state["c70_capa_bytes"] = buf.getvalue()
            st.session_state["c70_capa_info"] = (len(capa_out), preenchidos, n_novos - preenchidos)
        except Exception as e:
            st.error(f"Não consegui montar a capa: {e}")

    if st.session_state.get("c70_capa_bytes"):
        linhas, preench, nao_aloc = st.session_state.get("c70_capa_info", (0, 0, 0))
        st.success(
            f"Capa pronta: **{linhas:,} linhas** (acumulada, sinal original), **{preench}** número(s) novo(s) preenchido(s)."
            .replace(",", ".")
            + (f" {nao_aloc} sem linha única na Capa (ficam na esteira, sem chute)." if nao_aloc > 0 else "")
        )
        st.download_button(
            "⬇️ Baixar capa atualizada (.xlsx)",
            data=st.session_state["c70_capa_bytes"],
            file_name=f"capa_conta70_atualizada_{_date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def pagina_conta70():
    from src.conta70 import gerar_conta_70, carregar_historico_conta_70, STATUS_VALIDOS
    from io import BytesIO

    section_title("CONTA 70 — CONTROLE PROVISÓRIO")

    st.markdown(
        "A **Conta 70** é uma conta contábil provisória onde ficam os recebimentos que ainda **não "
        "foram identificados** (não se sabe de qual NF / cliente / pedido são). Aqui você **atrela** "
        "cada um à sua origem e dá um **número sequencial**, atualizando a capa da conta."
    )

    # v5.5: Casamento e numeração (Capa × Sankhya) — aditivo e independente da conciliação
    _render_conta70_casamento_numeracao()
    st.divider()

    resultado = st.session_state.get("resultado")
    if resultado is None:
        with st.expander("Visão complementar (vem da conciliação)", expanded=False):
            st.caption(
                "Esta seção é **opcional** e mostra os créditos não identificados a partir do "
                "**fechamento de uma conciliação**. Ela aparece depois que você roda uma conciliação — "
                "o atrelamento e a numeração acima não dependem dela."
            )
        return

    # Upload do histórico (opcional)
    with st.expander("📁 Subir histórico anterior (opcional)", expanded=False):
        st.markdown(
            "Suba aqui o arquivo `conta_70_historico.xlsx` que você mantém com os "
            "status das execuções passadas (ex.: linhas marcadas como **Regularizado**, "
            "com observações, etc). O sistema vai mesclar essas informações com os "
            "créditos da execução atual."
        )
        arq_hist = st.file_uploader(
            "Histórico Conta 70 (.xlsx)",
            type=["xlsx"],
            key="upload_historico_conta70",
            help="Arquivo gerado pelo botão 'Baixar Conta 70' em execuções anteriores, possivelmente editado por você.",
        )
        historico_df = pd.DataFrame()
        if arq_hist is not None:
            historico_df = carregar_historico_conta_70(arq_hist)
            if historico_df.empty:
                st.warning("Arquivo não pôde ser lido ou está vazio. Verifique o formato.")
            else:
                st.success(f"✅ {len(historico_df)} linhas de histórico carregadas.")

    # Gera Conta 70
    historico_df = locals().get("historico_df", pd.DataFrame())
    id_exec = st.session_state.get("id_execucao_atual", "")
    res_c70 = gerar_conta_70(
        resultado.pendentes_banco,
        historico_anterior=historico_df if not historico_df.empty else None,
        id_execucao=id_exec,
    )
    kpis_c70 = res_c70.kpis

    if res_c70.detalhado.empty:
        st.info(
            "A **conciliação bancária** desta sessão não deixou créditos não identificados. "
            "As pendências da Conta 70 (atrelamento Capa × Sankhya) aparecem na **esteira acima** — "
            "esta seção abaixo é só a visão que vem da conciliação."
        )
        return

    st.write("")
    section_title("INDICADORES — CONTA 70")

    cards1 = [
        card_kpi("Total a Lançar", fmt_brl(kpis_c70["total_a_lancar"]),
                 "valores não identificados",
                 classe="destaque-vermelho" if kpis_c70["total_a_lancar"] > 0 else ""),
        card_kpi("Quantidade", fmt_int(kpis_c70["qtd_total"]),
                 "lançamentos no controle"),
        card_kpi("Contas Envolvidas", fmt_int(kpis_c70["qtd_contas"])),
        card_kpi("Regularizados", fmt_int(kpis_c70["qtd_regularizado"]),
                 "identificados em revisões anteriores",
                 classe="destaque-verde" if kpis_c70["qtd_regularizado"] > 0 else ""),
    ]
    render_cards(cards1)

    cards2 = [
        card_kpi("Não Identificado", fmt_int(kpis_c70["qtd_nao_identificado"]),
                 classe="destaque-amarelo" if kpis_c70["qtd_nao_identificado"] > 0 else ""),
        card_kpi("Pendente de NF", fmt_int(kpis_c70["qtd_pendente_nf"])),
        card_kpi("Pendente de Baixa", fmt_int(kpis_c70["qtd_pendente_baixa"])),
        card_kpi("Em Análise", fmt_int(kpis_c70["qtd_em_analise"])),
    ]
    render_cards(cards2)

    st.divider()

    # Agrupamentos
    section_title("RESUMOS")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Por banco/conta:**")
        por_banco = res_c70.por_banco()
        if not por_banco.empty:
            por_banco["Total a Lançar"] = por_banco["Total a Lançar"].apply(fmt_brl)
            st.dataframe(por_banco, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem dados.")
    with col2:
        st.markdown("**Por data:**")
        por_data = res_c70.por_data()
        if not por_data.empty:
            por_data["Total a Lançar"] = por_data["Total a Lançar"].apply(fmt_brl)
            st.dataframe(por_data, use_container_width=True, hide_index=True)
        else:
            st.caption("Sem dados.")

    st.divider()

    section_title("DETALHAMENTO — EDITÁVEL")
    st.caption(
        "Você pode editar o **status** e a **observação** de cada linha. "
        "Depois, clique em **Baixar Conta 70** pra salvar o arquivo. Na próxima execução, "
        "suba esse arquivo em '📁 Subir histórico anterior' pra manter os status."
    )

    # Filtros
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filtro_status = st.multiselect(
            "Filtrar por status",
            options=STATUS_VALIDOS,
            default=[],
            placeholder="Todos",
        )
    with col_f2:
        contas_unicas = sorted(res_c70.detalhado["conta"].unique().tolist())
        filtro_conta = st.multiselect(
            "Filtrar por conta",
            options=contas_unicas,
            default=[],
            placeholder="Todas",
        )
    with col_f3:
        filtro_tipo = st.multiselect(
            "Filtrar por tipo",
            options=sorted(res_c70.detalhado["tipo_recebimento"].unique().tolist()),
            default=[],
            placeholder="Todos",
        )

    df_visu = res_c70.detalhado.copy()
    if filtro_status:
        df_visu = df_visu[df_visu["status"].isin(filtro_status)]
    if filtro_conta:
        df_visu = df_visu[df_visu["conta"].isin(filtro_conta)]
    if filtro_tipo:
        df_visu = df_visu[df_visu["tipo_recebimento"].isin(filtro_tipo)]

    if df_visu.empty:
        st.info("Nenhuma linha corresponde aos filtros.")
        return

    # Tabela editável
    edited = st.data_editor(
        df_visu,
        column_config={
            "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", disabled=True),
            "conta": st.column_config.TextColumn("Conta", disabled=True),
            "historico": st.column_config.TextColumn("Histórico", disabled=True),
            "documento": st.column_config.TextColumn("Documento", disabled=True),
            "valor": st.column_config.NumberColumn("Valor (R$)", format="%.2f", disabled=True),
            "tipo_recebimento": st.column_config.TextColumn("Tipo", disabled=True),
            "status": st.column_config.SelectboxColumn(
                "Status",
                options=STATUS_VALIDOS,
                required=True,
            ),
            "conta_contabil": st.column_config.TextColumn("Conta Contábil", disabled=True),
            "observacao": st.column_config.TextColumn("Observação", help="Edite aqui pra anotar"),
            "data_analise": st.column_config.DatetimeColumn("Análise", disabled=True),
            "id_execucao": st.column_config.TextColumn("ID Execução", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        key="editor_conta70",
    )

    st.write("")
    section_title("EXPORTAR")

    # Download Excel + CSV
    col_dl1, col_dl2 = st.columns(2)

    buf_xlsx = BytesIO()
    with pd.ExcelWriter(buf_xlsx, engine="openpyxl") as writer:
        edited.to_excel(writer, sheet_name="Conta 70", index=False)
        res_c70.por_banco().to_excel(writer, sheet_name="Por Banco", index=False)
        res_c70.por_data().to_excel(writer, sheet_name="Por Data", index=False)
        res_c70.por_status().to_excel(writer, sheet_name="Por Status", index=False)
    buf_xlsx.seek(0)
    from datetime import date as _date
    nome_xlsx = f"conta_70_{_date.today().strftime('%Y%m%d')}.xlsx"
    with col_dl1:
        st.download_button(
            "⬇️ Baixar Conta 70 (.xlsx)",
            data=buf_xlsx.getvalue(),
            file_name=nome_xlsx,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    with col_dl2:
        csv_bytes = edited.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "⬇️ Baixar Conta 70 (.csv)",
            data=csv_bytes,
            file_name=f"conta_70_{_date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
        )


# ============================================================
# Roteamento
# ============================================================
pagina = st.session_state.pagina
if pagina == "Dashboard":
    pagina_dashboard()
elif pagina == "Conciliação":
    pagina_conciliacao()
elif pagina == "Cadastro de Taxas":
    pagina_cadastro_taxas()
elif pagina == "Auditoria de Taxas":
    pagina_auditoria_taxas()
elif pagina == "Conta 70":
    pagina_conta70()
elif pagina == "Histórico":
    pagina_historico()
elif pagina == "Sobre":
    pagina_sobre()


# ============================================================
# Footer
# ============================================================
st.html(
    f"""
    <div class="lle-footer">
        <strong style="color:{CORES['amarelo']};">Grupo LLE</strong> · Conciliação Bancária ·
        Aplicação interna seguindo o Manual da Marca (Fev/2026).<br>
        Dúvidas sobre identidade visual:
        <a href="mailto:marketing@grupolle.com.br">marketing@grupolle.com.br</a>
    </div>
    """
)
