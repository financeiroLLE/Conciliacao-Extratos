# -*- coding: utf-8 -*-
"""
Página: Conciliação de Vendas — MVP-A · Fase 4 (motor integrado).

Esta página cobre:
    1. IMPORTAÇÃO de arquivos (Fase 3 · mantida)
       - Fila drag-drop, detecção automática, KPIs pós-leitura
    2. CONCILIAÇÃO (Fase 4 · nova)
       - Roda o motor (classificador Sankhya + matcher)
       - Layout "Painel Executivo": balanço financeiro, KPIs por adquirente,
         5 pills (A analisar / Auto-conciliadas / Compensadas / Aguardando / Devoluções),
         cards com timeline visual e candidatas
    3. AÇÕES manuais sobre resultados
       - Escolher candidata (motor nunca escolhe entre ambíguas — Débora decide)
       - Desfazer ligação (com popup de confirmação)
    4. EXPORTAÇÃO Excel com 8 abas para auditoria mensal

Estados guardados na sessão (namespace cv_*):
    cv_uploads              -> dict[nome] = {bytes, tipo_detectado, ...}
    cv_processado           -> bool  (arquivos lidos)
    cv_df_sankhya           -> DataFrame Financeiro Sankhya
    cv_df_cielo             -> DataFrame Cielo
    cv_df_getnet_vendas     -> DataFrame Getnet
    cv_df_getnet_repasses   -> DataFrame Getnet repasses
    cv_resumo               -> dict KPIs de importação
    cv_uploader_nonce       -> int (reset do file_uploader)
    cv_motor_resultado      -> ResultadoMotor (após rodar motor)
    cv_pill_ativa           -> str: "a_analisar" | "auto_conciliadas" | "compensadas" | "aguardando" | "devolucoes"
    cv_confirmadas_manual   -> dict {chave_venda: sk_idx} — escolhas em ambíguas
    cv_desfazer_pendente    -> dict com dados da venda aguardando confirmação de desfazer, ou None
    cv_ligacoes_desfeitas   -> set de chaves de venda que foram desfeitas manualmente
    cv_historico            -> list de dicts com trilha de auditoria da rodada

Regras invioláveis observadas:
    - Zero falso positivo: motor nunca escolhe entre candidatas; "a analisar" sempre visível
    - Additive-only: nenhuma alteração em layout global; estilização vive dentro desta página
    - Confirmação antes de desfazer: desfazer manda a venda de volta pra "a analisar"
    - Persistência via Supabase virá depois — nesta versão, decisões só sobrevivem à sessão
"""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from src.parsers.vendas import (
    detector_vendas,
    financeiro_sankhya,
    cielo_recebiveis,
    getnet_recebiveis,
)

# Motor de conciliação (Fase 4)
from src.motor_vendas import motor as motor_vendas
from src.motor_vendas import classificador_sankhya

# Exportação Excel (Fase 7 antecipada)
try:
    from src.reports import vendas_excel
    _EXCEL_DISPONIVEL = True
except ImportError:
    _EXCEL_DISPONIVEL = False


# ==============================================================================
# CORES CANÔNICAS LLE
# ==============================================================================

AZUL_NAVY = "#0A1730"
AZUL_CARD = "#14213D"
AZUL_CARD_2 = "#1F2E4C"
AMARELO = "#FFCC00"
CREME = "#FFF6C8"
VERDE = "#7ADB8F"
LARANJA = "#FF8A65"
VERMELHO = "#A32D2D"
VERMELHO_FUNDO = "#FCEBEB"
TEXTO_CLARO = "#E4E9F4"
TEXTO_MUTED = "#8A93A8"
BORDA_ESCURA = "#3A4560"


# ==============================================================================
# CSS
# ==============================================================================

_CSS = f"""
<style>
/* -------- HEADER INSTITUCIONAL -------- */
.cv-header {{
    background: {AZUL_NAVY};
    color: {AMARELO};
    padding: 20px 24px;
    border-radius: 12px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.cv-header-icon {{
    width: 44px; height: 44px;
    background: {AMARELO};
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px; color: {AZUL_NAVY};
}}
.cv-header-titulo {{ font-size: 20px; font-weight: 600; color: {AMARELO}; line-height: 1.1; }}
.cv-header-sub    {{ font-size: 13px; color: {CREME}; opacity: 0.85; margin-top: 2px; }}

/* -------- AVISO DE PRIVACIDADE -------- */
.cv-aviso {{
    background: {CREME} !important;
    border-left: 4px solid {AZUL_NAVY};
    border-radius: 12px;
    padding: 14px 20px;
    margin-bottom: 16px;
    display: flex; gap: 10px; align-items: center;
    font-size: 14px; font-weight: 500;
    color: {AZUL_NAVY} !important;
}}
.cv-aviso, .cv-aviso * {{ color: {AZUL_NAVY} !important; }}

/* -------- SEÇÃO -------- */
.cv-secao-titulo {{
    font-size: 12px; font-weight: 700; letter-spacing: 1.5px;
    color: {AMARELO} !important; text-transform: uppercase;
    margin: 20px 0 12px 0;
}}

/* -------- FILA DE ARQUIVOS -------- */
.cv-fila-card {{
    background: #ffffff !important;
    border-radius: 8px; padding: 12px 14px; margin-bottom: 8px;
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; border: 1px solid rgba(10,23,48,0.08);
}}
.cv-fila-card-fail {{ border-left: 3px solid {VERMELHO}; }}
.cv-fila-nome     {{ font-size: 13px; font-weight: 500; color: {AZUL_NAVY} !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 480px; }}
.cv-fila-detalhe  {{ font-size: 11px; color: {AZUL_NAVY} !important; opacity: 0.75; margin-top: 2px; }}
.cv-fila-detalhe-fail {{ color: {VERMELHO} !important; opacity: 1; }}
.cv-badge-ok   {{ background: {AZUL_NAVY} !important; color: {AMARELO} !important; font-size: 10px; font-weight: 600; padding: 4px 10px; border-radius: 20px; white-space: nowrap; letter-spacing: 0.5px; }}
.cv-badge-fail {{ background: {VERMELHO_FUNDO} !important; color: {VERMELHO} !important; font-size: 10px; font-weight: 600; padding: 4px 10px; border-radius: 20px; white-space: nowrap; letter-spacing: 0.5px; }}

/* -------- KPIs DE IMPORTAÇÃO -------- */
.cv-kpi {{ background: {CREME} !important; border-radius: 10px; padding: 14px 12px; text-align: center; }}
.cv-kpi-label      {{ font-size: 10px; letter-spacing: 0.5px; color: {AZUL_NAVY} !important; text-transform: uppercase; opacity: 0.7; margin-bottom: 6px; }}
.cv-kpi-valor      {{ font-size: 22px; font-weight: 600; color: {AZUL_NAVY} !important; line-height: 1.1; }}
.cv-kpi-secundario {{ font-size: 10px; color: {AZUL_NAVY} !important; opacity: 0.6; margin-top: 4px; }}

/* -------- TELA DE RESULTADO — BALANÇO -------- */
.cv-balanco-grid {{
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px; margin-bottom: 16px;
}}
.cv-balanco-card {{
    background: {AZUL_CARD}; border-radius: 10px;
    padding: 14px 16px;
}}
.cv-balanco-card.destaque {{ border-left: 3px solid {AMARELO}; }}
.cv-balanco-label {{ font-size: 10px; color: {TEXTO_MUTED}; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
.cv-balanco-valor {{ font-size: 22px; font-weight: 500; color: #FFFFFF; }}
.cv-balanco-sub   {{ font-size: 12px; color: {TEXTO_MUTED}; margin-top: 4px; }}
.cv-balanco-ok    {{ color: {VERDE}; }}
.cv-balanco-diff  {{ color: {LARANJA}; }}

/* -------- TELA DE RESULTADO — KPIs POR ADQUIRENTE -------- */
.cv-adq-bloco {{
    background: {AZUL_CARD}; border-radius: 10px; padding: 14px 16px; margin-bottom: 16px;
}}
.cv-adq-titulo {{ font-size: 10px; color: {TEXTO_MUTED}; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }}
.cv-adq-linha {{ margin-bottom: 12px; }}
.cv-adq-linha:last-child {{ margin-bottom: 0; }}
.cv-adq-linha-topo {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
.cv-adq-nome   {{ font-size: 13px; color: {TEXTO_CLARO}; }}
.cv-adq-info   {{ font-size: 12px; color: {TEXTO_MUTED}; }}
.cv-adq-pct    {{ color: {AMARELO}; font-weight: 500; }}
.cv-adq-barra  {{ height: 8px; background: {AZUL_NAVY}; border-radius: 4px; overflow: hidden; }}
.cv-adq-barra-preenchida {{ height: 100%; background: {AMARELO}; }}

/* -------- PILLS -------- */
.cv-pills-row {{
    display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap;
}}
/* botão base do Streamlit dentro dos pills — sobrepomos estilo via classe wrapper */
div[data-testid="stButton"] > button.cv-pill-btn,
div[data-testid="stButton"] > button.cv-pill-btn-ativa {{
    border-radius: 20px !important;
    padding: 8px 14px !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.8px !important;
    border: none !important;
}}

/* -------- CARDS DA TELA DE RESULTADO -------- */
.cv-card-analise {{
    background: {AZUL_CARD}; border-radius: 10px;
    padding: 14px 16px; margin-bottom: 10px;
    border-left: 3px solid {AMARELO};
}}
.cv-card-analise.divergencia {{ border-left-color: {LARANJA}; }}
.cv-card-analise.info-suave  {{ border-left-color: {BORDA_ESCURA}; opacity: 0.9; }}

.cv-card-topo {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }}

.cv-tag-line {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 4px; }}
.cv-tag {{
    background: {AZUL_NAVY}; color: {TEXTO_CLARO};
    font-size: 9px; padding: 2px 6px; border-radius: 3px;
    text-transform: uppercase; letter-spacing: 0.6px;
}}
.cv-tag-titulo    {{ background: {AMARELO}; color: {AZUL_NAVY}; font-weight: 500; }}
.cv-tag-alerta    {{ background: {LARANJA}; color: {AZUL_NAVY}; font-weight: 500; }}
.cv-tag-sucesso   {{ background: {VERDE};   color: {AZUL_NAVY}; font-weight: 500; }}
.cv-tag-adq       {{ color: {AMARELO}; }}

.cv-card-titulo   {{ font-size: 14px; color: #FFFFFF; font-weight: 500; }}
.cv-card-subtitulo {{ font-size: 11px; color: {TEXTO_MUTED}; margin-top: 2px; }}

.cv-trio {{ text-align: right; font-size: 11px; color: {TEXTO_MUTED}; }}
.cv-trio-liq {{ color: {TEXTO_CLARO}; }}
.cv-valor-grande {{ font-size: 16px; font-weight: 500; color: #FFFFFF; }}

/* -------- TIMELINE -------- */
.cv-timeline {{ display: flex; align-items: center; gap: 8px; margin: 12px 0; font-size: 11px; }}
.cv-timeline-passo {{ flex: 1; display: flex; flex-direction: column; align-items: center; }}
.cv-timeline-linha {{ flex: 1; height: 1px; }}
.cv-timeline-linha-ok  {{ background: {TEXTO_MUTED}; }}
.cv-timeline-linha-off {{ background: {BORDA_ESCURA}; }}
.cv-timeline-bolinha {{ width: 10px; height: 10px; border-radius: 50%; }}
.cv-timeline-bolinha-feito     {{ background: {VERDE}; }}
.cv-timeline-bolinha-atual     {{ background: {AMARELO}; }}
.cv-timeline-bolinha-pendente  {{ background: transparent; border: 1px solid {BORDA_ESCURA}; }}
.cv-timeline-data  {{ color: {TEXTO_MUTED}; margin-top: 4px; font-size: 10px; }}
.cv-timeline-label {{ color: {TEXTO_CLARO}; font-size: 10px; }}

/* -------- CANDIDATAS -------- */
.cv-candidatas-wrapper {{
    background: {AZUL_NAVY}; border-radius: 6px;
    padding: 10px 12px; font-size: 12px; color: {TEXTO_CLARO};
}}
.cv-candidatas-header {{
    color: {TEXTO_MUTED}; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px;
}}
.cv-candidata-linha {{ display: flex; justify-content: space-between; align-items: center; padding: 4px 0; gap: 8px; }}
.cv-candidata-info  {{ flex: 1; min-width: 0; }}
.cv-candidata-tag-nf   {{ background: {VERDE};   color: {AZUL_NAVY}; font-size: 8px; padding: 1px 5px; border-radius: 2px; margin-right: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.4px; }}
.cv-candidata-tag-adi  {{ background: {AMARELO}; color: {AZUL_NAVY}; font-size: 8px; padding: 1px 5px; border-radius: 2px; margin-right: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.4px; }}

/* -------- AUTO-CONCILIADAS (lista expandível) -------- */
.cv-auto-wrapper {{
    background: {AZUL_CARD}; border-radius: 10px;
    padding: 14px 16px;
}}
.cv-auto-header {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 12px;
}}
.cv-auto-titulo {{ font-size: 10px; color: {TEXTO_MUTED}; text-transform: uppercase; letter-spacing: 1px; }}
.cv-auto-card {{
    background: {AZUL_NAVY}; border-radius: 8px;
    padding: 10px 12px; margin-bottom: 8px;
}}
.cv-auto-card-topo {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }}
.cv-auto-parceiro  {{ font-size: 13px; color: #FFFFFF; font-weight: 500; }}
.cv-auto-info      {{ font-size: 10px; color: {TEXTO_MUTED}; margin-top: 2px; }}
.cv-auto-valor     {{ font-size: 14px; color: #FFFFFF; font-weight: 500; text-align: right; }}
.cv-auto-status    {{ font-size: 10px; color: {VERDE}; text-align: right; }}
.cv-auto-parcelas  {{ border-left: 2px solid {VERDE}; padding-left: 10px; margin-left: 2px; }}
.cv-auto-parc-linha {{ display: flex; justify-content: space-between; padding: 3px 0; font-size: 11px; }}
.cv-auto-nf {{ color: {AMARELO}; }}
.cv-auto-footer {{
    display: flex; justify-content: flex-end;
    margin-top: 8px; padding-top: 8px;
    border-top: 1px solid {AZUL_CARD_2};
}}

/* -------- CONFIRMAÇÃO DE DESFAZER (banner destacado) -------- */
.cv-confirmacao {{
    background: {AZUL_CARD}; border: 2px solid {AMARELO};
    border-radius: 12px; padding: 16px 20px; margin-bottom: 16px;
}}
.cv-confirmacao-titulo {{ font-size: 13px; color: #FFFFFF; font-weight: 500; margin-bottom: 4px; }}
.cv-confirmacao-descr  {{ font-size: 12px; color: {TEXTO_CLARO}; margin-bottom: 12px; }}

/* -------- RODAPÉ / EXPORTAR -------- */
.cv-rodape-acoes {{
    display: flex; justify-content: space-between; align-items: center;
    background: {AZUL_CARD}; border-radius: 10px;
    padding: 12px 16px; margin-top: 16px;
}}
.cv-rodape-info {{ font-size: 11px; color: {TEXTO_MUTED}; }}
</style>
"""


# ==============================================================================
# HELPERS BÁSICOS DE FORMATAÇÃO
# ==============================================================================

def _fmt_moeda(v: Any) -> str:
    """Formata número como R$ 1.234,56 (padrão brasileiro)."""
    try:
        s = f"{float(v):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def _fmt_data_br(d: Any) -> str:
    """Formata data como 24/07/2026. Retorna '—' se não parseável."""
    if d is None:
        return "—"
    try:
        if isinstance(d, (date, datetime)):
            return d.strftime("%d/%m/%Y")
        return pd.to_datetime(d).strftime("%d/%m/%Y")
    except Exception:
        return "—"


def _fmt_data_curta(d: Any) -> str:
    """Formata data como 24/07 (sem ano) — pro card compacto."""
    if d is None:
        return "—"
    try:
        if isinstance(d, (date, datetime)):
            return d.strftime("%d/%m")
        return pd.to_datetime(d).strftime("%d/%m")
    except Exception:
        return "—"


def _fmt_num(v: Any, casas: int = 0) -> str:
    """Formata inteiro/float sem prefixo (para contadores)."""
    try:
        return f"{float(v):,.{casas}f}".replace(",", ".") if casas == 0 else f"{float(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "0"


def _escape(s: Any) -> str:
    """Escape HTML básico."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _label_bandeira(b: Any) -> str:
    """'visa' -> 'Visa'; 'vis_mas' -> 'Vis/Mas'; retorna '—' se vazio."""
    if b is None:
        return "—"
    s = str(b).strip().lower()
    if not s or s == "none" or s == "nan":
        return "—"
    mapa = {
        "visa": "Visa",
        "master": "Master",
        "elo": "Elo",
        "vis_mas": "Vis/Mas",
        "mas_elo": "Mas/Elo",
        "hipercard": "Hipercard",
        "amex": "Amex",
    }
    return mapa.get(s, s.upper())


def _label_modalidade(m: Any, parcelas: Any = None) -> str:
    """'credito_parcelado' + parcelas=3 -> 'Crédito parc 3×'."""
    if m is None:
        return "—"
    s = str(m).strip().lower()
    if s in ("none", "nan", ""):
        return "—"
    if s == "debito":
        return "Débito"
    if s == "credito_avista":
        return "Crédito à vista"
    if s == "credito_parcelado":
        try:
            n = int(parcelas) if parcelas is not None else None
            if n and n > 1:
                return f"Crédito parc {n}×"
        except (ValueError, TypeError):
            pass
        return "Crédito parcelado"
    return s.capitalize()


def _label_adquirente(a: Any) -> str:
    """'getnet' -> 'Getnet'."""
    if a is None:
        return "—"
    s = str(a).strip().lower()
    mapa = {"getnet": "Getnet", "cielo": "Cielo", "pagseguro": "PagSeguro", "pagbank": "PagBank"}
    return mapa.get(s, s.capitalize())


# ==============================================================================
# ESTADO DA SESSÃO
# ==============================================================================

_SESSION_KEYS_IMPORTACAO = [
    "cv_uploads",
    "cv_processado",
    "cv_df_sankhya",
    "cv_df_cielo",
    "cv_df_getnet_vendas",
    "cv_df_getnet_repasses",
    "cv_resumo",
    "cv_uploader_nonce",
]

_SESSION_KEYS_MOTOR = [
    "cv_motor_resultado",
    "cv_pill_ativa",
    "cv_confirmadas_manual",
    "cv_desfazer_pendente",
    "cv_ligacoes_desfeitas",
    "cv_historico",
    "cv_tolerancia_dias",
    "cv_busca_auto",
    "cv_max_cards_a_analisar",
]


def _garantir_estado_inicial():
    # Importação
    st.session_state.setdefault("cv_uploads", {})
    st.session_state.setdefault("cv_processado", False)
    st.session_state.setdefault("cv_df_sankhya", None)
    st.session_state.setdefault("cv_df_cielo", None)
    st.session_state.setdefault("cv_df_getnet_vendas", None)
    st.session_state.setdefault("cv_df_getnet_repasses", None)
    st.session_state.setdefault("cv_resumo", {})
    st.session_state.setdefault("cv_uploader_nonce", 0)

    # Motor / resultado
    st.session_state.setdefault("cv_motor_resultado", None)
    st.session_state.setdefault("cv_pill_ativa", "a_analisar")
    st.session_state.setdefault("cv_confirmadas_manual", {})
    st.session_state.setdefault("cv_desfazer_pendente", None)
    st.session_state.setdefault("cv_ligacoes_desfeitas", set())
    st.session_state.setdefault("cv_historico", [])
    st.session_state.setdefault("cv_tolerancia_dias", 2)
    st.session_state.setdefault("cv_busca_auto", "")
    st.session_state.setdefault("cv_max_cards_a_analisar", 20)


def _limpar_estado_completo():
    """Zera tudo — usado pelo botão 'Nova rodada'."""
    for k in _SESSION_KEYS_IMPORTACAO + _SESSION_KEYS_MOTOR:
        if k == "cv_uploader_nonce":
            st.session_state[k] = st.session_state.get(k, 0) + 1
        elif k == "cv_uploads":
            st.session_state[k] = {}
        elif k in ("cv_processado",):
            st.session_state[k] = False
        elif k in ("cv_resumo", "cv_confirmadas_manual"):
            st.session_state[k] = {}
        elif k == "cv_ligacoes_desfeitas":
            st.session_state[k] = set()
        elif k == "cv_historico":
            st.session_state[k] = []
        elif k == "cv_pill_ativa":
            st.session_state[k] = "a_analisar"
        elif k == "cv_tolerancia_dias":
            st.session_state[k] = 2
        elif k == "cv_busca_auto":
            st.session_state[k] = ""
        elif k == "cv_max_cards_a_analisar":
            st.session_state[k] = 20
        else:
            st.session_state[k] = None


def _limpar_estado_motor():
    """Zera só resultado + decisões (mantém arquivos e DataFrames)."""
    st.session_state["cv_motor_resultado"] = None
    st.session_state["cv_pill_ativa"] = "a_analisar"
    st.session_state["cv_confirmadas_manual"] = {}
    st.session_state["cv_desfazer_pendente"] = None
    st.session_state["cv_ligacoes_desfeitas"] = set()
    st.session_state["cv_historico"] = []
    st.session_state["cv_busca_auto"] = ""
    st.session_state["cv_max_cards_a_analisar"] = 20


# ==============================================================================
# ABSORVER UPLOADS (COM BUG FIX)
# ==============================================================================

def _absorver_uploads(arquivos):
    """
    Guarda bytes em session_state e detecta tipo para cada arquivo NOVO.

    FIX v6.1: rastreia com flag `houve_novo` e só zera cv_processado se
    realmente teve arquivo novo. O bug original zerava sempre, mesmo em rerun
    sem upload novo, fazendo os KPIs (e o resultado do motor) sumirem.
    """
    if not arquivos:
        return

    uploads = st.session_state["cv_uploads"]
    houve_novo = False

    for arq in arquivos:
        nome = arq.name
        if nome in uploads:
            continue

        houve_novo = True

        try:
            dados = arq.getvalue()
        except Exception as e:
            uploads[nome] = {
                "bytes": b"",
                "tipo_detectado": "desconhecido",
                "tipo_legivel": "Erro ao ler bytes",
                "motivo": f"Falha ao acessar bytes do upload: {e}",
                "confianca": "nenhuma",
            }
            continue

        deteccao = detector_vendas.detectar(dados)
        uploads[nome] = {
            "bytes": dados,
            "tipo_detectado": deteccao.tipo,
            "tipo_legivel": deteccao.tipo_legivel,
            "motivo": deteccao.motivo or "",
            "confianca": deteccao.confianca,
        }

    st.session_state["cv_uploads"] = uploads

    # Só resetamos "processado" se de fato teve arquivo novo.
    # (Sem essa checagem, o rerun após "Processar" zerava tudo.)
    if houve_novo:
        st.session_state["cv_processado"] = False
        # Novo arquivo invalida o resultado do motor também
        _limpar_estado_motor()


# ==============================================================================
# PROCESSAR ARQUIVOS (mantido da Fase 3)
# ==============================================================================

def _processar_arquivos():
    """Roda leitores e popula DataFrames. Zero falso positivo: erros ficam visíveis."""
    uploads = st.session_state["cv_uploads"]
    if not uploads:
        return

    df_sankhya_lista: List[pd.DataFrame] = []
    df_cielo_lista: List[pd.DataFrame] = []
    df_getnet_vendas_lista: List[pd.DataFrame] = []
    df_getnet_repasses_lista: List[pd.DataFrame] = []

    resumo = {
        "sankhya_linhas": 0,
        "sankhya_top_1722": 0,
        "sankhya_top_0": 0,
        "sankhya_compensadas": 0,
        "sankhya_empresas": set(),
        "cielo_vendas": 0,
        "cielo_bruto": 0.0,
        "cielo_liquido": 0.0,
        "getnet_vendas": 0,
        "getnet_cancelamentos": 0,
        "getnet_repasses": 0,
        "getnet_liquido": 0.0,
        "getnet_repassado": 0.0,
    }

    for nome, entry in uploads.items():
        tipo = entry.get("tipo_detectado")
        dados = entry.get("bytes")
        if not dados:
            continue

        try:
            if tipo == "financeiro_sankhya":
                res = financeiro_sankhya.ler(dados)
                df_sankhya_lista.append(res.df)
                resumo["sankhya_linhas"] += res.total_linhas
                resumo["sankhya_empresas"].update(res.empresas_encontradas)
                for (top, _desc, _grp), n in res.resumo_top_baixa.items():
                    if top == 1722:
                        resumo["sankhya_top_1722"] += n
                    elif top == 0:
                        resumo["sankhya_top_0"] += n
                    elif top in (1731, 1732, 1716):
                        resumo["sankhya_compensadas"] += n
                entry["detalhe_pos_processamento"] = (
                    f"Financeiro Sankhya · {res.total_linhas} títulos · "
                    f"empresas {'+'.join(str(e) for e in res.empresas_encontradas)}"
                )

            elif tipo == "cielo_recebiveis":
                res = cielo_recebiveis.ler(dados)
                df_cielo_lista.append(res.df)
                resumo["cielo_vendas"] += res.total_linhas
                resumo["cielo_bruto"] += res.total_bruto
                resumo["cielo_liquido"] += res.total_liquido
                entry["detalhe_pos_processamento"] = (
                    f"Cielo Recebíveis · {res.total_linhas} vendas · "
                    f"{_fmt_moeda(res.total_liquido)} líquido"
                )

            elif tipo == "getnet_recebiveis":
                res = getnet_recebiveis.ler(dados)
                df_getnet_vendas_lista.append(res.df_vendas)
                df_getnet_repasses_lista.append(res.df_repasses)
                resumo["getnet_vendas"] += res.total_vendas
                resumo["getnet_cancelamentos"] += res.total_cancelamentos
                resumo["getnet_repasses"] += res.total_repasses
                resumo["getnet_liquido"] += res.total_liquido_vendas
                resumo["getnet_repassado"] += res.total_repassado
                entry["detalhe_pos_processamento"] = (
                    f"Getnet Recebíveis · {res.total_vendas} vendas · "
                    f"{_fmt_moeda(res.total_repassado)} repassado"
                )

            else:
                entry.setdefault("detalhe_pos_processamento", entry.get("motivo", "Tipo não reconhecido."))
                continue

        except Exception as e:
            entry["tipo_detectado"] = "desconhecido"
            entry["detalhe_pos_processamento"] = f"Falha ao processar: {e}"

    st.session_state["cv_df_sankhya"] = pd.concat(df_sankhya_lista, ignore_index=True) if df_sankhya_lista else None
    st.session_state["cv_df_cielo"] = pd.concat(df_cielo_lista, ignore_index=True) if df_cielo_lista else None
    st.session_state["cv_df_getnet_vendas"] = pd.concat(df_getnet_vendas_lista, ignore_index=True) if df_getnet_vendas_lista else None
    st.session_state["cv_df_getnet_repasses"] = pd.concat(df_getnet_repasses_lista, ignore_index=True) if df_getnet_repasses_lista else None

    resumo["sankhya_empresas"] = sorted(resumo["sankhya_empresas"])
    st.session_state["cv_resumo"] = resumo
    st.session_state["cv_processado"] = True

    # Ao reprocessar arquivos, invalida qualquer resultado anterior do motor
    _limpar_estado_motor()


# ==============================================================================
# RODAR MOTOR DE CONCILIAÇÃO
# ==============================================================================

def _rodar_motor():
    """Classifica Sankhya e roda o motor. Popula cv_motor_resultado."""
    df_sk = st.session_state.get("cv_df_sankhya")
    df_cielo = st.session_state.get("cv_df_cielo")
    df_getnet = st.session_state.get("cv_df_getnet_vendas")
    tol = int(st.session_state.get("cv_tolerancia_dias", 2))

    if df_sk is None or df_sk.empty:
        st.session_state["cv_motor_resultado"] = None
        return "Financeiro Sankhya não foi carregado."

    if (df_cielo is None or df_cielo.empty) and (df_getnet is None or df_getnet.empty):
        st.session_state["cv_motor_resultado"] = None
        return "Nenhum arquivo de adquirente (Cielo/Getnet) foi carregado."

    try:
        df_sk_classificado = classificador_sankhya.classificar(df_sk)
        resultado = motor_vendas.rodar(
            df_sankhya_classificado=df_sk_classificado,
            df_cielo=df_cielo,
            df_getnet_vendas=df_getnet,
            tolerancia_dias=tol,
        )
    except Exception as e:
        st.session_state["cv_motor_resultado"] = None
        return f"Erro ao rodar motor: {e}"

    st.session_state["cv_motor_resultado"] = resultado
    return None


# ==============================================================================
# HELPERS DE ANÁLISE (agrupamento, KPIs, status por card)
# ==============================================================================

def _chave_venda_original(row: pd.Series) -> Tuple[str, str, str]:
    """
    Chave estável de agrupamento de parcelas da mesma venda.

    Estratégia: (adquirente, nsu, autorizacao). Se nsu vazio, usa autorização
    isolada. Se ambos vazios, cai em (adquirente, sk_nome_parceiro, data_venda_str).
    """
    adq = str(row.get("adquirente") or "")
    nsu = str(row.get("nsu") or "").strip()
    auth = str(row.get("autorizacao") or "").strip()

    if nsu and auth:
        return (adq, nsu, auth)
    if nsu:
        return (adq, nsu, "")
    if auth:
        return (adq, "", auth)

    parc = str(row.get("sk_nome_parceiro") or row.get("nome_parceiro") or "")
    data = row.get("data_prev_pagamento")
    try:
        data_str = pd.to_datetime(data).strftime("%Y-%m-%d") if data is not None else ""
    except Exception:
        data_str = ""
    return (adq, parc, data_str)


def _agrupar_conciliadas_por_venda(
    df_g1: pd.DataFrame,
    ligacoes_desfeitas: set,
) -> List[Dict[str, Any]]:
    """
    Recebe grupo_1_conciliadas (uma linha por parcela) e retorna lista de dicts
    com uma entrada por venda original — cada entrada tem lista de parcelas.

    Filtra fora as chaves que estão em ligacoes_desfeitas.
    """
    if df_g1 is None or df_g1.empty:
        return []

    grupos: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for _, row in df_g1.iterrows():
        chave = _chave_venda_original(row)
        if chave in ligacoes_desfeitas:
            continue

        if chave not in grupos:
            grupos[chave] = {
                "chave": chave,
                "adquirente": row.get("adquirente"),
                "bandeira": row.get("bandeira"),
                "modalidade": row.get("modalidade"),
                "parcelas_total": row.get("parcelas_total") or 1,
                "nsu": row.get("nsu"),
                "autorizacao": row.get("autorizacao"),
                "data_prev_pagamento": row.get("data_prev_pagamento"),
                "nome_parceiro": row.get("sk_nome_parceiro"),
                "empresa": row.get("sk_empresa_nome"),
                "valor_total": 0.0,
                "parcelas": [],
            }

        grupos[chave]["valor_total"] += float(row.get("valor_match") or 0)
        grupos[chave]["parcelas"].append({
            "parcela_atual": row.get("parcela_atual"),
            "parcelas_total": row.get("parcelas_total"),
            "valor": row.get("valor_match"),
            "sk_nro_nota": row.get("sk_nro_nota"),
            "sk_nro_unico": row.get("sk_nro_unico"),
            "sk_dt_vencimento": row.get("sk_dt_vencimento"),
            "sk_classe": row.get("sk_classe"),
            "sk_ref_nf": row.get("sk_ref_nf"),
        })

    # Ordena parcelas dentro de cada grupo
    for g in grupos.values():
        g["parcelas"].sort(key=lambda p: (p.get("parcela_atual") or 0))

    # Ordena grupos por data mais recente primeiro
    lista = list(grupos.values())
    lista.sort(key=lambda g: (str(g.get("data_prev_pagamento") or ""), str(g.get("nome_parceiro") or "")), reverse=True)
    return lista


def _calcular_totais_adquirente(df_cielo, df_getnet) -> Dict[str, Any]:
    """Soma bruta do lado adquirente por adquirente + total."""
    total = 0.0
    cielo_total = 0.0
    getnet_total = 0.0
    cielo_n = 0
    getnet_n = 0

    if df_cielo is not None and not df_cielo.empty:
        cielo_total = float(df_cielo["valor_bruto"].sum())
        cielo_n = len(df_cielo)
        total += cielo_total
    if df_getnet is not None and not df_getnet.empty:
        col_valor = "valor_parcela_bruto" if "valor_parcela_bruto" in df_getnet.columns else "valor_bruto"
        getnet_total = float(df_getnet[col_valor].sum())
        getnet_n = len(df_getnet)
        total += getnet_total

    return {
        "total": total,
        "cielo_total": cielo_total,
        "getnet_total": getnet_total,
        "cielo_n": cielo_n,
        "getnet_n": getnet_n,
        "total_n": cielo_n + getnet_n,
    }


def _calcular_total_sankhya_elegivel(df_sankhya) -> Dict[str, Any]:
    """Soma dos títulos Sankhya elegíveis para match (nota fiscal + adiantamento, aberto ou 1722)."""
    if df_sankhya is None or df_sankhya.empty:
        return {"total": 0.0, "total_n": 0}

    df_c = classificador_sankhya.classificar(df_sankhya)
    df_el = classificador_sankhya.filtrar_elegiveis_para_match(df_c)

    if df_el is None or df_el.empty:
        return {"total": 0.0, "total_n": 0}

    return {
        "total": float(df_el["vlr_desdobramento"].sum()),
        "total_n": len(df_el),
    }


def _calcular_kpis_por_adquirente(resultado, df_cielo, df_getnet) -> Dict[str, Dict[str, Any]]:
    """
    Retorna % de auto-conciliação por adquirente:
        {"getnet": {"conciliadas": 128, "total": 198, "pct": 64.6},
         "cielo":  {"conciliadas": 45,  "total": 78,  "pct": 57.7}}

    Considera Grupo 1 (auto em aberto) + Grupo 2 (baixadas por cartão) como conciliadas.
    """
    result = {
        "getnet": {"conciliadas": 0, "total": 0, "pct": 0.0},
        "cielo":  {"conciliadas": 0, "total": 0, "pct": 0.0},
    }

    if df_cielo is not None and not df_cielo.empty:
        result["cielo"]["total"] = len(df_cielo)
    if df_getnet is not None and not df_getnet.empty:
        result["getnet"]["total"] = len(df_getnet)

    for df in (resultado.grupo_1_conciliadas, resultado.grupo_2_ja_baixadas):
        if df is None or df.empty:
            continue
        counts = df["adquirente"].value_counts().to_dict()
        for adq, n in counts.items():
            if adq in result:
                result[adq]["conciliadas"] += int(n)

    for adq, d in result.items():
        d["pct"] = round((d["conciliadas"] / d["total"] * 100), 1) if d["total"] > 0 else 0.0

    return result


def _calcular_contadores_pills(resultado, ligacoes_desfeitas: set) -> Dict[str, int]:
    """
    Contadores dos 5 pills:
        a_analisar        = ambíguos + venda_sem_titulo + título_sem_venda + desfeitas
        auto_conciliadas  = Grupo 1 (auto) menos as desfeitas
        compensadas       = Grupo 2 (baixadas por cartão)
        aguardando        = Grupo 3
        devolucoes        = Grupo 4
    """
    n_amb = len(resultado.a_analisar_ambiguos) if resultado.a_analisar_ambiguos is not None else 0
    n_vst = len(resultado.a_analisar_venda_sem_titulo) if resultado.a_analisar_venda_sem_titulo is not None else 0
    n_tsv = len(resultado.a_analisar_titulo_sem_venda) if resultado.a_analisar_titulo_sem_venda is not None else 0
    n_desf = len(ligacoes_desfeitas)

    # Contar quantas parcelas do Grupo 1 caem em ligações desfeitas
    n_g1_parcelas = len(resultado.grupo_1_conciliadas) if resultado.grupo_1_conciliadas is not None else 0
    n_g1_desfeitas = 0
    if n_desf > 0 and resultado.grupo_1_conciliadas is not None and not resultado.grupo_1_conciliadas.empty:
        for _, row in resultado.grupo_1_conciliadas.iterrows():
            if _chave_venda_original(row) in ligacoes_desfeitas:
                n_g1_desfeitas += 1

    return {
        "a_analisar": n_amb + n_vst + n_tsv + n_desf,
        "auto_conciliadas": n_g1_parcelas - n_g1_desfeitas,
        "compensadas": len(resultado.grupo_2_ja_baixadas) if resultado.grupo_2_ja_baixadas is not None else 0,
        "aguardando": len(resultado.grupo_3_aguardando) if resultado.grupo_3_aguardando is not None else 0,
        "devolucoes": len(resultado.grupo_4_devolucoes) if resultado.grupo_4_devolucoes is not None else 0,
    }


def _dias_desde(data: Any, hoje: Optional[date] = None) -> Optional[int]:
    """Diferença em dias entre `data` e hoje. None se não parseável."""
    if data is None:
        return None
    if hoje is None:
        hoje = date.today()
    try:
        d = pd.to_datetime(data).date() if not isinstance(data, date) else data
        return (hoje - d).days
    except Exception:
        return None


def _classificar_venda_sem_titulo(venda: pd.Series, hoje: Optional[date] = None) -> Tuple[str, str]:
    """
    Classifica uma venda sem título como:
        - ("aguardando_faturamento", "Aguardando faturamento")  → normal, < 3 dias
        - ("divergencia_real",       "Divergência real · N dias") → investigar, ≥ 3 dias
    """
    dias = _dias_desde(venda.get("data_prev_pagamento"), hoje)
    if dias is None:
        return ("aguardando_faturamento", "Aguardando faturamento · sem data")
    if dias < 3:
        return ("aguardando_faturamento", f"Aguardando faturamento · {dias} dia(s)")
    return ("divergencia_real", f"Divergência real · {dias} dias sem par")


# ==============================================================================
# RENDERS DA IMPORTAÇÃO (Fase 3)
# ==============================================================================

def _render_header():
    st.markdown(
        f"""
        <div class="cv-header">
            <div class="cv-header-icon">🛒</div>
            <div>
                <div class="cv-header-titulo">Conciliação de Vendas</div>
                <div class="cv-header-sub">MVP-A · PISA · KING · TRIO</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_aviso():
    st.markdown(
        f"""
        <div class="cv-aviso">
            <span style="font-size:18px;">ℹ️</span>
            <span>Arquivos são processados na sessão e <b>não ficam armazenados</b> no servidor.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_card_arquivo(nome: str, entry: Dict[str, Any]):
    tipo = entry.get("tipo_detectado", "desconhecido")
    reconhecido = tipo != "desconhecido"
    detalhe = entry.get("detalhe_pos_processamento") or entry.get("motivo") or entry.get("tipo_legivel", "")

    if reconhecido:
        card_class = "cv-fila-card"
        badge_html = '<div class="cv-badge-ok">✓ RECONHECIDO</div>'
        detalhe_class = "cv-fila-detalhe"
    else:
        card_class = "cv-fila-card cv-fila-card-fail"
        badge_html = '<div class="cv-badge-fail">✗ IGNORADO</div>'
        detalhe_class = "cv-fila-detalhe cv-fila-detalhe-fail"

    st.markdown(
        f"""
        <div class="{card_class}">
            <div style="display:flex; align-items:center; gap:12px; min-width:0; flex:1;">
                <span style="font-size:22px;">📄</span>
                <div style="min-width:0; overflow:hidden;">
                    <div class="cv-fila-nome">{_escape(nome)}</div>
                    <div class="{detalhe_class}">{_escape(detalhe)}</div>
                </div>
            </div>
            {badge_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_kpi(coluna, label: str, valor: str, secundario: Optional[str] = None):
    with coluna:
        sec_html = f'<div class="cv-kpi-secundario">{_escape(secundario)}</div>' if secundario else ""
        st.markdown(
            f"""
            <div class="cv-kpi">
                <div class="cv-kpi-label">{_escape(label)}</div>
                <div class="cv-kpi-valor">{_escape(valor)}</div>
                {sec_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_kpis_importacao():
    """Os 4 KPIs após processar arquivos (antes de rodar motor)."""
    r = st.session_state.get("cv_resumo", {})
    if not r:
        return
    st.markdown('<div class="cv-secao-titulo">Resumo do que foi lido</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    _render_kpi(
        c1, "Vendas Cielo", f"{r.get('cielo_vendas', 0)}",
        _fmt_moeda(r.get("cielo_liquido", 0.0)) + " líquido" if r.get("cielo_vendas", 0) else None,
    )
    _render_kpi(
        c2, "Vendas Getnet", f"{r.get('getnet_vendas', 0)}",
        _fmt_moeda(r.get("getnet_repassado", 0.0)) + " repassado" if r.get("getnet_vendas", 0) else None,
    )
    _render_kpi(
        c3, "Baixas TOP 1722", f"{r.get('sankhya_top_1722', 0)}",
        f"{r.get('sankhya_compensadas', 0)} compensadas" if r.get("sankhya_top_1722", 0) else None,
    )
    _render_kpi(
        c4, "Aguardando captura", f"{r.get('sankhya_top_0', 0)}",
        "títulos TOP 0" if r.get("sankhya_top_0", 0) else None,
    )

    empresas = r.get("sankhya_empresas", [])
    if empresas:
        map_emp = {1: "PISA", 2: "KING"}
        nomes = [map_emp.get(e, f"EMP{e}") for e in empresas]
        st.caption(f"Empresas identificadas no Financeiro: {' · '.join(nomes)}")


# ==============================================================================
# RENDERS DA TELA DE RESULTADO — TOPO (balanço, KPIs adquirentes, pills)
# ==============================================================================

def _render_topo_resultado(resultado, contadores):
    """Balanço financeiro + KPIs por adquirente."""
    hoje = date.today()
    df_cielo = st.session_state.get("cv_df_cielo")
    df_getnet = st.session_state.get("cv_df_getnet_vendas")
    df_sk = st.session_state.get("cv_df_sankhya")

    tot_adq = _calcular_totais_adquirente(df_cielo, df_getnet)
    tot_sk = _calcular_total_sankhya_elegivel(df_sk)

    diff = tot_adq["total"] - tot_sk["total"]
    bate = abs(diff) < 0.01
    diff_txt = "batem ao centavo" if bate else f"dif {_fmt_moeda(abs(diff))}"
    diff_class = "cv-balanco-ok" if bate else "cv-balanco-diff"

    # Cabeçalho da rodada
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:16px;">
          <div>
            <div style="font-size:11px; color:{TEXTO_MUTED}; letter-spacing:1.2px; text-transform:uppercase; margin-bottom:4px;">
              Rodada de {hoje.strftime("%d/%m/%Y")} · tolerância ±{st.session_state.get("cv_tolerancia_dias", 2)} dias
            </div>
            <div style="font-size:18px; font-weight:500; color:#FFFFFF;">Resultado da conciliação</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Balanço financeiro (dois cards lado a lado)
    st.markdown(
        f"""
        <div class="cv-balanco-grid">
          <div class="cv-balanco-card">
            <div class="cv-balanco-label">Total Adquirente</div>
            <div class="cv-balanco-valor">{_fmt_moeda(tot_adq['total'])}</div>
            <div class="cv-balanco-sub">{tot_adq['total_n']} vendas · Getnet {tot_adq['getnet_n']} · Cielo {tot_adq['cielo_n']}</div>
          </div>
          <div class="cv-balanco-card destaque">
            <div class="cv-balanco-label">Total Sankhya <span class="{diff_class}">· {diff_txt}</span></div>
            <div class="cv-balanco-valor">{_fmt_moeda(tot_sk['total'])}</div>
            <div class="cv-balanco-sub">{tot_sk['total_n']} títulos elegíveis (nota + adiantamento)</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # KPIs por adquirente (barras)
    kpis = _calcular_kpis_por_adquirente(resultado, df_cielo, df_getnet)
    linhas_html = ['<div class="cv-adq-titulo">Auto-conciliação por adquirente</div>']
    for adq_key in ("getnet", "cielo"):
        d = kpis[adq_key]
        if d["total"] == 0:
            continue
        pct = d["pct"]
        linhas_html.append(f"""
          <div class="cv-adq-linha">
            <div class="cv-adq-linha-topo">
              <span class="cv-adq-nome">{_label_adquirente(adq_key)}</span>
              <span class="cv-adq-info">{d['conciliadas']} de {d['total']} · <span class="cv-adq-pct">{pct:.1f}%</span></span>
            </div>
            <div class="cv-adq-barra"><div class="cv-adq-barra-preenchida" style="width:{min(pct, 100):.1f}%;"></div></div>
          </div>
        """)
    if len(linhas_html) > 1:
        st.markdown(f'<div class="cv-adq-bloco">{"".join(linhas_html)}</div>', unsafe_allow_html=True)


def _render_pills(contadores: Dict[str, int]):
    """5 pills clicáveis. Usa botões Streamlit com CSS por classe."""
    ordem = [
        ("a_analisar", "A analisar", contadores["a_analisar"]),
        ("auto_conciliadas", "Auto-conciliadas", contadores["auto_conciliadas"]),
        ("compensadas", "Compensadas", contadores["compensadas"]),
        ("aguardando", "Aguardando", contadores["aguardando"]),
        ("devolucoes", "Devoluções", contadores["devolucoes"]),
    ]
    ativa = st.session_state.get("cv_pill_ativa", "a_analisar")

    # Renderiza numa linha com colunas — 5 botões Streamlit lado a lado
    cols = st.columns(5)
    for i, (key, label, count) in enumerate(ordem):
        with cols[i]:
            is_ativa = (key == ativa)
            texto = f"{label} · {count}"
            if st.button(
                texto,
                key=f"cv_pill_{key}",
                type="primary" if is_ativa else "secondary",
                use_container_width=True,
            ):
                st.session_state["cv_pill_ativa"] = key
                st.rerun()


# ==============================================================================
# RENDERS DE CARDS — A ANALISAR
# ==============================================================================

def _render_timeline_card(dt_venda, dt_previsto, dt_baixado=None):
    """Timeline de 3 pontos: Vendido → Previsto → Baixado."""
    tem_baixa = dt_baixado is not None

    bolinha_venda = "cv-timeline-bolinha cv-timeline-bolinha-feito"
    bolinha_prev = "cv-timeline-bolinha cv-timeline-bolinha-atual"
    bolinha_baixa = "cv-timeline-bolinha cv-timeline-bolinha-feito" if tem_baixa else "cv-timeline-bolinha cv-timeline-bolinha-pendente"

    linha1 = "cv-timeline-linha cv-timeline-linha-ok"
    linha2 = "cv-timeline-linha cv-timeline-linha-ok" if tem_baixa else "cv-timeline-linha cv-timeline-linha-off"

    return f"""
      <div class="cv-timeline">
        <div class="cv-timeline-passo">
          <div class="{bolinha_venda}"></div>
          <div class="cv-timeline-data">{_fmt_data_curta(dt_venda)}</div>
          <div class="cv-timeline-label">Vendido</div>
        </div>
        <div class="{linha1}"></div>
        <div class="cv-timeline-passo">
          <div class="{bolinha_prev}"></div>
          <div class="cv-timeline-data">{_fmt_data_curta(dt_previsto)}</div>
          <div class="cv-timeline-label">Previsto</div>
        </div>
        <div class="{linha2}"></div>
        <div class="cv-timeline-passo">
          <div class="{bolinha_baixa}"></div>
          <div class="cv-timeline-data">{_fmt_data_curta(dt_baixado) if tem_baixa else "—"}</div>
          <div class="cv-timeline-label">Baixado</div>
        </div>
      </div>
    """


def _render_card_ambiguo(venda: pd.Series, idx_card: int):
    """Card de venda com múltiplas candidatas. Motor não escolhe — Débora decide."""
    adq = _label_adquirente(venda.get("adquirente"))
    ban = _label_bandeira(venda.get("bandeira"))
    mod = _label_modalidade(venda.get("modalidade"), venda.get("parcelas_total"))
    parc_atual = venda.get("parcela_atual")
    parc_total = venda.get("parcelas_total")
    parc_txt = ""
    try:
        pa = int(parc_atual) if parc_atual is not None else None
        pt = int(parc_total) if parc_total is not None else None
        if pa and pt and pt > 1:
            parc_txt = f"Parcela {pa}/{pt}"
    except (ValueError, TypeError):
        pass

    nsu = venda.get("nsu") or ""
    nsu_txt = f"Nro Único {nsu}" if nsu else ""

    valor = venda.get("valor_match")
    data_venda = venda.get("data_prev_pagamento")

    # Timeline (previsto = data_prev_pagamento; baixado = ainda não)
    timeline = _render_timeline_card(data_venda, data_venda, None)

    # Candidatas
    candidatas = venda.get("candidatos") or []
    candidatas_html = ['<div class="cv-candidatas-header">Motor não escolhe · você decide qual é o par correto</div>']
    for i, cand in enumerate(candidatas):
        classe = cand.get("classe")
        if classe == "adiantamento":
            tag_html = '<span class="cv-candidata-tag-adi">Adiantamento</span>'
            ref_nf = cand.get("nro_nota_referenciada")
            info = f"TOP_OP 1654 · REF NF {ref_nf}" if ref_nf else "TOP_OP 1654 · sem REF NF"
        else:
            tag_html = '<span class="cv-candidata-tag-nf">Nota fiscal</span>'
            nro = cand.get("nro_nota")
            info = f"NF {nro}" if nro else "Nota fiscal"

        parceiro = cand.get("nome_parceiro") or "—"
        vlr = cand.get("vlr_desdobramento")
        venc = cand.get("dt_vencimento")

        candidatas_html.append(f"""
          <div class="cv-candidata-linha" id="cand_{idx_card}_{i}">
            <div class="cv-candidata-info">
              {tag_html}
              <span>{_escape(info)} · {_escape(parceiro)} · venc {_fmt_data_br(venc)} · {_fmt_moeda(vlr)}</span>
            </div>
          </div>
        """)

    # Renderiza o card
    tags = [f'<span class="cv-tag cv-tag-alerta">Múltiplas candidatas</span>',
            f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
            f'<span class="cv-tag">{_escape(mod)} · {_escape(ban)}</span>']
    if parc_txt:
        tags.append(f'<span class="cv-tag">{_escape(parc_txt)}</span>')
    if nsu_txt:
        tags.append(f'<span class="cv-tag">{_escape(nsu_txt)}</span>')

    st.markdown(
        f"""
        <div class="cv-card-analise">
          <div class="cv-card-topo">
            <div>
              <div class="cv-tag-line">{"".join(tags)}</div>
              <div class="cv-card-titulo">{_fmt_moeda(valor)} · vendido {_fmt_data_br(data_venda)}</div>
            </div>
            <div class="cv-trio">
              <div>bruto {_fmt_moeda(valor)}</div>
            </div>
          </div>
          {timeline}
          <div class="cv-candidatas-wrapper">
            {"".join(candidatas_html)}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Botões "Escolher" pra cada candidata (usa botões Streamlit reais)
    if candidatas:
        st.markdown('<div style="margin-top:-6px; margin-bottom:12px;"></div>', unsafe_allow_html=True)
        cols = st.columns(len(candidatas))
        chave_venda = _chave_venda_original(venda)
        chave_str = "|".join(str(x) for x in chave_venda)
        for i, cand in enumerate(candidatas):
            with cols[i]:
                classe = cand.get("classe", "?")
                label_curto = f"Escolher {'NF ' + str(cand.get('nro_nota')) if classe == 'nota_fiscal' else 'Adiant.'}"
                if st.button(
                    label_curto,
                    key=f"cv_esc_{idx_card}_{i}",
                    use_container_width=True,
                ):
                    _acao_escolher_candidata(chave_str, cand)
                    st.rerun()


def _render_card_venda_sem_titulo(venda: pd.Series, idx_card: int, hoje: date):
    """Card de venda sem título correspondente no Sankhya."""
    status_key, status_label = _classificar_venda_sem_titulo(venda, hoje)

    adq = _label_adquirente(venda.get("adquirente"))
    ban = _label_bandeira(venda.get("bandeira"))
    mod = _label_modalidade(venda.get("modalidade"), venda.get("parcelas_total"))
    valor = venda.get("valor_match")
    data_venda = venda.get("data_prev_pagamento")

    if status_key == "divergencia_real":
        card_class = "cv-card-analise divergencia"
        tag_status = f'<span class="cv-tag cv-tag-alerta">{_escape(status_label)}</span>'
        subtitulo = "Sem par no Sankhya · pode ser Cielo link (CREDITO A DISTANCIA) ou faturamento pendente"
    else:
        card_class = "cv-card-analise info-suave"
        tag_status = f'<span class="cv-tag cv-tag-titulo">{_escape(status_label)}</span>'
        subtitulo = "Situação normal · a nota é faturada automaticamente pelo Sankhya"

    tags = [tag_status,
            f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
            f'<span class="cv-tag">{_escape(mod)} · {_escape(ban)}</span>']

    st.markdown(
        f"""
        <div class="{card_class}">
          <div class="cv-card-topo">
            <div>
              <div class="cv-tag-line">{"".join(tags)}</div>
              <div class="cv-card-titulo">{_fmt_moeda(valor)} · vendido {_fmt_data_br(data_venda)}</div>
              <div class="cv-card-subtitulo">{_escape(subtitulo)}</div>
            </div>
            <div class="cv-trio">
              <div>bruto {_fmt_moeda(valor)}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_pill_a_analisar(resultado):
    """Renderiza cards de 'a analisar': ambíguos + venda sem título + desfeitas."""
    hoje = date.today()

    ambiguos = resultado.a_analisar_ambiguos
    venda_st = resultado.a_analisar_venda_sem_titulo
    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())

    total = 0
    if ambiguos is not None:
        total += len(ambiguos)
    if venda_st is not None:
        total += len(venda_st)
    total += len(ligacoes_desf)

    if total == 0:
        st.markdown(
            f'<div style="background:{AZUL_CARD}; border-radius:10px; padding:20px; text-align:center; color:{TEXTO_MUTED};">'
            f'Nada a analisar nesta rodada. Motor casou tudo que era possível casar.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    max_cards = st.session_state.get("cv_max_cards_a_analisar", 20)
    cards_renderizados = 0
    idx_global = 0

    # 1. Ambíguos primeiro (mais urgente — motor achou candidatas, precisa escolher)
    if ambiguos is not None and not ambiguos.empty:
        for _, venda in ambiguos.iterrows():
            if cards_renderizados >= max_cards:
                break
            _render_card_ambiguo(venda, idx_global)
            cards_renderizados += 1
            idx_global += 1

    # 2. Divergência real (≥ 3 dias sem par)
    if venda_st is not None and not venda_st.empty:
        divergencias = []
        aguardando = []
        for _, venda in venda_st.iterrows():
            status_key, _ = _classificar_venda_sem_titulo(venda, hoje)
            if status_key == "divergencia_real":
                divergencias.append(venda)
            else:
                aguardando.append(venda)

        for venda in divergencias:
            if cards_renderizados >= max_cards:
                break
            _render_card_venda_sem_titulo(venda, idx_global, hoje)
            cards_renderizados += 1
            idx_global += 1

        # 3. Aguardando faturamento (< 3 dias) — cards mais discretos
        for venda in aguardando:
            if cards_renderizados >= max_cards:
                break
            _render_card_venda_sem_titulo(venda, idx_global, hoje)
            cards_renderizados += 1
            idx_global += 1

    if cards_renderizados < total:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"Mostrando {cards_renderizados} de {total} · aumente o limite pra ver mais")
        with col2:
            if st.button("Mostrar +20", key="cv_mais_a_analisar", use_container_width=True):
                st.session_state["cv_max_cards_a_analisar"] = max_cards + 20
                st.rerun()


# ==============================================================================
# RENDERS DE CARDS — AUTO-CONCILIADAS (lista expandível + desfazer)
# ==============================================================================

def _render_card_auto_conciliada(grupo: Dict[str, Any], idx_card: int):
    """Card de uma venda auto-conciliada (pode ter N parcelas)."""
    adq = _label_adquirente(grupo.get("adquirente"))
    ban = _label_bandeira(grupo.get("bandeira"))
    mod = _label_modalidade(grupo.get("modalidade"), grupo.get("parcelas_total"))

    parceiro = grupo.get("nome_parceiro") or "—"
    empresa = grupo.get("empresa") or ""
    empresa_txt = f" · {empresa}" if empresa else ""
    nsu = grupo.get("nsu") or ""
    nsu_txt = f"Nro Único {nsu}" if nsu else ""
    data_venda = grupo.get("data_prev_pagamento")

    parcelas = grupo.get("parcelas", [])
    n_parc = len(parcelas)
    valor_total = grupo.get("valor_total", 0)

    if n_parc > 1:
        status_txt = f"✓ {n_parc} parcelas ligadas"
        parcelas_html_partes = []
        for p in parcelas:
            pa = p.get("parcela_atual")
            pt = p.get("parcelas_total")
            nro_nota = p.get("sk_nro_nota")
            venc = p.get("sk_dt_vencimento")
            vlr = p.get("valor")
            classe = p.get("sk_classe")

            if classe == "adiantamento":
                ref_nf = p.get("sk_ref_nf")
                label_titulo = f'Adiantamento REF NF {ref_nf}' if ref_nf else 'Adiantamento'
            else:
                label_titulo = f'<span class="cv-auto-nf">NF {nro_nota}</span>' if nro_nota else 'Nota'

            parcelas_html_partes.append(f"""
              <div class="cv-auto-parc-linha">
                <span>Parcela {pa}/{pt} → {label_titulo} · venc {_fmt_data_br(venc)}</span>
                <span style="color:{TEXTO_MUTED};">{_fmt_moeda(vlr)}</span>
              </div>
            """)
        parcelas_html = f'<div class="cv-auto-parcelas">{"".join(parcelas_html_partes)}</div>'
    else:
        p = parcelas[0] if parcelas else {}
        nro_nota = p.get("sk_nro_nota")
        venc = p.get("sk_dt_vencimento")
        classe = p.get("sk_classe")
        if classe == "adiantamento":
            ref_nf = p.get("sk_ref_nf")
            label = f'Adiantamento · REF NF {ref_nf} · venc {_fmt_data_br(venc)}' if ref_nf else f'Adiantamento · venc {_fmt_data_br(venc)}'
        else:
            label = f'<span class="cv-auto-nf">NF {nro_nota}</span> · venc {_fmt_data_br(venc)}' if nro_nota else f'Nota · venc {_fmt_data_br(venc)}'
        status_txt = "✓ Ligado"
        parcelas_html = f'<div class="cv-auto-parcelas"><div class="cv-auto-parc-linha"><span>{label}</span><span style="color:{TEXTO_MUTED};">{_fmt_moeda(valor_total)}</span></div></div>'

    linha_info = f"{adq} · {mod} · {ban}"
    if nsu_txt:
        linha_info += f" · {nsu_txt}"
    linha_info += f" · vendido {_fmt_data_br(data_venda)}"

    st.markdown(
        f"""
        <div class="cv-auto-card">
          <div class="cv-auto-card-topo">
            <div>
              <div class="cv-auto-parceiro">{_escape(parceiro)}{_escape(empresa_txt)}</div>
              <div class="cv-auto-info">{_escape(linha_info)}</div>
            </div>
            <div>
              <div class="cv-auto-valor">{_fmt_moeda(valor_total)}</div>
              <div class="cv-auto-status">{status_txt}</div>
            </div>
          </div>
          {parcelas_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Botão de desfazer (fora do markdown pra ser Streamlit real)
    col1, col2 = st.columns([5, 1])
    with col2:
        chave = grupo.get("chave")
        chave_str = "|".join(str(x) for x in chave) if chave else f"idx_{idx_card}"
        if st.button(
            "↺ Desfazer",
            key=f"cv_desf_{idx_card}_{chave_str[:40]}",
            help="Desfazer esta ligação — a venda voltará a 'A analisar'",
            use_container_width=True,
        ):
            _acao_pedir_desfazer(grupo)
            st.rerun()
    st.markdown('<div style="margin-bottom:10px;"></div>', unsafe_allow_html=True)


def _render_pill_auto_conciliadas(resultado):
    """Lista expandível de auto-conciliadas agrupada por venda."""
    df_g1 = resultado.grupo_1_conciliadas
    if df_g1 is None or df_g1.empty:
        st.markdown(
            f'<div style="background:{AZUL_CARD}; border-radius:10px; padding:20px; text-align:center; color:{TEXTO_MUTED};">'
            f'Nenhuma venda auto-conciliada nesta rodada.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())
    grupos = _agrupar_conciliadas_por_venda(df_g1, ligacoes_desf)

    if not grupos:
        st.markdown(
            f'<div style="background:{AZUL_CARD}; border-radius:10px; padding:20px; text-align:center; color:{TEXTO_MUTED};">'
            f'Todas as auto-conciliações foram desfeitas manualmente.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div class="cv-auto-wrapper">
          <div class="cv-auto-header">
            <div class="cv-auto-titulo">{len(grupos)} vendas · agrupadas por venda</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Busca
    col_busca, _ = st.columns([2, 1])
    with col_busca:
        busca = st.text_input(
            "Buscar por parceiro ou nota",
            value=st.session_state.get("cv_busca_auto", ""),
            key="cv_busca_auto_input",
            placeholder="Digite parceiro ou número da NF...",
            label_visibility="collapsed",
        )
        st.session_state["cv_busca_auto"] = busca

    busca_lower = (busca or "").strip().lower()
    if busca_lower:
        grupos_filtrados = []
        for g in grupos:
            parceiro = str(g.get("nome_parceiro") or "").lower()
            if busca_lower in parceiro:
                grupos_filtrados.append(g)
                continue
            # busca em números de NF das parcelas
            for p in g.get("parcelas", []):
                if busca_lower in str(p.get("sk_nro_nota") or "").lower():
                    grupos_filtrados.append(g)
                    break
        grupos = grupos_filtrados

    if not grupos:
        st.caption(f"Nenhum resultado para '{busca}'.")
        return

    # Paginação simples: mostra 20 por vez
    max_mostrar = 20
    grupos_visiveis = grupos[:max_mostrar]

    for i, grupo in enumerate(grupos_visiveis):
        _render_card_auto_conciliada(grupo, i)

    if len(grupos) > max_mostrar:
        st.caption(f"Mostrando {max_mostrar} de {len(grupos)} · use a busca para filtrar")


# ==============================================================================
# RENDERS DE CARDS — COMPENSADAS / AGUARDANDO / DEVOLUÇÕES
# ==============================================================================

def _render_pill_compensadas(resultado):
    """Grupo 2: vendas já baixadas por cartão (TOP 1722). Auditoria."""
    df_g2 = resultado.grupo_2_ja_baixadas
    if df_g2 is None or df_g2.empty:
        st.markdown(
            f'<div style="background:{AZUL_CARD}; border-radius:10px; padding:20px; text-align:center; color:{TEXTO_MUTED};">'
            f'Nenhuma venda compensada nesta rodada.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())
    grupos = _agrupar_conciliadas_por_venda(df_g2, ligacoes_desf)

    st.markdown(
        f"""
        <div class="cv-auto-wrapper">
          <div class="cv-auto-header">
            <div class="cv-auto-titulo">{len(grupos)} vendas já baixadas por cartão (TOP 1722) · auditoria</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for i, grupo in enumerate(grupos[:20]):
        _render_card_auto_conciliada(grupo, i + 5000)

    if len(grupos) > 20:
        st.caption(f"Mostrando 20 de {len(grupos)}")


def _render_pill_aguardando(resultado):
    """Grupo 3: títulos Sankhya em aberto sem venda casando (aguardando captura)."""
    df_g3 = resultado.grupo_3_aguardando
    if df_g3 is None or df_g3.empty:
        st.markdown(
            f'<div style="background:{AZUL_CARD}; border-radius:10px; padding:20px; text-align:center; color:{TEXTO_MUTED};">'
            f'Nenhum título aguardando captura nesta rodada.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    total = len(df_g3)
    total_valor = float(df_g3["vlr_desdobramento"].sum()) if "vlr_desdobramento" in df_g3.columns else 0.0

    st.markdown(
        f"""
        <div class="cv-auto-wrapper">
          <div class="cv-auto-header">
            <div class="cv-auto-titulo">{total} títulos aguardando captura · {_fmt_moeda(total_valor)} em aberto</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for i, (_, tit) in enumerate(df_g3.head(20).iterrows()):
        classe = tit.get("classe")
        if classe == "adiantamento":
            tipo_label = "Adiantamento"
            ref_nf = tit.get("nro_nota_referenciada")
            id_titulo = f"REF NF {ref_nf}" if ref_nf else "sem REF NF"
        else:
            tipo_label = "Nota fiscal"
            id_titulo = f"NF {tit.get('nro_nota')}" if tit.get("nro_nota") else "sem número"

        parceiro = tit.get("nome_parceiro") or "—"
        valor = tit.get("vlr_desdobramento")
        venc = tit.get("dt_vencimento")
        adq_inf = tit.get("adquirente_sankhya")
        adq_txt = f" · {_label_adquirente(adq_inf)}" if adq_inf else ""

        st.markdown(
            f"""
            <div class="cv-auto-card">
              <div class="cv-auto-card-topo">
                <div>
                  <div class="cv-auto-parceiro">{_escape(parceiro)}</div>
                  <div class="cv-auto-info">{_escape(tipo_label)} · {_escape(id_titulo)}{_escape(adq_txt)} · venc {_fmt_data_br(venc)}</div>
                </div>
                <div>
                  <div class="cv-auto-valor">{_fmt_moeda(valor)}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if total > 20:
        st.caption(f"Mostrando 20 de {total}")


def _render_pill_devolucoes(resultado):
    """Grupo 4: cancelamentos/devoluções."""
    df_g4 = resultado.grupo_4_devolucoes
    if df_g4 is None or df_g4.empty:
        st.markdown(
            f'<div style="background:{AZUL_CARD}; border-radius:10px; padding:20px; text-align:center; color:{TEXTO_MUTED};">'
            f'Nenhuma devolução nesta rodada.'
            f'</div>',
            unsafe_allow_html=True,
        )
        return

    total = len(df_g4)
    st.markdown(
        f"""
        <div class="cv-auto-wrapper">
          <div class="cv-auto-header">
            <div class="cv-auto-titulo">{total} devoluções / cancelamentos</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for i, (_, dev) in enumerate(df_g4.head(20).iterrows()):
        adq = _label_adquirente(dev.get("adquirente"))
        valor = dev.get("valor_match")
        data = dev.get("data_prev_pagamento")

        st.markdown(
            f"""
            <div class="cv-auto-card">
              <div class="cv-auto-card-topo">
                <div>
                  <div class="cv-auto-parceiro">Devolução {_escape(adq)}</div>
                  <div class="cv-auto-info">Vendido {_fmt_data_br(data)}</div>
                </div>
                <div>
                  <div class="cv-auto-valor">{_fmt_moeda(valor)}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if total > 20:
        st.caption(f"Mostrando 20 de {total}")


# ==============================================================================
# AÇÕES (mutações de estado)
# ==============================================================================

def _acao_escolher_candidata(chave_venda_str: str, candidato_dict: Dict[str, Any]):
    """Débora escolheu uma candidata pra uma venda ambígua."""
    st.session_state["cv_confirmadas_manual"][chave_venda_str] = {
        "sk_idx": candidato_dict.get("idx_sankhya"),
        "sk_nro_nota": candidato_dict.get("nro_nota"),
        "sk_classe": candidato_dict.get("classe"),
        "sk_nome_parceiro": candidato_dict.get("nome_parceiro"),
        "sk_vlr_desdobramento": candidato_dict.get("vlr_desdobramento"),
        "sk_dt_vencimento": candidato_dict.get("dt_vencimento"),
    }
    st.session_state["cv_historico"].append({
        "acao": "escolher_candidata",
        "chave_venda": chave_venda_str,
        "sk_nro_nota": candidato_dict.get("nro_nota"),
        "sk_classe": candidato_dict.get("classe"),
        "quando": datetime.now().isoformat(timespec="seconds"),
    })


def _acao_pedir_desfazer(grupo: Dict[str, Any]):
    """Registra que uma confirmação de desfazer está pendente."""
    st.session_state["cv_desfazer_pendente"] = {
        "chave": grupo.get("chave"),
        "nome_parceiro": grupo.get("nome_parceiro"),
        "adquirente": grupo.get("adquirente"),
        "valor_total": grupo.get("valor_total"),
        "n_parcelas": len(grupo.get("parcelas", [])),
    }


def _acao_confirmar_desfazer():
    """Confirma desfazer: adiciona chave em ligacoes_desfeitas."""
    pend = st.session_state.get("cv_desfazer_pendente")
    if not pend:
        return
    chave = pend.get("chave")
    if chave:
        st.session_state["cv_ligacoes_desfeitas"].add(chave)
        st.session_state["cv_historico"].append({
            "acao": "desfazer_ligacao",
            "chave_venda": "|".join(str(x) for x in chave),
            "nome_parceiro": pend.get("nome_parceiro"),
            "adquirente": pend.get("adquirente"),
            "valor_total": pend.get("valor_total"),
            "n_parcelas": pend.get("n_parcelas"),
            "quando": datetime.now().isoformat(timespec="seconds"),
        })
    st.session_state["cv_desfazer_pendente"] = None


def _acao_cancelar_desfazer():
    st.session_state["cv_desfazer_pendente"] = None


# ==============================================================================
# CONFIRMAÇÃO DE DESFAZER (banner destacado)
# ==============================================================================

def _render_confirmacao_desfazer():
    """Se houver desfazer pendente, mostra banner de confirmação no topo do corpo."""
    pend = st.session_state.get("cv_desfazer_pendente")
    if not pend:
        return

    parceiro = pend.get("nome_parceiro") or "essa venda"
    adq = _label_adquirente(pend.get("adquirente"))
    valor = pend.get("valor_total")
    n_parc = pend.get("n_parcelas", 1)
    parcelas_txt = f"{n_parc} parcelas voltarão" if n_parc > 1 else "A venda voltará"

    st.markdown(
        f"""
        <div class="cv-confirmacao">
          <div class="cv-confirmacao-titulo">Desfazer ligação de {_escape(parceiro)}?</div>
          <div class="cv-confirmacao-descr">
            {_escape(adq)} · {_fmt_moeda(valor)} · {_escape(parcelas_txt)} a "A analisar" e os títulos do Sankhya voltarão pra pool de candidatas.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1, 3])
    with col1:
        if st.button("Confirmar desfazer", key="cv_confirmar_desfazer", type="primary", use_container_width=True):
            _acao_confirmar_desfazer()
            st.rerun()
    with col2:
        if st.button("Cancelar", key="cv_cancelar_desfazer", use_container_width=True):
            _acao_cancelar_desfazer()
            st.rerun()


# ==============================================================================
# EXPORTAR EXCEL
# ==============================================================================

def _render_rodape_exportar(resultado, contadores):
    """Botão de exportar Excel + info de auditoria."""
    n_desf = len(st.session_state.get("cv_ligacoes_desfeitas", set()))
    n_conf = len(st.session_state.get("cv_confirmadas_manual", {}))
    total_hist = len(st.session_state.get("cv_historico", []))

    info_txt = f"Rodada com {contadores['auto_conciliadas']} auto-conciliadas · {n_conf} confirmadas manualmente · {n_desf} ligações desfeitas · {total_hist} ações no histórico"

    st.markdown(f'<div class="cv-rodape-info" style="margin-top:16px; margin-bottom:8px;">{_escape(info_txt)}</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        if _EXCEL_DISPONIVEL:
            try:
                excel_bytes = vendas_excel.gerar_excel(
                    resultado=resultado,
                    confirmadas_manual=st.session_state.get("cv_confirmadas_manual", {}),
                    ligacoes_desfeitas=st.session_state.get("cv_ligacoes_desfeitas", set()),
                    historico=st.session_state.get("cv_historico", []),
                    contadores=contadores,
                    df_cielo=st.session_state.get("cv_df_cielo"),
                    df_getnet=st.session_state.get("cv_df_getnet_vendas"),
                    df_sankhya=st.session_state.get("cv_df_sankhya"),
                    tolerancia_dias=st.session_state.get("cv_tolerancia_dias", 2),
                )
                nome_arq = f"conciliacao_vendas_{date.today().strftime('%Y%m%d')}.xlsx"
                st.download_button(
                    "⬇  Exportar Excel (8 abas)",
                    data=excel_bytes,
                    file_name=nome_arq,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="cv_baixar_excel",
                    type="primary",
                    use_container_width=True,
                )
            except Exception as e:
                st.error(f"Falha ao gerar Excel: {e}")
        else:
            st.warning("Módulo de exportação Excel indisponível — verifique se src/relatorios/vendas_excel.py existe.")

    with col2:
        if st.button("↺  Nova rodada", key="cv_nova_rodada", use_container_width=True):
            _limpar_estado_completo()
            st.rerun()

    with col3:
        if st.button("🔄  Reprocessar", key="cv_reprocessar_motor", help="Rodar motor novamente com os arquivos atuais", use_container_width=True):
            _limpar_estado_motor()
            _rodar_motor()
            st.rerun()


# ==============================================================================
# TELA COMPLETA DE RESULTADO
# ==============================================================================

def _render_tela_resultado():
    """Renderiza a tela completa de resultado (Painel Executivo · Opção A)."""
    resultado = st.session_state.get("cv_motor_resultado")
    if resultado is None:
        return

    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())
    contadores = _calcular_contadores_pills(resultado, ligacoes_desf)

    # Topo: balanço + KPIs por adquirente
    _render_topo_resultado(resultado, contadores)

    # Confirmação de desfazer (se houver) — aparece antes das pills
    _render_confirmacao_desfazer()

    # Pills (5 botões clicáveis)
    _render_pills(contadores)

    # Corpo condicional pela pill ativa
    pill_ativa = st.session_state.get("cv_pill_ativa", "a_analisar")
    if pill_ativa == "a_analisar":
        _render_pill_a_analisar(resultado)
    elif pill_ativa == "auto_conciliadas":
        _render_pill_auto_conciliadas(resultado)
    elif pill_ativa == "compensadas":
        _render_pill_compensadas(resultado)
    elif pill_ativa == "aguardando":
        _render_pill_aguardando(resultado)
    elif pill_ativa == "devolucoes":
        _render_pill_devolucoes(resultado)

    # Rodapé com exportar
    _render_rodape_exportar(resultado, contadores)


# ==============================================================================
# FUNÇÃO PRINCIPAL DE RENDER (chamada pelo app.py)
# ==============================================================================

def render_conciliacao_vendas():
    """Ponto de entrada da página."""
    _garantir_estado_inicial()

    # CSS
    st.markdown(_CSS, unsafe_allow_html=True)

    # Header
    _render_header()

    # ---- Se já rodou o motor, mostra a tela de resultado ----
    if st.session_state.get("cv_motor_resultado") is not None:
        _render_tela_resultado()
        return

    # ---- Caso contrário, mostra o fluxo de importação ----
    _render_aviso()

    st.markdown('<div class="cv-secao-titulo">Enviar arquivos</div>', unsafe_allow_html=True)

    nonce = st.session_state["cv_uploader_nonce"]
    arquivos = st.file_uploader(
        "Arraste os arquivos aqui  ·  Financeiro Sankhya · Cielo Recebíveis · Getnet Recebíveis Completos",
        type=["xls", "xlsx"],
        accept_multiple_files=True,
        key=f"cv_uploader_{nonce}",
        label_visibility="visible",
    )

    if arquivos:
        _absorver_uploads(arquivos)

    uploads = st.session_state["cv_uploads"]

    if uploads:
        st.markdown('<div class="cv-secao-titulo">Fila de arquivos</div>', unsafe_allow_html=True)
        for nome, entry in uploads.items():
            _render_card_arquivo(nome, entry)

        st.write("")
        col_processar, col_limpar = st.columns([3, 1])
        with col_processar:
            processar_clicado = st.button(
                "▶  Processar arquivos",
                key="cv_btn_processar",
                type="primary",
                use_container_width=True,
            )
        with col_limpar:
            limpar_clicado = st.button(
                "↻  Limpar fila",
                key="cv_btn_limpar",
                use_container_width=True,
            )

        if limpar_clicado:
            _limpar_estado_completo()
            st.rerun()

        if processar_clicado:
            with st.spinner("Lendo arquivos..."):
                _processar_arquivos()
            st.rerun()
    else:
        st.info("Nenhum arquivo na fila. Envie o Financeiro do Sankhya, o Recebíveis da Cielo e o Recebíveis Completos da Getnet.")

    # KPIs de importação (se processou)
    if st.session_state.get("cv_processado") and st.session_state.get("cv_resumo"):
        _render_kpis_importacao()

        # Botão para iniciar conciliação
        st.markdown('<div class="cv-secao-titulo">Iniciar conciliação</div>', unsafe_allow_html=True)

        col_config, col_rodar = st.columns([1, 3])
        with col_config:
            tol = st.number_input(
                "Tolerância de data (dias)",
                min_value=0, max_value=30,
                value=int(st.session_state.get("cv_tolerancia_dias", 2)),
                key="cv_tol_input",
                help="Janela de tolerância entre data prevista de pagamento (adquirente) e vencimento do título (Sankhya). Padrão 2 dias.",
            )
            st.session_state["cv_tolerancia_dias"] = int(tol)

        with col_rodar:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)  # alinhar com o input
            if st.button(
                "▶  Rodar motor de conciliação",
                key="cv_rodar_motor",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner("Cruzando vendas × títulos..."):
                    erro = _rodar_motor()
                if erro:
                    st.error(erro)
                else:
                    st.rerun()
