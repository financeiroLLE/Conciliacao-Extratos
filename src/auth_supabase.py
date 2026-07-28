"""
src/auth_supabase.py — v2 (Magic Link com redirect)

Autenticacao via Supabase Auth com Magic Link.

Fluxo:
1. Usuario digita email na tela de login
2. Sistema chama send_magic_link(email) -> Supabase envia link por email
3. Usuario clica no link "Sign in"
4. Supabase valida e redireciona pra REDIRECT_URL com tokens no fragment (#)
5. JavaScript no login_supabase.py move tokens de fragment pra query
6. login_supabase.py chama set_session_from_tokens(access, refresh)
7. Sessao criada, perfil buscado, usuario logado
"""

from __future__ import annotations

import streamlit as st

from src.supabase_client import get_supabase, is_supabase_configured


# ============================================================
# Constantes
# ============================================================
SESSION_KEY = "supabase_session"
USER_KEY = "supabase_user"
PROFILE_KEY = "supabase_profile"
OTP_SENT_KEY = "supabase_otp_sent_to"

# URL para onde o Supabase redireciona apos o clique no link do email
REDIRECT_URL = "https://conciliacao-extratos.streamlit.app/?page=login_supabase"


# ============================================================
# Envio de Magic Link
# ============================================================

def send_magic_link(email: str) -> dict:
    """Solicita ao Supabase que envie um link magico por email."""
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao esta configurado nos Secrets."}

    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "erro": "Email invalido."}

    try:
        sb = get_supabase()
        sb.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "should_create_user": False,
                "email_redirect_to": REDIRECT_URL,
            },
        })
        st.session_state[OTP_SENT_KEY] = email
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}


# ============================================================
# Criacao de sessao a partir de tokens do URL
# ============================================================

def set_session_from_tokens(access_token: str, refresh_token: str) -> dict:
    """Cria sessao Supabase a partir de tokens vindos do URL de retorno."""
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao esta configurado."}

    if not access_token or not refresh_token:
        return {"ok": False, "erro": "Tokens faltando na URL."}

    try:
        sb = get_supabase()
        resp = sb.auth.set_session(access_token, refresh_token)

        session = resp.session
        user = resp.user

        if session is None or user is None:
            return {"ok": False, "erro": "Falha ao criar sessao com os tokens."}

        st.session_state[SESSION_KEY] = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
        }
        st.session_state[USER_KEY] = {
            "id": user.id,
            "email": user.email,
        }

        # Busca perfil na tabela public.usuarios
        try:
            perfil_data = (
                sb.table("usuarios")
                .select("id, nome_completo, perfil, ativo")
                .eq("id", user.id)
                .single()
                .execute()
            )
            st.session_state[PROFILE_KEY] = perfil_data.data
        except Exception as e_perfil:
            st.session_state[PROFILE_KEY] = {
                "id": user.id,
                "nome_completo": "(sem perfil)",
                "perfil": None,
                "ativo": False,
                "_erro_perfil": str(e_perfil),
            }

        return {
            "ok": True,
            "user": st.session_state[USER_KEY],
            "profile": st.session_state[PROFILE_KEY],
        }
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}


# ============================================================
# Sessao — helpers
# ============================================================

def is_logged_in() -> bool:
    return (
        SESSION_KEY in st.session_state
        and USER_KEY in st.session_state
        and PROFILE_KEY in st.session_state
    )


def current_user() -> dict | None:
    if not is_logged_in():
        return None
    return {
        **st.session_state[USER_KEY],
        **st.session_state[PROFILE_KEY],
    }


def is_admin() -> bool:
    if not is_logged_in():
        return False
    return st.session_state.get(PROFILE_KEY, {}).get("perfil") == "admin"


def sign_out() -> None:
    try:
        if is_supabase_configured():
            sb = get_supabase()
            sb.auth.sign_out()
    except Exception:
        pass

    for k in (SESSION_KEY, USER_KEY, PROFILE_KEY, OTP_SENT_KEY):
        if k in st.session_state:
            del st.session_state[k]
