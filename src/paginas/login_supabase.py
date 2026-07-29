"""
src/paginas/login_supabase.py — v7 (visual proporcional com logo oficial)

Tela de login oficial do app (email + senha via Supabase Auth).
Usa o mesmo card institucional que aparece na sidebar do app.
"""

import base64
from pathlib import Path

import streamlit as st

from src.auth_supabase import (
    current_user,
    is_admin,
    is_logged_in,
    sign_in_with_password,
    sign_out,
)


# Caminho absoluto para a pasta assets (na raiz do repo)
_ASSETS = Path(__file__).parent.parent.parent / "assets"


@st.cache_data
def _logo_data_uri() -> str:
    """Retorna a logo PNG (com fundo transparente) como data URI."""
    for nome in ("logo-grupo-lle-transparente.png", "logo-grupo-lle-branco.png"):
        arq = _ASSETS / nome
        if arq.exists():
            b64 = base64.b64encode(arq.read_bytes()).decode("ascii")
            return f"data:image/png;base64,{b64}"
    return ""


_CSS = """
<style>
  /* Fundo geral navy */
  .stApp {
    background: #0A1730;
  }
  /* Container principal centralizado e estreito */
  section.main > div.block-container {
    max-width: 420px;
    padding-top: 4rem;
  }
  /* Cartao institucional (proporcional, mesmo estilo da sidebar) */
  .lle-login-card {
    background: #0A1730;
    border: 2px solid #FFCC00;
    border-radius: 14px;
    padding: 20px 24px 18px 24px;
    text-align: center;
    margin-bottom: 24px;
  }
  .lle-login-card img {
    max-width: 140px;
    height: auto;
    margin-bottom: 10px;
  }
  .lle-login-card .subtitle {
    color: #FFCC00;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 2.5px;
    margin-top: 6px;
  }
  /* Titulo do form */
  .lle-form-title {
    color: #FFF6C8;
    font-size: 13px;
    font-weight: 500;
    text-align: center;
    margin-bottom: 12px;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  /* Labels dos inputs */
  .stTextInput label p {
    color: #FFF6C8 !important;
    font-size: 12px !important;
    font-weight: 500 !important;
  }
  /* Inputs */
  .stTextInput input {
    background: #FFF6C8 !important;
    color: #0A1730 !important;
    border: 1px solid #FFCC00 !important;
    border-radius: 6px !important;
  }
  /* Botao entrar */
  .stButton > button[kind="primary"] {
    background: #FFCC00 !important;
    color: #0A1730 !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 8px !important;
    padding: 8px !important;
  }
  .stButton > button[kind="primary"]:hover {
    background: #FFD833 !important;
  }
  /* Botao sair (secondary) */
  .stButton > button[kind="secondary"] {
    background: transparent !important;
    color: #FFF6C8 !important;
    border: 1px solid #FFCC00 !important;
    border-radius: 8px !important;
  }
  /* Mensagens */
  .lle-info-line {
    color: #FFF6C8;
    font-size: 13px;
    margin: 4px 0;
    text-align: center;
  }
  .lle-info-line strong {
    color: #FFCC00;
  }
</style>
"""


def _render_topo():
    logo = _logo_data_uri()
    st.markdown(_CSS, unsafe_allow_html=True)

    if logo:
        st.markdown(
            f"""
            <div class="lle-login-card">
              <img src="{logo}" alt="Grupo LLE" />
              <div class="subtitle">CONCILIAÇÃO FINANCEIRA</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        # Fallback caso a logo nao seja encontrada
        st.markdown(
            """
            <div class="lle-login-card">
              <div style="color:#FFCC00;font-size:20px;font-weight:700;letter-spacing:1px;">GRUPO LLE</div>
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
        <div class="lle-info-line"><strong>{user.get('nome_completo', '-')}</strong></div>
        <div class="lle-info-line">{user.get('email', '-')}</div>
        <div class="lle-info-line">Perfil: {user.get('perfil', '-')}</div>
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
    st.markdown('<div class="lle-form-title">Entrar</div>', unsafe_allow_html=True)

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
