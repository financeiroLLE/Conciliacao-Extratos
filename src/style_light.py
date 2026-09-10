"""src/style_light.py — Fase A do redesign visual (v6.2)

Layout INVERTIDO aprovado pela Débora em 10/09/2026:
  - Sidebar em NAVY escuro (era amarela vibrante)
  - Corpo do app em BRANCO (era navy gradient)
  - Bordas AMARELAS nos cards principais
  - Botão principal (Executar) navy sobre amarelo
  - Item ativo do menu com barra amarela lateral

v6.2 (11/09/2026) — pós segundo deploy:
  - Header "Conciliação": título BRANCO peso 800 + subtítulo amarelo, logo
    alinhada verticalmente. Antes o texto estava navy sobre navy → invisível.
  - Labels do corpo ("Modo de execução", "Data de referência", etc.):
    navy escuro peso 600 — antes estavam em cinza claro apagado.
  - Bloco do usuário: avatar com halo amarelo + borda dourada, cargo como
    badge amarelo pequeno, botão Sair colado ao card (sem o gap grande).
  - Especificidade REFORÇADA em todos os seletores (html body + !important
    duplo em partes críticas) para vencer o CSS antigo por especificidade.
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
   FASE A · v6.2 — LAYOUT INVERTIDO (navy sidebar + light body + amarelo)
   Todos os seletores prefixados com html body para garantir especificidade
   suficiente para vencer o CSS antigo pelo peso + ordem.
   ============================================================================ */

/* ---------- 1) CORPO DO APP: fundo claro ---------- */
html body .stApp {{
    background: {_BG_APP} !important;
    color: {_TEXTO} !important;
}}
html body .stApp > header {{ background: transparent !important; }}

html body .block-container {{
    background: transparent !important;
    color: {_TEXTO} !important;
}}

/* ---------- 1.1) LABELS E TEXTOS DO CORPO — navy escuro legível ---------- */
/* Labels dos widgets Streamlit (Modo de execução, Data de referência, etc.) */
html body .block-container [data-testid="stWidgetLabel"],
html body .block-container [data-testid="stWidgetLabel"] p,
html body .block-container [data-testid="stWidgetLabel"] label,
html body .block-container label[data-testid="stWidgetLabel"] {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    font-weight: 600 !important;
    opacity: 1 !important;
}}

/* Radio, checkbox, selectbox labels */
html body .block-container [data-testid="stRadio"] label,
html body .block-container [data-testid="stRadio"] label p,
html body .block-container [data-testid="stCheckbox"] label,
html body .block-container [data-testid="stCheckbox"] label p,
html body .block-container [data-testid="stSelectbox"] label,
html body .block-container [data-testid="stDateInput"] label,
html body .block-container [data-testid="stTextInput"] label,
html body .block-container [data-testid="stFileUploader"] label {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    font-weight: 600 !important;
    opacity: 1 !important;
}}

/* Labels dos file_uploaders ("Arraste os extratos", "Arraste os relatórios") */
html body .block-container [data-testid="stFileUploaderDropzoneInstructions"],
html body .block-container [data-testid="stFileUploaderDropzoneInstructions"] * {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    opacity: 0.85 !important;
}}

/* Textos gerais do body via stMarkdown */
html body .block-container [data-testid="stMarkdownContainer"] p,
html body .block-container [data-testid="stMarkdownContainer"] span,
html body .block-container [data-testid="stMarkdownContainer"] li,
html body .block-container [data-testid="stMarkdownContainer"] h1,
html body .block-container [data-testid="stMarkdownContainer"] h2,
html body .block-container [data-testid="stMarkdownContainer"] h3,
html body .block-container [data-testid="stMarkdownContainer"] h4,
html body .block-container [data-testid="stMarkdownContainer"] h5,
html body .block-container [data-testid="stMarkdownContainer"] h6 {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}

/* Captions e small */
html body .block-container [data-testid="stCaption"],
html body .block-container [data-testid="stCaption"] *,
html body .block-container small {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
}}

/* Textos dentro de radio individual (opções "1 conta por vez", "Várias contas") */
html body .block-container [data-testid="stRadio"] [role="radiogroup"] label p,
html body .block-container [data-testid="stRadio"] [role="radiogroup"] label span {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    font-weight: 500 !important;
    opacity: 1 !important;
}}

/* ---------- 1.2) HEADER PRINCIPAL (.lle-header) — branco + alinhado ---------- */
html body .lle-header {{
    display: flex !important;
    align-items: center !important;
    gap: 20px !important;
    padding: 22px 26px !important;
    border-radius: 14px !important;
}}
html body .lle-header img {{
    height: 56px !important;
    width: auto !important;
    flex-shrink: 0 !important;
}}
html body .lle-header > div:not(:has(img)) {{
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    line-height: 1.2 !important;
}}
html body .lle-header .lle-title,
html body .lle-header .lle-title * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 800 !important;
    font-size: 26px !important;
    letter-spacing: -0.5px !important;
    margin: 0 !important;
}}
html body .lle-header .lle-subtitle,
html body .lle-header .lle-subtitle * {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    letter-spacing: 0.5px !important;
    margin-top: 4px !important;
    opacity: 0.95 !important;
}}

/* KPIs / cards de indicador do dashboard */
html body .lle-kpi {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}
html body .lle-kpi .lle-kpi-label,
html body .lle-kpi .lle-kpi-label * {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
}}
html body .lle-kpi .lle-kpi-value,
html body .lle-kpi .lle-kpi-value * {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-weight: 700 !important;
}}
html body .lle-kpi .lle-kpi-suffix,
html body .lle-kpi .lle-kpi-suffix * {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
}}

/* ---------- 2) SIDEBAR: navy escuro ---------- */
html body [data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border-right: 1px solid {_SB_BORDER} !important;
}}
html body [data-testid="stSidebar"] * {{
    color: {_SB_TEXTO} !important;
}}
html body [data-testid="stSidebar"] hr {{
    border-color: {_SB_BORDER} !important;
}}

/* Card da logo */
html body [data-testid="stSidebar"] .lle-sidebar-logo {{
    background: linear-gradient(180deg, {_NAVY_2} 0%, #030d2b 100%) !important;
    border: 1.5px solid {_AMARELO} !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35) !important;
}}
html body [data-testid="stSidebar"] .lle-sidebar-tagline {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}

/* ---------- 2.1) BLOCO DO USUÁRIO — avatar amarelo + halo, cargo badge ---------- */
html body [data-testid="stSidebar"] .lle-user-block {{
    background: linear-gradient(180deg, rgba(255,255,255,0.04) 0%, transparent 100%) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 10px !important;
    padding: 12px 14px !important;
    margin: 6px 0 4px !important;
}}
html body [data-testid="stSidebar"] .lle-user-header {{
    display: flex !important;
    align-items: center !important;
    gap: 12px !important;
    padding: 2px 0 10px !important;
    border-bottom: 1px solid {_SB_BORDER} !important;
}}
html body [data-testid="stSidebar"] .lle-user-avatar-circle {{
    width: 46px !important;
    height: 46px !important;
    border-radius: 50% !important;
    background: linear-gradient(135deg, {_NAVY_2} 0%, #030d2b 100%) !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    border: 2px solid {_AMARELO} !important;
    box-shadow: 0 0 0 3px rgba(250,195,24,0.15) !important;
    flex-shrink: 0 !important;
}}
html body [data-testid="stSidebar"] .lle-user-avatar-circle svg {{
    fill: {_AMARELO} !important;
    width: 22px !important;
    height: 22px !important;
}}
html body [data-testid="stSidebar"] .lle-user-avatar-circle svg path {{
    fill: {_AMARELO} !important;
}}
html body [data-testid="stSidebar"] .lle-user-info {{
    flex: 1 !important;
    min-width: 0 !important;
    overflow: hidden !important;
}}
html body [data-testid="stSidebar"] .lle-user-name,
html body [data-testid="stSidebar"] .lle-user-name * {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    font-weight: 700 !important;
    font-size: 13px !important;
    line-height: 1.2 !important;
}}
html body [data-testid="stSidebar"] .lle-user-email,
html body [data-testid="stSidebar"] .lle-user-email * {{
    color: {_SB_TEXTO3} !important;
    -webkit-text-fill-color: {_SB_TEXTO3} !important;
    font-size: 11px !important;
    opacity: 1 !important;
    margin-top: 1px !important;
}}
html body [data-testid="stSidebar"] .lle-user-role,
html body [data-testid="stSidebar"] .lle-user-role * {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    background: rgba(250,195,24,0.10) !important;
    padding: 2px 8px !important;
    border-radius: 3px !important;
    font-size: 9.5px !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    margin-top: 4px !important;
    display: inline-block !important;
    text-transform: uppercase !important;
    opacity: 1 !important;
}}

/* Botão Sair (dentro do container key="lle_sair") — colado ao card acima */
html body [data-testid="stSidebar"] .st-key-lle_sair {{
    margin-top: 6px !important;
    margin-bottom: 8px !important;
}}
html body [data-testid="stSidebar"] .st-key-lle_sair button,
html body [data-testid="stSidebar"] .st-key-lle_sair .stButton > button {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    border: 1px solid rgba(250,195,24,0.35) !important;
    border-left: 1px solid rgba(250,195,24,0.35) !important;
    border-radius: 6px !important;
    padding: 7px 12px !important;
    font-size: 11.5px !important;
    font-weight: 600 !important;
    width: 100% !important;
    text-align: center !important;
    box-shadow: none !important;
    transition: all 0.15s ease !important;
    margin: 0 !important;
}}
html body [data-testid="stSidebar"] .st-key-lle_sair button:hover,
html body [data-testid="stSidebar"] .st-key-lle_sair .stButton > button:hover {{
    background: rgba(250,195,24,0.10) !important;
    color: {_AMARELO} !important;
    border-color: {_AMARELO} !important;
    transform: none !important;
}}
html body [data-testid="stSidebar"] .st-key-lle_sair button p,
html body [data-testid="stSidebar"] .st-key-lle_sair button span,
html body [data-testid="stSidebar"] .st-key-lle_sair button div {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
}}

/* ---------- 2.2) MENU: seções agrupadas, botões com fundo sutil ---------- */
html body [data-testid="stSidebar"] .lle-menu-section {{
    color: {_SB_TEXTO3} !important;
    -webkit-text-fill-color: {_SB_TEXTO3} !important;
    font-size: 10.5px !important;
    font-weight: 700 !important;
    letter-spacing: 1.4px !important;
    margin: 22px 4px 8px !important;
    padding: 8px 12px 6px !important;
    border-top: 1px solid {_SB_BORDER} !important;
    text-transform: uppercase !important;
    opacity: 0.85 !important;
}}
html body [data-testid="stSidebar"] .lle-menu-section:first-of-type {{
    border-top: none !important;
    margin-top: 12px !important;
}}

/* Botões do menu (Dashboard, Conciliação Bancária, etc.) */
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button {{
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
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button:hover {{
    background: rgba(250,195,24,0.10) !important;
    color: {_AMARELO} !important;
    border-color: rgba(250,195,24,0.35) !important;
    border-left-color: {_AMARELO_SUAVE} !important;
    transform: translateX(2px) !important;
}}
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button p,
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button span,
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button div {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
    font-weight: inherit !important;
}}

/* Item ATIVO */
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button[kind="primary"],
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button[data-testid*="baseButton-primary"] {{
    background: linear-gradient(90deg, rgba(250,195,24,0.20) 0%, rgba(250,195,24,0.02) 70%) !important;
    color: {_AMARELO} !important;
    font-weight: 700 !important;
    border: 1px solid rgba(250,195,24,0.20) !important;
    border-left: 3px solid {_AMARELO} !important;
    box-shadow: inset 2px 0 0 rgba(250,195,24,0.20), 0 2px 8px rgba(250,195,24,0.10) !important;
}}
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button[kind="primary"] p,
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button[kind="primary"] span,
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button[kind="primary"] div {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}

/* Itens "em breve" */
html body [data-testid="stSidebar"] .lle-menu-item-soon {{
    background: rgba(255,255,255,0.02) !important;
    color: {_SB_TEXTO3} !important;
    -webkit-text-fill-color: {_SB_TEXTO3} !important;
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
html body [data-testid="stSidebar"] .lle-menu-item-soon span {{
    color: {_SB_TEXTO3} !important;
    -webkit-text-fill-color: {_SB_TEXTO3} !important;
}}
html body [data-testid="stSidebar"] .lle-badge-soon {{
    background: rgba(250,195,24,0.15) !important;
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    padding: 2px 8px !important;
    border-radius: 4px !important;
    font-size: 10px !important;
    font-style: normal !important;
    font-weight: 700 !important;
    opacity: 1 !important;
    letter-spacing: 0.5px !important;
}}

/* Expander na sidebar */
html body [data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: 8px !important;
    margin-bottom: 3px !important;
}}
html body [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    padding: 11px 14px !important;
    font-size: 13.5px !important;
    font-weight: 500 !important;
}}
html body [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
    background: rgba(250,195,24,0.08) !important;
}}
html body [data-testid="stSidebar"] [data-testid="stExpander"] summary p,
html body [data-testid="stSidebar"] [data-testid="stExpander"] summary span,
html body [data-testid="stSidebar"] [data-testid="stExpander"] summary div {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
}}

/* Botão de expandir sidebar quando fechada */
html body [data-testid="stExpandSidebarButton"] {{
    background: {_AMARELO} !important;
}}
html body [data-testid="stExpandSidebarButton"] svg,
html body [data-testid="stExpandSidebarButton"] * {{
    color: {_NAVY} !important;
    fill: {_NAVY} !important;
}}

/* ---------- 3) CARDS PRINCIPAIS: borda amarela ---------- */
html body .block-container [data-testid="stVerticalBlockBorderWrapper"],
html body .block-container [data-testid="stExpander"] {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}

/* Inputs, selects */
html body .block-container [data-testid="stTextInput"] input,
html body .block-container [data-testid="stTextArea"] textarea,
html body .block-container [data-testid="stNumberInput"] input,
html body .block-container [data-testid="stDateInput"] input,
html body .block-container [data-testid="stSelectbox"] > div,
html body .block-container [data-baseweb="select"] > div {{
    background: {_BG_CARD} !important;
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    border-color: {_AMARELO_SUAVE} !important;
}}

/* File uploader */
html body .block-container [data-testid="stFileUploader"] section {{
    background: rgba(250,195,24,0.03) !important;
    border: 2px dashed {_AMARELO} !important;
    border-radius: 8px !important;
}}
html body .block-container [data-testid="stFileUploader"] * {{
    color: {_TEXTO} !important;
}}

/* Botão Executar e outros primaries do corpo */
html body .block-container .stButton > button[kind="primary"] {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
    border: 2px solid {_NAVY} !important;
    font-weight: 700 !important;
    box-shadow: 0 3px 10px rgba(250,195,24,0.30) !important;
}}
html body .block-container .stButton > button[kind="primary"]:hover {{
    background: #FFD54B !important;
    transform: translateY(-1px) !important;
}}
html body .block-container .stButton > button[kind="primary"] p,
html body .block-container .stButton > button[kind="primary"] span,
html body .block-container .stButton > button[kind="primary"] div {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
}}

/* Botões secundários do corpo */
html body .block-container .stButton > button[kind="secondary"] {{
    background: {_BG_CARD} !important;
    color: {_NAVY} !important;
    border: 1px solid {_BORDA_SUAVE} !important;
}}
html body .block-container .stButton > button[kind="secondary"]:hover {{
    border-color: {_AMARELO} !important;
}}
html body .block-container .stButton > button[kind="secondary"] p,
html body .block-container .stButton > button[kind="secondary"] span {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
}}

/* Alerts */
html body .block-container [data-testid="stAlert"] {{
    background: {_BG_CARD} !important;
    color: {_TEXTO} !important;
    border-radius: 8px !important;
}}
html body .block-container [data-testid="stAlert"] * {{
    color: inherit !important;
}}

/* Expander no corpo */
html body .block-container [data-testid="stExpander"] summary {{
    background: {_BG_CARD_ALT} !important;
    color: {_TEXTO} !important;
    border-radius: 8px 8px 0 0 !important;
}}
html body .block-container [data-testid="stExpander"] details[open] > summary {{
    border-bottom: 1px solid {_AMARELO_SUAVE} !important;
}}
html body .block-container [data-testid="stExpander"] summary p,
html body .block-container .block-container [data-testid="stExpander"] summary span {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}

/* Métricas nativas do Streamlit */
html body .block-container [data-testid="stMetric"] {{
    background: {_BG_CARD} !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 14px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}
html body .block-container [data-testid="stMetricLabel"] {{
    color: {_TEXTO2} !important;
    font-weight: 600 !important;
}}
html body .block-container [data-testid="stMetricValue"] {{
    color: {_NAVY} !important;
    font-weight: 700 !important;
}}
</style>
"""
    )
