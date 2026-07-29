# -*- coding: utf-8 -*-
"""
Página: Conciliação de Vendas (MVP-A · Fase 3 · Parte B)

Esta é a tela de IMPORTAÇÃO de arquivos.
Etapas seguintes (Fase 4+) consomem os DataFrames que esta tela deixa em session_state.

Estados guardados na sessão:
    cv_uploads              -> dict[nome_arquivo] = {bytes, tipo_detectado, tipo_legivel, motivo}
    cv_processado           -> bool  (True depois de rodar leitores com sucesso)
    cv_df_sankhya           -> pd.DataFrame     (Financeiro Sankhya normalizado)
    cv_df_cielo             -> pd.DataFrame     (vendas Cielo normalizadas)
    cv_df_getnet_vendas     -> pd.DataFrame     (vendas Getnet normalizadas)
    cv_df_getnet_repasses   -> pd.DataFrame     (repasses Getnet normalizados)
    cv_resumo               -> dict com contadores exibidos nos KPIs

Regras invioláveis observadas:
    - Zero falso positivo: se o leitor falha, o card fica em vermelho com o motivo real.
    - Additive-only: nenhuma alteração em layout global; toda estilização vive dentro desta página.
    - Persistência de bytes: os arquivos são guardados em bytes na sessão para sobreviver ao rerun.
    - Aviso claro ao usuário: arquivos não ficam armazenados no servidor.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from src.parsers.vendas import (
    detector_vendas,
    financeiro_sankhya,
    cielo_recebiveis,
    getnet_recebiveis,
)


# ==============================================================================
# CORES CANÔNICAS LLE
# ==============================================================================

AZUL_NAVY = "#0A1730"
AMARELO = "#FFCC00"
CREME = "#FFF6C8"
VERMELHO = "#A32D2D"
VERMELHO_FUNDO = "#FCEBEB"


# ==============================================================================
# CSS
# ==============================================================================

_CSS = f"""
<style>
/* Header institucional */
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
    width: 44px;
    height: 44px;
    background: {AMARELO};
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 22px;
    color: {AZUL_NAVY};
}}
.cv-header-titulo {{
    font-size: 20px;
    font-weight: 600;
    color: {AMARELO};
    line-height: 1.1;
}}
.cv-header-sub {{
    font-size: 13px;
    color: {CREME};
    opacity: 0.85;
    margin-top: 2px;
}}

/* Aviso de privacidade — texto navy escuro sobre fundo creme */
.cv-aviso {{
    background: {CREME} !important;
    border-left: 4px solid {AZUL_NAVY};
    border-radius: 12px;
    padding: 14px 20px;
    margin-bottom: 16px;
    display: flex;
    gap: 10px;
    align-items: center;
    font-size: 14px;
    font-weight: 500;
    color: {AZUL_NAVY} !important;
}}
.cv-aviso, .cv-aviso * {{
    color: {AZUL_NAVY} !important;
}}

/* Seção header — texto AMARELO sobre fundo escuro do app (era navy sobre navy = invisível) */
.cv-secao-titulo {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.5px;
    color: {AMARELO} !important;
    text-transform: uppercase;
    margin: 20px 0 12px 0;
}}

/* Card de arquivo na fila */
.cv-fila-card {{
    background: #ffffff !important;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    border: 1px solid rgba(10,23,48,0.08);
}}
.cv-fila-card-fail {{
    border-left: 3px solid {VERMELHO};
}}
.cv-fila-nome {{
    font-size: 13px;
    font-weight: 500;
    color: {AZUL_NAVY} !important;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 480px;
}}
.cv-fila-detalhe {{
    font-size: 11px;
    color: {AZUL_NAVY} !important;
    opacity: 0.75;
    margin-top: 2px;
}}
.cv-fila-detalhe-fail {{
    color: {VERMELHO} !important;
    opacity: 1;
}}
.cv-badge-ok {{
    background: {AZUL_NAVY} !important;
    color: {AMARELO} !important;
    font-size: 10px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    white-space: nowrap;
    letter-spacing: 0.5px;
}}
.cv-badge-fail {{
    background: {VERMELHO_FUNDO} !important;
    color: {VERMELHO} !important;
    font-size: 10px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 20px;
    white-space: nowrap;
    letter-spacing: 0.5px;
}}

/* Contadores KPI */
.cv-kpi {{
    background: {CREME} !important;
    border-radius: 10px;
    padding: 14px 12px;
    text-align: center;
}}
.cv-kpi-label {{
    font-size: 10px;
    letter-spacing: 0.5px;
    color: {AZUL_NAVY} !important;
    text-transform: uppercase;
    opacity: 0.7;
    margin-bottom: 6px;
}}
.cv-kpi-valor {{
    font-size: 22px;
    font-weight: 600;
    color: {AZUL_NAVY} !important;
    line-height: 1.1;
}}
.cv-kpi-secundario {{
    font-size: 10px;
    color: {AZUL_NAVY} !important;
    opacity: 0.6;
    margin-top: 4px;
}}

/* Wrapper de bloco (padding interno em amarelo) */
.cv-bloco {{
    background: {CREME};
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 16px;
}}
</style>
"""


# ==============================================================================
# HELPERS DE UI
# ==============================================================================

def _fmt_moeda(v: float) -> str:
    """Formata número como R$ 1.234,56"""
    try:
        s = f"{float(v):,.2f}"
        # troca separadores para o padrão brasileiro
        return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "R$ 0,00"


def _render_header():
    st.markdown(
        f"""
        <div class="cv-header">
            <div class="cv-header-icon">🛒</div>
            <div>
                <div class="cv-header-titulo">Conciliação de Vendas</div>
                <div class="cv-header-sub">MVP-A · Importação de arquivos · PISA · KING · TRIO</div>
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
    """Renderiza um card da fila de arquivos."""
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


def _escape(s: Any) -> str:
    """Escape HTML básico pra evitar quebra do markdown."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
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


# ==============================================================================
# LÓGICA DE ESTADO
# ==============================================================================

_SESSION_KEYS = [
    "cv_uploads",
    "cv_processado",
    "cv_df_sankhya",
    "cv_df_cielo",
    "cv_df_getnet_vendas",
    "cv_df_getnet_repasses",
    "cv_resumo",
    "cv_uploader_nonce",   # usado pra resetar o file_uploader
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


def _limpar_estado():
    """Zera toda a sessão desta página (chamado pelo botão 'Limpar fila')."""
    for k in _SESSION_KEYS:
        if k == "cv_uploader_nonce":
            # incrementa em vez de zerar — força novo widget do file_uploader
            st.session_state[k] = st.session_state.get(k, 0) + 1
        elif k == "cv_uploads":
            st.session_state[k] = {}
        elif k == "cv_processado":
            st.session_state[k] = False
        elif k == "cv_resumo":
            st.session_state[k] = {}
        else:
            st.session_state[k] = None


def _absorver_uploads(arquivos):
    """
    Recebe a lista do st.file_uploader, guarda bytes em session_state,
    e roda a detecção automática de tipo para cada arquivo novo.
    """
    if not arquivos:
        return

    uploads = st.session_state["cv_uploads"]

    for arq in arquivos:
        nome = arq.name
        # Só re-detecta se ainda não conhece esse nome
        if nome in uploads:
            continue
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
    # Novo arquivo -> resetamos o estado de "processado"
    st.session_state["cv_processado"] = False


def _processar_arquivos():
    """
    Roda os leitores em cada upload conhecido e popula os DataFrames em session_state.
    Regra de zero falso positivo: se o leitor falha, guardamos o motivo no card.
    """
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
                # desconhecido -> mantém motivo original do detector
                entry.setdefault("detalhe_pos_processamento", entry.get("motivo", "Tipo não reconhecido."))
                continue

        except Exception as e:
            entry["tipo_detectado"] = "desconhecido"
            entry["detalhe_pos_processamento"] = f"Falha ao processar: {e}"

    # Consolida DataFrames (pode haver mais de um arquivo do mesmo tipo)
    st.session_state["cv_df_sankhya"] = pd.concat(df_sankhya_lista, ignore_index=True) if df_sankhya_lista else None
    st.session_state["cv_df_cielo"] = pd.concat(df_cielo_lista, ignore_index=True) if df_cielo_lista else None
    st.session_state["cv_df_getnet_vendas"] = pd.concat(df_getnet_vendas_lista, ignore_index=True) if df_getnet_vendas_lista else None
    st.session_state["cv_df_getnet_repasses"] = pd.concat(df_getnet_repasses_lista, ignore_index=True) if df_getnet_repasses_lista else None

    # empresas como lista serializável
    resumo["sankhya_empresas"] = sorted(resumo["sankhya_empresas"])
    st.session_state["cv_resumo"] = resumo
    st.session_state["cv_processado"] = True


# ==============================================================================
# FUNÇÃO PRINCIPAL DE RENDER
# ==============================================================================

def render_conciliacao_vendas():
    """Ponto de entrada da página, chamado pelo app.py via dicionário _PAGINAS."""
    _garantir_estado_inicial()

    # CSS
    st.markdown(_CSS, unsafe_allow_html=True)

    # Header
    _render_header()

    # Aviso
    _render_aviso()

    # Uploader
    st.markdown('<div class="cv-secao-titulo">Enviar arquivos</div>', unsafe_allow_html=True)

    nonce = st.session_state["cv_uploader_nonce"]
    arquivos = st.file_uploader(
        "Arraste os arquivos aqui  ·  Financeiro Sankhya · Cielo Recebíveis · Getnet Recebíveis Completos",
        type=["xls"],
        accept_multiple_files=True,
        key=f"cv_uploader_{nonce}",
        label_visibility="visible",
    )

    if arquivos:
        _absorver_uploads(arquivos)

    uploads = st.session_state["cv_uploads"]

    # Fila
    if uploads:
        st.markdown('<div class="cv-secao-titulo">Fila de arquivos</div>', unsafe_allow_html=True)
        for nome, entry in uploads.items():
            _render_card_arquivo(nome, entry)

        # Botões
        st.write("")  # espaço
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
            _limpar_estado()
            st.rerun()

        if processar_clicado:
            with st.spinner("Lendo arquivos..."):
                _processar_arquivos()
            st.rerun()

    else:
        st.info("Nenhum arquivo na fila. Envie o Financeiro do Sankhya, o Recebíveis da Cielo e o Recebíveis Completos da Getnet.")

    # Contadores (só depois de processar)
    if st.session_state.get("cv_processado") and st.session_state.get("cv_resumo"):
        st.markdown('<div class="cv-secao-titulo">Resumo do que foi lido</div>', unsafe_allow_html=True)
        r = st.session_state["cv_resumo"]

        c1, c2, c3, c4 = st.columns(4)
        _render_kpi(
            c1,
            "Vendas Cielo",
            f"{r.get('cielo_vendas', 0)}",
            _fmt_moeda(r.get("cielo_liquido", 0.0)) + " líquido" if r.get("cielo_vendas", 0) else None,
        )
        _render_kpi(
            c2,
            "Vendas Getnet",
            f"{r.get('getnet_vendas', 0)}",
            _fmt_moeda(r.get("getnet_repassado", 0.0)) + " repassado" if r.get("getnet_vendas", 0) else None,
        )
        _render_kpi(
            c3,
            "Baixas TOP 1722",
            f"{r.get('sankhya_top_1722', 0)}",
            f"{r.get('sankhya_compensadas', 0)} compensadas" if r.get("sankhya_top_1722", 0) else None,
        )
        _render_kpi(
            c4,
            "Aguardando captura",
            f"{r.get('sankhya_top_0', 0)}",
            "títulos TOP 0" if r.get("sankhya_top_0", 0) else None,
        )

        empresas = r.get("sankhya_empresas", [])
        if empresas:
            map_emp = {1: "PISA", 2: "KING"}
            nomes = [map_emp.get(e, f"EMP{e}") for e in empresas]
            st.caption(f"Empresas identificadas no Financeiro: {' · '.join(nomes)}")

        st.info(
            "Fase 3 concluída — arquivos lidos e prontos para o motor de conciliação. "
            "A próxima etapa (Fase 4) fará o cruzamento venda × baixa."
        )
