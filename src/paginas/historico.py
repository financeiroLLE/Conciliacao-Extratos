"""
src/paginas/historico.py — Página de Histórico de rodadas

Lista as rodadas salvas pelo usuário no Supabase.
Cada rodada é clicável e mostra:
- Métricas (adquirente, conciliado, pendente, %)
- Arquivos armazenados
- Botão "Baixar tudo" (ZIP com arquivos brutos + resultado)
- Botão "Excluir" (com confirmação)
- Data de expiração automática (60 dias)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List

import streamlit as st

from src import rodadas as rd_mod
from src.rodadas import Rodada


# ==============================================================================
# CORES (mesma paleta do restante do app)
# ==============================================================================
AZUL_NAVY = "#0A1730"
AMARELO = "#FFCC00"
AMARELO_ESCURO = "#E5B800"
VERDE = "#2E7D4F"
VERMELHO = "#A32D2D"
TEXTO_MUTED = "#7A7A7A"
BORDA = "#D0D0D0"


# ==============================================================================
# HELPERS DE FORMATO
# ==============================================================================
def _fmt_moeda(v: float) -> str:
    """R$ 1.234,56 — padrão brasileiro."""
    if v is None or v == 0:
        return "R$ 0,00"
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_data(d) -> str:
    if d is None:
        return "—"
    if isinstance(d, str):
        return d[:10]
    if hasattr(d, "strftime"):
        return d.strftime("%d/%m/%Y")
    return str(d)


def _dias_ate_expirar(expira_em) -> int:
    if expira_em is None:
        return 0
    if isinstance(expira_em, str):
        try:
            expira_em = datetime.fromisoformat(expira_em.replace("Z", "+00:00"))
        except Exception:
            return 0
    if expira_em.tzinfo is None:
        expira_em = expira_em.replace(tzinfo=timezone.utc)
    delta = expira_em - datetime.now(timezone.utc)
    return max(0, delta.days)


# ==============================================================================
# CSS
# ==============================================================================
def _injetar_css():
    st.markdown(
        f"""
        <style>
        .hist-cabecalho {{
            font-size: 22px; font-weight: 600; color: {AMARELO}; margin-bottom: 4px;
        }}
        .hist-sub {{
            font-size: 12px; color: #FFFFFF; opacity: 0.75; margin-bottom: 20px;
        }}
        .hist-card {{
            background: #FFFFFF; border-radius: 8px; padding: 16px 20px;
            border-left: 4px solid {AMARELO}; margin-bottom: 10px;
        }}
        .hist-card-arq {{ border-left-color: #999; opacity: 0.7; }}
        .hist-titulo {{ font-size: 15px; font-weight: 600; color: {AZUL_NAVY}; margin-bottom: 4px; }}
        .hist-meta {{ font-size: 11px; color: {TEXTO_MUTED}; }}
        .hist-metrica {{ display: flex; gap: 24px; margin-top: 10px; padding-top: 10px; border-top: 1px solid #EEE; }}
        .hist-metrica-item {{ }}
        .hist-metrica-label {{ font-size: 10px; color: {TEXTO_MUTED}; letter-spacing: 0.5px; text-transform: uppercase; }}
        .hist-metrica-valor {{ font-size: 14px; color: {AZUL_NAVY}; font-weight: 600; }}
        .hist-status {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 10px;
                        font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; margin-left: 8px; }}
        .hist-status-aberta {{ background: #FFF3D6; color: #7A5C00; }}
        .hist-status-fechada {{ background: #E8F5EC; color: {VERDE}; }}
        .hist-status-arquivada {{ background: #EEE; color: #666; }}
        .hist-expira {{ font-size: 10px; color: {TEXTO_MUTED}; margin-top: 4px; }}
        .hist-expira-alerta {{ color: {VERMELHO}; font-weight: 600; }}
        .hist-vazio {{
            background: #FFFFFF; border-radius: 8px; padding: 40px 20px;
            text-align: center; color: {TEXTO_MUTED}; font-size: 14px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# RENDER
# ==============================================================================
def render_pagina_historico(modulo_fixo: str = None):
    """Página principal do Histórico.

    Args:
        modulo_fixo: se informado ('vendas' ou 'bancario'), oculta o filtro de
                     módulo e mostra só rodadas daquele tipo. Útil quando a
                     página é aberta de dentro de um módulo específico.
    """
    _injetar_css()

    if modulo_fixo == "vendas":
        titulo = "Histórico das suas conciliações de vendas"
    elif modulo_fixo == "bancario":
        titulo = "Histórico das suas conciliações bancárias"
    else:
        titulo = "Histórico de rodadas"

    st.markdown(
        f'<div class="hist-cabecalho">{titulo}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="hist-sub">Rodadas salvas por você. Arquivos ficam disponíveis por 60 dias.</div>',
        unsafe_allow_html=True,
    )

    # ---- Filtros ----
    if modulo_fixo:
        # Sem dropdown de módulo — já está fixado pelo contexto
        col_f2, col_f3 = st.columns([3, 1])
        modulo = modulo_fixo
    else:
        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        with col_f1:
            modulo_sel = st.selectbox(
                "Módulo",
                options=["Todos", "vendas", "bancario"],
                index=0,
                key="hist_filtro_modulo",
            )
            modulo = None if modulo_sel == "Todos" else modulo_sel

    with col_f2:
        incluir_arq = st.checkbox(
            "Mostrar arquivadas (expiradas)",
            value=False,
            key="hist_incluir_arq",
        )
    with col_f3:
        if st.button("🔄 Atualizar", key="hist_reload", use_container_width=True):
            st.rerun()

    # ---- Buscar rodadas ----
    try:
        rodadas = rd_mod.listar_rodadas(
            modulo=modulo,
            incluir_arquivadas=incluir_arq,
            limite=50,
        )
    except Exception as e:
        st.error(f"Erro ao carregar rodadas: {e}")
        return

    if not rodadas:
        st.markdown(
            '<div class="hist-vazio">Nenhuma rodada salva ainda. '
            'Rode uma conciliação e clique em "Salvar rodada" para aparecer aqui.</div>',
            unsafe_allow_html=True,
        )
        return

    # ---- Listar cards ----
    for r in rodadas:
        _render_card_rodada(r)


def _render_card_rodada(r: Rodada):
    """Renderiza uma rodada como card (com botões de ação)."""
    dias = _dias_ate_expirar(r.expira_em)
    arquivada = r.status == "arquivada"

    # Status badge
    status_class = f"hist-status hist-status-{r.status}"
    status_txt = {
        "aberta": "aberta",
        "fechada": "fechada",
        "arquivada": "arquivada",
    }.get(r.status, r.status)

    # Alerta expira
    if arquivada:
        expira_html = f'<div class="hist-expira">Arquivada — arquivos apagados</div>'
    elif dias <= 7:
        expira_html = f'<div class="hist-expira hist-expira-alerta">⚠️ Expira em {dias} dia(s)</div>'
    else:
        expira_html = f'<div class="hist-expira">Expira em {dias} dias</div>'

    n_arq = len(r.arquivos_json) if not arquivada else 0
    card_class = "hist-card hist-card-arq" if arquivada else "hist-card"

    modulo_label = {"vendas": "Conciliação de Vendas", "bancario": "Conciliação Bancária"}.get(
        r.modulo, r.modulo
    )

    html = (
        f'<div class="{card_class}">'
        f'<div class="hist-titulo">'
        f'Rodada de {_fmt_data(r.data_rodada)} · {modulo_label}'
        f'<span class="{status_class}">{status_txt}</span>'
        f'</div>'
        f'<div class="hist-meta">'
        f'Criada por {r.criada_por_email} · {_fmt_data(r.criada_em)}'
        f' · {n_arq} arquivo(s) armazenado(s)'
        f'</div>'
        f'<div class="hist-metrica">'
        f'<div class="hist-metrica-item">'
        f'<div class="hist-metrica-label">Adquirente</div>'
        f'<div class="hist-metrica-valor">{_fmt_moeda(r.valor_total_adq)}</div>'
        f'</div>'
        f'<div class="hist-metrica-item">'
        f'<div class="hist-metrica-label">Conciliado</div>'
        f'<div class="hist-metrica-valor" style="color:{VERDE};">{_fmt_moeda(r.valor_conciliado)} · {r.resolvido_pct:.1f}%</div>'
        f'</div>'
        f'<div class="hist-metrica-item">'
        f'<div class="hist-metrica-label">Pendente</div>'
        f'<div class="hist-metrica-valor" style="color:{VERMELHO};">{_fmt_moeda(r.valor_pendente)} · {r.pendentes_n} vendas</div>'
        f'</div>'
        f'</div>'
        f'{expira_html}'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)

    # ---- Botões de ação ----
    if arquivada:
        col_del, _ = st.columns([1, 3])
        with col_del:
            if st.button(f"🗑️ Remover", key=f"hist_del_{r.id}", use_container_width=True):
                _confirmar_delete(r)
        return

    col_baixar, col_del, _ = st.columns([1, 1, 2])

    with col_baixar:
        # Prepara ZIP na hora e disponibiliza download
        try:
            zip_bytes = rd_mod.baixar_rodada_zip(r.id)
            st.download_button(
                label="⬇️  Baixar tudo (ZIP)",
                data=zip_bytes,
                file_name=f"conciliacao_{_fmt_data(r.data_rodada).replace('/', '-')}.zip",
                mime="application/zip",
                key=f"hist_zip_{r.id}",
                use_container_width=True,
            )
        except Exception as e:
            st.button(
                "⚠️ Erro ao gerar ZIP",
                key=f"hist_zip_err_{r.id}",
                use_container_width=True,
                disabled=True,
                help=str(e),
            )

    with col_del:
        if st.button("🗑️  Excluir", key=f"hist_del_{r.id}", use_container_width=True):
            _confirmar_delete(r)

    st.markdown('<div style="margin-bottom:12px;"></div>', unsafe_allow_html=True)


def _confirmar_delete(r: Rodada):
    """Marca rodada para confirmação de delete."""
    st.session_state["hist_confirm_delete"] = r.id
    st.rerun()


def render_dialogo_confirmacao_delete():
    """Renderiza dialogo de confirmação de exclusão (se marcado)."""
    rodada_id = st.session_state.get("hist_confirm_delete")
    if not rodada_id:
        return

    st.warning(
        f"Excluir esta rodada? Os arquivos armazenados serão apagados permanentemente."
    )
    col_sim, col_nao = st.columns(2)
    with col_sim:
        if st.button("Sim, excluir", key="hist_confirm_sim", type="primary", use_container_width=True):
            try:
                rd_mod.deletar_rodada(rodada_id)
                st.success("Rodada excluída.")
            except Exception as e:
                st.error(f"Erro ao excluir: {e}")
            st.session_state.pop("hist_confirm_delete", None)
            st.rerun()
    with col_nao:
        if st.button("Cancelar", key="hist_confirm_nao", use_container_width=True):
            st.session_state.pop("hist_confirm_delete", None)
            st.rerun()
