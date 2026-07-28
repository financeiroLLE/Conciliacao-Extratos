"""
src/paginas/login_supabase.py — v3 (PKCE)
"""

import streamlit as st

from src.auth_supabase import (
    OTP_SENT_KEY,
    current_user,
    exchange_code_for_session,
    is_admin,
    is_logged_in,
    send_magic_link,
    sign_out,
)


def _tentar_autenticar_via_code() -> None:
    """Se tem ?code=XXX na URL, troca por sessao e loga."""
    qp = st.query_params
    code = qp.get("code")

    if not code or is_logged_in():
        return

    with st.spinner("Autenticando..."):
        r = exchange_code_for_session(code)

    # Limpar code da URL apos usar
    try:
        del st.query_params["code"]
    except Exception:
        pass

    if r["ok"]:
        st.rerun()
    else:
        st.error(f"Falha ao autenticar: {r['erro']}")


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

    if email_enviado:
        with st.container(border=True):
            st.subheader("Passo 2 — Verifique seu email")
            st.info(
                f"Enviamos um link de acesso para **{email_enviado}**. "
                f"Abra seu email e clique no botao **'Sign in'**. "
                f"Voce sera redirecionado para o app ja autenticado."
            )
            st.caption("O link expira em 1 hora e so pode ser usado uma vez.")

            if st.button("Reenviar link"):
                with st.spinner("Reenviando..."):
                    r = send_magic_link(email_enviado)
                if r["ok"]:
                    st.success("Novo link enviado.")
                else:
                    st.error(r["erro"])


def render():
    # PRIMEIRA COISA: se tem ?code= na URL, troca por sessao
    _tentar_autenticar_via_code()

    st.title("Login Supabase (teste)")
    st.caption("Parte 1.3.B da Fase 1 — MVP-A. Login por Magic Link (PKCE).")

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
