"""
src/paginas/login_supabase.py — v4 (colar URL do email)
"""

import streamlit as st

from src.auth_supabase import (
    OTP_SENT_KEY,
    current_user,
    extrair_tokens_da_url,
    is_admin,
    is_logged_in,
    send_magic_link,
    set_session_from_tokens,
    sign_out,
)


def _render_ja_logado():
    user = current_user()
    st.success("Login Supabase ativo")
    st.write("**Nome:**", user.get("nome_completo", "-"))
    st.write("**Email:**", user.get("email", "-"))
    st.write("**Perfil:**", user.get("perfil", "-"))
    st.write("**Ativo:**", user.get("ativo", False))
    st.write("**Admin:**", is_admin())

    if user.get("_erro_perfil"):
        st.warning(f"Perfil nao encontrado: {user['_erro_perfil']}")

    st.divider()
    if st.button("Sair (logout Supabase)", type="secondary"):
        sign_out()
        st.rerun()


def _render_form_login():
    email_enviado = st.session_state.get(OTP_SENT_KEY, "")

    # Passo 1
    with st.container(border=True):
        st.subheader("Passo 1 — Digite seu email")
        email = st.text_input(
            "Seu email",
            value=email_enviado,
            placeholder="financeiro@grupolle.com.br",
            key="login_supabase_email_input",
        )

        if st.button("Enviar link de acesso", type="primary", use_container_width=True):
            with st.spinner("Enviando..."):
                r = send_magic_link(email)
            if r["ok"]:
                st.success(f"Link enviado para {email}.")
                st.rerun()
            else:
                st.error(f"Falha ao enviar: {r['erro']}")

    # Passo 2 — Instrucao
    if email_enviado:
        with st.container(border=True):
            st.subheader("Passo 2 — Abra seu email e clique no link 'Sign in'")
            st.info(
                f"Enviamos um link para **{email_enviado}**. "
                f"Clique no email. Voce sera redirecionado para uma pagina. "
                f"Copie a URL COMPLETA da barra de enderecos dessa pagina "
                f"e cole no passo 3 abaixo."
            )

        # Passo 3 — Colar URL
        with st.container(border=True):
            st.subheader("Passo 3 — Cole aqui a URL da pagina de retorno")
            st.caption(
                "Depois de clicar no link do email, uma pagina abre. "
                "Selecione a URL COMPLETA na barra de enderecos (Ctrl+L, "
                "depois Ctrl+A, Ctrl+C) e cole abaixo."
            )

            url_colada = st.text_area(
                "URL da pagina de retorno",
                placeholder="https://conciliacao-extratos.streamlit.app/?page=login_supabase#access_token=...",
                height=100,
                key="login_url_colada",
            )

            if st.button("Autenticar com essa URL", type="primary"):
                if not url_colada.strip():
                    st.error("Cole a URL primeiro.")
                else:
                    with st.spinner("Extraindo tokens..."):
                        r_ext = extrair_tokens_da_url(url_colada)
                    if not r_ext["ok"]:
                        st.error(r_ext["erro"])
                    else:
                        with st.spinner("Criando sessao..."):
                            r_ses = set_session_from_tokens(
                                r_ext["access_token"],
                                r_ext["refresh_token"],
                            )
                        if r_ses["ok"]:
                            st.success("Login com sucesso!")
                            st.rerun()
                        else:
                            st.error(f"Falha: {r_ses['erro']}")


def render():
    st.title("Login Supabase (teste)")
    st.caption("Parte 1.3.B da Fase 1 — MVP-A. Login por Magic Link (com URL colada).")

    st.divider()

    if is_logged_in():
        _render_ja_logado()
    else:
        _render_form_login()

    st.divider()

    with st.expander("Diagnostico tecnico", expanded=False):
        st.write("**is_logged_in():**", is_logged_in())
        st.write("**is_admin():**", is_admin())
        st.write("**OTP enviado para:**", st.session_state.get(OTP_SENT_KEY, "(nenhum)"))
        st.write("**Query params:**", dict(st.query_params))
        st.write("**Session state:**", [k for k in st.session_state.keys() if "supabase" in k.lower()])


if __name__ == "__main__":
    render()
