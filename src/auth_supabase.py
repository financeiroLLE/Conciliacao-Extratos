"""
src/auth_supabase.py — v4 (parse de URL colada)
"""

from __future__ import annotations

from urllib.parse import urlparse, parse_qs

import streamlit as st

from src.supabase_client import get_supabase, is_supabase_configured


SESSION_KEY = "supabase_session"
USER_KEY = "supabase_user"
PROFILE_KEY = "supabase_profile"
OTP_SENT_KEY = "supabase_otp_sent_to"

REDIRECT_URL = "https://conciliacao-extratos.streamlit.app/?page=login_supabase"


def send_magic_link(email: str) -> dict:
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao configurado."}

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


def extrair_tokens_da_url(url_colada: str) -> dict:
    """Extrai access_token e refresh_token de uma URL colada.
    A URL vem no formato: https://.../?page=login_supabase#access_token=X&refresh_token=Y&...
    Retorna: {"ok": True, "access_token": "...", "refresh_token": "..."} ou {"ok": False, "erro": "..."}
    """
    if not url_colada or not url_colada.strip():
        return {"ok": False, "erro": "URL vazia."}

    try:
        parsed = urlparse(url_colada.strip())
        # Fragmento vem depois do #
        fragment = parsed.fragment
        if not fragment:
            return {"ok": False, "erro": "URL nao tem fragment (#access_token=...). Certifique-se de copiar a URL COMPLETA da barra de enderecos apos clicar no link do email."}

        params = parse_qs(fragment)
        access_token = params.get("access_token", [None])[0]
        refresh_token = params.get("refresh_token", [None])[0]

        if not access_token or not refresh_token:
            return {"ok": False, "erro": "URL nao contem access_token e refresh_token. Voce colou a URL correta?"}

        return {
            "ok": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    except Exception as e:
        return {"ok": False, "erro": f"Erro ao processar URL: {e}"}


def set_session_from_tokens(access_token: str, refresh_token: str) -> dict:
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao configurado."}
    if not access_token or not refresh_token:
        return {"ok": False, "erro": "Tokens faltando."}

    try:
        sb = get_supabase()
        resp = sb.auth.set_session(access_token, refresh_token)

        session = resp.session
        user = resp.user

        if session is None or user is None:
            return {"ok": False, "erro": "Falha ao criar sessao."}

        st.session_state[SESSION_KEY] = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
        }
        st.session_state[USER_KEY] = {
            "id": user.id,
            "email": user.email,
        }

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

        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}


def is_logged_in() -> bool:
    return (
        SESSION_KEY in st.session_state
        and USER_KEY in st.session_state
        and PROFILE_KEY in st.session_state
    )


def current_user() -> dict | None:
    if not is_logged_in():
        return None
    return {**st.session_state[USER_KEY], **st.session_state[PROFILE_KEY]}


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
