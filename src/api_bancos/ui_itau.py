"""
src/api_bancos/ui_itau.py — componente Streamlit para puxar extrato Itaú

Adiciona um bloco visual acima do file_uploader do módulo bancário.
Se credenciais não estiverem configuradas, mostra explicação clara.
Se configuradas, mostra botões "Testar conexão" e "Puxar extrato".

Gera arquivo XLSX temporário compatível com o parser atual do app.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import streamlit as st

from src.api_bancos import itau as api_itau


# ==============================================================================
# CORES
# ==============================================================================
AMARELO = "#FFCC00"
AZUL_NAVY = "#0A1730"
VERDE = "#2E7D4F"
VERMELHO = "#A32D2D"


def _credenciais_configuradas() -> bool:
    """Retorna True se st.secrets['itau'] tem os 4 campos mínimos."""
    try:
        if "itau" not in st.secrets:
            return False
        s = st.secrets["itau"]
        return bool(
            s.get("client_id") and s.get("client_secret")
            and s.get("certificado_crt") and s.get("chave_privada_key")
        )
    except Exception:
        return False


def _render_bloco_nao_configurado():
    """Bloco explicativo se credenciais faltarem."""
    st.markdown(
        f'<div style="background:#F5F5F5;border-left:3px solid #999;'
        f'padding:10px 14px;border-radius:4px;margin-bottom:10px;font-size:12px;">'
        f'<b style="color:{AZUL_NAVY};">🔌 API Itaú não configurada</b><br>'
        f'<span style="color:#666;">Adicione as credenciais em '
        f'<b>Settings → Secrets → [itau]</b> para puxar extratos automaticamente.</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_dialogo_puxar(contas_disponiveis: dict):
    """Formulário compacto para puxar extrato."""
    with st.form(key="frm_puxar_itau", clear_on_submit=False):
        col_data1, col_data2, col_conta = st.columns([1, 1, 2])

        with col_data1:
            hoje = date.today()
            data_inicio = st.date_input(
                "De",
                value=hoje - timedelta(days=7),
                key="itau_data_ini",
                format="DD/MM/YYYY",
            )
        with col_data2:
            data_fim = st.date_input(
                "Até",
                value=hoje,
                key="itau_data_fim",
                format="DD/MM/YYYY",
            )
        with col_conta:
            apelidos = list(contas_disponiveis.keys())
            if not apelidos:
                st.warning("Nenhuma conta configurada em [itau.contas]")
                return
            apelido_sel = st.selectbox(
                "Conta",
                options=apelidos,
                key="itau_conta_sel",
                format_func=lambda x: f"{x} ({contas_disponiveis[x]})",
            )

        submitted = st.form_submit_button(
            "🔄  Puxar extrato",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            conta_numero = contas_disponiveis.get(apelido_sel)
            if not conta_numero:
                st.error("Conta inválida.")
                return
            _puxar_e_disponibilizar(
                apelido=apelido_sel,
                conta_numero=str(conta_numero),
                data_inicio=data_inicio,
                data_fim=data_fim,
            )


def _puxar_e_disponibilizar(apelido: str, conta_numero: str,
                             data_inicio: date, data_fim: date):
    """Faz a chamada real na API e cria arquivo em memória."""
    with st.spinner(f"Puxando extrato Itaú · {apelido} · "
                    f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m')}..."):
        try:
            bytes_xlsx, nome_arquivo = api_itau.puxar_extrato_xlsx(
                conta_formatada=conta_numero,
                data_inicio=data_inicio,
                data_fim=data_fim,
                conta_apelido=apelido,
            )
        except Exception as e:
            st.error(f"❌ Falha ao puxar extrato Itaú: {e}")
            return

    # Guarda em session_state para o resto do fluxo pegar
    st.session_state["itau_extrato_baixado"] = {
        "bytes": bytes_xlsx,
        "nome": nome_arquivo,
        "apelido": apelido,
        "conta": conta_numero,
        "periodo": (data_inicio, data_fim),
    }
    st.success(
        f"✓ Extrato {apelido} baixado ({len(bytes_xlsx):,} bytes). "
        f"Arraste-o abaixo ou baixe pelo botão. "
        "Nota: por limitação técnica do Streamlit, você precisa colocá-lo manualmente no upload."
    )
    # Botão de download
    st.download_button(
        "⬇  Baixar XLSX (para colocar no upload abaixo)",
        data=bytes_xlsx,
        file_name=nome_arquivo,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="itau_baixar_arquivo",
        use_container_width=True,
    )


def _render_botao_testar():
    """Botão que só testa se as credenciais estão OK (sem puxar dados)."""
    if st.button("🧪  Testar conexão Itaú",
                 key="itau_testar",
                 use_container_width=True,
                 help="Verifica se client_id, secret e certificado estão corretos"):
        with st.spinner("Testando conexão com Itaú..."):
            resultado = api_itau.testar_conexao()

        if resultado["ok"]:
            st.success(f"✓ {resultado['mensagem']}")
        else:
            st.error(f"❌ {resultado['mensagem']}")


def render():
    """Renderiza o bloco completo (chamado do app.py)."""
    if not _credenciais_configuradas():
        _render_bloco_nao_configurado()
        return

    # Container discreto
    with st.expander("🏦  Puxar extrato Itaú direto da API (opcional)",
                     expanded=False):
        contas = api_itau.listar_contas()

        col_a, col_b = st.columns([1, 3])
        with col_a:
            _render_botao_testar()

        if not contas:
            st.warning(
                "Nenhuma conta cadastrada. Adicione no Secrets:\n"
                "```\n[itau.contas]\nprincipal = \"002300788615\"\n```"
            )
            return

        _render_dialogo_puxar(contas)


# ==============================================================================
# API CHAMADA DO app.py
# ==============================================================================
def _render_botao_puxar_itau():
    """Wrapper para o app.py chamar (evita renomeação lá)."""
    render()
