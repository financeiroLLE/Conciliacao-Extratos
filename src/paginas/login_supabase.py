"""
src/paginas/login_supabase.py

Tela de login por Email OTP (Supabase).

Acessivel via URL: `?page=login_supabase`

Fluxo:
1. Usuario digita email -> botao "Enviar codigo"
2. Backend envia codigo por email
3. Usuario digita codigo -> botao "Entrar"
4. Se OK, mostra tela de sucesso com dados do perfil
"""

import streamlit as st

from src.auth_supabase import (
    OTP_SENT_KEY,
    current_user,
    is_admin,
    is_logged_in,
    send_email_otp,
    sign_out,
    verify_email_otp,
)


def _render_ja_logado():
    """Tela mostrada quando o usuario ja esta logado."""
    user = current_user()
    st.success("Login Supabase ativo")
    st.write("**Nome:**", user.get("nome_completo", "-"))
    st.write("**Email:**", user.get("email", "-"))
    st.write("**Perfil:**", user.get("perfil", "-"))
    st.write("**Ativo:**", user.get("ativo", False))
    st.write("**Admin:**", is_admin())

    if user.get("_erro_perfil"):
        st.warning(f"Perfil nao encontrado em public.usuarios: {user['_erro_perfil']}")

    st.divider()
    if st.button("Sair (logout Supabase)", type="secondary"):
        sign_out()
        st.rerun()


def _render_form_login():
    """Formulario de login em duas etapas."""
    email_enviado = st.session_state.get(OTP_SENT_KEY, "")

    # ETAPA 1 — Enviar codigo
    with st.container(border=True):
        st.subheader("Passo 1 — Receber codigo")

        email = st.text_input(
            "Seu email",
            value=email_enviado,
            placeholder="financeiro@grupolle.com.br",
            key="login_supabase_email_input",
        )

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("Enviar codigo", type="primary", use_container_width=True):
                with st.spinner("Enviando..."):
                    r = send_email_otp(email)
                if r["ok"]:
                    st.success(f"Codigo enviado para {email}. Confira sua caixa de entrada.")
                    st.rerun()
                else:
                    st.error(f"Falha ao enviar: {r['erro']}")

    # ETAPA 2 — Digitar codigo
    if email_enviado:
        with st.container(border=True):
            st.subheader("Passo 2 — Digitar codigo")
            st.caption(f"Codigo enviado para {email_enviado}. Codigo tem 6 digitos e expira em 10 minutos.")

            codigo = st.text_input(
                "Codigo",
                placeholder="000000",
                max_chars=6,
                key="login_supabase_codigo_input",
            )

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("Entrar", type="primary", use_container_width=True):
                    if not codigo:
                        st.error("Digite o codigo recebido.")
                    else:
                        with st.spinner("Verificando..."):
                            r = verify_email_otp(email_enviado, codigo)
                        if r["ok"]:
                            st.success("Login com sucesso.")
                            st.rerun()
                        else:
                            st.error(f"Falha: {r['erro']}")
            with col2:
                if st.button("Reenviar", use_container_width=True):
                    with st.spinner("Reenviando..."):
                        r = send_email_otp(email_enviado)
                    if r["ok"]:
                        st.success("Novo codigo enviado.")
                    else:
                        st.error(r["erro"])


def render():
    """Renderiza a pagina de login Supabase."""
    st.title("Login Supabase (teste)")
    st.caption("Tela temporaria da Parte 1.3.B da Fase 1 — MVP-A. Testando login por Email OTP.")

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
        st.write("**Session state keys:**", [k for k in st.session_state.keys() if "supabase" in k.lower()])


if __name__ == "__main__":
    render()
