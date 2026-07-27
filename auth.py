"""v6.0 — Camada de autenticação do app Conciliação LLE.

Usa `streamlit-authenticator` (bcrypt) com credenciais armazenadas em
`st.secrets` (fora do repositório GitHub — visível apenas no painel do
Streamlit Cloud). Cookie de 1 dia (renovado a cada login) — decisão da
Débora priorizando segurança.

Como usar (no início do app.py, depois de st.set_page_config):

    from auth import autenticar
    nome, usuario = autenticar()
    # daqui em diante, o resto do app roda só se a usuária estiver logada

Formato esperado do st.secrets (painel Streamlit Cloud → Settings → Secrets):

    [auth]
    cookie_name = "conciliacao_lle_auth"
    cookie_key = "chave-secreta-longa-e-aleatoria-de-32-caracteres-ou-mais"
    cookie_expiry_days = 1

    [auth.credentials.usernames.debora]
    name = "Débora Azevedo"
    email = "debora@grupolle.com.br"
    password = "$2b$12$..."   # hash bcrypt gerado pelo gerar_hash_senha.py
    failed_login_attempts = 0
    logged_in = false

Para adicionar nova pessoa, replique o bloco `[auth.credentials.usernames.<username>]`
com os campos correspondentes.
"""
from __future__ import annotations

import streamlit as st

try:
    import streamlit_authenticator as stauth
    _STAUTH_OK = True
except ImportError:
    _STAUTH_OK = False


def _erro_e_para(mensagem: str) -> None:
    """Mostra erro e interrompe execução do app."""
    st.error(mensagem)
    st.stop()


def _config_do_secrets() -> dict | None:
    """Lê credenciais do st.secrets. Retorna None se ausente."""
    try:
        if "auth" not in st.secrets:
            return None
        cfg = dict(st.secrets["auth"])
        # Streamlit Secrets retorna sub-tabelas como AttrDict — converte pra dict
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
    """Bloqueia o app até a usuária autenticar. Retorna (nome, username)
    da usuária logada; interrompe execução se não autenticada.

    Renderiza tela de login (fundo azul-navy + amarelo, alinhado ao visual
    do app). Depois de logar, mostra 'Olá, <Nome>' + botão Sair na sidebar.
    Cookie de 1 dia — precisa logar de novo no dia seguinte.
    """
    if not _STAUTH_OK:
        _erro_e_para(
            "⚠️ Biblioteca `streamlit-authenticator` não está instalada. "
            "Adicione ao `requirements.txt`:\n\n"
            "    streamlit-authenticator>=0.4,<0.5"
        )

    cfg = _config_do_secrets()
    if cfg is None:
        _erro_e_para(
            "🔐 Configuração de autenticação ausente. No painel do Streamlit "
            "Cloud (Settings → Secrets), adicione o bloco `[auth]` conforme "
            "instruções em `auth.py`."
        )

    # Header institucional acima do form de login (padrão visual do app)
    if not st.session_state.get("authentication_status"):
        st.markdown(
            """
            <div style="text-align:center; padding: 30px 0 10px;">
              <div style="display:inline-flex; align-items:center; gap:14px;">
                <div style="width:52px; height:52px;
                            background:linear-gradient(135deg,#FFCC00 0%,#F9C74F 100%);
                            border-radius:10px; display:flex; align-items:center;
                            justify-content:center; color:#0A1730;
                            font-weight:800; font-size:20px;">LLE</div>
                <div style="text-align:left;">
                  <div style="color:#E6EEF8; font-size:17px; font-weight:600;">
                    GRUPO LLE</div>
                  <div style="color:#9fb3d6; font-size:12px;">
                    Conciliação Bancária</div>
                </div>
              </div>
            </div>
            <div style="text-align:center; margin-top:24px;">
              <span style="color:#FFCC00; font-size:11px; letter-spacing:1.5px;
                           font-weight:700;">ACESSO</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Constrói o autenticador
    autenticador = stauth.Authenticate(
        credentials=cfg.get("credentials", {"usernames": {}}),
        cookie_name=cfg.get("cookie_name", "conciliacao_lle_auth"),
        cookie_key=cfg.get("cookie_key", "SEM_CHAVE_CONFIGURADA"),
        cookie_expiry_days=int(cfg.get("cookie_expiry_days", 1)),
    )

    # Renderiza tela de login (fica visível até autenticar)
    try:
        autenticador.login(
            location="main",
            fields={
                "Form name": "Entre para continuar",
                "Username": "Usuário",
                "Password": "Senha",
                "Login": "Entrar",
            },
        )
    except Exception as e:
        _erro_e_para(f"Erro na autenticação: {e}")

    status = st.session_state.get("authentication_status")
    if status is False:
        st.error("❌ Usuário ou senha inválidos.")
        st.stop()
    if status is None:
        st.markdown(
            "<div style='text-align:center; margin-top:20px; color:#9fb3d6; "
            "font-size:12px;'>Problemas com acesso? Fale com "
            "<b style='color:#FFCC00;'>conciliacao@grupolle.com.br</b></div>",
            unsafe_allow_html=True,
        )
        st.stop()

    # Autenticada — botão Sair na sidebar + saudação
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
            # fallback se a API do stauth for diferente
            if st.button("Sair", key="btn_logout_manual"):
                for k in ("authentication_status", "name", "username"):
                    st.session_state.pop(k, None)
                st.rerun()

    return nome, username
