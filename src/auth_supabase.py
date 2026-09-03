"""
src/auth_supabase.py — v5 (email + senha)

Autenticacao via Supabase Auth com email + senha (fluxo tradicional).
Sem magic link, sem OTP, sem redirect.
"""

from __future__ import annotations

import streamlit as st

from src.supabase_client import get_supabase, is_supabase_configured


SESSION_KEY = "supabase_session"
USER_KEY = "supabase_user"
PROFILE_KEY = "supabase_profile"


def _derivar_nome_do_email(email: str) -> str:
    """
    Deriva um nome amigável do email quando não há perfil cadastrado.
    Exemplos:
        debora.silva@grupolle.com.br  -> "Débora Silva"
        conciliacao@grupolle.com.br   -> "Conciliação"
        fernanda.lopes@grupolle.com.br -> "Fernanda Lopes"
    """
    if not email or "@" not in email:
        return "Usuário"

    # Mapa de nomes conhecidos para preservar acentuação correta
    conhecidos = {
        "debora.silva": "Débora Silva",
        "debora.azevedo": "Débora Azevedo",
        "conciliacao": "Conciliação",
        "financeiro": "Financeiro",
        "fernanda.lopes": "Fernanda Lopes",
        "vanderson": "Vanderson",
        "beatriz": "Beatriz",
        "viviane": "Viviane",
    }

    parte_local = email.split("@", 1)[0].strip().lower()
    if parte_local in conhecidos:
        return conhecidos[parte_local]

    # Genérico: separa por . _ - e capitaliza cada palavra
    import re
    palavras = re.split(r"[._\-]+", parte_local)
    if not palavras:
        return "Usuário"
    return " ".join(p.capitalize() for p in palavras if p)


def sign_in_with_password(email: str, password: str) -> dict:
    """Autentica com email + senha. Retorna dict com resultado."""
    if not is_supabase_configured():
        return {"ok": False, "erro": "Supabase nao configurado."}

    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "erro": "Email invalido."}

    if not password:
        return {"ok": False, "erro": "Senha obrigatoria."}

    try:
        sb = get_supabase()
        resp = sb.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        session = resp.session
        user = resp.user

        if session is None or user is None:
            return {"ok": False, "erro": "Credenciais invalidas."}

        # Guarda sessao no state
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
            # Sem perfil cadastrado — derivar nome amigável do email
            # (ex: "debora.silva@grupolle.com.br" -> "Débora Silva")
            nome_derivado = _derivar_nome_do_email(user.email or "")
            st.session_state[PROFILE_KEY] = {
                "id": user.id,
                "nome_completo": nome_derivado,
                "perfil": "Colaborador",
                "ativo": True,
                "_erro_perfil": str(e_perfil),
            }

        return {"ok": True}
    except Exception as e:
        msg = str(e)
        # Traduzir erros comuns
        if "invalid" in msg.lower() and "credential" in msg.lower():
            return {"ok": False, "erro": "Email ou senha incorretos."}
        if "email not confirmed" in msg.lower():
            return {"ok": False, "erro": "Email nao confirmado. Fale com o admin."}
        return {"ok": False, "erro": f"{type(e).__name__}: {msg}"}


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
    for k in (SESSION_KEY, USER_KEY, PROFILE_KEY):
        if k in st.session_state:
            del st.session_state[k]
