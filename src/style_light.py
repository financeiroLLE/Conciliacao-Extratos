"""src/style_light.py — Fase A do redesign visual (v6.1)

Layout INVERTIDO aprovado pela Débora em 10/09/2026:
  - Sidebar em NAVY escuro (era amarela vibrante)
  - Corpo do app em BRANCO (era navy gradient)
  - Bordas AMARELAS nos cards principais
  - Botão principal (Executar) navy sobre amarelo
  - Item ativo do menu com barra amarela lateral

v6.1 (11/09/2026) — ajustes pós primeiro deploy:
  - Header .lle-header agora tem texto BRANCO (era navy sobre navy → invisível)
  - Menu do sidebar reformulado: botões com fundo sutil (rgba), separadores
    entre seções, hierarquia visual clara. Corrige o "desestruturado" que a
    Débora apontou.
  - Avatar do usuário: fundo amarelo com texto navy (era cinza opaco)
  - Botão "Sair" com borda visível
"""
from __future__ import annotations

import streamlit as st


# ==============================================================================
# PALETA
# ==============================================================================
_NAVY = "#0F1F46"
_NAVY_2 = "#0A1730"
_NAVY_SIDEBAR = "#051d5c"
_NAVY_SIDEBAR_2 = "#041747"
_AMARELO = "#FAC318"
_AMARELO_SUAVE = "#FFDD66"

_BG_APP = "#F5F7FB"
_BG_CARD = "#FFFFFF"
_BG_CARD_ALT = "#FAFBFD"
_BORDA_SUAVE = "#E5E9F0"

_SB_TEXTO = "#EAF0FB"
_SB_TEXTO2 = "#9FB3D6"
_SB_TEXTO3 = "#6B83B0"
_SB_BORDER = "#1E3B7A"

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
   FASE A · v6.1 — LAYOUT INVERTIDO (navy sidebar + light body + amarelo)
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

/* Textos gerais SOLTOS (sem container próprio) — navy escuro.
   NÃO afeta textos dentro de containers customizados (.lle-header,
   .lle-kpi, cards com bg escuro, etc.) que têm cor própria. */
.block-container > div > .stMarkdown p,
.block-container > div > .stMarkdown span,
.block-container > div > .stMarkdown li,
.block-container > div > .stMarkdown h1,
.block-container > div > .stMarkdown h2,
.block-container > div > .stMarkdown h3,
.block-container > div > .stMarkdown h4,
.block-container > div > .stMarkdown h5,
.block-container > div > .stMarkdown h6 {{
    color: {_TEXTO} !important;
}}

/* Labels dos widgets (Modo de execução, Data de referência, etc.) */
.block-container [data-testid="stWidgetLabel"] p,
.block-container [data-testid="stWidgetLabel"] label,
.block-container label[data-testid="stWidgetLabel"] {{
    color: {_TEXTO} !important;
    font-weight: 600 !important;
}}

/* Captions gerais */
.block-container [data-testid="stCaption"],
.block-container small {{
    color: {_TEXTO2} !important;
}}

/* ---------- 1.1) HEADER PRINCIPAL (.lle-header) — texto BRANCO ---------- */
.lle-header,
.lle-header * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}
.lle-header .lle-title {{
    color: #FFFFFF !important;
    font-weight: 700 !important;
}}
.lle-header .lle-subtitle {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    opacity: 0.9 !important;
}}

/* KPIs (cards de indicador) — texto escuro no fundo claro que a Fase A traz */
.lle-kpi {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}
.lle-kpi .lle-kpi-label {{
    color: {_TEXTO2} !important;
}}
.lle-kpi .lle-kpi-value {{
    color: {_NAVY} !important;
    font-weight: 700 !important;
}}
.lle-kpi .lle-kpi-suffix {{
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

/* Card da logo */
[data-testid="stSidebar"] .lle-sidebar-logo {{
    background: linear-gradient(180deg, {_NAVY_2} 0%, #030d2b 100%) !important;
    border: 1.5px solid {_AMARELO} !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35) !important;
}}
[data-testid="stSidebar"] .lle-sidebar-tagline {{
    color: {_AMARELO} !important;
}}

/* ---------- 2.1) MENU: seções agrupadas, botões com fundo sutil ---------- */
/* Cabeçalhos de seção (VISÃO GERAL, OPERAÇÃO, AUDITORIA) */
[data-testid="stSidebar"] .lle-menu-section {{
    color: {_SB_TEXTO3} !important;
    font-size: 10.5px !important;
    font-weight: 700 !important;
    letter-spacing: 1.4px !important;
    margin: 22px 4px 8px !important;
    padding: 8px 12px 6px !important;
    border-top: 1px solid {_SB_BORDER} !important;
    text-transform: uppercase !important;
    opacity: 0.85 !important;
}}
/* Primeira seção não tem borda-top */
[data-testid="stSidebar"] .lle-menu-section:first-of-type,
[data-testid="stSidebar"] > div > div > div:first-child .lle-menu-section {{
    border-top: none !important;
    margin-top: 12px !important;
}}

/* Botões do menu — fundo sutil que dá "corpo" a cada item */
[data-testid="stSidebar"] .stButton > button {{
    background: rgba(255,255,255,0.04) !important;
    color: {_SB_TEXTO} !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-left: 3px solid transparent !important;
    border-radius: 8px !important;
    padding: 11px 14px !important;
    text-align: left !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    box-shadow: none !important;
    margin-bottom: 3px !important;
    transition: all 0.18s ease !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(250,195,24,0.10) !important;
    color: {_AMARELO} !important;
    border-color: rgba(250,195,24,0.35) !important;
    border-left-color: {_AMARELO_SUAVE} !important;
    transform: translateX(2px) !important;
}}
[data-testid="stSidebar"] .stButton > button p,
[data-testid="stSidebar"] .stButton > button span,
[data-testid="stSidebar"] .stButton > button div {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
    font-weight: inherit !important;
}}

/* Item ATIVO (type="primary") — barra amarela lateral + destaque */
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[data-testid*="baseButton-primary"] {{
    background: linear-gradient(90deg, rgba(250,195,24,0.20) 0%, rgba(250,195,24,0.02) 70%) !important;
    color: {_AMARELO} !important;
    font-weight: 700 !important;
    border: 1px solid rgba(250,195,24,0.20) !important;
    border-left: 3px solid {_AMARELO} !important;
    box-shadow: inset 2px 0 0 rgba(250,195,24,0.20), 0 2px 8px rgba(250,195,24,0.10) !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
[data-testid="stSidebar"] .stButton > button[kind="primary"] div {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}

/* Itens "em breve" — visual coerente com botões, mas em opacidade menor */
[data-testid="stSidebar"] .lle-menu-item-soon {{
    background: rgba(255,255,255,0.02) !important;
    color: {_SB_TEXTO3} !important;
    opacity: 0.65 !important;
    border: 1px solid rgba(255,255,255,0.04) !important;
    border-left: 3px solid transparent !important;
    border-radius: 8px !important;
    padding: 11px 14px !important;
    margin-bottom: 3px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
    cursor: not-allowed !important;
}}
[data-testid="stSidebar"] .lle-menu-item-soon span {{
    color: {_SB_TEXTO3} !important;
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
    letter-spacing: 0.5px !important;
}}

/* Expander na sidebar (Cartão, Configurações, etc.) */
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 8px !important;
    margin-bottom: 3px !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    padding: 11px 14px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
    background: rgba(250,195,24,0.08) !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary p,
[data-testid="stSidebar"] [data-testid="stExpander"] summary span,
[data-testid="stSidebar"] [data-testid="stExpander"] summary div {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
}}

/* ---------- 2.2) CARD DO USUÁRIO (avatar) ---------- */
/* O bloco de usuário do auth.render_sidebar_usuario usa um avatar cinza
   padrão. Sobrescrever com nossa paleta. */
[data-testid="stSidebar"] [data-testid="stImage"] img,
[data-testid="stSidebar"] .stImage img {{
    border: 2px solid {_AMARELO} !important;
    border-radius: 50% !important;
}}

/* Botão Sair — visualmente separado, com borda navy no dark */
[data-testid="stSidebar"] .stButton > button:has(> div:has-text("Sair")),
[data-testid="stSidebar"] button[key*="ogout"],
[data-testid="stSidebar"] button[key*="sair"] {{
    background: transparent !important;
    border: 1px solid {_SB_BORDER} !important;
    border-left: 1px solid {_SB_BORDER} !important;
    color: {_SB_TEXTO2} !important;
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
.block-container [data-testid="stVerticalBlockBorderWrapper"],
.block-container [data-testid="stExpander"] {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}

/* Inputs, selects, textareas no corpo */
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

/* File uploader */
.block-container [data-testid="stFileUploader"] section {{
    background: rgba(250,195,24,0.03) !important;
    border: 2px dashed {_AMARELO} !important;
    border-radius: 8px !important;
}}
.block-container [data-testid="stFileUploader"] * {{
    color: {_TEXTO} !important;
}}

/* Botão "Executar conciliação" e primaries do corpo */
.block-container .stButton > button[kind="primary"] {{
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
.block-container .stButton > button[kind="primary"] p,
.block-container .stButton > button[kind="primary"] span,
.block-container .stButton > button[kind="primary"] div {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
}}

/* Botões secundários do corpo */
.block-container .stButton > button[kind="secondary"] {{
    background: {_BG_CARD} !important;
    color: {_NAVY} !important;
    border: 1px solid {_BORDA_SUAVE} !important;
}}
.block-container .stButton > button[kind="secondary"]:hover {{
    border-color: {_AMARELO} !important;
}}
.block-container .stButton > button[kind="secondary"] p,
.block-container .stButton > button[kind="secondary"] span {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
}}

/* Alerts */
.block-container [data-testid="stAlert"] {{
    background: {_BG_CARD} !important;
    color: {_TEXTO} !important;
    border-radius: 8px !important;
}}
.block-container [data-testid="stAlert"] * {{
    color: inherit !important;
}}

/* Expander no corpo */
.block-container [data-testid="stExpander"] summary {{
    background: {_BG_CARD_ALT} !important;
    color: {_TEXTO} !important;
    border-radius: 8px 8px 0 0 !important;
}}
.block-container [data-testid="stExpander"] details[open] > summary {{
    border-bottom: 1px solid {_AMARELO_SUAVE} !important;
}}
.block-container [data-testid="stExpander"] summary p,
.block-container [data-testid="stExpander"] summary span {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}

/* Dataframes */
.block-container [data-testid="stDataFrame"] {{
    background: {_BG_CARD} !important;
}}

/* Métricas nativas do Streamlit (st.metric) */
.block-container [data-testid="stMetric"] {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 14px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}
.block-container [data-testid="stMetricLabel"] {{
    color: {_TEXTO2} !important;
    font-weight: 600 !important;
}}
.block-container [data-testid="stMetricValue"] {{
    color: {_NAVY} !important;
    font-weight: 700 !important;
}}
</style>
"""
    )
