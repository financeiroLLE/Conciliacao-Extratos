# -*- coding: utf-8 -*-
"""
Página: Conciliação de Vendas — MVP-A · Fase 4 (motor integrado · visual v2).

Esta versão segue o padrão visual das demais telas do app:
    - Fundo navy do app (imutável)
    - Cards em creme (#FFF6C8) ou branco (#FFFFFF) com texto navy
    - Faixas coloridas laterais para categorização (amarelo=analisar, verde=ok,
      laranja=divergência, cinza=informativo)
    - Títulos de seção em amarelo caixa-alta pequeno

Escopo:
    1. IMPORTAÇÃO de arquivos (Fase 3 · mantida)
    2. CONCILIAÇÃO (Fase 4 · motor + tela Painel Executivo)
    3. AÇÕES manuais (escolher candidata, desfazer com confirmação)
    4. EXPORTAÇÃO Excel (8 abas)

Estados guardados na sessão (namespace cv_*): ver _SESSION_KEYS_*.

Regras invioláveis observadas:
    - Zero falso positivo: motor nunca escolhe entre candidatas
    - Additive-only: nada tocado fora desta página
    - Confirmação antes de desfazer
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

from src.motor_vendas import motor as motor_vendas
from src.motor_vendas import classificador_sankhya

try:
    from src.reports import vendas_excel
    _EXCEL_DISPONIVEL = True
except ImportError:
    _EXCEL_DISPONIVEL = False


# ==============================================================================
# CORES CANÔNICAS LLE — padrão claro
# ==============================================================================

# Navy institucional (fundo do app, headers)
AZUL_NAVY = "#0A1730"
AZUL_NAVY_SUAVE = "#1A2540"

# Amarelo LLE
AMARELO = "#FFCC00"
AMARELO_ESCURO = "#E5B800"

# Cremes e brancos (fundo dos cards)
CREME = "#FFF6C8"
CREME_ESCURO = "#F5EBB2"
BRANCO = "#FFFFFF"
CINZA_CLARO = "#F5F5F5"

# Cores semânticas de faixas laterais
VERDE = "#2E7D4F"
LARANJA = "#D97706"
VERMELHO = "#A32D2D"
CINZA_INFO = "#6B7280"

# Fundos de tag
VERMELHO_FUNDO = "#FCEBEB"
VERDE_FUNDO = "#E8F5EC"
LARANJA_FUNDO = "#FFF0E0"

# Texto
TEXTO_NAVY = "#0A1730"
TEXTO_MUTED = "#5A6478"
TEXTO_MUTED_CLARO = "#8A93A8"


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

/* -------- AVISO -------- */
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

/* -------- TÍTULOS DE SEÇÃO -------- */
.cv-secao-titulo {{
    font-size: 12px; font-weight: 700; letter-spacing: 1.5px;
    color: {AMARELO} !important; text-transform: uppercase;
    margin: 20px 0 12px 0;
}}
.cv-secao-titulo-navy {{
    font-size: 11px; font-weight: 700; letter-spacing: 1.2px;
    color: {TEXTO_MUTED} !important; text-transform: uppercase;
    margin: 0 0 10px 0;
}}

/* -------- FILA DE ARQUIVOS -------- */
.cv-fila-card {{
    background: {BRANCO} !important;
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

/* -------- KPI de IMPORTAÇÃO (creme) -------- */
.cv-kpi {{ background: {CREME} !important; border-radius: 10px; padding: 14px 12px; text-align: center; }}
.cv-kpi-label      {{ font-size: 10px; letter-spacing: 0.5px; color: {AZUL_NAVY} !important; text-transform: uppercase; opacity: 0.7; margin-bottom: 6px; }}
.cv-kpi-valor      {{ font-size: 22px; font-weight: 600; color: {AZUL_NAVY} !important; line-height: 1.1; }}
.cv-kpi-secundario {{ font-size: 10px; color: {AZUL_NAVY} !important; opacity: 0.6; margin-top: 4px; }}

/* -------- RESULTADO — CABEÇALHO DA RODADA -------- */
.cv-rodada-header {{ margin-bottom: 14px; }}
.cv-rodada-supra  {{ font-size: 11px; color: {AMARELO}; letter-spacing: 1.2px; text-transform: uppercase; margin-bottom: 4px; }}
.cv-rodada-titulo {{ font-size: 18px; font-weight: 500; color: {CREME}; }}

/* -------- RESULTADO — BALANÇO (cards creme) -------- */
.cv-balanco-card {{
    background: {CREME}; border-radius: 10px; padding: 16px 18px;
}}
.cv-balanco-card-destaque {{ border-left: 4px solid {AMARELO_ESCURO}; }}
.cv-balanco-label {{ font-size: 10px; color: {TEXTO_MUTED}; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; font-weight: 600; }}
.cv-balanco-valor {{ font-size: 24px; font-weight: 600; color: {AZUL_NAVY}; }}
.cv-balanco-sub   {{ font-size: 12px; color: {TEXTO_MUTED}; margin-top: 4px; }}
.cv-balanco-ok    {{ color: {VERDE}; font-weight: 600; }}
.cv-balanco-diff  {{ color: {LARANJA}; font-weight: 600; }}

/* -------- RESULTADO — BARRAS POR ADQUIRENTE -------- */
.cv-adq-bloco {{
    background: {CREME}; border-radius: 10px; padding: 16px 18px; margin-top: 10px;
}}
.cv-adq-titulo {{ font-size: 10px; color: {TEXTO_MUTED}; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; font-weight: 600; }}
.cv-adq-linha  {{ margin-bottom: 10px; }}
.cv-adq-linha:last-child {{ margin-bottom: 0; }}
.cv-adq-linha-topo {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
.cv-adq-nome  {{ font-size: 13px; color: {AZUL_NAVY}; font-weight: 500; }}
.cv-adq-info  {{ font-size: 12px; color: {TEXTO_MUTED}; }}
.cv-adq-pct   {{ color: {AZUL_NAVY}; font-weight: 700; }}
.cv-adq-barra {{ height: 8px; background: {CREME_ESCURO}; border-radius: 4px; overflow: hidden; }}
.cv-adq-barra-preenchida {{ height: 100%; background: {AMARELO_ESCURO}; }}

/* -------- CARDS DE A ANALISAR / RESULTADO -------- */
.cv-card {{
    background: {BRANCO}; border-radius: 10px;
    padding: 14px 16px; margin-bottom: 10px;
    border-left: 4px solid {AMARELO};
    box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}}
.cv-card-divergencia {{ border-left-color: {LARANJA}; }}
.cv-card-info       {{ border-left-color: {CINZA_INFO}; }}
.cv-card-sucesso    {{ border-left-color: {VERDE}; }}

.cv-card-topo {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; gap: 10px; }}

.cv-tag-linha {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; align-items: center; }}
.cv-tag {{
    background: {AZUL_NAVY}; color: {CREME};
    font-size: 9px; padding: 3px 7px; border-radius: 4px;
    text-transform: uppercase; letter-spacing: 0.6px; font-weight: 500;
}}
.cv-tag-amarelo  {{ background: {AMARELO}; color: {AZUL_NAVY}; }}
.cv-tag-laranja  {{ background: {LARANJA_FUNDO}; color: {LARANJA}; font-weight: 600; }}
.cv-tag-verde    {{ background: {VERDE_FUNDO}; color: {VERDE}; font-weight: 600; }}
.cv-tag-adq      {{ background: {AZUL_NAVY_SUAVE}; color: {AMARELO}; }}

.cv-card-titulo {{ font-size: 15px; color: {AZUL_NAVY}; font-weight: 600; }}
.cv-card-sub    {{ font-size: 12px; color: {TEXTO_MUTED}; margin-top: 2px; }}

.cv-valor-dir  {{ text-align: right; }}
.cv-valor-grande {{ font-size: 17px; font-weight: 600; color: {AZUL_NAVY}; }}
.cv-valor-sub    {{ font-size: 10px; color: {TEXTO_MUTED}; }}

/* -------- TIMELINE (dentro dos cards claros) -------- */
.cv-timeline {{ display: flex; align-items: center; gap: 8px; margin: 10px 0 4px 0; }}
.cv-timeline-passo {{ flex: 1; display: flex; flex-direction: column; align-items: center; }}
.cv-timeline-linha {{ flex: 1; height: 2px; }}
.cv-timeline-linha-ok  {{ background: {AZUL_NAVY_SUAVE}; opacity: 0.4; }}
.cv-timeline-linha-off {{ background: {CINZA_CLARO}; }}
.cv-timeline-bolinha {{ width: 12px; height: 12px; border-radius: 50%; }}
.cv-timeline-bolinha-feito    {{ background: {VERDE}; }}
.cv-timeline-bolinha-atual    {{ background: {AMARELO_ESCURO}; }}
.cv-timeline-bolinha-pendente {{ background: {BRANCO}; border: 2px solid {CINZA_INFO}; }}
.cv-timeline-data  {{ color: {AZUL_NAVY}; margin-top: 4px; font-size: 10px; font-weight: 600; }}
.cv-timeline-label {{ color: {TEXTO_MUTED}; font-size: 10px; }}

/* -------- CANDIDATAS -------- */
.cv-candidatas-wrapper {{
    background: {CINZA_CLARO}; border-radius: 6px;
    padding: 10px 12px; font-size: 12px; color: {AZUL_NAVY};
    margin-top: 8px;
}}
.cv-candidatas-header {{
    color: {TEXTO_MUTED}; font-size: 10px;
    text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; font-weight: 600;
}}
.cv-candidata-linha {{ padding: 4px 0; color: {AZUL_NAVY}; }}
.cv-candidata-tag-nf   {{ background: {VERDE_FUNDO}; color: {VERDE}; font-size: 9px; padding: 2px 6px; border-radius: 3px; margin-right: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }}
.cv-candidata-tag-adi  {{ background: {LARANJA_FUNDO}; color: {LARANJA}; font-size: 9px; padding: 2px 6px; border-radius: 3px; margin-right: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }}

/* -------- AUTO-CONCILIADAS -------- */
.cv-secao-wrapper {{
    background: {CREME}; border-radius: 10px;
    padding: 14px 16px; margin-bottom: 12px;
}}
.cv-secao-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }}
.cv-secao-header-titulo {{ font-size: 11px; color: {TEXTO_MUTED}; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; }}

.cv-parcelas-lista {{ margin-top: 8px; padding-left: 12px; border-left: 2px solid {VERDE}; }}
.cv-parc-linha {{ display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; color: {AZUL_NAVY}; }}
.cv-parc-nf {{ color: {AZUL_NAVY}; font-weight: 600; }}

.cv-empty-state {{
    background: {CREME}; border-radius: 10px;
    padding: 24px 20px; text-align: center;
    color: {TEXTO_MUTED}; font-size: 13px;
}}

/* -------- CONFIRMAÇÃO DE DESFAZER -------- */
.cv-confirmacao {{
    background: {CREME} !important;
    border: 2px solid {AMARELO_ESCURO};
    border-radius: 12px; padding: 16px 20px; margin-bottom: 14px;
}}
.cv-confirmacao, .cv-confirmacao * {{ color: {AZUL_NAVY} !important; }}
.cv-confirmacao-titulo {{ font-size: 14px; color: {AZUL_NAVY} !important; font-weight: 700; margin-bottom: 4px; }}
.cv-confirmacao-descr  {{ font-size: 13px; color: {AZUL_NAVY} !important; margin-bottom: 10px; }}

/* -------- RODAPÉ -------- */
.cv-rodape-info {{
    font-size: 11px; color: {CREME}; opacity: 0.75;
    text-align: center; margin: 12px 0 8px 0;
}}
</style>
"""


# ==============================================================================
# HELPERS DE FORMATAÇÃO
# ==============================================================================

def _fmt_moeda(v: Any) -> str:
    try:
        s = f"{float(v):,.2f}"
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def _fmt_data_br(d: Any) -> str:
    if d is None:
        return "—"
    try:
        if isinstance(d, (date, datetime)):
            return d.strftime("%d/%m/%Y")
        return pd.to_datetime(d).strftime("%d/%m/%Y")
    except Exception:
        return "—"


def _fmt_data_curta(d: Any) -> str:
    if d is None:
        return "—"
    try:
        if isinstance(d, (date, datetime)):
            return d.strftime("%d/%m")
        return pd.to_datetime(d).strftime("%d/%m")
    except Exception:
        return "—"


def _escape(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _label_bandeira(b: Any) -> str:
    if b is None:
        return "—"
    s = str(b).strip().lower()
    if not s or s in ("none", "nan"):
        return "—"
    mapa = {
        "visa": "Visa", "master": "Master", "elo": "Elo",
        "vis_mas": "Vis/Mas", "mas_elo": "Mas/Elo",
        "hipercard": "Hipercard", "amex": "Amex",
    }
    return mapa.get(s, s.upper())


def _label_modalidade(m: Any, parcelas: Any = None) -> str:
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
    if a is None:
        return "—"
    s = str(a).strip().lower()
    mapa = {"getnet": "Getnet", "cielo": "Cielo", "pagseguro": "PagSeguro", "pagbank": "PagBank"}
    return mapa.get(s, s.capitalize())


# ==============================================================================
# ESTADO DA SESSÃO
# ==============================================================================

_SESSION_KEYS_IMPORTACAO = [
    "cv_uploads", "cv_processado",
    "cv_df_sankhya", "cv_df_cielo", "cv_df_getnet_vendas", "cv_df_getnet_repasses",
    "cv_resumo", "cv_uploader_nonce",
]

_SESSION_KEYS_MOTOR = [
    "cv_motor_resultado", "cv_df_sankhya_classificado", "cv_pill_ativa",
    "cv_confirmadas_manual", "cv_desfazer_pendente", "cv_ligacoes_desfeitas",
    "cv_historico", "cv_tolerancia_dias",
    "cv_busca_auto", "cv_max_cards_a_analisar",
    "cv_busca_aberta", "cv_busca_texto",
]


def _garantir_estado_inicial():
    st.session_state.setdefault("cv_uploads", {})
    st.session_state.setdefault("cv_processado", False)
    st.session_state.setdefault("cv_df_sankhya", None)
    st.session_state.setdefault("cv_df_cielo", None)
    st.session_state.setdefault("cv_df_getnet_vendas", None)
    st.session_state.setdefault("cv_df_getnet_repasses", None)
    st.session_state.setdefault("cv_resumo", {})
    st.session_state.setdefault("cv_uploader_nonce", 0)
    st.session_state.setdefault("cv_motor_resultado", None)
    st.session_state.setdefault("cv_df_sankhya_classificado", None)
    st.session_state.setdefault("cv_pill_ativa", "a_analisar")
    st.session_state.setdefault("cv_busca_aberta", {})
    st.session_state.setdefault("cv_busca_texto", {})
    st.session_state.setdefault("cv_confirmadas_manual", {})
    st.session_state.setdefault("cv_desfazer_pendente", None)
    st.session_state.setdefault("cv_ligacoes_desfeitas", set())
    st.session_state.setdefault("cv_historico", [])
    st.session_state.setdefault("cv_tolerancia_dias", 2)
    st.session_state.setdefault("cv_busca_auto", "")
    st.session_state.setdefault("cv_max_cards_a_analisar", 20)


def _limpar_estado_completo():
    for k in _SESSION_KEYS_IMPORTACAO + _SESSION_KEYS_MOTOR:
        if k == "cv_uploader_nonce":
            st.session_state[k] = st.session_state.get(k, 0) + 1
        elif k == "cv_uploads":
            st.session_state[k] = {}
        elif k == "cv_processado":
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
    st.session_state["cv_motor_resultado"] = None
    st.session_state["cv_df_sankhya_classificado"] = None
    st.session_state["cv_pill_ativa"] = "a_analisar"
    st.session_state["cv_confirmadas_manual"] = {}
    st.session_state["cv_desfazer_pendente"] = None
    st.session_state["cv_ligacoes_desfeitas"] = set()
    st.session_state["cv_historico"] = []
    st.session_state["cv_busca_auto"] = ""
    st.session_state["cv_max_cards_a_analisar"] = 20
    st.session_state["cv_busca_aberta"] = {}
    st.session_state["cv_busca_texto"] = {}


# ==============================================================================
# ABSORVER UPLOADS (COM BUG FIX)
# ==============================================================================

def _absorver_uploads(arquivos):
    """FIX v6.1: só zera cv_processado se realmente teve arquivo novo."""
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

    if houve_novo:
        st.session_state["cv_processado"] = False
        _limpar_estado_motor()


# ==============================================================================
# PROCESSAR ARQUIVOS
# ==============================================================================

def _processar_arquivos():
    uploads = st.session_state["cv_uploads"]
    if not uploads:
        return

    df_sankhya_lista: List[pd.DataFrame] = []
    df_cielo_lista: List[pd.DataFrame] = []
    df_getnet_vendas_lista: List[pd.DataFrame] = []
    df_getnet_repasses_lista: List[pd.DataFrame] = []

    resumo = {
        "sankhya_linhas": 0, "sankhya_top_1722": 0, "sankhya_top_0": 0,
        "sankhya_compensadas": 0, "sankhya_empresas": set(),
        "cielo_vendas": 0, "cielo_bruto": 0.0, "cielo_liquido": 0.0,
        "getnet_vendas": 0, "getnet_cancelamentos": 0, "getnet_repasses": 0,
        "getnet_liquido": 0.0, "getnet_repassado": 0.0,
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
    _limpar_estado_motor()


# ==============================================================================
# RODAR MOTOR
# ==============================================================================

def _rodar_motor():
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
        st.session_state["cv_df_sankhya_classificado"] = None
        return f"Erro ao rodar motor: {e}"

    st.session_state["cv_motor_resultado"] = resultado
    st.session_state["cv_df_sankhya_classificado"] = df_sk_classificado
    return None


# ==============================================================================
# HELPERS DE BUSCA MANUAL
# ==============================================================================

def _get_series(row: pd.Series, col: str, default=None):
    """Retorna valor da coluna se existir e não for NaN; senão default."""
    if col not in row.index:
        return default
    v = row[col]
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    return v


def _puxar_valores_originais(venda: pd.Series) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Puxa (bruto, taxa_pct, liquido) do DataFrame original (Cielo ou Getnet).
    Retorna (None, None, None) se não encontrar.

    Tenta múltiplos nomes de coluna comuns dos parsers.
    """
    tipo = venda.get("origem_tipo")
    idx = venda.get("origem_venda")

    if tipo == "cielo":
        df = st.session_state.get("cv_df_cielo")
    elif tipo == "getnet":
        df = st.session_state.get("cv_df_getnet_vendas")
    else:
        return (None, None, None)

    if df is None or idx is None:
        return (None, None, None)

    try:
        row = df.loc[idx]
    except (KeyError, IndexError):
        return (None, None, None)

    # Bruto: tenta várias colunas
    bruto = None
    for col in ("valor_bruto", "valor_parcela_bruto", "vlr_bruto"):
        v = _get_series(row, col)
        if v is not None:
            bruto = float(v)
            break

    # Líquido
    liquido = None
    for col in ("valor_liquido", "valor_parcela_liquido", "vlr_liquido", "valor_liq"):
        v = _get_series(row, col)
        if v is not None:
            liquido = float(v)
            break

    # Taxa em % (procurar campo pct)
    taxa_pct = None
    for col in ("taxa_pct", "percentual_taxa", "pct_taxa", "taxa_percentual"):
        v = _get_series(row, col)
        if v is not None:
            try:
                taxa_pct = float(v)
                break
            except (ValueError, TypeError):
                continue

    # Se não achou taxa%, tenta calcular a partir de bruto/líquido
    if taxa_pct is None and bruto and liquido and bruto > 0:
        diff = bruto - liquido
        if 0 <= diff <= bruto * 0.15:  # taxa razoável até 15%
            taxa_pct = (diff / bruto) * 100

    return (bruto, taxa_pct, liquido)


def _buscar_titulos_em_aberto(texto_busca: str, valor_venda: Optional[float] = None,
                              limite: int = 15) -> List[Dict[str, Any]]:
    """
    Busca títulos do Sankhya EM ABERTO por texto (parceiro/NF/valor).

    Se texto_busca vazio E valor_venda dado, retorna os com valor mais próximo.
    Se texto_busca dado, filtra por match textual.
    """
    df = st.session_state.get("cv_df_sankhya_classificado")
    if df is None or df.empty:
        return []

    df_abertos = df[df["situacao"] == "em_aberto"].copy()
    if df_abertos.empty:
        return []

    texto = (texto_busca or "").strip().lower()

    if texto:
        # Match textual em parceiro, NF, valor
        mask = pd.Series(False, index=df_abertos.index)

        # Parceiro
        if "nome_parceiro" in df_abertos.columns:
            mask = mask | df_abertos["nome_parceiro"].astype(str).str.lower().str.contains(texto, na=False)

        # NF
        if "nro_nota" in df_abertos.columns:
            mask = mask | df_abertos["nro_nota"].astype(str).str.lower().str.contains(texto, na=False)

        # Valor: tenta parsear texto como número
        try:
            texto_num = float(texto.replace(",", ".").replace("r$", "").replace(" ", ""))
            if "vlr_desdobramento" in df_abertos.columns:
                mask = mask | (df_abertos["vlr_desdobramento"].round(2) == round(texto_num, 2))
        except ValueError:
            pass

        # NF referenciada (adiantamento)
        if "nro_nota_referenciada" in df_abertos.columns:
            mask = mask | df_abertos["nro_nota_referenciada"].astype(str).str.lower().str.contains(texto, na=False)

        df_filt = df_abertos[mask]
    else:
        df_filt = df_abertos

    # Se tem valor de referência, ordena por proximidade
    if valor_venda is not None and "vlr_desdobramento" in df_filt.columns:
        df_filt = df_filt.copy()
        df_filt["_dist"] = (df_filt["vlr_desdobramento"] - valor_venda).abs()
        df_filt = df_filt.sort_values("_dist").head(limite)
        df_filt = df_filt.drop(columns=["_dist"])
    else:
        df_filt = df_filt.head(limite)

    # Retorna como lista de dicts
    resultados = []
    for _, row in df_filt.iterrows():
        resultados.append({
            "sk_idx": row.name,
            "sk_nro_nota": row.get("nro_nota"),
            "sk_nro_unico": row.get("nro_unico"),
            "sk_classe": row.get("classe"),
            "sk_nome_parceiro": row.get("nome_parceiro"),
            "sk_empresa_nome": row.get("empresa_nome"),
            "sk_vlr_desdobramento": row.get("vlr_desdobramento"),
            "sk_dt_vencimento": row.get("dt_vencimento"),
            "sk_ref_nf": row.get("nro_nota_referenciada"),
            "sk_historico": row.get("historico"),
        })
    return resultados


# ==============================================================================
# HELPERS DE ANÁLISE
# ==============================================================================

def _chave_venda_original(row: pd.Series) -> Tuple[str, str, str]:
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


def _agrupar_conciliadas_por_venda(df_g1: pd.DataFrame, ligacoes_desfeitas: set) -> List[Dict[str, Any]]:
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

    for g in grupos.values():
        g["parcelas"].sort(key=lambda p: (p.get("parcela_atual") or 0))

    lista = list(grupos.values())
    lista.sort(key=lambda g: (str(g.get("data_prev_pagamento") or ""), str(g.get("nome_parceiro") or "")), reverse=True)
    return lista


def _calcular_totais_adquirente(df_cielo, df_getnet) -> Dict[str, Any]:
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
        "total": total, "cielo_total": cielo_total, "getnet_total": getnet_total,
        "cielo_n": cielo_n, "getnet_n": getnet_n, "total_n": cielo_n + getnet_n,
    }


def _calcular_total_sankhya_elegivel(df_sankhya) -> Dict[str, Any]:
    if df_sankhya is None or df_sankhya.empty:
        return {"total": 0.0, "total_n": 0}

    df_c = classificador_sankhya.classificar(df_sankhya)
    df_el = classificador_sankhya.filtrar_elegiveis_para_match(df_c)

    if df_el is None or df_el.empty:
        return {"total": 0.0, "total_n": 0}

    return {"total": float(df_el["vlr_desdobramento"].sum()), "total_n": len(df_el)}


def _calcular_kpis_por_adquirente(resultado, df_cielo, df_getnet) -> Dict[str, Dict[str, Any]]:
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
    n_amb = len(resultado.a_analisar_ambiguos) if resultado.a_analisar_ambiguos is not None else 0
    n_vst = len(resultado.a_analisar_venda_sem_titulo) if resultado.a_analisar_venda_sem_titulo is not None else 0
    n_tsv = len(resultado.a_analisar_titulo_sem_venda) if resultado.a_analisar_titulo_sem_venda is not None else 0
    n_desf = len(ligacoes_desfeitas)

    n_g1_parcelas = len(resultado.grupo_1_conciliadas) if resultado.grupo_1_conciliadas is not None else 0
    n_g1_desfeitas = 0
    if n_desf > 0 and resultado.grupo_1_conciliadas is not None and not resultado.grupo_1_conciliadas.empty:
        for _, row in resultado.grupo_1_conciliadas.iterrows():
            if _chave_venda_original(row) in ligacoes_desfeitas:
                n_g1_desfeitas += 1

    # Contar confirmações manuais separando as que vieram de ambíguos vs. sem-título
    confirmadas = st.session_state.get("cv_confirmadas_manual", {})
    n_manuais_de_amb = 0
    n_manuais_de_vst = 0

    chaves_amb = set()
    if resultado.a_analisar_ambiguos is not None and not resultado.a_analisar_ambiguos.empty:
        for _, row in resultado.a_analisar_ambiguos.iterrows():
            chaves_amb.add("|".join(str(x) for x in _chave_venda_original(row)))

    chaves_vst = set()
    if resultado.a_analisar_venda_sem_titulo is not None and not resultado.a_analisar_venda_sem_titulo.empty:
        for _, row in resultado.a_analisar_venda_sem_titulo.iterrows():
            chaves_vst.add("|".join(str(x) for x in _chave_venda_original(row)))

    for chave_str in confirmadas.keys():
        if chave_str in chaves_amb:
            n_manuais_de_amb += 1
        elif chave_str in chaves_vst:
            n_manuais_de_vst += 1

    n_confirmadas_total = len(confirmadas)

    return {
        "a_analisar": (n_amb - n_manuais_de_amb) + (n_vst - n_manuais_de_vst) + n_tsv + n_desf,
        "auto_conciliadas": n_g1_parcelas - n_g1_desfeitas + n_confirmadas_total,
        "compensadas": len(resultado.grupo_2_ja_baixadas) if resultado.grupo_2_ja_baixadas is not None else 0,
        "aguardando": len(resultado.grupo_3_aguardando) if resultado.grupo_3_aguardando is not None else 0,
        "devolucoes": len(resultado.grupo_4_devolucoes) if resultado.grupo_4_devolucoes is not None else 0,
    }


def _dias_desde(data: Any, hoje: Optional[date] = None) -> Optional[int]:
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
    dias = _dias_desde(venda.get("data_prev_pagamento"), hoje)
    if dias is None:
        return ("aguardando_faturamento", "Aguardando faturamento · sem data")
    if dias < 3:
        return ("aguardando_faturamento", f"Aguardando faturamento · {dias} dia(s)")
    return ("divergencia_real", f"Divergência real · {dias} dias sem par")


# ==============================================================================
# RENDERS BÁSICOS (importação)
# ==============================================================================

def _render_header():
    html = (
        f'<div class="cv-header">'
        f'<div class="cv-header-icon">🛒</div>'
        f'<div>'
        f'<div class="cv-header-titulo">Conciliação de Vendas</div>'
        f'<div class="cv-header-sub">MVP-A · PISA · KING · TRIO</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_aviso():
    html = (
        f'<div class="cv-aviso">'
        f'<span style="font-size:18px;">ℹ️</span>'
        f'<span>Arquivos são processados na sessão e <b>não ficam armazenados</b> no servidor.</span>'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_card_arquivo(nome: str, entry: Dict[str, Any]):
    tipo = entry.get("tipo_detectado", "desconhecido")
    reconhecido = tipo != "desconhecido"
    detalhe = entry.get("detalhe_pos_processamento") or entry.get("motivo") or entry.get("tipo_legivel", "")

    if reconhecido:
        card_class = "cv-fila-card"
        badge = '<div class="cv-badge-ok">✓ RECONHECIDO</div>'
        det_class = "cv-fila-detalhe"
    else:
        card_class = "cv-fila-card cv-fila-card-fail"
        badge = '<div class="cv-badge-fail">✗ IGNORADO</div>'
        det_class = "cv-fila-detalhe cv-fila-detalhe-fail"

    html = (
        f'<div class="{card_class}">'
        f'<div style="display:flex; align-items:center; gap:12px; min-width:0; flex:1;">'
        f'<span style="font-size:22px;">📄</span>'
        f'<div style="min-width:0; overflow:hidden;">'
        f'<div class="cv-fila-nome">{_escape(nome)}</div>'
        f'<div class="{det_class}">{_escape(detalhe)}</div>'
        f'</div>'
        f'</div>'
        f'{badge}'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_kpi(coluna, label: str, valor: str, secundario: Optional[str] = None):
    with coluna:
        sec = f'<div class="cv-kpi-secundario">{_escape(secundario)}</div>' if secundario else ""
        html = (
            f'<div class="cv-kpi">'
            f'<div class="cv-kpi-label">{_escape(label)}</div>'
            f'<div class="cv-kpi-valor">{_escape(valor)}</div>'
            f'{sec}'
            f'</div>'
        )
        st.markdown(html, unsafe_allow_html=True)


def _render_kpis_importacao():
    r = st.session_state.get("cv_resumo", {})
    if not r:
        return
    st.markdown('<div class="cv-secao-titulo">Resumo do que foi lido</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    _render_kpi(c1, "Vendas Cielo", f"{r.get('cielo_vendas', 0)}",
                _fmt_moeda(r.get("cielo_liquido", 0.0)) + " líquido" if r.get("cielo_vendas", 0) else None)
    _render_kpi(c2, "Vendas Getnet", f"{r.get('getnet_vendas', 0)}",
                _fmt_moeda(r.get("getnet_repassado", 0.0)) + " repassado" if r.get("getnet_vendas", 0) else None)
    _render_kpi(c3, "Baixas TOP 1722", f"{r.get('sankhya_top_1722', 0)}",
                f"{r.get('sankhya_compensadas', 0)} compensadas" if r.get("sankhya_top_1722", 0) else None)
    _render_kpi(c4, "Aguardando captura", f"{r.get('sankhya_top_0', 0)}",
                "títulos TOP 0" if r.get("sankhya_top_0", 0) else None)

    empresas = r.get("sankhya_empresas", [])
    if empresas:
        map_emp = {1: "PISA", 2: "KING"}
        nomes = [map_emp.get(e, f"EMP{e}") for e in empresas]
        st.caption(f"Empresas identificadas no Financeiro: {' · '.join(nomes)}")


# ==============================================================================
# RENDERS DA TELA DE RESULTADO — TOPO
# ==============================================================================

def _render_topo_resultado(resultado):
    """Cabeçalho + balanço + barras por adquirente. Tudo em cards creme."""
    hoje = date.today()
    df_cielo = st.session_state.get("cv_df_cielo")
    df_getnet = st.session_state.get("cv_df_getnet_vendas")
    df_sk = st.session_state.get("cv_df_sankhya")

    tot_adq = _calcular_totais_adquirente(df_cielo, df_getnet)
    tot_sk = _calcular_total_sankhya_elegivel(df_sk)

    diff = tot_adq["total"] - tot_sk["total"]
    bate = abs(diff) < 0.01
    if bate:
        diff_html = f'<span class="cv-balanco-ok">· bate ao centavo</span>'
    else:
        diff_html = f'<span class="cv-balanco-diff">· dif {_fmt_moeda(abs(diff))}</span>'

    # Cabeçalho da rodada
    tol = st.session_state.get("cv_tolerancia_dias", 2)
    header_html = (
        f'<div class="cv-rodada-header">'
        f'<div class="cv-rodada-supra">Rodada de {hoje.strftime("%d/%m/%Y")} · tolerância ±{tol} dias</div>'
        f'<div class="cv-rodada-titulo">Resultado da conciliação</div>'
        f'</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    # Balanço lado a lado (usando st.columns pra evitar problemas de layout)
    col1, col2 = st.columns(2)

    with col1:
        html1 = (
            f'<div class="cv-balanco-card">'
            f'<div class="cv-balanco-label">Total Adquirente</div>'
            f'<div class="cv-balanco-valor">{_fmt_moeda(tot_adq["total"])}</div>'
            f'<div class="cv-balanco-sub">{tot_adq["total_n"]} vendas · Getnet {tot_adq["getnet_n"]} · Cielo {tot_adq["cielo_n"]}</div>'
            f'</div>'
        )
        st.markdown(html1, unsafe_allow_html=True)

    with col2:
        html2 = (
            f'<div class="cv-balanco-card cv-balanco-card-destaque">'
            f'<div class="cv-balanco-label">Total Sankhya {diff_html}</div>'
            f'<div class="cv-balanco-valor">{_fmt_moeda(tot_sk["total"])}</div>'
            f'<div class="cv-balanco-sub">{tot_sk["total_n"]} títulos elegíveis (nota + adiantamento)</div>'
            f'</div>'
        )
        st.markdown(html2, unsafe_allow_html=True)

    # Barras por adquirente
    kpis = _calcular_kpis_por_adquirente(resultado, df_cielo, df_getnet)

    linhas_partes = []
    for adq_key in ("getnet", "cielo"):
        d = kpis[adq_key]
        if d["total"] == 0:
            continue
        pct = d["pct"]
        pct_barra = min(pct, 100)
        nome = _label_adquirente(adq_key)
        linhas_partes.append(
            f'<div class="cv-adq-linha">'
            f'<div class="cv-adq-linha-topo">'
            f'<span class="cv-adq-nome">{nome}</span>'
            f'<span class="cv-adq-info">{d["conciliadas"]} de {d["total"]} · '
            f'<span class="cv-adq-pct">{pct:.1f}%</span></span>'
            f'</div>'
            f'<div class="cv-adq-barra">'
            f'<div class="cv-adq-barra-preenchida" style="width:{pct_barra:.1f}%;"></div>'
            f'</div>'
            f'</div>'
        )

    if linhas_partes:
        bloco_html = (
            f'<div class="cv-adq-bloco">'
            f'<div class="cv-adq-titulo">Auto-conciliação por adquirente</div>'
            f'{"".join(linhas_partes)}'
            f'</div>'
        )
        st.markdown(bloco_html, unsafe_allow_html=True)


def _render_pills(contadores: Dict[str, int]):
    """5 pills clicáveis via st.button."""
    ordem = [
        ("a_analisar", "A analisar", contadores["a_analisar"]),
        ("auto_conciliadas", "Auto-conciliadas", contadores["auto_conciliadas"]),
        ("compensadas", "Compensadas", contadores["compensadas"]),
        ("aguardando", "Aguardando", contadores["aguardando"]),
        ("devolucoes", "Devoluções", contadores["devolucoes"]),
    ]
    ativa = st.session_state.get("cv_pill_ativa", "a_analisar")

    st.markdown('<div style="margin: 16px 0 4px 0;"></div>', unsafe_allow_html=True)
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

def _render_timeline_html(dt_venda, dt_previsto, dt_baixado=None) -> str:
    """Retorna HTML da timeline em uma linha só."""
    tem_baixa = dt_baixado is not None
    b_venda = "cv-timeline-bolinha cv-timeline-bolinha-feito"
    b_prev = "cv-timeline-bolinha cv-timeline-bolinha-atual"
    b_baixa = "cv-timeline-bolinha cv-timeline-bolinha-feito" if tem_baixa else "cv-timeline-bolinha cv-timeline-bolinha-pendente"
    l1 = "cv-timeline-linha cv-timeline-linha-ok"
    l2 = "cv-timeline-linha cv-timeline-linha-ok" if tem_baixa else "cv-timeline-linha cv-timeline-linha-off"

    return (
        f'<div class="cv-timeline">'
        f'<div class="cv-timeline-passo">'
        f'<div class="{b_venda}"></div>'
        f'<div class="cv-timeline-data">{_fmt_data_curta(dt_venda)}</div>'
        f'<div class="cv-timeline-label">Vendido</div>'
        f'</div>'
        f'<div class="{l1}"></div>'
        f'<div class="cv-timeline-passo">'
        f'<div class="{b_prev}"></div>'
        f'<div class="cv-timeline-data">{_fmt_data_curta(dt_previsto)}</div>'
        f'<div class="cv-timeline-label">Previsto</div>'
        f'</div>'
        f'<div class="{l2}"></div>'
        f'<div class="cv-timeline-passo">'
        f'<div class="{b_baixa}"></div>'
        f'<div class="cv-timeline-data">{_fmt_data_curta(dt_baixado) if tem_baixa else "—"}</div>'
        f'<div class="cv-timeline-label">Baixado</div>'
        f'</div>'
        f'</div>'
    )


def _bloco_valores_direita_html(valor: Any, bruto: Optional[float], taxa_pct: Optional[float],
                                liquido: Optional[float]) -> str:
    """Bloco direito do card com valor grande + linha bruto/taxa/líq."""
    # Usa o bruto se disponível, senão cai no valor_match
    v_grande = bruto if bruto is not None else valor
    partes = []
    if bruto is not None:
        partes.append(f"bruto {_fmt_moeda(bruto)}")
    if taxa_pct is not None:
        try:
            partes.append(f"taxa {float(taxa_pct):.2f}%".replace(".", ","))
        except (ValueError, TypeError):
            pass
    if liquido is not None:
        partes.append(f"líq {_fmt_moeda(liquido)}")

    if partes:
        linha_extra = f'<div class="cv-valor-sub">{_escape(" · ".join(partes))}</div>'
    else:
        linha_extra = f'<div class="cv-valor-sub">bruto</div>'

    return (
        f'<div class="cv-valor-dir">'
        f'<div class="cv-valor-grande">{_fmt_moeda(v_grande)}</div>'
        f'{linha_extra}'
        f'</div>'
    )


def _render_card_ambiguo(venda: pd.Series, idx_card: int):
    """Card branco com faixa amarela. Múltiplas candidatas."""
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
    valor = venda.get("valor_match")
    data_venda = venda.get("data_prev_pagamento")

    # Puxar bruto/taxa/liq do df original
    bruto, taxa_pct, liquido = _puxar_valores_originais(venda)

    tags = [
        '<span class="cv-tag cv-tag-amarelo">Múltiplas candidatas</span>',
        f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
        f'<span class="cv-tag">{_escape(mod)} · {_escape(ban)}</span>',
    ]
    if parc_txt:
        tags.append(f'<span class="cv-tag">{_escape(parc_txt)}</span>')
    if nsu:
        tags.append(f'<span class="cv-tag">Nº {_escape(nsu)}</span>')

    candidatas = venda.get("candidatos") or []
    linhas_cand = [f'<div class="cv-candidatas-header">{len(candidatas)} candidatas em aberto no Sankhya · motor não escolhe, você decide</div>']
    for i, cand in enumerate(candidatas):
        classe = cand.get("classe")
        if classe == "adiantamento":
            tag_html = '<span class="cv-candidata-tag-adi">Adiantamento</span>'
            ref_nf = cand.get("nro_nota_referenciada")
            info = f"REF NF {ref_nf}" if ref_nf else "sem REF NF"
        else:
            tag_html = '<span class="cv-candidata-tag-nf">Nota fiscal</span>'
            nro = cand.get("nro_nota")
            info = f"NF {nro}" if nro else "Nota fiscal"

        parceiro = cand.get("nome_parceiro") or "—"
        vlr = cand.get("vlr_desdobramento")
        venc = cand.get("dt_vencimento")

        linhas_cand.append(
            f'<div class="cv-candidata-linha">'
            f'{tag_html}'
            f'<span>{_escape(info)} · {_escape(parceiro)} · venc {_fmt_data_br(venc)} · {_fmt_moeda(vlr)}</span>'
            f'</div>'
        )

    timeline_html = _render_timeline_html(data_venda, data_venda, None)
    valores_dir = _bloco_valores_direita_html(valor, bruto, taxa_pct, liquido)

    card_html = (
        f'<div class="cv-card">'
        f'<div class="cv-card-topo">'
        f'<div style="flex:1; min-width:0;">'
        f'<div class="cv-tag-linha">{"".join(tags)}</div>'
        f'<div class="cv-card-titulo">{_fmt_moeda(valor)}</div>'
        f'<div class="cv-card-sub">Vendido em {_fmt_data_br(data_venda)}</div>'
        f'</div>'
        f'{valores_dir}'
        f'</div>'
        f'{timeline_html}'
        f'<div class="cv-candidatas-wrapper">'
        f'{"".join(linhas_cand)}'
        f'</div>'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    if candidatas:
        chave_venda = _chave_venda_original(venda)
        chave_str = "|".join(str(x) for x in chave_venda)
        venda_dict = venda.to_dict() if hasattr(venda, "to_dict") else dict(venda)
        cols = st.columns(len(candidatas) + 1)
        for i, cand in enumerate(candidatas):
            with cols[i]:
                classe = cand.get("classe", "?")
                if classe == "nota_fiscal":
                    label = f"Escolher NF {cand.get('nro_nota')}"
                else:
                    label = "Escolher Adiantamento"
                if st.button(label, key=f"cv_esc_{idx_card}_{i}", use_container_width=True):
                    _acao_escolher_candidata(chave_str, cand, venda_dict=venda_dict)
                    st.rerun()
        st.markdown('<div style="margin-bottom:6px;"></div>', unsafe_allow_html=True)


def _render_card_venda_sem_titulo(venda: pd.Series, idx_card: int, hoje: date):
    """Card branco. Layout rico + botão 'Buscar par no Sankhya' que expande busca."""
    status_key, status_label = _classificar_venda_sem_titulo(venda, hoje)

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
    valor = venda.get("valor_match")
    data_venda = venda.get("data_prev_pagamento")
    bruto, taxa_pct, liquido = _puxar_valores_originais(venda)

    if status_key == "divergencia_real":
        card_class = "cv-card cv-card-divergencia"
        tag_status = f'<span class="cv-tag cv-tag-laranja">{_escape(status_label)}</span>'
    else:
        card_class = "cv-card cv-card-info"
        tag_status = f'<span class="cv-tag">{_escape(status_label)}</span>'

    tags = [
        tag_status,
        f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
        f'<span class="cv-tag">{_escape(mod)} · {_escape(ban)}</span>',
    ]
    if parc_txt:
        tags.append(f'<span class="cv-tag">{_escape(parc_txt)}</span>')
    if nsu:
        tags.append(f'<span class="cv-tag">Nº {_escape(nsu)}</span>')

    timeline_html = _render_timeline_html(data_venda, data_venda, None)
    valores_dir = _bloco_valores_direita_html(valor, bruto, taxa_pct, liquido)

    card_html = (
        f'<div class="{card_class}">'
        f'<div class="cv-card-topo">'
        f'<div style="flex:1; min-width:0;">'
        f'<div class="cv-tag-linha">{"".join(tags)}</div>'
        f'<div class="cv-card-titulo">{_fmt_moeda(valor)}</div>'
        f'<div class="cv-card-sub">Vendido em {_fmt_data_br(data_venda)} · sem par no Sankhya</div>'
        f'</div>'
        f'{valores_dir}'
        f'</div>'
        f'{timeline_html}'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    # Botão de busca + área expandida
    chave_venda = _chave_venda_original(venda)
    chave_str = "|".join(str(x) for x in chave_venda)
    aberta = st.session_state.get("cv_busca_aberta", {}).get(chave_str, False)

    col_btn, col_esp = st.columns([2, 3])
    with col_btn:
        label_btn = "✕  Fechar busca" if aberta else "🔍  Buscar par no Sankhya"
        if st.button(label_btn, key=f"cv_toggle_busca_{idx_card}", use_container_width=True):
            _acao_toggle_busca(chave_str)
            st.rerun()

    if aberta:
        _render_busca_inline(venda, chave_str, idx_card)

    st.markdown('<div style="margin-bottom:6px;"></div>', unsafe_allow_html=True)


def _render_busca_inline(venda: pd.Series, chave_str: str, idx_card: int):
    """Renderiza o input de busca + resultados dentro do card sem par."""
    valor_venda = venda.get("valor_match")
    try:
        valor_venda = float(valor_venda) if valor_venda is not None else None
    except (ValueError, TypeError):
        valor_venda = None

    # Container visual da busca
    st.markdown(
        f'<div style="background:{CINZA_CLARO}; border-radius:6px; padding:12px; margin-top:-4px;">'
        f'<div style="font-size:10px; color:{TEXTO_MUTED}; text-transform:uppercase; letter-spacing:0.8px; font-weight:700; margin-bottom:8px;">'
        f'Buscar par no Sankhya · digite parceiro, número da NF ou valor'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    texto_atual = st.session_state.get("cv_busca_texto", {}).get(chave_str, "")
    col_input, col_help = st.columns([3, 1])
    with col_input:
        novo = st.text_input(
            "Buscar",
            value=texto_atual,
            key=f"cv_busca_txt_{idx_card}",
            placeholder="Ex: Terra Ltda · 8214 · 304,31",
            label_visibility="collapsed",
        )
        st.session_state["cv_busca_texto"][chave_str] = novo
    with col_help:
        st.caption("Vazio = por valor")

    resultados = _buscar_titulos_em_aberto(novo, valor_venda=valor_venda, limite=15)

    if not resultados:
        st.caption("Nenhum título em aberto encontrado.")
        return

    st.caption(f"{len(resultados)} título(s) em aberto — clique em 'Ligar aqui' pra confirmar")

    venda_dict = venda.to_dict() if hasattr(venda, "to_dict") else dict(venda)

    for i, tit in enumerate(resultados):
        classe = tit.get("sk_classe")
        if classe == "adiantamento":
            tag_html = '<span class="cv-candidata-tag-adi">Adiant.</span>'
            ref_nf = tit.get("sk_ref_nf")
            id_txt = f"REF NF {ref_nf}" if ref_nf else "sem REF NF"
        else:
            tag_html = '<span class="cv-candidata-tag-nf">NF</span>'
            id_txt = f"NF {tit.get('sk_nro_nota')}" if tit.get("sk_nro_nota") else "sem número"

        parceiro = tit.get("sk_nome_parceiro") or "—"
        vlr = tit.get("sk_vlr_desdobramento")
        venc = tit.get("sk_dt_vencimento")

        # Diferença ao valor da venda
        dif_txt = ""
        if valor_venda is not None and vlr is not None:
            try:
                dif = float(vlr) - valor_venda
                if abs(dif) < 0.01:
                    dif_txt = f' <span style="color:{VERDE}; font-weight:600;">· ao centavo</span>'
                else:
                    dif_txt = f' <span style="color:{LARANJA};">· dif {_fmt_moeda(abs(dif))}</span>'
            except (ValueError, TypeError):
                pass

        col_info, col_btn = st.columns([4, 1])
        with col_info:
            st.markdown(
                f'<div style="background:{BRANCO}; border-radius:4px; padding:6px 10px; font-size:12px; color:{AZUL_NAVY}; margin-bottom:4px;">'
                f'{tag_html} '
                f'<span>{_escape(id_txt)} · {_escape(parceiro)} · venc {_fmt_data_br(venc)} · {_fmt_moeda(vlr)}{dif_txt}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col_btn:
            if st.button("Ligar aqui", key=f"cv_ligar_{idx_card}_{i}", type="primary", use_container_width=True):
                _acao_ligar_manualmente(chave_str, tit, venda_dict=venda_dict)
                st.rerun()


def _render_pill_a_analisar(resultado):
    hoje = date.today()
    ambiguos = resultado.a_analisar_ambiguos
    venda_st = resultado.a_analisar_venda_sem_titulo
    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())
    confirmadas = st.session_state.get("cv_confirmadas_manual", {})

    def _foi_confirmada(venda_row) -> bool:
        chave = _chave_venda_original(venda_row)
        chave_str = "|".join(str(x) for x in chave)
        return chave_str in confirmadas

    # Filtrar vendas que já foram confirmadas manualmente
    ambiguos_pendentes = []
    if ambiguos is not None and not ambiguos.empty:
        for _, venda in ambiguos.iterrows():
            if not _foi_confirmada(venda):
                ambiguos_pendentes.append(venda)

    vst_pendentes = []
    if venda_st is not None and not venda_st.empty:
        for _, venda in venda_st.iterrows():
            if not _foi_confirmada(venda):
                vst_pendentes.append(venda)

    total = len(ambiguos_pendentes) + len(vst_pendentes) + len(ligacoes_desf)

    if total == 0:
        st.markdown(
            '<div class="cv-empty-state">Nada a analisar nesta rodada. Motor casou tudo que era possível casar.</div>',
            unsafe_allow_html=True,
        )
        return

    max_cards = st.session_state.get("cv_max_cards_a_analisar", 20)
    renderizados = 0
    idx = 0

    # 1. Ambíguos (mais urgentes)
    for venda in ambiguos_pendentes:
        if renderizados >= max_cards:
            break
        _render_card_ambiguo(venda, idx)
        renderizados += 1
        idx += 1

    # 2. Divergências reais e depois aguardando faturamento
    divergencias = []
    aguardando = []
    for venda in vst_pendentes:
        status_key, _ = _classificar_venda_sem_titulo(venda, hoje)
        if status_key == "divergencia_real":
            divergencias.append(venda)
        else:
            aguardando.append(venda)

    for venda in divergencias:
        if renderizados >= max_cards:
            break
        _render_card_venda_sem_titulo(venda, idx, hoje)
        renderizados += 1
        idx += 1

    for venda in aguardando:
        if renderizados >= max_cards:
            break
        _render_card_venda_sem_titulo(venda, idx, hoje)
        renderizados += 1
        idx += 1

    if renderizados < total:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption(f"Mostrando {renderizados} de {total} · aumente o limite pra ver mais")
        with col2:
            if st.button("Mostrar +20", key="cv_mais_a_analisar", use_container_width=True):
                st.session_state["cv_max_cards_a_analisar"] = max_cards + 20
                st.rerun()


# ==============================================================================
# RENDERS DE CARDS — AUTO-CONCILIADAS / COMPENSADAS / AGUARDANDO / DEVOLUÇÕES
# ==============================================================================

def _render_card_conciliada(grupo: Dict[str, Any], idx_card: int, mostrar_desfazer: bool = True):
    """Card branco com faixa verde. Uma venda auto-conciliada (pode ter N parcelas)."""
    adq = _label_adquirente(grupo.get("adquirente"))
    ban = _label_bandeira(grupo.get("bandeira"))
    mod = _label_modalidade(grupo.get("modalidade"), grupo.get("parcelas_total"))

    parceiro = grupo.get("nome_parceiro") or "—"
    empresa = grupo.get("empresa") or ""
    empresa_txt = f" · {empresa}" if empresa else ""
    nsu = grupo.get("nsu") or ""
    data_venda = grupo.get("data_prev_pagamento")

    parcelas = grupo.get("parcelas", [])
    n_parc = len(parcelas)
    valor_total = grupo.get("valor_total", 0)

    # Tags
    tags = [
        f'<span class="cv-tag cv-tag-verde">✓ Ligado</span>',
        f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
        f'<span class="cv-tag">{_escape(mod)} · {_escape(ban)}</span>',
    ]
    if n_parc > 1:
        tags.append(f'<span class="cv-tag">{n_parc} parcelas</span>')
    if nsu:
        tags.append(f'<span class="cv-tag">Nº {_escape(nsu)}</span>')

    # Parcelas
    linhas_parc = []
    for p in parcelas:
        pa = p.get("parcela_atual")
        pt = p.get("parcelas_total")
        nro_nota = p.get("sk_nro_nota")
        venc = p.get("sk_dt_vencimento")
        vlr = p.get("valor")
        classe = p.get("sk_classe")

        if classe == "adiantamento":
            ref_nf = p.get("sk_ref_nf")
            titulo_html = f'Adiantamento REF NF {ref_nf}' if ref_nf else 'Adiantamento'
        else:
            titulo_html = f'<span class="cv-parc-nf">NF {nro_nota}</span>' if nro_nota else 'Nota'

        if pt and pt > 1:
            desc = f'Parcela {pa}/{pt} → {titulo_html} · venc {_fmt_data_br(venc)}'
        else:
            desc = f'{titulo_html} · venc {_fmt_data_br(venc)}'

        linhas_parc.append(
            f'<div class="cv-parc-linha">'
            f'<span>{desc}</span>'
            f'<span style="color:{TEXTO_MUTED};">{_fmt_moeda(vlr)}</span>'
            f'</div>'
        )

    parcelas_html = f'<div class="cv-parcelas-lista">{"".join(linhas_parc)}</div>' if linhas_parc else ""

    card_html = (
        f'<div class="cv-card cv-card-sucesso">'
        f'<div class="cv-card-topo">'
        f'<div style="flex:1; min-width:0;">'
        f'<div class="cv-tag-linha">{"".join(tags)}</div>'
        f'<div class="cv-card-titulo">{_escape(parceiro)}{_escape(empresa_txt)}</div>'
        f'<div class="cv-card-sub">Vendido em {_fmt_data_br(data_venda)}</div>'
        f'</div>'
        f'<div class="cv-valor-dir">'
        f'<div class="cv-valor-sub">total</div>'
        f'<div class="cv-valor-grande">{_fmt_moeda(valor_total)}</div>'
        f'</div>'
        f'</div>'
        f'{parcelas_html}'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    if mostrar_desfazer:
        col_esp, col_btn = st.columns([5, 1])
        with col_btn:
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
        st.markdown('<div style="margin-bottom:8px;"></div>', unsafe_allow_html=True)


def _render_card_confirmacao_manual(chave_str: str, dados: Dict[str, Any], idx_card: int):
    """Card branco com faixa verde. Confirmação manual (via candidata ou busca)."""
    fonte = dados.get("fonte", "?")
    fonte_label = "Escolhida entre candidatas" if fonte == "ambiguo" else "Ligada via busca manual"

    adq = _label_adquirente(dados.get("venda_adquirente"))
    ban = _label_bandeira(dados.get("venda_bandeira"))
    mod = _label_modalidade(dados.get("venda_modalidade"))
    parceiro = dados.get("sk_nome_parceiro") or "—"
    valor = dados.get("venda_valor") or dados.get("sk_vlr_desdobramento")
    data_venda = dados.get("venda_data")
    classe_sk = dados.get("sk_classe")
    nro_nota = dados.get("sk_nro_nota")
    venc = dados.get("sk_dt_vencimento")

    if classe_sk == "adiantamento":
        ref_nf = dados.get("sk_ref_nf")
        titulo_txt = f"Adiantamento · REF NF {ref_nf}" if ref_nf else "Adiantamento"
    else:
        titulo_txt = f"NF {nro_nota}" if nro_nota else "Nota fiscal"

    tags = [
        f'<span class="cv-tag cv-tag-verde">✓ {_escape(fonte_label)}</span>',
        f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
        f'<span class="cv-tag">{_escape(mod)} · {_escape(ban)}</span>',
    ]

    card_html = (
        f'<div class="cv-card cv-card-sucesso">'
        f'<div class="cv-card-topo">'
        f'<div style="flex:1; min-width:0;">'
        f'<div class="cv-tag-linha">{"".join(tags)}</div>'
        f'<div class="cv-card-titulo">{_escape(parceiro)}</div>'
        f'<div class="cv-card-sub">'
        f'Vendido em {_fmt_data_br(data_venda)} → {_escape(titulo_txt)} · venc {_fmt_data_br(venc)}'
        f'</div>'
        f'</div>'
        f'<div class="cv-valor-dir">'
        f'<div class="cv-valor-grande">{_fmt_moeda(valor)}</div>'
        f'<div class="cv-valor-sub">valor da venda</div>'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    col_esp, col_btn = st.columns([5, 1])
    with col_btn:
        if st.button(
            "↺ Desfazer",
            key=f"cv_desf_man_{idx_card}_{chave_str[:40]}",
            help="Desfazer esta ligação manual — a venda voltará a 'A analisar'",
            use_container_width=True,
        ):
            _acao_desfazer_confirmacao_manual(chave_str)
            st.rerun()
    st.markdown('<div style="margin-bottom:8px;"></div>', unsafe_allow_html=True)


def _render_pill_auto_conciliadas(resultado):
    df_g1 = resultado.grupo_1_conciliadas
    confirmadas = st.session_state.get("cv_confirmadas_manual", {})

    tem_g1 = df_g1 is not None and not df_g1.empty
    tem_manuais = bool(confirmadas)

    if not tem_g1 and not tem_manuais:
        st.markdown(
            '<div class="cv-empty-state">Nenhuma venda auto-conciliada nesta rodada.</div>',
            unsafe_allow_html=True,
        )
        return

    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())
    grupos = _agrupar_conciliadas_por_venda(df_g1, ligacoes_desf) if tem_g1 else []

    # BLOCO 1: Confirmadas manualmente (aparece primeiro, se houver)
    if tem_manuais:
        st.markdown(
            f'<div class="cv-secao-wrapper">'
            f'<div class="cv-secao-header">'
            f'<div class="cv-secao-header-titulo">'
            f'{len(confirmadas)} confirmadas manualmente · você ligou nesta rodada'
            f'</div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        for i, (chave_str, dados) in enumerate(confirmadas.items()):
            _render_card_confirmacao_manual(chave_str, dados, i)

    if not grupos:
        if not tem_manuais:
            st.markdown(
                '<div class="cv-empty-state">Todas as auto-conciliações foram desfeitas manualmente.</div>',
                unsafe_allow_html=True,
            )
        return

    # BLOCO 2: Auto-conciliadas pelo motor
    header_html = (
        f'<div class="cv-secao-wrapper">'
        f'<div class="cv-secao-header">'
        f'<div class="cv-secao-header-titulo">{len(grupos)} auto-conciliadas pelo motor · agrupadas por venda</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    col_busca, _ = st.columns([2, 1])
    with col_busca:
        busca = st.text_input(
            "Buscar",
            value=st.session_state.get("cv_busca_auto", ""),
            key="cv_busca_auto_input",
            placeholder="Buscar por parceiro ou número da NF...",
            label_visibility="collapsed",
        )
        st.session_state["cv_busca_auto"] = busca

    busca_lower = (busca or "").strip().lower()
    if busca_lower:
        filtrados = []
        for g in grupos:
            parceiro = str(g.get("nome_parceiro") or "").lower()
            if busca_lower in parceiro:
                filtrados.append(g)
                continue
            for p in g.get("parcelas", []):
                if busca_lower in str(p.get("sk_nro_nota") or "").lower():
                    filtrados.append(g)
                    break
        grupos = filtrados

    if not grupos:
        st.caption(f"Nenhum resultado para '{busca}'.")
        return

    max_mostrar = 20
    visiveis = grupos[:max_mostrar]

    for i, grupo in enumerate(visiveis):
        _render_card_conciliada(grupo, i, mostrar_desfazer=True)

    if len(grupos) > max_mostrar:
        st.caption(f"Mostrando {max_mostrar} de {len(grupos)} · use a busca para filtrar")


def _render_pill_compensadas(resultado):
    df_g2 = resultado.grupo_2_ja_baixadas
    if df_g2 is None or df_g2.empty:
        st.markdown(
            '<div class="cv-empty-state">Nenhuma venda compensada nesta rodada.</div>',
            unsafe_allow_html=True,
        )
        return

    grupos = _agrupar_conciliadas_por_venda(df_g2, set())

    header_html = (
        f'<div class="cv-secao-wrapper">'
        f'<div class="cv-secao-header">'
        f'<div class="cv-secao-header-titulo">'
        f'{len(grupos)} vendas já baixadas por cartão (TOP 1722) · auditoria'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    for i, grupo in enumerate(grupos[:20]):
        _render_card_conciliada(grupo, i + 5000, mostrar_desfazer=False)

    if len(grupos) > 20:
        st.caption(f"Mostrando 20 de {len(grupos)}")


def _render_pill_aguardando(resultado):
    df_g3 = resultado.grupo_3_aguardando
    if df_g3 is None or df_g3.empty:
        st.markdown(
            '<div class="cv-empty-state">Nenhum título aguardando captura nesta rodada.</div>',
            unsafe_allow_html=True,
        )
        return

    total = len(df_g3)
    total_valor = float(df_g3["vlr_desdobramento"].sum()) if "vlr_desdobramento" in df_g3.columns else 0.0

    header_html = (
        f'<div class="cv-secao-wrapper">'
        f'<div class="cv-secao-header">'
        f'<div class="cv-secao-header-titulo">'
        f'{total} títulos aguardando captura · {_fmt_moeda(total_valor)} em aberto'
        f'</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    for _, tit in df_g3.head(20).iterrows():
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

        tags = [
            f'<span class="cv-tag">{_escape(tipo_label)}</span>',
            f'<span class="cv-tag">{_escape(id_titulo)}</span>',
        ]
        if adq_inf:
            tags.append(f'<span class="cv-tag cv-tag-adq">{_escape(_label_adquirente(adq_inf))}</span>')

        card_html = (
            f'<div class="cv-card cv-card-info">'
            f'<div class="cv-card-topo">'
            f'<div style="flex:1; min-width:0;">'
            f'<div class="cv-tag-linha">{"".join(tags)}</div>'
            f'<div class="cv-card-titulo">{_escape(parceiro)}</div>'
            f'<div class="cv-card-sub">Vencimento {_fmt_data_br(venc)}</div>'
            f'</div>'
            f'<div class="cv-valor-dir">'
            f'<div class="cv-valor-grande">{_fmt_moeda(valor)}</div>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    if total > 20:
        st.caption(f"Mostrando 20 de {total}")


def _render_pill_devolucoes(resultado):
    df_g4 = resultado.grupo_4_devolucoes
    if df_g4 is None or df_g4.empty:
        st.markdown(
            '<div class="cv-empty-state">Nenhuma devolução nesta rodada.</div>',
            unsafe_allow_html=True,
        )
        return

    total = len(df_g4)
    header_html = (
        f'<div class="cv-secao-wrapper">'
        f'<div class="cv-secao-header">'
        f'<div class="cv-secao-header-titulo">{total} devoluções / cancelamentos</div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)

    for _, dev in df_g4.head(20).iterrows():
        adq = _label_adquirente(dev.get("adquirente"))
        valor = dev.get("valor_match")
        data = dev.get("data_prev_pagamento")

        tags = [
            '<span class="cv-tag cv-tag-laranja">Devolução</span>',
            f'<span class="cv-tag cv-tag-adq">{_escape(adq)}</span>',
        ]

        card_html = (
            f'<div class="cv-card cv-card-divergencia">'
            f'<div class="cv-card-topo">'
            f'<div style="flex:1; min-width:0;">'
            f'<div class="cv-tag-linha">{"".join(tags)}</div>'
            f'<div class="cv-card-sub">Vendido em {_fmt_data_br(data)}</div>'
            f'</div>'
            f'<div class="cv-valor-dir">'
            f'<div class="cv-valor-grande">{_fmt_moeda(valor)}</div>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    if total > 20:
        st.caption(f"Mostrando 20 de {total}")


# ==============================================================================
# AÇÕES
# ==============================================================================

def _acao_escolher_candidata(chave_venda_str: str, candidato_dict: Dict[str, Any],
                             venda_dict: Optional[Dict[str, Any]] = None):
    st.session_state["cv_confirmadas_manual"][chave_venda_str] = {
        "fonte": "ambiguo",
        "sk_idx": candidato_dict.get("idx_sankhya") or candidato_dict.get("sk_idx"),
        "sk_nro_nota": candidato_dict.get("nro_nota") or candidato_dict.get("sk_nro_nota"),
        "sk_classe": candidato_dict.get("classe") or candidato_dict.get("sk_classe"),
        "sk_nome_parceiro": candidato_dict.get("nome_parceiro") or candidato_dict.get("sk_nome_parceiro"),
        "sk_vlr_desdobramento": candidato_dict.get("vlr_desdobramento") or candidato_dict.get("sk_vlr_desdobramento"),
        "sk_dt_vencimento": candidato_dict.get("dt_vencimento") or candidato_dict.get("sk_dt_vencimento"),
        "sk_ref_nf": candidato_dict.get("nro_nota_referenciada") or candidato_dict.get("sk_ref_nf"),
        "venda_adquirente": (venda_dict or {}).get("adquirente"),
        "venda_bandeira": (venda_dict or {}).get("bandeira"),
        "venda_modalidade": (venda_dict or {}).get("modalidade"),
        "venda_valor": (venda_dict or {}).get("valor_match"),
        "venda_data": (venda_dict or {}).get("data_prev_pagamento"),
        "venda_nsu": (venda_dict or {}).get("nsu"),
    }
    st.session_state["cv_historico"].append({
        "acao": "escolher_candidata",
        "chave_venda": chave_venda_str,
        "sk_nro_nota": candidato_dict.get("nro_nota") or candidato_dict.get("sk_nro_nota"),
        "sk_classe": candidato_dict.get("classe") or candidato_dict.get("sk_classe"),
        "quando": datetime.now().isoformat(timespec="seconds"),
    })


def _acao_toggle_busca(chave_venda_str: str):
    aberta = st.session_state.get("cv_busca_aberta", {})
    aberta[chave_venda_str] = not aberta.get(chave_venda_str, False)
    st.session_state["cv_busca_aberta"] = aberta


def _acao_ligar_manualmente(chave_venda_str: str, titulo_dict: Dict[str, Any],
                            venda_dict: Optional[Dict[str, Any]] = None):
    """Registra ligação manual a partir da busca. Fecha a busca do card."""
    st.session_state["cv_confirmadas_manual"][chave_venda_str] = {
        "fonte": "busca_manual",
        "sk_idx": titulo_dict.get("sk_idx"),
        "sk_nro_nota": titulo_dict.get("sk_nro_nota"),
        "sk_classe": titulo_dict.get("sk_classe"),
        "sk_nome_parceiro": titulo_dict.get("sk_nome_parceiro"),
        "sk_vlr_desdobramento": titulo_dict.get("sk_vlr_desdobramento"),
        "sk_dt_vencimento": titulo_dict.get("sk_dt_vencimento"),
        "sk_ref_nf": titulo_dict.get("sk_ref_nf"),
        "venda_adquirente": (venda_dict or {}).get("adquirente"),
        "venda_bandeira": (venda_dict or {}).get("bandeira"),
        "venda_modalidade": (venda_dict or {}).get("modalidade"),
        "venda_valor": (venda_dict or {}).get("valor_match"),
        "venda_data": (venda_dict or {}).get("data_prev_pagamento"),
        "venda_nsu": (venda_dict or {}).get("nsu"),
    }
    st.session_state["cv_historico"].append({
        "acao": "ligar_manualmente",
        "chave_venda": chave_venda_str,
        "sk_nro_nota": titulo_dict.get("sk_nro_nota"),
        "sk_classe": titulo_dict.get("sk_classe"),
        "sk_nome_parceiro": titulo_dict.get("sk_nome_parceiro"),
        "quando": datetime.now().isoformat(timespec="seconds"),
    })
    # Fecha a busca do card
    aberta = st.session_state.get("cv_busca_aberta", {})
    aberta[chave_venda_str] = False
    st.session_state["cv_busca_aberta"] = aberta


def _acao_desfazer_confirmacao_manual(chave_venda_str: str):
    """Remove uma confirmação manual (ambíguo ou busca_manual)."""
    confirmadas = st.session_state.get("cv_confirmadas_manual", {})
    dados = confirmadas.pop(chave_venda_str, None)
    st.session_state["cv_confirmadas_manual"] = confirmadas
    if dados:
        st.session_state["cv_historico"].append({
            "acao": "desfazer_manual",
            "chave_venda": chave_venda_str,
            "fonte_original": dados.get("fonte"),
            "sk_nro_nota": dados.get("sk_nro_nota"),
            "quando": datetime.now().isoformat(timespec="seconds"),
        })


def _acao_pedir_desfazer(grupo: Dict[str, Any]):
    st.session_state["cv_desfazer_pendente"] = {
        "chave": grupo.get("chave"),
        "nome_parceiro": grupo.get("nome_parceiro"),
        "adquirente": grupo.get("adquirente"),
        "valor_total": grupo.get("valor_total"),
        "n_parcelas": len(grupo.get("parcelas", [])),
    }


def _acao_confirmar_desfazer():
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
# CONFIRMAÇÃO DE DESFAZER
# ==============================================================================

def _render_confirmacao_desfazer():
    pend = st.session_state.get("cv_desfazer_pendente")
    if not pend:
        return

    parceiro = pend.get("nome_parceiro") or "essa venda"
    adq = _label_adquirente(pend.get("adquirente"))
    valor = pend.get("valor_total")
    n_parc = pend.get("n_parcelas", 1)
    parcelas_txt = f"{n_parc} parcelas voltarão" if n_parc > 1 else "A venda voltará"

    html = (
        f'<div class="cv-confirmacao">'
        f'<div class="cv-confirmacao-titulo">Desfazer ligação de {_escape(parceiro)}?</div>'
        f'<div class="cv-confirmacao-descr">'
        f'{_escape(adq)} · {_fmt_moeda(valor)} · {_escape(parcelas_txt)} a "A analisar" '
        f'e os títulos do Sankhya voltarão pra pool de candidatas.'
        f'</div>'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)

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
# RODAPÉ / EXPORTAR
# ==============================================================================

def _render_rodape_exportar(resultado, contadores):
    n_desf = len(st.session_state.get("cv_ligacoes_desfeitas", set()))
    n_conf = len(st.session_state.get("cv_confirmadas_manual", {}))
    total_hist = len(st.session_state.get("cv_historico", []))

    info_txt = (
        f"Rodada com {contadores['auto_conciliadas']} auto-conciliadas · "
        f"{n_conf} confirmadas manualmente · "
        f"{n_desf} ligações desfeitas · "
        f"{total_hist} ações no histórico"
    )

    st.markdown(f'<div class="cv-rodape-info">{_escape(info_txt)}</div>', unsafe_allow_html=True)

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
            st.warning("Módulo de exportação Excel indisponível.")

    with col2:
        if st.button("↺  Nova rodada", key="cv_nova_rodada", use_container_width=True):
            _limpar_estado_completo()
            st.rerun()

    with col3:
        if st.button("🔄  Reprocessar", key="cv_reprocessar_motor",
                     help="Rodar motor novamente", use_container_width=True):
            _limpar_estado_motor()
            _rodar_motor()
            st.rerun()


# ==============================================================================
# TELA DE RESULTADO COMPLETA
# ==============================================================================

def _render_tela_resultado():
    resultado = st.session_state.get("cv_motor_resultado")
    if resultado is None:
        return

    ligacoes_desf = st.session_state.get("cv_ligacoes_desfeitas", set())
    contadores = _calcular_contadores_pills(resultado, ligacoes_desf)

    _render_topo_resultado(resultado)
    _render_confirmacao_desfazer()
    _render_pills(contadores)

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

    _render_rodape_exportar(resultado, contadores)


# ==============================================================================
# FUNÇÃO PRINCIPAL (chamada pelo app.py)
# ==============================================================================

def render_conciliacao_vendas():
    _garantir_estado_inicial()
    st.markdown(_CSS, unsafe_allow_html=True)
    _render_header()

    if st.session_state.get("cv_motor_resultado") is not None:
        _render_tela_resultado()
        return

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
            proc_clicado = st.button("▶  Processar arquivos", key="cv_btn_processar",
                                     type="primary", use_container_width=True)
        with col_limpar:
            limpar_clicado = st.button("↻  Limpar fila", key="cv_btn_limpar",
                                       use_container_width=True)

        if limpar_clicado:
            _limpar_estado_completo()
            st.rerun()

        if proc_clicado:
            with st.spinner("Lendo arquivos..."):
                _processar_arquivos()
            st.rerun()
    else:
        st.info("Nenhum arquivo na fila. Envie o Financeiro do Sankhya, o Recebíveis da Cielo e o Recebíveis Completos da Getnet.")

    if st.session_state.get("cv_processado") and st.session_state.get("cv_resumo"):
        _render_kpis_importacao()

        st.markdown('<div class="cv-secao-titulo">Iniciar conciliação</div>', unsafe_allow_html=True)
        col_cfg, col_rodar = st.columns([1, 3])
        with col_cfg:
            tol = st.number_input(
                "Tolerância de data (dias)",
                min_value=0, max_value=30,
                value=int(st.session_state.get("cv_tolerancia_dias", 2)),
                key="cv_tol_input",
                help="Tolerância entre data prevista de pagamento e vencimento do título. Padrão 2 dias.",
            )
            st.session_state["cv_tolerancia_dias"] = int(tol)

        with col_rodar:
            st.markdown('<div style="height:28px;"></div>', unsafe_allow_html=True)
            if st.button("▶  Rodar motor de conciliação", key="cv_rodar_motor",
                         type="primary", use_container_width=True):
                with st.spinner("Cruzando vendas × títulos..."):
                    erro = _rodar_motor()
                if erro:
                    st.error(erro)
                else:
                    st.rerun()
