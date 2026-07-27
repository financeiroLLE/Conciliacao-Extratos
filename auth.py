"""v6.0.1 — Camada de autenticação do app Conciliação LLE.

Visual premium (Opção 3 aprovada pela Débora): gradiente radial de fundo,
card do form com blur/sombra, detalhes amarelos e linhas decorativas.

Usa `streamlit-authenticator` (bcrypt) com credenciais em `st.secrets`.
Cookie de 1 dia (segurança).

Como usar (no início do app.py, depois de st.set_page_config):

    from auth import autenticar
    nome, usuario = autenticar()

Config esperada em st.secrets (painel Streamlit Cloud → Settings → Secrets):

    [auth]
    cookie_name = "conciliacao_lle_auth"
    cookie_key = "<chave-secreta-longa>"
    cookie_expiry_days = 1

    [auth.credentials.usernames.debora]
    name = "Débora Azevedo"
    email = "debora@grupolle.com.br"
    password = "$2b$12$..."
    failed_login_attempts = 0
    logged_in = false
"""
from __future__ import annotations

import streamlit as st

try:
    import streamlit_authenticator as stauth
    _STAUTH_OK = True
except ImportError:
    _STAUTH_OK = False


_CSS_LOGIN = """
<style>
/* fundo com gradiente radial */
[data-testid="stAppViewContainer"] > .main {
    background: radial-gradient(ellipse at top, #142049 0%, #0A1730 60%) !important;
    min-height: 100vh;
}
[data-testid="stHeader"] { background: transparent !important; }

/* linhas decorativas amarelas topo/base */
[data-testid="stAppViewContainer"] > .main::before {
    content: ""; position: fixed; top: 30px; left: 30px; right: 30px;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,204,0,0.3), transparent);
    z-index: 1;
}
[data-testid="stAppViewContainer"] > .main::after {
    content: ""; position: fixed; bottom: 30px; left: 30px; right: 30px;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(255,204,0,0.3), transparent);
    z-index: 1;
}

.lle-login-wrap { max-width: 440px; margin: 0 auto; padding: 20px 0 10px; }
.lle-login-header { text-align: center; margin-bottom: 24px; }
.lle-login-logo {
    width: 64px; height: 64px;
    background: linear-gradient(135deg, #FFCC00 0%, #F9C74F 100%);
    border-radius: 14px;
    display: inline-flex; align-items: center; justify-content: center;
    color: #0A1730; font-weight: 800; font-size: 26px;
    box-shadow: 0 8px 24px rgba(255,204,0,0.25);
    margin-bottom: 14px;
}
.lle-login-title { color: #E6EEF8; font-size: 18px; font-weight: 700; letter-spacing: 0.5px; }
.lle-login-sub { color: #9fb3d6; font-size: 11px; margin-top: 2px; }
.lle-login-acesso {
    color: #FFCC00; font-size: 10px; letter-spacing: 2.5px; font-weight: 800;
    text-align: center; margin-bottom: 6px;
}
.lle-login-entre { color: #E6EEF8; font-size: 14px; text-align: center; margin-bottom: 20px; }

/* CARD do form (streamlit-authenticator usa st.form internamente) */
[data-testid="stForm"] {
    background: linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 100%) !important;
    border: 1px solid rgba(255,204,0,0.2) !important;
    border-radius: 16px !important;
    padding: 24px 32px !important;
    box-shadow: 0 20px 60px rgba(0,0,0,0.4) !important;
    backdrop-filter: blur(20px) !important;
    max-width: 440px;
    margin: 0 auto;
}

/* remove títulos duplicados do form */
[data-testid="stForm"] > div:first-child > div:first-child h3,
[data-testid="stForm"] > div:first-child > div:first-child h2,
[data-testid="stForm"] > div:first-child > div:first-child h1 {
    display: none !important;
}

/* labels amarelos uppercase */
[data-testid="stForm"] label {
    color: #FFCC00 !important;
    font-size: 10px !important;
    letter-spacing: 1.5px !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    margin-bottom: 6px !important;
}

/* inputs fundo escuro + borda amarela esquerda */
[data-testid="stForm"] input {
    background: rgba(0,0,0,0.4) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-left: 3px solid #FFCC00 !important;
    border-radius: 8px !important;
    color: #E6EEF8 !important;
    font-size: 14px !important;
    padding: 12px 14px !important;
}
[data-testid="stForm"] input:focus {
    border-color: rgba(255,255,255,0.15) !important;
    border-left: 3px solid #FFCC00 !important;
    box-shadow: 0 0 0 2px rgba(255,204,0,0.1) !important;
    outline: none !important;
}
[data-testid="stForm"] div[data-baseweb="input"],
[data-testid="stForm"] div[data-baseweb="base-input"] {
    background: transparent !important;
    border: none !important;
}

/* botão gradiente amarelo */
[data-testid="stForm"] .stFormSubmitButton button {
    width: 100% !important;
    padding: 14px !important;
    background: linear-gradient(135deg, #FFCC00 0%, #F9C74F 100%) !important;
    color: #0A1730 !important;
    border: none !important;
    border-radius: 10px !important;
    font-size: 12px !important;
    font-weight: 800 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase;
    cursor: pointer !important;
    box-shadow: 0 6px 20px rgba(255,204,0,0.3) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
[data-testid="stForm"] .stFormSubmitButton button:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 24px rgba(255,204,0,0.4) !important;
}
[data-testid="stForm"] .stFormSubmitButton button p {
    font-weight: 800 !important;
    letter-spacing: 1.5px !important;
    margin: 0 !important;
}

.lle-login-footer {
    text-align: center; margin-top: 20px;
    color: #9fb3d6; font-size: 10px;
}
.lle-login-footer b { color: #FFCC00; }

[data-testid="stAppViewContainer"] > .main .block-container {
    padding-top: 3rem !important;
    padding-bottom: 3rem !important;
    max-width: 560px !important;
}
</style>
"""


def _erro_e_para(mensagem: str) -> None:
    st.error(mensagem)
    st.stop()


def _config_do_secrets() -> dict | None:
    try:
        if "auth" not in st.secrets:
            return None
        cfg = dict(st.secrets["auth"])
        creds_raw = cfg.get("credentials", {})
        creds_dict = {"usernames": {}}
        usernames_raw = creds_raw.get("usernames", {}) if creds_raw else {}
        for user, dados in usernames_raw.items():
            creds_dict["usernames"][user] = dict(dados)
        cfg["credentials"] = creds_dict
        return cfg
    except Exception as e:
        _erro_e_para(f"Erro ao ler configuração de autenticação: {e}")


def autenticar() -> tuple[str | None, str | None]:
    """Bloqueia o app até autenticação. Retorna (nome, username)."""
    if not _STAUTH_OK:
        _erro_e_para(
            "⚠️ Biblioteca `streamlit-authenticator` não está instalada. "
            "Adicione ao `requirements.txt`: streamlit-authenticator>=0.4,<0.5"
        )

    cfg = _config_do_secrets()
    if cfg is None:
        _erro_e_para(
            "🔐 Configuração de autenticação ausente. No painel do Streamlit "
            "Cloud (Settings → Secrets), adicione o bloco `[auth]` conforme "
            "instruções em `auth.py`."
        )

    autenticador = stauth.Authenticate(
        credentials=cfg.get("credentials", {"usernames": {}}),
        cookie_name=cfg.get("cookie_name", "conciliacao_lle_auth"),
        cookie_key=cfg.get("cookie_key", "SEM_CHAVE_CONFIGURADA"),
        cookie_expiry_days=int(cfg.get("cookie_expiry_days", 1)),
    )

    if not st.session_state.get("authentication_status"):
        st.markdown(_CSS_LOGIN, unsafe_allow_html=True)
        st.markdown(
            "<style>[data-testid='stSidebar']{display:none !important;}</style>",
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="lle-login-wrap">
              <div class="lle-login-header">
                <div class="lle-login-logo">LLE</div>
                <div class="lle-login-title">GRUPO LLE</div>
                <div class="lle-login-sub">Conciliação Bancária · v6.0</div>
              </div>
              <div class="lle-login-acesso">◆ ACESSO ◆</div>
              <div class="lle-login-entre">Entre para continuar</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    try:
        autenticador.login(
            location="main",
            fields={
                "Form name": " ",
                "Username": "Usuário",
                "Password": "Senha",
                "Login": "▶  ENTRAR",
            },
        )
    except Exception as e:
        _erro_e_para(f"Erro na autenticação: {e}")

    status = st.session_state.get("authentication_status")
    if status is False:
        st.markdown(
            "<div style='max-width:440px;margin:16px auto 0;text-align:center;"
            "color:#ff6b6b;font-size:12px;'>❌ Usuário ou senha inválidos.</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div class='lle-login-footer'>Problemas? "
            "<b>conciliacao@grupolle.com.br</b></div>",
            unsafe_allow_html=True,
        )
        st.stop()
    if status is None:
        st.markdown(
            "<div class='lle-login-footer'>Problemas? "
            "<b>conciliacao@grupolle.com.br</b></div>",
            unsafe_allow_html=True,
        )
        st.stop()

    nome = st.session_state.get("name") or ""
    username = st.session_state.get("username") or ""
    with st.sidebar:
        st.markdown(
            f"<div style='padding:8px 0 4px; color:#E6EEF8; font-size:13px;'>"
            f"👤 <b>{nome}</b></div>",
            unsafe_allow_html=True,
        )
        try:
            autenticador.logout("Sair", location="sidebar", key="btn_logout_lle")
        except Exception:
            if st.button("Sair", key="btn_logout_manual"):
                for k in ("authentication_status", "name", "username"):
                    st.session_state.pop(k, None)
                st.rerun()

    return nome, username
