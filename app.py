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
    """Retorna a logo PNG (com fundo transparente) como data URI."""
    # Preferir a versão transparente; cair para a com fundo se a transparente não existir
    for nome in ("logo-grupo-lle-transparente.png", "logo-grupo-lle-branco.png"):
        arq = ASSETS / nome
        if arq.exists():
            b64 = base64.b64encode(arq.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    return ""


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
    """v5.15: conserto duplo no card de Investimentos.

    Bug anterior: o df vinha com lançamentos do banco E do sankhya, e a soma
    contava o mesmo movimento duas vezes (R$ 27.698 virava R$ 55.396).

    Correções:
    1) DEDUP: agrupa por (data + valor + conta + tipo_aplicacao), preferindo
       o lado Sankhya quando ambos existem (ERP é a verdade contábil).
    2) Ignora SALDO defensivamente — saldo aplicado não é movimento, não
       deveria nem chegar aqui, mas se chegar (bug em src/), é filtrado.
    """
    if df.empty:
        return card_kpi("Investimentos", "—", "sem aplicações/resgates")

    df = df.copy()

    # (2) Filtro defensivo: SALDO não é aplicação nem resgate
    if "historico" in df.columns:
        mask_saldo = df["historico"].astype(str).str.upper().str.contains("SALDO", na=False)
        df = df[~mask_saldo]

    if df.empty:
        return card_kpi("Investimentos", "—", "sem aplicações/resgates")

    # (1) DEDUP banco × sankhya: preferir Sankhya quando ambos existem
    cols_chave = [c for c in ["data", "valor", "conta", "tipo_aplicacao"] if c in df.columns]
    if cols_chave and "origem" in df.columns:
        # Ordena pra Sankhya vir antes de Banco, depois drop_duplicates mantém o primeiro
        df["_ord_origem"] = df["origem"].apply(lambda x: 0 if "Sankhya" in str(x) else 1)
        df = df.sort_values("_ord_origem").drop_duplicates(subset=cols_chave, keep="first")
        df = df.drop(columns=["_ord_origem"])

    aplic = df[df["tipo_aplicacao"] == "Aplicação"] if "tipo_aplicacao" in df.columns else pd.DataFrame()
    resg = df[df["tipo_aplicacao"] == "Resgate"] if "tipo_aplicacao" in df.columns else pd.DataFrame()
    qtd_a = len(aplic)
    val_a = float(aplic["valor"].abs().sum()) if not aplic.empty else 0.0
    qtd_r = len(resg)
    val_r = float(resg["valor"].abs().sum()) if not resg.empty else 0.0
    total = val_a + val_r
    sub = f"""
    <div class="lle-kpi-sub-stack">
        <div class="lle-kpi-sub-label">Aplicações:</div>
        <div class="lle-kpi-sub-valor">{fmt_int(qtd_a)} mov. · {fmt_brl(val_a)}</div>
        <div class="lle-kpi-sub-label">Resgates:</div>
        <div class="lle-kpi-sub-valor">{fmt_int(qtd_r)} mov. · {fmt_brl(val_r)}</div>
    </div>
    """
    return card_kpi_html("Investimentos", fmt_brl(total), sub, classe="destaque-amarelo")


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

    # Investimentos: pega global ou por conta
    if conta:
        df_inv = resultado.aplicacoes_resgates_da_conta(conta)
    else:
        df_inv = resultado.aplicacoes_resgates
    tem_invest = not df_inv.empty

    # Só renderiza a seção se houver pelo menos uma exceção
    if not (qtd_est_anu > 0 or qtd_est_par > 0 or qtd_top1722 > 0 or tem_invest):
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
    df_inv = resultado.aplicacoes_resgates
    tem_invest = not df_inv.empty

    # Se nenhuma das regras se aplica, mostra seção minimalista com "nenhuma exceção"
    if not (qtd_est_anu > 0 or qtd_est_par > 0 or qtd_top1722 > 0 or tem_invest):
        editorial_secao_head("Exceções aplicadas", "nenhuma neste período")
        return

    total_regras = sum(1 for x in [qtd_est_anu > 0, qtd_est_par > 0, qtd_top1722 > 0, tem_invest] if x)
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
    df_inv = resultado.aplicacoes_resgates
    tem_invest = not df_inv.empty

    # Se nenhuma exceção, esconde a seção (não polui)
    if not (qtd_est_anu > 0 or qtd_est_par > 0 or qtd_top1722 > 0 or tem_invest):
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
        card_kpi("Total Conciliado", fmt_brl(kpis["total_conciliado"]),
                 "match Banco × Sankhya", classe="destaque-verde"),
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
    """v3.10: `mostrar_botao=False` no Dashboard (cards só informativos)."""
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
                <div class="lle-kpi">
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
            if mostrar_botao:
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
            # v5.8: auto-preenche o nome da conta a partir do nome do arquivo.
            # O usu\u00e1rio pode editar livremente.
            nome_default = ""
            if arquivo_banco is not None:
                nome_default = arquivo_banco.name.rsplit(".", 1)[0].strip()

            nome_conta = st.text_input(
                "Extrato Bancário (identificador da conta)",
                value=nome_default,
                placeholder="ex: Bradesco-CC-12345",
                key="conta_single",
                help="Rótulo único da conta. Mínimo 3 caracteres. Auto-preenchido com o nome do arquivo.",
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

                sistema = carregar_relatorio_sistema(
                    arquivo_sistema,
                    coluna_conta=coluna_conta_sistema or None,
                )

                # v3.6: mesmo tratamento para o sistema
                if not sistema.empty:
                    if "data" in sistema.columns:
                        sistema["data"] = pd.to_datetime(sistema["data"], errors="coerce")
                    if "valor" in sistema.columns:
                        sistema["valor"] = pd.to_numeric(sistema["valor"], errors="coerce").fillna(0.0)
                    sistema = sistema.dropna(subset=["data"]).reset_index(drop=True)

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
def tela_resultado():
    resultado: ResultadoConciliacao = st.session_state.resultado
    kpis = resultado.kpis_globais()

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
        # v3.10: cache no session_state — evita regerar o zip a cada rerun
        zip_bytes = st.session_state.get("csvs_zip_atual")
        if zip_bytes is None:
            zip_bytes = gerar_csvs_zip(resultado)
            st.session_state.csvs_zip_atual = zip_bytes
        nome_zip = f"conciliacao_{resultado.data_referencia.strftime('%Y%m%d')}_csvs.zip"
        st.download_button(
            "⬇️ CSVs (zip)",
            data=zip_bytes,
            file_name=nome_zip,
            mime="application/zip",
            type="primary",
            use_container_width=True,
        )

    st.divider()

    # v3.9: RESUMO EXECUTIVO global só aparece quando NENHUMA conta está selecionada.
    # Quando o usuário entra no detalhamento de uma conta específica, mostra direto
    # o detalhe da conta — evita confundir KPIs globais com KPIs da conta selecionada.
    if not st.session_state.banco_conta_selecionada:
        # KPIs executivos
        section_title("RESUMO EXECUTIVO")

        # Linha 1: principais (com receitas/despesas embaixo dos 2 totais)
        sub_banco = _card_total_com_rec_desp(kpis["receitas_banco"], kpis["despesas_banco"])
        sub_sankhya = _card_total_com_rec_desp(kpis["receitas_sistema"], kpis["despesas_sistema"])
        cards1 = [
            card_kpi_html("Total Movimentado no Banco", fmt_brl(kpis["total_movimentado_banco"]),
                          sub_banco),
            card_kpi_html("Total Extrato Sankhya", fmt_brl(kpis["total_extrato_sistema"]),
                          sub_sankhya),
            card_kpi("Total Conciliado", fmt_brl(kpis["total_conciliado"]),
                     "match Banco × Sankhya", classe="destaque-verde"),
            card_kpi("Percentual Conciliado", fmt_pct(kpis["percentual_conciliado"]),
                     classe="destaque-amarelo"),
        ]
        render_cards(cards1)

        # Linha 2: Falta Conciliar + Divergência + Qtd Divergências + Contas
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

        # Linha 3: contagens (v5.14: Investimentos no 4º card no lugar do placeholder vazio)
        investimentos_html_lin3 = _card_investimentos(resultado)
        cards3 = [
            card_kpi("Registros Banco", fmt_int(kpis["qtd_registros_banco"]),
                     f"{fmt_int(kpis['qtd_movimentacoes_banco'])} movimentações"),
            card_kpi("Registros Sistema", fmt_int(kpis["qtd_registros_sistema"]),
                     f"{fmt_int(kpis['qtd_movimentacoes_sistema'])} movimentações"),
            card_kpi("Conciliados", fmt_int(kpis["qtd_conciliados"]),
                     "pares Banco × Sankhya", classe="destaque-verde"),
            investimentos_html_lin3,
        ]
        render_cards(cards3)

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
        card_kpi_html("Movimentado no Banco", fmt_brl(k["total_movimentado_banco"]),
                      sub_banco_c),
        card_kpi_html("Total Sankhya", fmt_brl(k["total_extrato_sistema"]),
                      sub_sankhya_c),
        card_kpi("Conciliado", fmt_brl(k["total_conciliado"]), classe="destaque-verde"),
        card_kpi("% Conciliado", fmt_pct(k["percentual_conciliado"]), classe="destaque-amarelo"),
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
    # Investimentos filtrados por conta
    investimentos_conta_html = _card_investimentos_da_conta(resultado, conta)

    cards2 = [
        card_kpi_html("Falta Conciliar", fmt_brl(k["falta_conciliar"]),
                      sub_fc, classe="destaque-vermelho"),
        card_kpi_html("Divergência (Sankhya × Banco)",
                      fmt_brl(k["divergencia_sankhya_banco"]),
                      _card_falta_conciliar_vertical(
                          k["divergencia_sankhya_banco_receitas"],
                          k["divergencia_sankhya_banco_despesas"],
                      ),
                      classe="destaque-vermelho"),
        card_kpi("Qtd Divergências", fmt_int(k["qtd_divergencia_sankhya_banco"]),
                 "lançamentos do Sankhya sem par no banco",
                 classe="destaque-amarelo" if k["qtd_divergencia_sankhya_banco"] > 0 else ""),
        investimentos_conta_html,
    ]
    render_cards(cards2)

    # Card de Saldo Final quando 100% conciliado
    info_saldo = resultado.saldo_final_da_conta(conta)
    if info_saldo is not None:
        render_card_saldo_final(info_saldo)

    # Download específico desse banco
    try:
        # v3.10: cache do Excel da conta no session_state
        excel_conta_key = f"xlsx_conta_{st.session_state.get('id_execucao_atual', 'novo')}_{conta}"
        xlsx_banco = st.session_state.get(excel_conta_key)
        if xlsx_banco is None:
            xlsx_banco = gerar_relatorio_excel_de_conta(resultado, conta)
            st.session_state[excel_conta_key] = xlsx_banco
        st.download_button(
            f"⬇️ Baixar relatório de {conta}",
            data=xlsx_banco,
            file_name=f"conciliacao_{conta}_{resultado.data_referencia.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    except Exception as e:
        st.warning(f"Não foi possível gerar o Excel deste banco: {e}")

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

    tabs_nomes = ["✅ Conciliadas", "⏳ Pendentes",
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
        tabs_nomes.append(f"♻️ Anulados por Estorno ({len(estornos_anu_conta)})")
    if not estornos_par_conta.empty:
        tabs_nomes.append(f"⚖️ Estornos Parciais ({len(estornos_par_conta)})")
    if not top1722_grupos_conta.empty:
        tabs_nomes.append(f"🃏 Cartão TOP 1722 ({len(top1722_grupos_conta)})")
    if not top1722_diff_conta.empty:
        tabs_nomes.append(f"⚠️ TOP 1722 Diferença ({len(top1722_diff_conta)})")

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
            st.toast(f"\u2705 {len(novas_edicoes) - len(edicoes)} classifica\u00e7\u00f5es atualizadas", icon="\u2705")

    # Bot\u00e3o pra resetar edi\u00e7\u00f5es
    if edicoes:
        col_a, col_b = st.columns([3, 1])
        with col_b:
            if st.button(f"\ud83d\udd04 Resetar edi\u00e7\u00f5es ({len(edicoes)})",
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
        "- **Sem par no banco**: lançamentos do Sankhya que não casaram com nenhuma linha do banco "
        "(marcados como `Conciliado=Não` ou pendentes pós-match).\n"
        "- **Excesso no Sankhya**: mesma data+valor+conta aparece mais vezes no Sankhya do que no banco.\n"
        "- **Valor diferente**: mesma chave (data+histórico+conta) com valor diferente entre Sankhya e Banco."
    )
    if df.empty:
        st.success("🎉 Sem divergências — Sankhya está alinhado com o banco!")
        return

    # Resumo por origem
    if "origem_divergencia" in df.columns:
        resumo = df.groupby("origem_divergencia").agg(
            quantidade=("valor", "count"),
            total=("valor", lambda s: s.abs().sum()),
        ).reset_index()
        resumo.columns = ["Origem da Divergência", "Quantidade", "Valor Total"]
        resumo["Valor Total"] = resumo["Valor Total"].apply(fmt_brl)
        st.markdown("**Resumo por origem:**")
        st.dataframe(resumo, use_container_width=True, hide_index=True)
        st.write("")

    cols = ["origem_divergencia", "data", "historico", "documento", "valor", "conta"]
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
    tipos_disponiveis = ["Todos"] + TIPOS_PRINCIPAIS + ["Pagamentos", "Recebimentos", "Outros"]
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

    for tab, tipo in zip(tabs, tipos_disponiveis):
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
                _exibir_df(out, f"tipo_{tipo.lower().replace(' ', '_').replace('/', '_')}")

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
        "Suba o arquivo de taxas (.xlsx)",
        type=["xlsx"],
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
        "e marca cada lançamento como **OK**, **Divergente** ou **Sem contrato**."
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
            "Relatório padronizado das adquirentes (.xlsx)",
            type=["xlsx"],
            key="upload_relatorio_adq",
            help=(
                "Colunas: data_venda, adquirente, modalidade, parcelas, valor_bruto, "
                "taxa_aplicada, valor_liquido (opcional), data_prevista_recebimento (opcional)."
            ),
        )

    # Recupera histórico do session_state (carregado no expander acima)
    historico_df = locals().get("historico_df", pd.DataFrame())

    if arq is None and (historico_df is None or historico_df.empty):
        st.info(
            "🙋 Suba o relatório padronizado das adquirentes para iniciar a auditoria.\n\n"
            "**Formato esperado**: uma planilha Excel com as colunas\n"
            "- `data_venda` (data da transação)\n"
            "- `adquirente`, `modalidade`, `parcelas`\n"
            "- `valor_bruto`, `taxa_aplicada`\n"
            "- `valor_liquido` (opcional — calculado se vier vazio)\n"
            "- `data_prevista_recebimento` (opcional)\n\n"
            "💡 Há um arquivo de exemplo em `data/samples/relatorio_adquirente_exemplo.xlsx`."
        )
        return

    # Carrega relatório atual (se subiu)
    if arq is not None:
        try:
            relatorio = carregar_relatorio_adquirente(arq)
        except Exception as e:
            st.error(f"❌ Erro ao ler o relatório: {e}")
            return
        if relatorio.empty:
            st.warning("⚠️ O relatório está vazio ou não tem linhas válidas.")
            relatorio = pd.DataFrame()
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
        card_kpi("Divergências", fmt_int(k["qtd_divergencias"]),
                 "taxa aplicada ≠ contratada",
                 classe="destaque-vermelho" if k["qtd_divergencias"] > 0 else ""),
        card_kpi("Sem Contrato", fmt_int(k["qtd_sem_contrato"]),
                 "modalidade não cadastrada",
                 classe="destaque-amarelo" if k["qtd_sem_contrato"] > 0 else ""),
        card_kpi("OK", fmt_int(k["qtd_ok"]),
                 "conforme contrato", classe="destaque-verde"),
        card_kpi("Impacto Acumulado",
                 fmt_brl(k["impacto_acumulado"]),
                 "soma das diferenças (+ você pagou mais)",
                 classe="destaque-vermelho" if k["impacto_pagou_mais"] > 0 else ""),
    ]
    render_cards(cards2)

    st.divider()

    # Tabela com abas: divergentes / sem contrato / tudo
    tabs = st.tabs([
        f"⚠️ Divergentes ({k['qtd_divergencias']})",
        f"❓ Sem contrato ({k['qtd_sem_contrato']})",
        f"✅ OK ({k['qtd_ok']})",
        "📋 Tudo",
    ])

    cols_show = [
        "data_venda", "adquirente", "modalidade", "parcelas",
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
        if res.divergentes.empty:
            st.success("🎉 Nenhuma divergência! Todas as taxas estão conforme contrato.")
        else:
            st.warning(
                f"⚠️ **{len(res.divergentes)} divergências detectadas.** "
                f"Impacto financeiro acumulado: **{fmt_brl(k['impacto_acumulado'])}** "
                f"(valor positivo = você pagou mais que o contratado)."
            )
            visu = _formatar_visualizacao(res.divergentes)
            st.dataframe(visu, use_container_width=True, hide_index=True)

            # Download das divergentes
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                _formatar_visualizacao(res.divergentes).to_excel(
                    writer, sheet_name="Divergentes", index=False
                )
                # Aba "Bruto" com dados originais (sem formatação) pra reanálise
                res.divergentes[cols_show].to_excel(
                    writer, sheet_name="Bruto", index=False
                )
            buf.seek(0)
            st.download_button(
                "⬇️ Baixar Excel com divergentes",
                data=buf.getvalue(),
                file_name=f"divergencias_taxas_{data_ate.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )

    with tabs[1]:
        sc = res.detalhado[res.detalhado["status"] == "Sem contrato"]
        if sc.empty:
            st.success("✅ Todas as transações têm taxa cadastrada.")
        else:
            st.warning(
                f"❓ **{len(sc)} transações sem contrato cadastrado.** "
                f"Cadastre a taxa correspondente em `🏦 Cadastro de Taxas` para que entrem na auditoria."
            )
            st.dataframe(_formatar_visualizacao(sc), use_container_width=True, hide_index=True)

    with tabs[2]:
        ok = res.detalhado[res.detalhado["status"] == "OK"]
        if ok.empty:
            st.info("Nenhuma transação OK neste período.")
        else:
            st.success(f"✅ **{len(ok)} transações conforme contrato.**")
            st.dataframe(_formatar_visualizacao(ok), use_container_width=True, hide_index=True)

    with tabs[3]:
        st.dataframe(_formatar_visualizacao(res.detalhado),
                     use_container_width=True, hide_index=True)

        # Resumo por adquirente
        if not res.divergentes.empty:
            st.write("")
            st.markdown("**Divergências por adquirente:**")
            por_adq = res.divergentes_por_adquirente()
            por_adq["impacto"] = por_adq["impacto"].apply(fmt_brl)
            por_adq.columns = ["Adquirente", "Quantidade", "Impacto Acumulado"]
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
def pagina_conta70():
    from src.conta70 import gerar_conta_70, carregar_historico_conta_70, STATUS_VALIDOS
    from io import BytesIO

    section_title("CONTA 70 — CONTROLE PROVISÓRIO")

    st.markdown(
        "Esta tela mostra os **créditos bancários** (recebimentos) que **não foram identificados** "
        "no extrato Sankhya — ou seja, não casaram com nenhum lançamento e não foram resolvidos por "
        "estorno, agrupamento de cartão ou outras regras automáticas.\n\n"
        "A **Conta 70** é uma conta contábil fictícia/provisória que o financeiro usa enquanto não "
        "identifica de qual NF / cliente / pedido aquele valor pertence. Quando identificar, marca "
        "como **Regularizado**."
    )

    resultado = st.session_state.get("resultado")
    if resultado is None:
        st.warning(
            "⚠️ Você ainda não rodou uma conciliação nesta sessão. "
            "Vá em `✅ Conciliação` e faça uma conciliação primeiro."
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
        st.success("🎉 Nenhum crédito não identificado! Tudo conciliado.")
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
