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

v6.3 (11/09/2026) — pós terceiro deploy:
  - Captions do corpo agora legíveis (múltiplos seletores).
  - Tentativa de colar Sair ao card do usuário.

v6.4 (11/09/2026) — pós quarto deploy:
  - Botão Sair: o stauth Authenticate().logout(location="sidebar") renderiza
    o botão com key="btn_logout_lle" FORA do container st.container(key=
    "lle_sair") em algumas versões. Agora captamos AMBOS os targets
    (.st-key-lle_sair e .st-key-btn_logout_lle) para garantir que pega.
  - Alinhamento vertical sidebar × corpo: padroniza padding-top do
    .block-container e do [data-testid="stSidebar"] > div para começarem
    na mesma altura.

v6.5 (11/09/2026) — pós quinto deploy:
  - Sair AGORA fica dentro do container `.st-key-lle_sair` de verdade
    (mudança no auth.py: st.button manual + auth_supabase.sign_out() em
    vez de stauth logout com location="sidebar"). CSS antigo do sair
    passa a pegar sem depender de seletores frágeis.
  - Alinhamento vertical: ajustado padding-top do corpo para casar
    exatamente com o topo do card da logo no sidebar.

v6.6 (11/09/2026) — pós sexto deploy:
  - Namespace .cv-* inteiro em navy escuro.
  - Menu do sidebar: contraste reforçado.
  - Modal "Clear caches" navy.

v6.7 (11/09/2026) — pós sétimo deploy:
  - Datepicker (calendário): fundo navy com texto branco, dia selecionado
    amarelo. Antes: datas quase invisíveis sobre fundo branco.
  - Selectbox de conta e outros: texto legível (branco navy no dropdown
    aberto e no valor selecionado).
  - KPIs do Resumo Executivo (.lle-kpi): fundo NAVY (era branco com borda
    amarela), altura reduzida — cards ficaram menores. Valores em amarelo,
    labels em cinza claro. Consistente com KPIs do módulo Conciliação
    de Vendas.
  - Cards do dashboard (opa-card-*, opa-chip, opa-excecoes-*): mesmo
    esquema navy.
  - Rodapé de conferência do Detalhamento ("Rodapé do Sankhya", "Extrato
    do banco", "Diferença") — dentro de card amarelo com texto navy
    legível. Antes: inline-styles em cores claras sobre fundo branco.
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
    padding-top: 1.2rem !important;   /* v6.5: alinha o header com o topo da logo */
}}

/* v6.5: sidebar SEM padding-top extra, e a logo com margin-top pequeno
   equivalente ao padding do corpo. Assim topo da logo = topo do header. */
html body [data-testid="stSidebar"] > div:first-child,
html body [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
    padding-top: 0.8rem !important;
}}
html body [data-testid="stSidebar"] .lle-sidebar-logo {{
    margin-top: 0 !important;
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

/* Captions e small — reforço v6.3 (múltiplos seletores para vencer o
   CSS antigo que pintava branco sobre branco) */
html body .block-container [data-testid="stCaption"],
html body .block-container [data-testid="stCaption"] *,
html body .block-container [data-testid="stCaptionContainer"],
html body .block-container [data-testid="stCaptionContainer"] *,
html body .block-container .stCaption,
html body .block-container .stCaption *,
html body .block-container small,
html body .block-container small *,
html body .block-container [data-testid="stMarkdownContainer"] small,
html body .block-container [data-testid="stMarkdownContainer"] small * {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
    opacity: 1 !important;
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

/* KPIs / cards de indicador do dashboard — v6.7: navy escuro consistente
   com módulo Conciliação de Vendas. Padding reduzido — antes ficavam imensos. */
html body .lle-kpi {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_NAVY_SIDEBAR} !important;
    border-left: 3px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(15,31,70,0.15) !important;
    padding: 14px 16px !important;
    min-height: unset !important;
    height: auto !important;
}}
html body .lle-kpi .lle-kpi-label,
html body .lle-kpi .lle-kpi-label *,
html body .lle-kpi .lle-kpi-sub-label,
html body .lle-kpi .lle-kpi-sub-label * {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
}}
html body .lle-kpi .lle-kpi-value,
html body .lle-kpi .lle-kpi-value *,
html body .lle-kpi .lle-kpi-sub-valor,
html body .lle-kpi .lle-kpi-sub-valor * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 800 !important;
}}
html body .lle-kpi .lle-kpi-suffix,
html body .lle-kpi .lle-kpi-suffix *,
html body .lle-kpi .lle-kpi-sub-stack {{
    color: {_SB_TEXTO2} !important;
    -webkit-text-fill-color: {_SB_TEXTO2} !important;
}}
html body .lle-kpi-row {{
    gap: 12px !important;
}}

/* Cards opa-* do dashboard/detalhamento — mesmo esquema navy */
html body .opa-card-conciliado,
html body .opa-card-secundario,
html body .opa-card-ancora,
html body .opa-card-donut {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_NAVY_SIDEBAR} !important;
    border-left: 3px solid {_AMARELO} !important;
    border-radius: 10px !important;
    box-shadow: 0 3px 12px rgba(15,31,70,0.15) !important;
    color: #FFFFFF !important;
}}
html body .opa-card-conciliado *,
html body .opa-card-secundario *,
html body .opa-card-ancora *,
html body .opa-card-donut * {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
}}
html body .opa-card-conciliado-valor,
html body .opa-card-secundario-valor,
html body .opa-card-ancora-valor,
html body .opa-card-sec-valor,
html body .opa-card-donut-pct {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 800 !important;
}}
html body .opa-card-conciliado-label,
html body .opa-card-secundario-label,
html body .opa-card-ancora-label,
html body .opa-card-sec-label,
html body .opa-card-donut-label,
html body .opa-card-sec-head {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
}}
html body .opa-card-sec-icon {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
}}

/* Chips e exceções */
html body .opa-chip {{
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    color: {_SB_TEXTO} !important;
}}
html body .opa-chip-label {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}
html body .opa-chip-valor {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 700 !important;
}}
html body .opa-chip-icon {{
    color: {_AMARELO} !important;
}}
html body .opa-excecoes-head {{
    background: transparent !important;
    border-top: 1px dashed {_AMARELO_SUAVE} !important;
}}
html body .opa-excecoes-head-label {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
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
/* v6.3: bordas inferiores retas, para o botão Sair encaixar visualmente
   como se fossem UM bloco só. */
html body [data-testid="stSidebar"] .lle-user-block {{
    background: linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-bottom: none !important;
    border-radius: 10px 10px 0 0 !important;
    padding: 12px 14px !important;
    margin: 6px 0 0 !important;
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

/* Botão Sair — v6.4: captura AMBOS os targets possíveis pra garantir
   que pega o botão do stauth Authenticate() (que pode renderizar
   dentro do container "lle_sair" ou direto no sidebar como
   "btn_logout_lle" dependendo da versão).
   O elemento pai do botão vira o "rodapé" do card do usuário. */

/* Container do st.container(key="lle_sair"), quando presente */
html body [data-testid="stSidebar"] .st-key-lle_sair {{
    margin-top: 0 !important;
    margin-bottom: 12px !important;
    padding: 0 !important;
    background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-top: 1px solid {_SB_BORDER} !important;
    border-radius: 0 0 10px 10px !important;
}}
html body [data-testid="stSidebar"] .st-key-lle_sair [data-testid="stVerticalBlock"] {{
    padding: 8px 12px !important;
    gap: 0 !important;
}}

/* Container direto do stauth logout button (quando ele não vai
   pro st.container) */
html body [data-testid="stSidebar"] .st-key-btn_logout_lle,
html body [data-testid="stSidebar"] [data-testid*="element-container"]:has(button[data-testid*="btn_logout_lle"]),
html body [data-testid="stSidebar"] [class*="st-key-btn_logout"] {{
    margin-top: 0 !important;
    margin-bottom: 12px !important;
    padding: 8px 12px !important;
    background: linear-gradient(180deg, rgba(255,255,255,0.02) 0%, transparent 100%) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-top: 1px solid {_SB_BORDER} !important;
    border-radius: 0 0 10px 10px !important;
}}

/* Estilo do botão em si (independente de onde está) */
html body [data-testid="stSidebar"] .st-key-lle_sair button,
html body [data-testid="stSidebar"] .st-key-lle_sair .stButton > button,
html body [data-testid="stSidebar"] button[data-testid*="btn_logout_lle"],
html body [data-testid="stSidebar"] button[key*="btn_logout"],
html body [data-testid="stSidebar"] .st-key-btn_logout_lle button,
html body [data-testid="stSidebar"] .st-key-btn_logout_manual button {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    border: 1px solid rgba(250,195,24,0.35) !important;
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
html body [data-testid="stSidebar"] .st-key-lle_sair .stButton > button:hover,
html body [data-testid="stSidebar"] button[data-testid*="btn_logout_lle"]:hover,
html body [data-testid="stSidebar"] button[key*="btn_logout"]:hover,
html body [data-testid="stSidebar"] .st-key-btn_logout_lle button:hover {{
    background: rgba(250,195,24,0.10) !important;
    color: {_AMARELO} !important;
    border-color: {_AMARELO} !important;
    transform: none !important;
}}
html body [data-testid="stSidebar"] .st-key-lle_sair button p,
html body [data-testid="stSidebar"] .st-key-lle_sair button span,
html body [data-testid="stSidebar"] .st-key-lle_sair button div,
html body [data-testid="stSidebar"] button[data-testid*="btn_logout_lle"] p,
html body [data-testid="stSidebar"] button[data-testid*="btn_logout_lle"] span,
html body [data-testid="stSidebar"] button[data-testid*="btn_logout_lle"] div,
html body [data-testid="stSidebar"] .st-key-btn_logout_lle button p,
html body [data-testid="stSidebar"] .st-key-btn_logout_lle button span,
html body [data-testid="stSidebar"] .st-key-btn_logout_lle button div {{
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

/* Botões do menu (Dashboard, Conciliação Bancária, etc.)
   v6.6: fundo mais opaco + texto sólido para não sumirem quando outro
   item está ativo. */
html body [data-testid="stSidebar"] .stButton:not(.st-key-lle_sair *) > button {{
    background: rgba(255,255,255,0.07) !important;
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-left: 3px solid transparent !important;
    border-radius: 8px !important;
    padding: 11px 14px !important;
    text-align: left !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    box-shadow: none !important;
    margin-bottom: 3px !important;
    opacity: 1 !important;
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
/* v6.10: botão "Upload" dentro do file_uploader — reforço extra com
   seletores por key (banco_single, banco_multi, pendencias, banco_hist,
   c70_capa/sk/fat, dash_hist) para vencer o CSS antigo que estilizava
   o uploader do banco de forma mais específica. Também aumentei o
   tamanho do botão (padding + font-size). */
html body .block-container [data-testid="stFileUploader"] button,
html body .block-container [data-testid="stFileUploaderDropzone"] button,
html body .block-container [data-testid="stBaseButton-secondary"][data-testid*="FileUploader"],
html body .block-container [data-testid="stFileUploader"] section button,
html body .block-container .st-key-banco_single button,
html body .block-container .st-key-banco_multi button,
html body .block-container .st-key-pendencias button,
html body .block-container .st-key-sistema button,
html body .block-container .st-key-adquirente button,
html body .block-container .st-key-c70_capa button,
html body .block-container .st-key-c70_sk button,
html body .block-container .st-key-c70_fat button,
html body .block-container .st-key-dash_hist button,
html body .block-container [class*="st-key"] [data-testid="stFileUploader"] button,
html body [data-testid="stFileUploaderDropzone"] > button,
html body [data-testid="stFileUploader"] > section > button {{
    background: {_AMARELO} !important;
    background-color: {_AMARELO} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    border: 2px solid {_NAVY} !important;
    font-weight: 700 !important;
    font-size: 13px !important;
    padding: 10px 22px !important;
    min-height: 40px !important;
    box-shadow: 0 2px 6px rgba(250,195,24,0.25) !important;
}}
html body .block-container [data-testid="stFileUploader"] button *,
html body .block-container [data-testid="stFileUploader"] section button *,
html body [data-testid="stFileUploader"] > section > button *,
html body [data-testid="stFileUploaderDropzone"] > button * {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-weight: 700 !important;
    fill: {_NAVY} !important;
}}
html body .block-container [data-testid="stFileUploader"] button:hover,
html body .block-container [data-testid="stFileUploader"] section button:hover,
html body [data-testid="stFileUploaderDropzone"] > button:hover,
html body [data-testid="stFileUploader"] > section > button:hover {{
    background: #FFD54B !important;
    background-color: #FFD54B !important;
    transform: translateY(-1px) !important;
}}
/* Ícone SVG dentro do botão Upload */
html body .block-container [data-testid="stFileUploader"] button svg,
html body .block-container [data-testid="stFileUploader"] section button svg,
html body [data-testid="stFileUploader"] > section > button svg,
html body [data-testid="stFileUploaderDropzone"] > button svg {{
    fill: {_NAVY} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
}}
html body .block-container [data-testid="stFileUploader"] button svg *,
html body [data-testid="stFileUploader"] > section > button svg * {{
    fill: {_NAVY} !important;
    color: {_NAVY} !important;
}}

/* v6.9: card ITAÚ · API (.arqcard-itau) — fundo navy escuro para o
   texto claro ficar legível no tema light. v6.11: + margem entre cards
   sucessivos. */
html body .arqcard-itau {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_NAVY_SIDEBAR} !important;
    border-left: 3px solid #EC7000 !important;
    color: #FFFFFF !important;
    margin-bottom: 12px !important;
}}
html body .arqcard-itau * {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
}}
html body .arqcard-itau b,
html body .arqcard-itau strong {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
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

/* ============================================================================
   v6.6 · CONCILIAÇÃO DE VENDAS — namespace .cv-*
   Todos os cards do módulo em ESQUEMA NAVY escuro, para dados saltarem
   no tema light. Valores em amarelo, texto secundário em cinza claro.
   ============================================================================ */

/* Header do módulo ("Conciliação de Vendas · MVP-A · PISA · KING · TRIO") */
html body .cv-header {{
    background: linear-gradient(135deg, {_NAVY_2} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border-radius: 12px !important;
    padding: 20px 24px !important;
    color: #FFFFFF !important;
}}
html body .cv-header,
html body .cv-header * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}
html body .cv-header-titulo {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-weight: 800 !important;
    font-size: 22px !important;
}}
html body .cv-header-sub {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 600 !important;
    font-size: 12px !important;
    letter-spacing: 0.5px !important;
}}
html body .cv-header-icon {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
}}

/* Títulos de seção ("ENVIAR ARQUIVOS", "RESUMO DO QUE FOI LIDO",
   "INICIAR CONCILIAÇÃO") — amarelo forte sobre fundo claro */
html body .cv-secao-titulo,
html body .cv-secao-header-titulo {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 800 !important;
    font-size: 11px !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    opacity: 1 !important;
}}
html body .cv-secao-header {{
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    margin: 6px 0 12px !important;
}}
html body .cv-secao-wrapper {{
    background: transparent !important;
}}

/* Rodada + resultado — v6.11: pílula verde para "Rodada de..." */
html body .cv-rodada-header {{
    background: transparent !important;
    margin-bottom: 12px !important;
}}
html body .cv-rodada-supra {{
    color: #0F8C3B !important;
    -webkit-text-fill-color: #0F8C3B !important;
    font-size: 12px !important;
    font-weight: 800 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    opacity: 1 !important;
    display: inline-block !important;
    padding: 4px 12px !important;
    background: rgba(15,140,59,0.10) !important;
    border: 1px solid #0F8C3B !important;
    border-radius: 14px !important;
}}
html body .cv-rodada-titulo {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-size: 22px !important;
    font-weight: 800 !important;
    margin-top: 8px !important;
    opacity: 1 !important;
}}

/* KPIs do "RESUMO DO QUE FOI LIDO" (VENDAS CIELO/GETNET/BAIXAS/AGUARDANDO) */
html body .cv-kpi {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_NAVY_SIDEBAR} !important;
    border-left: 3px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    box-shadow: 0 3px 12px rgba(15,31,70,0.15) !important;
    text-align: center !important;
}}
html body .cv-kpi-label {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    text-transform: uppercase !important;
}}
html body .cv-kpi-valor {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    font-size: 26px !important;
    font-weight: 800 !important;
    margin: 6px 0 !important;
}}
html body .cv-kpi-secundario {{
    color: {_SB_TEXTO2} !important;
    -webkit-text-fill-color: {_SB_TEXTO2} !important;
    font-size: 10.5px !important;
    opacity: 1 !important;
}}

/* Card de conciliação (múltiplas candidatas, ok, divergência) */
html body .cv-card {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_NAVY_SIDEBAR} !important;
    border-left: 4px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 16px 20px !important;
    color: #FFFFFF !important;
    box-shadow: 0 4px 14px rgba(15,31,70,0.20) !important;
    margin-bottom: 12px !important;
}}
html body .cv-card,
html body .cv-card * {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
}}
html body .cv-card-topo {{
    display: flex !important;
    justify-content: space-between !important;
    align-items: flex-start !important;
    margin-bottom: 8px !important;
}}
html body .cv-card-titulo {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
    font-size: 15px !important;
}}
html body .cv-card-sub {{
    color: {_SB_TEXTO2} !important;
    -webkit-text-fill-color: {_SB_TEXTO2} !important;
    font-size: 11.5px !important;
}}

/* Tags dos cards (MÚLTIPLAS CANDIDATAS, CIELO, GETNET, PIX, etc.) */
html body .cv-tag {{
    background: rgba(255,255,255,0.08) !important;
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    padding: 3px 9px !important;
    border-radius: 4px !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
}}
html body .cv-badge-ok {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    padding: 3px 9px !important;
    border-radius: 4px !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
}}
html body .cv-badge-fail {{
    background: #C0392B !important;
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    padding: 3px 9px !important;
    border-radius: 4px !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
}}

/* Bloco de candidatas dentro do card — v6.11: linhas com bg sutil */
html body .cv-candidatas-wrapper {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 6px !important;
    padding: 10px 12px !important;
    margin-top: 12px !important;
}}
html body .cv-candidatas-header {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-size: 10.5px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
    text-transform: uppercase !important;
    margin-bottom: 6px !important;
}}
html body .cv-candidata-linha {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    font-size: 11.5px !important;
    padding: 6px 8px !important;
    background: rgba(255,255,255,0.03) !important;
    border-radius: 4px !important;
    margin-bottom: 3px !important;
    border-bottom: 1px dashed rgba(255,255,255,0.06) !important;
}}
html body .cv-candidata-linha * {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
}}
html body .cv-candidata-linha b,
html body .cv-candidata-linha strong,
html body .cv-candidata-linha a {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
}}
html body .cv-candidata-linha:last-child {{
    border-bottom: none !important;
}}
html body .cv-candidata-tag-adi {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    padding: 2px 6px !important;
    border-radius: 3px !important;
    font-size: 9px !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
}}
html body .cv-candidata-tag-nf {{
    background: rgba(255,255,255,0.10) !important;
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    padding: 2px 6px !important;
    border-radius: 3px !important;
    font-size: 9px !important;
    font-weight: 700 !important;
}}

/* Parcelas (timeline visual das parcelas de venda) */
html body .cv-parcelas-lista,
html body .cv-parcela-linha,
html body .cv-parc-linha {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    font-size: 11.5px !important;
}}
html body .cv-parcela-bullet {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
}}
html body .cv-parc-nf {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}

/* Fila / lista lateral com nomes de venda */
html body .cv-fila-nome {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    font-weight: 600 !important;
}}

/* Estado vazio */
html body .cv-empty-state {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
    text-align: center !important;
    padding: 20px !important;
    background: {_BG_CARD_ALT} !important;
    border-radius: 8px !important;
    border: 1px dashed {_BORDA_SUAVE} !important;
}}

/* Aviso (banner com fundo amarelo claro do topo:
   "Arquivos são processados na sessão e não ficam armazenados") */
html body .cv-aviso {{
    background: #FFFBEE !important;
    border: 1px solid {_AMARELO_SUAVE} !important;
    border-left: 3px solid {_AMARELO} !important;
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    padding: 10px 14px !important;
    border-radius: 6px !important;
}}
html body .cv-aviso * {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}
html body .cv-aviso b {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-weight: 700 !important;
}}

/* Confirmação (modal interno de desfazer, etc.) */
html body .cv-confirmacao {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 16px 20px !important;
    color: {_SB_TEXTO} !important;
}}
html body .cv-confirmacao-titulo {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
    font-size: 15px !important;
}}
html body .cv-confirmacao-descr {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    font-size: 12px !important;
}}

/* Rodapé (Grupo LLE · Conciliação Bancária · ...) */
html body .cv-rodape-info {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
    text-align: center !important;
    font-size: 11px !important;
    padding: 12px 0 !important;
}}

/* Wrapper de botão de busca */
html body .cv-btn-busca-wrapper {{
    margin: 8px 0 !important;
}}

/* ============================================================================
   v6.8 · DATEPICKER (calendário) — navy escuro TODO, incluindo cabeçalho
   ============================================================================ */
/* Popover do datepicker (o container que abre) — fundo navy inteiro */
html body [data-baseweb="popover"]:has([data-baseweb="calendar"]),
html body [data-baseweb="popover"] > div:has([data-baseweb="calendar"]) {{
    background: {_NAVY_SIDEBAR} !important;
}}
html body [data-baseweb="calendar"] {{
    background: {_NAVY_SIDEBAR} !important;
    border: 1px solid {_AMARELO} !important;
    border-radius: 8px !important;
    color: #FFFFFF !important;
    box-shadow: 0 6px 24px rgba(0,0,0,0.35) !important;
    padding: 8px !important;
}}
html body [data-baseweb="calendar"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background-color: transparent !important;
}}

/* CABEÇALHO do calendário (mês/ano + setas) — v6.8: força fundo navy
   e texto amarelo. O componente padrão vinha branco sobre branco. */
html body [data-baseweb="calendar"] > div:first-child,
html body [data-baseweb="calendar"] [data-baseweb="calendar-header"] {{
    background: {_NAVY_SIDEBAR} !important;
    color: {_AMARELO} !important;
    padding: 6px 10px !important;
    border-bottom: 1px solid rgba(250,195,24,0.20) !important;
    margin-bottom: 4px !important;
}}
html body [data-baseweb="calendar"] > div:first-child *,
html body [data-baseweb="calendar"] [data-baseweb="calendar-header"] * {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
}}
/* Setas de navegação (< e >) */
html body [data-baseweb="calendar"] button {{
    background: transparent !important;
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    border: none !important;
}}
html body [data-baseweb="calendar"] button:hover {{
    background: rgba(250,195,24,0.15) !important;
}}
html body [data-baseweb="calendar"] button svg,
html body [data-baseweb="calendar"] button svg * {{
    fill: {_AMARELO} !important;
    color: {_AMARELO} !important;
}}

/* Nomes dos dias da semana (Su Mo Tu We Th Fr Sa) — v6.8: força
   fundo navy e texto amarelo (antes vinham num retângulo cinza) */
html body [data-baseweb="calendar"] div[role="rowheader"],
html body [data-baseweb="calendar"] div[role="columnheader"],
html body [data-baseweb="calendar"] div[role="grid"] > div:first-child {{
    background: {_NAVY_SIDEBAR} !important;
    color: {_AMARELO} !important;
}}
html body [data-baseweb="calendar"] div[role="rowheader"] *,
html body [data-baseweb="calendar"] div[role="columnheader"] *,
html body [data-baseweb="calendar"] div[role="grid"] > div:first-child * {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
    background: transparent !important;
    opacity: 0.9 !important;
}}
/* Fallback: qualquer div com background cinza claro dentro do calendário */
html body [data-baseweb="calendar"] div[style*="background"] {{
    background: {_NAVY_SIDEBAR} !important;
}}

/* Dias do mês (números) */
html body [data-baseweb="calendar"] [role="gridcell"] {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
    background: transparent !important;
}}
html body [data-baseweb="calendar"] [role="gridcell"] * {{
    color: inherit !important;
    -webkit-text-fill-color: inherit !important;
    background: transparent !important;
}}
html body [data-baseweb="calendar"] [role="gridcell"][aria-disabled="true"] {{
    color: {_SB_TEXTO3} !important;
    -webkit-text-fill-color: {_SB_TEXTO3} !important;
    opacity: 0.5 !important;
}}
/* Dia hoje — destaca com borda amarela suave (sem fundo) */
html body [data-baseweb="calendar"] [aria-current="date"]:not([aria-selected="true"]) {{
    border: 1px solid {_AMARELO_SUAVE} !important;
    border-radius: 50% !important;
}}
/* Dia SELECIONADO — bolinha amarela com número NAVY DENTRO
   Sobrescrevemos os inherit=amarelo genéricos com navy explícito. */
html body [data-baseweb="calendar"] [aria-selected="true"],
html body [data-baseweb="calendar"] [aria-pressed="true"],
html body [data-baseweb="calendar"] [role="gridcell"][aria-selected="true"] {{
    background: {_AMARELO} !important;
    background-color: {_AMARELO} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    border-radius: 50% !important;
    font-weight: 800 !important;
}}
html body [data-baseweb="calendar"] [aria-selected="true"] *,
html body [data-baseweb="calendar"] [aria-pressed="true"] *,
html body [data-baseweb="calendar"] [role="gridcell"][aria-selected="true"] * {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    background: transparent !important;
    background-color: transparent !important;
    font-weight: 800 !important;
}}

/* Selectbox (Conta) — quando aberto e valor selecionado */
html body [data-baseweb="select"] {{
    background: {_BG_CARD} !important;
}}
html body [data-baseweb="select"] > div {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    background: {_BG_CARD} !important;
}}
html body [data-baseweb="select"] input {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}
html body [data-baseweb="select"] [data-baseweb="tag"],
html body [data-baseweb="select"] span {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}
/* Dropdown do selectbox aberto — fundo navy escuro para as opções */
html body [data-baseweb="popover"] [data-baseweb="menu"] {{
    background: {_NAVY_SIDEBAR} !important;
    border: 1px solid {_AMARELO} !important;
}}
html body [data-baseweb="popover"] [data-baseweb="menu"] li,
html body [data-baseweb="popover"] [data-baseweb="menu"] * {{
    color: #FFFFFF !important;
    -webkit-text-fill-color: #FFFFFF !important;
}}
html body [data-baseweb="popover"] [data-baseweb="menu"] li[aria-selected="true"],
html body [data-baseweb="popover"] [data-baseweb="menu"] li:hover {{
    background: rgba(250,195,24,0.15) !important;
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}

/* ============================================================================
   v6.7 · RODAPÉ DE CONFERÊNCIA DO DETALHAMENTO (Rodapé do Sankhya)
   Os inline styles do app antigo pintavam textos em cores claras sobre
   fundo branco. Meu CSS com !important vence o inline (que não tem
   !important) por especificidade. Aqui, além disso, pinto o CONTAINER
   pai como amarelo claro, para o rodapé ficar dentro de um card amarelo.
   ============================================================================ */
/* Container do rodapé — capturar por td com color específica que o app usa */
html body .block-container td[style*="color:#FAC318"] {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-weight: 700 !important;
}}
html body .block-container td[style*="color:#cdd9f2"],
html body .block-container td[style*="color:#9fb3d6"],
html body .block-container td[style*="color:#eaf0fb"] {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}
/* Bordas escuras que o app antigo colocava (border-top: 1px solid #163062)
   — trocar por cor visível no fundo claro */
html body .block-container td[style*="border-top:1px solid #163062"],
html body .block-container tr[style*="border-top"] td {{
    border-top: 1px solid {_AMARELO_SUAVE} !important;
}}
/* Cabeçalhos da tabela (Crédito, Débito, Movimentação total) */
html body .block-container th[style*="color:#9fb3d6"],
html body .block-container th {{
    color: {_TEXTO2} !important;
    -webkit-text-fill-color: {_TEXTO2} !important;
    font-weight: 700 !important;
}}
/* Envolvendo a tabela de rodapé com um card amarelo:
   como o app renderiza sem classe custom, pego pela estrutura */
html body .block-container [data-testid="stMarkdownContainer"]:has(> table) {{
    background: #FFFDEE !important;
    border: 2px solid {_AMARELO} !important;
    border-radius: 10px !important;
    padding: 14px !important;
    box-shadow: 0 3px 12px rgba(250,195,24,0.10) !important;
}}
html body .block-container [data-testid="stMarkdownContainer"] table {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    background: transparent !important;
}}
html body .block-container [data-testid="stMarkdownContainer"] table td,
html body .block-container [data-testid="stMarkdownContainer"] table th {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}
html body .block-container [data-testid="stMarkdownContainer"] table span[style*="color:#7ee0a6"] {{
    color: {_VERDE if False else "#0F8C3B"} !important;
    -webkit-text-fill-color: #0F8C3B !important;
    font-weight: 800 !important;
}}

/* ============================================================================
   v6.6 · MODAL/DIALOG NATIVO DO STREAMLIT (Clear caches, etc.)
   Fundo navy, botão principal amarelo. O texto interno em inglês é do
   Streamlit — só a apresentação visual pode ser customizada.
   ============================================================================ */
html body [data-testid="stModal"] > div,
html body [data-testid="stDialog"] > div,
html body [role="dialog"] {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_AMARELO} !important;
    border-left: 3px solid {_AMARELO} !important;
    color: {_SB_TEXTO} !important;
}}
html body [data-testid="stModal"] h1,
html body [data-testid="stModal"] h2,
html body [data-testid="stModal"] h3,
html body [data-testid="stModal"] h4,
html body [role="dialog"] h1,
html body [role="dialog"] h2,
html body [role="dialog"] h3,
html body [role="dialog"] h4 {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}
html body [data-testid="stModal"] p,
html body [data-testid="stModal"] span,
html body [role="dialog"] p,
html body [role="dialog"] span {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
}}
html body [data-testid="stModal"] code,
html body [role="dialog"] code {{
    background: rgba(255,255,255,0.10) !important;
    color: {_AMARELO} !important;
    padding: 2px 6px !important;
    border-radius: 3px !important;
}}
/* Botão primário do modal (Clear caches, Confirmar) — amarelo */
html body [data-testid="stModal"] button[kind="primary"],
html body [role="dialog"] button[kind="primary"],
html body [data-testid="stModal"] button:not([kind]):not([data-testid*="close"]),
html body [role="dialog"] button:not([kind]):not([data-testid*="close"]) {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    border: 1px solid {_AMARELO} !important;
    font-weight: 700 !important;
}}
/* Botão secundário (Cancel) — transparente com borda */
html body [data-testid="stModal"] button[kind="secondary"],
html body [role="dialog"] button[kind="secondary"] {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    border: 1px solid rgba(255,255,255,0.20) !important;
}}

/* ============================================================================
   v6.11 · TABS (st.tabs — Conciliadas / Sem baixa / Divergências etc.)
   Pílulas amarelas arredondadas com item ativo em amarelo sólido.
   ============================================================================ */
html body [data-baseweb="tab-list"],
html body .stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    border-bottom: 2px solid {_AMARELO} !important;
    padding: 10px 0 !important;
    gap: 8px !important;
    flex-wrap: wrap !important;
}}
html body [data-baseweb="tab"],
html body .stTabs [data-baseweb="tab"] {{
    background: #FFFDEE !important;
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
    padding: 9px 18px !important;
    border: 1.5px solid {_AMARELO_SUAVE} !important;
    border-radius: 22px !important;
    font-size: 12px !important;
    font-weight: 600 !important;
    height: auto !important;
    transition: all 0.18s ease !important;
}}
html body [data-baseweb="tab"] *,
html body .stTabs [data-baseweb="tab"] * {{
    color: {_TEXTO} !important;
    -webkit-text-fill-color: {_TEXTO} !important;
}}
html body [data-baseweb="tab"]:hover {{
    background: rgba(250,195,24,0.15) !important;
    border-color: {_AMARELO} !important;
}}
html body [data-baseweb="tab"][aria-selected="true"],
html body .stTabs [data-baseweb="tab"][aria-selected="true"] {{
    background: {_AMARELO} !important;
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    border: 2px solid {_NAVY} !important;
    font-weight: 700 !important;
    box-shadow: 0 2px 6px rgba(250,195,24,0.35) !important;
}}
html body [data-baseweb="tab"][aria-selected="true"] * {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-weight: 700 !important;
}}
html body [data-baseweb="tab-highlight"],
html body [data-baseweb="tab-border"] {{
    display: none !important;
}}

/* ============================================================================
   v6.11 · TABELAS NATIVAS (st.dataframe)
   Fundo navy escuro, cabeçalho amarelo, texto claro.
   ============================================================================ */
html body .block-container [data-testid="stDataFrame"],
html body .block-container [data-testid="stDataFrameResizable"] {{
    background: linear-gradient(135deg, {_NAVY_SIDEBAR} 0%, {_NAVY_SIDEBAR_2} 100%) !important;
    border: 1px solid {_AMARELO} !important;
    border-radius: 8px !important;
    padding: 4px !important;
    box-shadow: 0 4px 14px rgba(15,31,70,0.20) !important;
}}
html body .block-container [data-testid="stDataFrame"] * {{
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
}}
html body .block-container [data-testid="stDataFrame"] th,
html body .block-container [data-testid="stDataFrame"] [role="columnheader"],
html body .block-container [data-testid="stDataFrame"] .col_heading {{
    background: rgba(250,195,24,0.12) !important;
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
    border-color: rgba(250,195,24,0.20) !important;
}}
html body .block-container [data-testid="stDataFrame"] [role="columnheader"] * {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
}}
html body .block-container [data-testid="stDataFrame"] [role="rowheader"] {{
    color: {_AMARELO} !important;
    -webkit-text-fill-color: {_AMARELO} !important;
    font-weight: 700 !important;
    background: rgba(250,195,24,0.05) !important;
}}
html body .block-container [data-testid="stDataFrame"] [role="gridcell"] {{
    background: transparent !important;
    color: {_SB_TEXTO} !important;
    -webkit-text-fill-color: {_SB_TEXTO} !important;
    border-color: rgba(255,255,255,0.06) !important;
}}
html body .block-container [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] {{
    background: rgba(255,255,255,0.03) !important;
}}

/* ============================================================================
   v6.11 · KPIs Receita VERDE / Despesa VERMELHO
   ============================================================================ */
html body .lle-kpi .lle-kpi-sub-stack:nth-child(1) .lle-kpi-sub-valor {{
    color: #0F8C3B !important;
    -webkit-text-fill-color: #0F8C3B !important;
}}
html body .lle-kpi .lle-kpi-sub-stack:nth-child(2) .lle-kpi-sub-valor {{
    color: #C0392B !important;
    -webkit-text-fill-color: #C0392B !important;
}}
html body .lle-kpi-sub-receita,
html body .lle-kpi-sub-credito,
html body .lle-kpi-sub-aplicacao {{
    color: #0F8C3B !important;
    -webkit-text-fill-color: #0F8C3B !important;
    font-weight: 700 !important;
}}
html body .lle-kpi-sub-despesa,
html body .lle-kpi-sub-debito,
html body .lle-kpi-sub-resgate {{
    color: #C0392B !important;
    -webkit-text-fill-color: #C0392B !important;
    font-weight: 700 !important;
}}

/* ============================================================================
   v6.11 · FILA DE ARQUIVOS (cv-fila-nome)
   ============================================================================ */
html body .cv-fila-nome,
html body .cv-fila-nome * {{
    color: {_NAVY} !important;
    -webkit-text-fill-color: {_NAVY} !important;
    font-weight: 700 !important;
    font-size: 13px !important;
    opacity: 1 !important;
}}
</style>
"""
    )
