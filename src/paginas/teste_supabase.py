"""
src/paginas/teste_supabase.py

Pagina de diagnostico da conexao Supabase.

Nao aparece no menu principal — e acessada apenas para testar
a Parte 1.2 da Fase 1. Depois de validar, pode ser removida.

Como acessar:
- Chamada explicita em algum lugar (temporario)
- Ou via `st.query_params` (?page=teste_supabase)
"""

import streamlit as st

from src.supabase_client import (
    is_supabase_configured,
    testar_conexao,
)


def render():
    st.markdown("### Diagnostico Supabase")
    st.caption("Pagina temporaria para validar a Parte 1.2 da Fase 1.")

    st.divider()

    st.subheader("1. Credenciais configuradas?")

    if is_supabase_configured():
        st.success("Sim — url e anon_key encontradas nos Secrets.")
    else:
        st.error(
            "Nao encontrei as credenciais nos Secrets. "
            "Volte ao painel do Streamlit Cloud e verifique."
        )
        st.stop()

    st.divider()

    st.subheader("2. Teste de consulta")

    if st.button("Executar teste"):
        with st.spinner("Consultando Supabase..."):
            resultado = testar_conexao()

        if resultado["ok"]:
            det = resultado["detalhes"]
            st.success(
                f"Conexao OK. {det['registros_lidos']} registro(s) lido(s)."
            )
            if det["dados"]:
                st.dataframe(det["dados"], use_container_width=True)
            else:
                st.info(
                    "Nenhum registro retornado. Isso pode ser esperado "
                    "se voce ainda nao esta autenticada — RLS bloqueia leitura."
                )
        else:
            st.error("Falha na conexao.")
            st.code(resultado["erro"], language="text")
            st.caption(
                "Verifique: 1) Secrets colados corretamente, "
                "2) URL do Supabase correta, 3) chave publishable correta."
            )


if __name__ == "__main__":
    render()
