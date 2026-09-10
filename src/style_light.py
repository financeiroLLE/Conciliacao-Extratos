"""src/style_light.py — Fase A do redesign visual (v6.0)

Layout INVERTIDO aprovado pela Débora em 10/09/2026:
  - Sidebar em NAVY escuro (era amarela vibrante)
  - Corpo do app em BRANCO (era navy gradient)
  - Bordas AMARELAS nos cards principais
  - Botão principal (Executar) navy sobre amarelo
  - Item ativo do menu com barra amarela lateral

Estratégia de implementação:
  Este módulo é um OVERRIDE — injeta CSS DEPOIS do bloco de estilos
  original do app.py, então vence pela ordem no DOM (mesma especificidade,
  o último ganha). O CSS antigo continua carregado sem alteração; se
  você quiser reverter, basta:
    1. remover a chamada `render_style_override()` no app.py
    2. remover o import `from src.style_light import render_style_override`
    3. (opcional) reverter .streamlit/config.toml para base = "dark"

O app volta 100% ao visual anterior — sem risco funcional.
"""
from __future__ import annotations

import streamlit as st


# ==============================================================================
# PALETA
# ==============================================================================
# Cores institucionais preservadas
_NAVY = "#0F1F46"
_NAVY_2 = "#0A1730"
_NAVY_SIDEBAR = "#051d5c"       # fundo da sidebar (um pouco mais claro que navy puro)
_NAVY_SIDEBAR_2 = "#041747"     # gradient inferior
_AMARELO = "#FAC318"
_AMARELO_SUAVE = "#FFDD66"

# Corpo light
_BG_APP = "#F5F7FB"             # fundo geral
_BG_CARD = "#FFFFFF"            # cards
_BG_CARD_ALT = "#FAFBFD"         # cards secundários / inputs
_BORDA_SUAVE = "#E5E9F0"

# Sidebar dark
_SB_TEXTO = "#EAF0FB"
_SB_TEXTO2 = "#9FB3D6"
_SB_TEXTO3 = "#6B83B0"
_SB_BORDER = "#1E3B7A"

# Textos do corpo
_TEXTO = "#1A2547"
_TEXTO2 = "#5A6A8A"
_TEXTO3 = "#8A99B5"


def render_style_override() -> None:
    """Injeta o CSS de override. Chamar UMA vez, DEPOIS do bloco de CSS
    original do app.py — assim vence pela ordem no DOM.
    """
    st.html(
        f"""
<style>
/* ============================================================================
   FASE A — OVERRIDE PARA LAYOUT INVERTIDO (navy sidebar + light body)
   ============================================================================ */

/* ---------- 1) CORPO DO APP: fundo claro ---------- */
.stApp {{
    background: {_BG_APP} !important;
    color: {_TEXTO} !important;
}}
.stApp > header {{ background: transparent !important; }}

.block-container {{
    background: transparent !important;
    color: {_TEXTO} !important;
}}

/* Textos gerais do corpo (fora do sidebar) — navy escuro */
.block-container h1,
.block-container h2,
.block-container h3,
.block-container h4,
.block-container h5,
.block-container h6,
.block-container p,
.block-container span,
.block-container label,
.block-container div:not([data-testid]) {{
    color: {_TEXTO} !important;
}}
.block-container .stMarkdown p,
.block-container .stMarkdown span,
.block-container .stMarkdown li {{
    color: {_TEXTO} !important;
}}
.block-container small,
.block-container .stCaption {{
    color: {_TEXTO2} !important;
}}

/* ---------- 2) SIDEBAR: navy escuro ---------- */
[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border-right: 1px solid {_SB_BORDER} !important;
}}
[data-testid="stSidebar"] * {{
    color: {_SB_TEXTO} !important;
}}
[data-testid="stSidebar"] hr {{
    border-color: {_SB_BORDER} !important;
}}

/* Cartão da logo — mantém o fundo navy que já tem, reforça borda amarela */
[data-testid="stSidebar"] .lle-sidebar-logo {{
    background: linear-gradient(180deg, {_NAVY_2} 0%, #030d2b 100%) !important;
    border: 1.5px solid {_AMARELO} !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35) !important;
}}
[data-testid="stSidebar"] .lle-sidebar-tagline {{
    color: {_AMARELO} !important;
}}

/* Seções do menu (VISÃO GERAL, OPERAÇÃO, AUDITORIA) */
[data-testid="stSidebar"] .lle-menu-section {{
    color: {_SB_TEXTO3} !important;
    font-weight: 700 !important;
    letter-spacing: 1.4px !important;
    margin-top: 18px !important;
    text-transform: uppercase !important;
}}

/* Botões do menu — fundo transparente, texto claro, item ativo amarelo */
[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    border: 1px solid transparent !important;
    border-left: 3px solid transparent !important;
    border-radius: 6px !important;
    padding: 10px 14px !important;
    text-align: left !important;
    font-weight: 500 !important;
    box-shadow: none !important;
    transition: all 0.18s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(250,195,24,0.08) !important;
    color: {_AMARELO} !important;
    transform: translateX(2px) !important;
    border-left-color: rgba(250,195,24,0.35) !important;
}}
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span,
[data-testid="stSidebar"] .stButton > button div {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
}}

/* Item ATIVO (type="primary") — barra amarela lateral + destaque */
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[data-testid*="baseButton-primary"] {{
    background: linear-gradient(90deg, rgba(250,195,24,0.18) 0%, rgba(250,195,24,0.02) 65%) !important;
    color: {_AMARELO} !important;
    font-weight: 700 !important;
    border-left: 3px solid {_AMARELO} !important;
    border-top: 1px solid transparent !important;
    border-right: 1px solid transparent !important;
    border-bottom: 1px solid transparent !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
[data-testid="stSidebar"] .stButton > button[kind="primary"] div {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}

/* Itens "em breve" — mais discretos sobre fundo navy */
[data-testid="stSidebar"] .lle-menu-item-soon {{
    background: rgba(255,255,255,0.03) !important;
    color: {_SB_TEXTO3} !important;
    opacity: 0.6 !important;
    border: 1px solid rgba(255,255,255,0.05) !important;
    border-radius: 6px !important;
    padding: 10px 14px !important;
}}
[data-testid="stSidebar"] .lle-badge-soon {{
    background: rgba(250,195,24,0.15) !important;
    color: {_AMARELO} !important;
    padding: 2px 8px !important;
    border-radius: 4px !important;
    font-size: 10px !important;
    font-style: normal !important;
    font-weight: 700 !important;
    opacity: 1 !important;
}}

/* Expander na sidebar */
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: rgba(255,255,255,0.03) !important;
    border: 1px solid {_SB_BORDER} !important;
    border-radius: 6px !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
    background: rgba(250,195,24,0.08) !important;
}}

/* Botão de expandir sidebar quando fechada */
[data-testid="stExpandSidebarButton"] {{
    background: {_AMARELO} !important;
}}
[data-testid="stExpandSidebarButton"] svg,
[data-testid="stExpandSidebarButton"] * {{
    color: {_NAVY} !important;
    fill: {_NAVY} !important;
}}

/* ---------- 3) CARDS PRINCIPAIS: borda amarela ---------- */
/* Streamlit renderiza cards principalmente via st.container, colunas ou HTML
   customizado. Aplicar borda amarela em elementos comuns: */
.block-container [data-testid="stVerticalBlockBorderWrapper"],
.block-container [data-testid="stExpander"] {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}

/* Inputs, selects, textareas no corpo — fundo branco, borda amarela suave */
.block-container [data-testid="stTextInput"] input,
.block-container [data-testid="stTextArea"] textarea,
.block-container [data-testid="stNumberInput"] input,
.block-container [data-testid="stDateInput"] input,
.block-container [data-testid="stSelectbox"] > div,
.block-container [data-baseweb="select"] > div {{
    background: {_BG_CARD} !important;
    color: {_TEXTO} !important;
    border-color: {_AMARELO_SUAVE} !important;
}}

/* File uploader — borda amarela tracejada */
.block-container [data-testid="stFileUploader"] section {{
    background: rgba(250,195,24,0.03) !important;
    border: 2px dashed {_AMARELO} !important;
    border-radius: 8px !important;
}}
.block-container [data-testid="stFileUploader"] * {{
    color: {_TEXTO} !important;
}}

/* Botão "Executar conciliação" e outros primary do corpo:
   navy sobre amarelo — o botão de ação principal salta. */
.block-container .stButton > button[kind="primary"],
.block-container [data-testid="stButton"] > button[kind="primary"] {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
    border: 2px solid {_NAVY} !important;
    font-weight: 700 !important;
    box-shadow: 0 3px 10px rgba(250,195,24,0.30) !important;
}}
.block-container .stButton > button[kind="primary"]:hover {{
    background: #FFD54B !important;
    transform: translateY(-1px) !important;
}}

/* Botões secundários do corpo */
.block-container .stButton > button[kind="secondary"] {{
    background: {_BG_CARD} !important;
    color: {_NAVY} !important;
    border: 1px solid {_BORDA_SUAVE} !important;
}}
.block-container .stButton > button[kind="secondary"]:hover {{
    border-color: {_AMARELO} !important;
    color: {_NAVY} !important;
}}

/* Tags amarelas dos títulos (EXTRATO BANCÁRIO, CONFIGURAR EXECUÇÃO)
   já estão amarelas — só reforçar contraste com o navy no texto. */
.section-title,
.card-secao-titulo {{
    color: {_NAVY} !important;
}}

/* Alerts do Streamlit no light theme */
.block-container [data-testid="stAlert"] {{
    background: {_BG_CARD} !important;
    color: {_TEXTO} !important;
    border-radius: 8px !important;
}}
.block-container [data-testid="stAlert"] * {{
    color: inherit !important;
}}

/* ---------- 4) EXPANDER NO CORPO ---------- */
.block-container [data-testid="stExpander"] summary {{
    background: {_BG_CARD_ALT} !important;
    color: {_TEXTO} !important;
    border-radius: 8px 8px 0 0 !important;
}}
.block-container [data-testid="stExpander"] details[open] > summary {{
    border-bottom: 1px solid {_AMARELO_SUAVE} !important;
}}

/* ---------- 5) DATAFRAMES / TABELAS ---------- */
.block-container [data-testid="stDataFrame"] {{
    background: {_BG_CARD} !important;
}}
.block-container [data-testid="stDataFrame"] * {{
    color: {_TEXTO} !important;
}}

/* Métricas do Streamlit (usadas no dashboard) */
.block-container [data-testid="stMetric"] {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 14px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}
.block-container [data-testid="stMetric"] label,
.block-container [data-testid="stMetricLabel"] {{
    color: {_TEXTO2} !important;
    font-weight: 600 !important;
}}
.block-container [data-testid="stMetric"] [data-testid="stMetricValue"] {{
    color: {_NAVY} !important;
    font-weight: 700 !important;
}}
</style>
"""
    )
