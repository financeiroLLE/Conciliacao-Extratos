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

    sub = f"""
    <div class="lle-kpi-sub-stack">
        <div class="lle-kpi-sub-label">Aplicações:</div>
        <div class="lle-kpi-sub-valor">{fmt_int(qtd_a)} mov. · {fmt_brl(val_a)}</div>
        <div class="lle-kpi-sub-label">Resgates:</div>
        <div class="lle-kpi-sub-valor">{fmt_int(qtd_r)} mov. · {fmt_brl(val_r)}</div>
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

    cols = st.columns(min(len(contas_ordenadas), 4))
    for i, conta in enumerate(contas_ordenadas):
        col = cols[i % len(cols)]
        k = kpis_pb[conta]
        pct = k["percentual_conciliado"]
        qtd_itens, valor_resolver = _itens_a_resolver(conta, k)

        # Selo de alerta (badge) — a cor vive AQUI, não no card.
        if qtd_itens == 0:
            badge_classe = "verde"
            badge_texto = "ok"
        elif qtd_itens <= 2:
            badge_classe = "amarelo"
            badge_texto = f"{qtd_itens} item" if qtd_itens == 1 else f"{qtd_itens} itens"
        else:
            badge_classe = "vermelho"
            badge_texto = f"{qtd_itens} itens"

        # Barra: verde só quando a conta está limpa; neutra quando há alerta.
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

        with col:
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
                    <div class="lle-kpi-suffix">mov. {fmt_brl(k.get("total_movimentado_banco", 0.0))}</div>
                    {linha_resolver}
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
