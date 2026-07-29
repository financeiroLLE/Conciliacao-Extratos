"""
src/paginas/login_supabase.py — v5 (email + senha)

Tela simples de login com email + senha.
"""

import streamlit as st

from src.auth_supabase import (
    current_user,
    is_admin,
    is_logged_in,
    sign_in_with_password,
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
    with st.container(border=True):
        st.subheader("Entrar")

        email = st.text_input(
            "Email",
            placeholder="financeiro@grupolle.com.br",
            key="login_email",
        )

        password = st.text_input(
            "Senha",
            type="password",
            key="login_password",
        )

        if st.button("Entrar", type="primary", use_container_width=True):
            if not email or not password:
                st.error("Preencha email e senha.")
            else:
                with st.spinner("Autenticando..."):
                    r = sign_in_with_password(email, password)
                if r["ok"]:
                    st.rerun()
                else:
                    st.error(r["erro"])


def render():
    st.title("Login Supabase (teste)")
    st.caption("Parte 1.3.B da Fase 1 — MVP-A. Login por email + senha.")

    st.divider()

    if is_logged_in():
        _render_ja_logado()
    else:
        _render_form_login()

    st.divider()

    with st.expander("Diagnostico tecnico", expanded=False):
        st.write("**is_logged_in():**", is_logged_in())
        st.write("**is_admin():**", is_admin())
        st.write("**Session state:**", [k for k in st.session_state.keys() if "supabase" in k.lower()])


if __name__ == "__main__":
    render()
