"""
src/auth_supabase.py

Autenticacao via Supabase Auth com Email OTP (login sem senha).

Fluxo:
1. Usuario digita email na tela de login
2. Sistema chama send_email_otp(email) -> Supabase envia codigo por email
3. Usuario recebe codigo de 6 digitos no email
4. Usuario digita codigo na tela
5. Sistema chama verify_email_otp(email, codigo)
6. Se OK, sessao Supabase e criada e guardada no session_state

Filosofia:
- Nao quebra login antigo (streamlit-authenticator) — coexistem
- Sessao Supabase fica em st.session_state["supabase_session"]
- Perfil do usuario (admin/analista/consulta) vem da tabela public.usuarios
"""

from __future__ import annotations

import streamlit as st

from src.supabase_client import get_supabase, is_supabase_configured


# ============================================================
# Chaves de sessao
# ============================================================
SESSION_KEY = "supabase_session"
USER_KEY = "supabase_user"
PROFILE_KEY = "supabase_profile"
OTP_SENT_KEY = "supabase_otp_sent_to"


# ============================================================
# Envio e verificacao de OTP
# ============================================================

def send_email_otp(email: str) -> dict:
    """Solicita ao Supabase que envie um codigo OTP por email.

    Retorna:
        {"ok": True} se enviou com sucesso
        {"ok": False, "erro": "..."} se falhou
    """
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao esta configurado nos Secrets."}

    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "erro": "Email invalido."}

    try:
        sb = get_supabase()
        # sign_in_with_otp envia codigo por email (nao envia link magico se
        # a config do provider tiver 'Enable email OTP' ligado, que ja
        # configuramos na Parte 1.3.A)
        # should_create_user=False: nao cria novo usuario; so autentica
        # os que ja existem em auth.users
        sb.auth.sign_in_with_otp({
            "email": email,
            "options": {
                "should_create_user": False,
            },
        })
        # Guarda em session_state pra proxima tela lembrar o email
        st.session_state[OTP_SENT_KEY] = email
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}


def verify_email_otp(email: str, codigo: str) -> dict:
    """Verifica o codigo OTP digitado pelo usuario.

    Se valido, guarda a sessao Supabase em st.session_state.

    Retorna:
        {"ok": True, "user": {...}, "profile": {...}}
        {"ok": False, "erro": "..."}
    """
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao esta configurado."}

    email = (email or "").strip().lower()
    codigo = (codigo or "").strip()

    if not email or not codigo:
        return {"ok": False, "erro": "Email e codigo sao obrigatorios."}

    if not codigo.isdigit() or len(codigo) != 6:
        return {"ok": False, "erro": "Codigo deve ter exatamente 6 digitos."}

    try:
        sb = get_supabase()
        resp = sb.auth.verify_otp({
            "email": email,
            "token": codigo,
            "type": "email",
        })

        # Se chegou aqui sem exception, deu certo
        session = resp.session
        user = resp.user

        if session is None or user is None:
            return {"ok": False, "erro": "Falha na autenticacao. Codigo invalido ou expirado."}

        # Guarda sessao no state
        st.session_state[SESSION_KEY] = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
        }
        st.session_state[USER_KEY] = {
            "id": user.id,
            "email": user.email,
        }

        # Busca perfil da tabela public.usuarios
        # Nota: nesse ponto o cliente esta autenticado, entao o RLS
        # deixa ler o proprio perfil (policy usuarios_select_self)
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
            # Usuario existe em auth.users mas nao em public.usuarios
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
    """Retorna True se o usuario tem sessao Supabase valida."""
    return (
        SESSION_KEY in st.session_state
        and USER_KEY in st.session_state
        and PROFILE_KEY in st.session_state
    )


def current_user() -> dict | None:
    """Retorna dict com dados do usuario logado, ou None."""
    if not is_logged_in():
        return None
    return {
        **st.session_state[USER_KEY],
        **st.session_state[PROFILE_KEY],
    }


def is_admin() -> bool:
    """True se o usuario logado tem perfil admin."""
    if not is_logged_in():
        return False
    return st.session_state.get(PROFILE_KEY, {}).get("perfil") == "admin"


def sign_out() -> None:
    """Encerra a sessao Supabase (limpa state)."""
    try:
        if is_supabase_configured():
            sb = get_supabase()
            sb.auth.sign_out()
    except Exception:
        pass

    for k in (SESSION_KEY, USER_KEY, PROFILE_KEY, OTP_SENT_KEY):
        if k in st.session_state:
            del st.session_state[k]
