"""App Streamlit — Conciliação Bancária Grupo LLE.

Layout: fundo azul institucional, sidebar amarela, cards executivos.
Fluxo: Upload → tela única de Resultado com cards, painel de bancos
e abas internas por status / subabas por tipo.
"""

from __future__ import annotations

import base64
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
    """Retorna a logo PNG (texto branco, ideal para fundo azul) como data URI."""
    arq = ASSETS / "logo-grupo-lle-branco.png"
    if not arq.exists():
        return ""
    b64 = base64.b64encode(arq.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


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
<style>
/* ===== Tipografia e fundo ===== */
html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {{
    font-family: 'Montserrat', sans-serif !important;
}}
.stApp {{
    background-color: {CORES["azul_escuro"]};
    color: {CORES["branco"]};
}}
.block-container {{
    padding-top: 1.2rem;
    padding-bottom: 4rem;
    max-width: 1500px;
}}
h1, h2, h3, h4, h5, h6, p, span, div, label {{ color: {CORES["branco"]}; }}

/* ===== Sidebar AMARELA ===== */
[data-testid="stSidebar"] {{
    background-color: {CORES["amarelo"]} !important;
    border-right: none;
}}
[data-testid="stSidebar"] * {{ color: {CORES["azul_escuro"]} !important; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(4,23,71,0.18) !important; }}

.lle-sidebar-logo {{
    background-color: {CORES["azul_escuro"]};
    padding: 18px 12px 14px 12px;
    margin: -16px -16px 14px -16px;
    border-radius: 0 0 16px 16px;
    text-align: center;
}}
.lle-sidebar-logo img {{
    height: 72px;
    width: auto;
    display: inline-block;
}}
.lle-sidebar-tagline {{
    text-align: center;
    color: {CORES["amarelo"]} !important;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    margin-top: 8px;
}}

[data-testid="stSidebar"] .stButton > button {{
    background-color: rgba(4,23,71,0.05);
    color: {CORES["azul_escuro"]} !important;
    border: 1px solid rgba(4,23,71,0.2);
    border-radius: 10px;
    padding: 12px 16px;
    font-weight: 600;
    font-size: 14px;
    text-align: left;
    width: 100%;
    transition: all 0.18s ease;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background-color: {CORES["azul_escuro"]};
    color: {CORES["amarelo"]} !important;
    border-color: {CORES["azul_escuro"]};
    transform: translateX(2px);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background-color: {CORES["azul_escuro"]} !important;
    border-color: {CORES["azul_escuro"]} !important;
}}
/* Texto e ícone do botão primary na sidebar precisam ser AMARELOS, sobrepondo o seletor genérico */
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[kind="primary"] * {{
    color: {CORES["amarelo"]} !important;
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
    background-color: {CORES["card_bg"]};
    border: 1px solid {CORES["card_borda"]};
    border-radius: 14px;
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
    transition: all 0.2s ease;
}}
.lle-kpi:hover {{
    border-color: {CORES["amarelo"]};
    transform: translateY(-2px);
}}
.lle-kpi::before {{
    content: "";
    position: absolute;
    top: 0; left: 0;
    width: 4px; height: 100%;
    background-color: {CORES["amarelo"]};
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

/* Botões primários e gerais */
.stButton > button {{
    background-color: {CORES["azul"]};
    color: {CORES["branco"]};
    border: none;
    border-radius: 10px;
    font-weight: 600;
    padding: 10px 18px;
    transition: all 0.18s ease;
}}
.stButton > button:hover {{
    background-color: {CORES["amarelo"]};
    color: {CORES["azul_escuro"]} !important;
}}
.stButton > button[kind="primary"] {{
    background-color: {CORES["amarelo"]};
    color: {CORES["azul_escuro"]} !important;
}}
.stButton > button[kind="primary"]:hover {{
    background-color: {CORES["amarelo_2"]};
}}

/* ===== Inputs e file uploader ===== */
input, textarea, select, [data-baseweb="select"] > div {{
    background-color: {CORES["azul_escuro_2"]} !important;
    color: {CORES["branco"]} !important;
    border-color: {CORES["card_borda"]} !important;
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
[data-testid="stFileUploaderDropzone"] * {{ color: {CORES["branco"]} !important; }}

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

    paginas = [
        ("📊 Dashboard", "Dashboard"),
        ("🔄 Conciliação", "Conciliação"),
        ("📂 Histórico", "Histórico"),
        ("ℹ️ Sobre", "Sobre"),
    ]
    for label, key in paginas:
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


def render_cards(cards: list[str]):
    html = '<div class="lle-kpi-row">' + "".join(cards) + "</div>"
    st.html(html)


def section_title(texto: str):
    st.html(f'<div class="lle-section-title">{texto}</div>')


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

    cards1 = [
        card_kpi("Total Extrato Bancário", fmt_brl(kpis["total_extrato_bancario"])),
        card_kpi("Total Extrato Sankhya", fmt_brl(kpis["total_extrato_sistema"])),
        card_kpi("Total Conciliado", fmt_brl(kpis["total_conciliado"]), classe="destaque-verde"),
        card_kpi("Percentual Conciliado", fmt_pct(kpis["percentual_conciliado"]),
                 classe="destaque-amarelo"),
    ]
    render_cards(cards1)

    cards2 = [
        card_kpi("Falta Conciliar", fmt_brl(kpis["falta_conciliar"]),
                 "no sistema (pendência banco)", classe="destaque-vermelho"),
        card_kpi("Falta Lançar", fmt_brl(kpis["falta_lancar"]),
                 "no banco (pendência sistema)", classe="destaque-vermelho"),
        card_kpi("Conciliado c/ Divergência", fmt_brl(kpis["valor_divergencia"]),
                 classe="destaque-amarelo" if kpis["valor_divergencia"] > 0 else ""),
        card_kpi("Total Processado", fmt_int(kpis["qtd_total_processado"]), "registros"),
    ]
    render_cards(cards2)

    cards3 = [
        card_kpi("Registros Processados", fmt_int(kpis["qtd_registros_banco"] + kpis["qtd_registros_sistema"])),
        card_kpi("Conciliados", fmt_int(kpis["qtd_conciliados"]), classe="destaque-verde"),
        card_kpi("Pendentes", fmt_int(kpis["qtd_pendentes_banco"] + kpis["qtd_pendentes_sistema"]),
                 classe="destaque-vermelho"),
        card_kpi("Divergentes", fmt_int(kpis["qtd_divergencias"]),
                 classe="destaque-amarelo" if kpis["qtd_divergencias"] > 0 else ""),
    ]
    render_cards(cards3)

    st.divider()
    section_title("CONTAS PROCESSADAS")
    render_painel_bancos(resultado)


# ============================================================
# Painel de botões por banco
# ============================================================
def render_painel_bancos(resultado: ResultadoConciliacao):
    contas = resultado.contas_processadas
    if not contas:
        st.warning("Nenhuma conta foi processada.")
        return

    kpis_pb = resultado.kpis_por_banco()
    cols = st.columns(min(len(contas), 4))
    for i, conta in enumerate(contas):
        col = cols[i % len(cols)]
        k = kpis_pb[conta]
        pct = k["percentual_conciliado"]
        if pct >= 95:
            classe = "verde"
        elif pct >= 70:
            classe = "amarelo"
        else:
            classe = "vermelho"

        with col:
            st.html(
                f"""
                <div class="lle-kpi" style="cursor:pointer;">
                    <div class="lle-kpi-label">{conta}</div>
                    <div class="lle-kpi-value" style="font-size:22px;">
                        {fmt_pct(pct)}
                    </div>
                    <div class="lle-kpi-suffix">
                        <span class="lle-badge {classe}">
                            {fmt_int(k["qtd_conciliados"])} conciliados
                        </span>
                    </div>
                </div>
                """
            )
            st.button(
                "Ver detalhamento →",
                key=f"banco_btn_{conta}",
                on_click=selecionar_banco,
                args=(conta,),
                use_container_width=True,
            )


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
        data_ref = st.date_input(
            "Data de referência",
            value=date.today(),
            format="DD/MM/YYYY",
        )

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        section_title("EXTRATO BANCÁRIO")
        st.caption("Formato padronizado: Data, Histórico, Documento, Valor (R$).")
        if modo == "1 conta por vez":
            arquivo_banco = st.file_uploader(
                "Arraste o extrato",
                type=["xlsx", "xls"],
                key="banco_single",
            )
            nome_conta = st.text_input(
                "Extrato Bancário (identificador da conta)",
                placeholder="ex: Bradesco-CC-12345",
                key="conta_single",
                help="Rótulo único da conta. Mínimo 3 caracteres.",
            )
            arquivos_banco = (
                [(nome_conta.strip(), arquivo_banco)]
                if arquivo_banco and nome_conta.strip()
                else []
            )
        else:
            st.caption("Use o nome do arquivo como identificador da conta (ex: `Bradesco-12345.xlsx`).")
            arquivos_multi = st.file_uploader(
                "Arraste os extratos (um por conta)",
                type=["xlsx", "xls"],
                accept_multiple_files=True,
                key="banco_multi",
            )
            arquivos_banco = [
                (f.name.rsplit(".", 1)[0], f) for f in (arquivos_multi or [])
            ]

    with col2:
        section_title("EXTRATO SANKHYA CONCILIAÇÃO")
        st.caption("Relatório de Conciliação Bancária exportado do ERP.")
        arquivo_sistema = st.file_uploader(
            "Arraste o relatório do sistema",
            type=["xlsx", "xls"],
            key="sistema",
        )
        coluna_conta_sistema = st.text_input(
            "Extrato Sankhya Conciliação — coluna da conta",
            value="",
            placeholder="(deixe vazio para auto-detectar)",
            help="Nome exato da coluna do ERP que identifica a conta. Se vazio, tenta detectar.",
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

    if not arquivos_banco or not arquivo_sistema:
        st.warning("⏳ Aguardando upload do extrato bancário **e** do relatório do sistema.")
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
                    df = carregar_extrato_banco(arq, conta=nome_conta)
                    dfs_banco.append(df)
                banco = pd.concat(dfs_banco, ignore_index=True) if dfs_banco else pd.DataFrame()

                sistema = carregar_relatorio_sistema(
                    arquivo_sistema,
                    coluna_conta=coluna_conta_sistema or None,
                )

                if modo == "1 conta por vez" and not sistema.empty and (sistema["conta"] == "—").all():
                    sistema["conta"] = arquivos_banco[0][0]
                    st.info(
                        f"ℹ️ Relatório do sistema sem coluna de conta — atribuído a '{arquivos_banco[0][0]}'."
                    )

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

                id_exec = novo_id_execucao()

                # Gera o Excel já para snapshot
                xlsx_bytes = gerar_relatorio_excel(
                    resultado,
                    pendencias_anteriores=pendencias,
                    execucao={"id": id_exec, "versao": versao, "status": "processado"},
                )

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
                        relatorio_xlsx=xlsx_bytes,
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
                st.session_state.pendencias_anteriores = pendencias
                st.session_state.id_execucao_atual = id_exec
                st.session_state.xlsx_atual = xlsx_bytes
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
def tela_resultado():
    resultado: ResultadoConciliacao = st.session_state.resultado
    kpis = resultado.kpis_globais()

    # Topo: botão voltar + ações principais
    col_top1, col_top2, col_top3 = st.columns([2, 1, 1])
    with col_top1:
        st.button(
            "← Nova conciliação / reprocessar",
            on_click=voltar_upload,
            use_container_width=True,
        )
    with col_top2:
        xlsx_bytes = st.session_state.get("xlsx_atual") or gerar_relatorio_excel(
            resultado, pendencias_anteriores=st.session_state.pendencias_anteriores
        )
        nome = f"conciliacao_{resultado.data_referencia.strftime('%Y%m%d')}.xlsx"
        st.download_button(
            "⬇️ Excel (todas as abas)",
            data=xlsx_bytes,
            file_name=nome,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    with col_top3:
        zip_bytes = gerar_csvs_zip(resultado)
        nome_zip = f"conciliacao_{resultado.data_referencia.strftime('%Y%m%d')}_csvs.zip"
        st.download_button(
            "⬇️ CSVs (zip)",
            data=zip_bytes,
            file_name=nome_zip,
            mime="application/zip",
            use_container_width=True,
        )

    st.divider()

    # KPIs executivos
    section_title("RESUMO EXECUTIVO")
    cards1 = [
        card_kpi("Total Extrato Bancário", fmt_brl(kpis["total_extrato_bancario"])),
        card_kpi("Total Extrato Sankhya", fmt_brl(kpis["total_extrato_sistema"])),
        card_kpi("Total Conciliado", fmt_brl(kpis["total_conciliado"]), classe="destaque-verde"),
        card_kpi("Percentual Conciliado", fmt_pct(kpis["percentual_conciliado"]), classe="destaque-amarelo"),
    ]
    render_cards(cards1)

    cards2 = [
        card_kpi("Falta Conciliar", fmt_brl(kpis["falta_conciliar"]),
                 "pendência do banco", classe="destaque-vermelho"),
        card_kpi("Falta Lançar", fmt_brl(kpis["falta_lancar"]),
                 "pendência do sistema", classe="destaque-vermelho"),
        card_kpi("Valor c/ Divergência", fmt_brl(kpis["valor_divergencia"]),
                 classe="destaque-amarelo" if kpis["valor_divergencia"] > 0 else ""),
        card_kpi("Total Processado", fmt_int(kpis["qtd_total_processado"]), "registros"),
    ]
    render_cards(cards2)

    cards3 = [
        card_kpi("Registros Banco", fmt_int(kpis["qtd_registros_banco"])),
        card_kpi("Registros Sistema", fmt_int(kpis["qtd_registros_sistema"])),
        card_kpi("Pendentes Banco", fmt_int(kpis["qtd_pendentes_banco"])),
        card_kpi("Pendentes Sistema", fmt_int(kpis["qtd_pendentes_sistema"])),
    ]
    render_cards(cards3)

    st.divider()

    # Painel de bancos OU detalhe do banco selecionado
    if st.session_state.banco_conta_selecionada:
        tela_detalhamento_banco(resultado, st.session_state.banco_conta_selecionada)
    else:
        section_title("CONTAS PROCESSADAS — CLIQUE PARA DETALHAR")
        render_painel_bancos(resultado)

        st.write("")
        section_title("CONCILIAÇÃO POR TIPO DE LANÇAMENTO")
        render_subabas_tipo(resultado)


# ============================================================
# Detalhamento por banco — cards + abas internas
# ============================================================
def tela_detalhamento_banco(resultado: ResultadoConciliacao, conta: str):
    col_back, _ = st.columns([1, 5])
    with col_back:
        if st.button("← Voltar ao painel"):
            st.session_state.banco_conta_selecionada = None
            st.rerun()

    section_title(f"DETALHAMENTO · {conta}")

    k = resultado.kpis_da_conta(conta)
    cards = [
        card_kpi("Total Banco", fmt_brl(k["total_extrato_bancario"])),
        card_kpi("Total Sankhya", fmt_brl(k["total_extrato_sistema"])),
        card_kpi("Conciliado", fmt_brl(k["total_conciliado"]), classe="destaque-verde"),
        card_kpi("% Conciliado", fmt_pct(k["percentual_conciliado"]), classe="destaque-amarelo"),
    ]
    render_cards(cards)

    cards2 = [
        card_kpi("Falta Conciliar", fmt_brl(k["falta_conciliar"]), classe="destaque-vermelho"),
        card_kpi("Falta Lançar", fmt_brl(k["falta_lancar"]), classe="destaque-vermelho"),
        card_kpi("c/ Divergência", fmt_brl(k["valor_divergencia"]),
                 classe="destaque-amarelo" if k["valor_divergencia"] > 0 else ""),
        card_kpi("Total Lançamentos", fmt_int(k["qtd_registros_banco"] + k["qtd_registros_sistema"])),
    ]
    render_cards(cards2)

    # Download específico desse banco
    try:
        xlsx_banco = gerar_relatorio_excel_de_conta(resultado, conta)
        st.download_button(
            f"⬇️ Baixar relatório de {conta}",
            data=xlsx_banco,
            file_name=f"conciliacao_{conta}_{resultado.data_referencia.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except Exception as e:
        st.warning(f"Não foi possível gerar o Excel deste banco: {e}")

    st.divider()

    # Abas internas por status
    div_conta = resultado.divergencias_da_conta(conta)
    tabs_nomes = ["✅ Conciliadas", "⏳ Pendentes", "🏦 Não Pertence à Conta"]
    if not div_conta.empty:
        tabs_nomes.append("⚠️ Conciliadas com Divergência")

    tabs = st.tabs(tabs_nomes)

    with tabs[0]:
        render_tab_conciliadas(resultado.conciliados_da_conta(conta), conta)
    with tabs[1]:
        render_tab_pendentes(resultado, conta)
    with tabs[2]:
        render_tab_nao_pertence(resultado.nao_pertence_da_conta(conta), conta)
    if not div_conta.empty:
        with tabs[3]:
            render_tab_divergencias(div_conta, conta)


def _exibir_df(df: pd.DataFrame, nome_arquivo: str, msg_vazio: str = "Nenhum registro nesta categoria."):
    if df.empty:
        st.success(f"🎉 {msg_vazio}")
        return
    df_show = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")
    st.dataframe(df_show, use_container_width=True, height=420)
    col_xls, col_csv = st.columns(2)
    with col_xls:
        buf_xls = _df_to_xlsx_bytes(df_show, nome_arquivo)
        st.download_button(
            f"⬇️ Baixar Excel ({len(df_show)} linhas)",
            data=buf_xls,
            file_name=f"{nome_arquivo}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with col_csv:
        csv_str = df_show.to_csv(index=False, sep=";", encoding="utf-8-sig", decimal=",")
        st.download_button(
            f"⬇️ Baixar CSV ({len(df_show)} linhas)",
            data=csv_str.encode("utf-8-sig"),
            file_name=f"{nome_arquivo}.csv",
            mime="text/csv",
            use_container_width=True,
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
    ps = (
        resultado.pendentes_sistema[resultado.pendentes_sistema["conta"] == conta].copy()
        if not resultado.pendentes_sistema.empty else pd.DataFrame()
    )
    if not pb.empty:
        pb["origem"] = "Banco (falta lançar no Sistema)"
    if not ps.empty:
        ps["origem"] = "Sistema (falta no Banco)"
    df = pd.concat([pb, ps], ignore_index=True)
    if df.empty:
        st.success("🎉 Não há pendências nesta conta.")
        return
    cols = ["origem", "data", "historico", "documento", "valor", "tipo", "natureza"]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]
    df.columns = [c.title() for c in df.columns]
    _exibir_df(df, f"pendentes_{conta}")


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


# ============================================================
# Subabas por TIPO de lançamento (Boleto, Pix, Tarifa...)
# ============================================================
def render_subabas_tipo(resultado: ResultadoConciliacao):
    tipos_disponiveis = ["Todos"] + TIPOS_PRINCIPAIS + ["Pagamentos", "Recebimentos", "Outros"]
    tabs = st.tabs(tipos_disponiveis)

    for tab, tipo in zip(tabs, tipos_disponiveis):
        with tab:
            if tipo == "Todos":
                df = pd.concat(
                    [resultado.banco_completo.assign(origem="Banco"),
                     resultado.sistema_completo.assign(origem="Sistema")],
                    ignore_index=True,
                ) if not (resultado.banco_completo.empty and resultado.sistema_completo.empty) else pd.DataFrame()
            elif tipo == "Pagamentos":
                df = _filtrar_por(resultado, lambda d: d[d["natureza"] == "Pagamento"])
            elif tipo == "Recebimentos":
                df = _filtrar_por(resultado, lambda d: d[d["natureza"] == "Recebimento"])
            else:
                df = _filtrar_por(resultado, lambda d: d[d["tipo"] == tipo])

            if df.empty:
                st.info(f"Nenhum lançamento do tipo **{tipo}**.")
                continue

            # KPIs do tipo
            qtd = len(df)
            valor_total = float(df["valor"].abs().sum()) if "valor" in df.columns else 0.0
            por_conta = (
                df.groupby("conta")["valor"].agg(["count", "sum"]).reset_index()
                if "conta" in df.columns else pd.DataFrame()
            )

            cards = [
                card_kpi(f"Lançamentos {tipo}", fmt_int(qtd)),
                card_kpi("Valor total (absoluto)", fmt_brl(valor_total), classe="destaque-amarelo"),
                card_kpi("Contas envolvidas",
                         fmt_int(df["conta"].nunique() if "conta" in df.columns else 0)),
            ]
            render_cards(cards)

            cols_show = ["origem", "data", "conta", "historico", "documento", "valor", "tipo", "natureza"]
            cols_show = [c for c in cols_show if c in df.columns]
            out = df[cols_show].copy()
            out.columns = [c.title() for c in out.columns]
            _exibir_df(out, f"tipo_{tipo.lower().replace(' ', '_')}")


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
- Data: tolerância de **±N dias corridos** (configurável na sidebar, default 2).
  Cobre compensação por fim de semana e feriados curtos.
- Match é **1-pra-1**. Cada lançamento do banco casa com no máximo um do sistema.

**Divergência de valor:**
- Mesma data + histórico exato (após normalização) + conta, mas valores diferentes.

**Duplicidade (estrita):**
- Só é sinalizada quando **data, histórico, valor E documento** são todos iguais.
- 5 boletos de R$ 1.000 com documentos diferentes **não** são duplicidade — são pagamentos legítimos.

**Não Pertence à Conta:**
- Pendência em uma conta que tem candidato perfeito (mesmo valor + data próxima) em **outra conta**.

**Sugestões Fuzzy:**
- Aba complementar — históricos similares com mesmo valor/conta para revisão manual.
- **Não entra na conciliação automática**.
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
# Roteamento
# ============================================================
pagina = st.session_state.pagina
if pagina == "Dashboard":
    pagina_dashboard()
elif pagina == "Conciliação":
    pagina_conciliacao()
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
