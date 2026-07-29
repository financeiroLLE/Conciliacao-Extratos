"""
src/paginas/login_supabase.py — v6 (visual definitivo)

Tela de login oficial do app (email + senha via Supabase Auth).
"""

import streamlit as st

from src.auth_supabase import (
    current_user,
    is_admin,
    is_logged_in,
    sign_in_with_password,
    sign_out,
)


_CSS = """
<style>
  /* Fundo geral */
  .stApp {
    background: #0A1730;
  }
  /* Container principal centralizado */
  section.main > div.block-container {
    max-width: 480px;
    padding-top: 2rem;
  }
  /* Cartao institucional */
  .lle-card {
    background: #FFCC00;
    border-radius: 14px;
    padding: 24px 28px;
    text-align: center;
    margin-bottom: 24px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
  }
  .lle-card h1 {
    color: #0A1730;
    font-size: 24px;
    font-weight: 700;
    margin: 0 0 4px 0;
    letter-spacing: 1px;
  }
  .lle-card .subtitle {
    color: #0A1730;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 2px;
  }
  /* Formulario */
  .stTextInput label {
    color: #FFF6C8 !important;
    font-weight: 500;
  }
  .stTextInput input {
    background: #FFF6C8 !important;
    color: #0A1730 !important;
    border: none !important;
  }
  /* Botao entrar */
  .stButton > button[kind="primary"] {
    background: #FFCC00 !important;
    color: #0A1730 !important;
    font-weight: 600 !important;
    border: none !important;
    padding: 10px !important;
  }
  .stButton > button[kind="primary"]:hover {
    background: #FFD833 !important;
  }
  /* Info logado */
  .lle-info-row {
    color: #FFF6C8;
    font-size: 13px;
    margin: 4px 0;
  }
  .lle-info-row strong {
    color: #FFCC00;
  }
</style>
"""


def _render_topo():
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="lle-card">
          <h1>GRUPO LLE</h1>
          <div class="subtitle">CONCILIAÇÃO FINANCEIRA</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_ja_logado():
    user = current_user()
    st.success("Sessão ativa")
    st.markdown(
        f"""
        <div class="lle-info-row"><strong>Nome:</strong> {user.get('nome_completo', '-')}</div>
        <div class="lle-info-row"><strong>Email:</strong> {user.get('email', '-')}</div>
        <div class="lle-info-row"><strong>Perfil:</strong> {user.get('perfil', '-')}</div>
        """,
        unsafe_allow_html=True,
    )
    if user.get("_erro_perfil"):
        st.warning(f"Perfil não encontrado: {user['_erro_perfil']}")

    st.divider()
    if st.button("Sair", type="secondary", use_container_width=True):
        sign_out()
        st.rerun()


def _render_form_login():
    email = st.text_input(
        "Email",
        placeholder="seuemail@grupolle.com.br",
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
    _render_topo()

    if is_logged_in():
        _render_ja_logado()
    else:
        _render_form_login()


if __name__ == "__main__":
    render()
