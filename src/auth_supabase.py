"""
src/auth_supabase.py — v3 (PKCE)

Fluxo PKCE:
1. Usuario digita email na tela
2. sign_in_with_otp com email_redirect_to
3. Supabase manda link
4. Usuario clica no link
5. Supabase redireciona pra REDIRECT_URL?code=XXX (query param, nao fragment!)
6. login_supabase.py detecta code em st.query_params
7. Chama exchange_code_for_session(code)
8. Sessao criada
"""

from __future__ import annotations

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


def exchange_code_for_session(code: str) -> dict:
    """Troca o 'code' do URL de retorno por uma sessao ativa (PKCE)."""
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao configurado."}
    if not code:
        return {"ok": False, "erro": "Code faltando."}

    try:
        sb = get_supabase()
        resp = sb.auth.exchange_code_for_session({"auth_code": code})

        session = resp.session
        user = resp.user

        if session is None or user is None:
            return {"ok": False, "erro": "Falha na troca de code por sessao."}

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
