"""
src/supabase_client.py — v3 (PKCE flow)
"""

from __future__ import annotations

import streamlit as st

try:
    from supabase import Client, create_client
    from supabase.lib.client_options import ClientOptions
    _SUPABASE_LIB_OK = True
except ImportError:
    Client = None
    create_client = None
    ClientOptions = None
    _SUPABASE_LIB_OK = False


def is_supabase_configured() -> bool:
    if not _SUPABASE_LIB_OK:
        return False
    try:
        cfg = st.secrets.get("supabase", {})
        return bool(cfg.get("url") and cfg.get("anon_key"))
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    if not _SUPABASE_LIB_OK:
        raise RuntimeError("Biblioteca 'supabase' nao instalada.")

    cfg = st.secrets.get("supabase", {})
    url = cfg.get("url")
    key = cfg.get("anon_key")

    if not url or not key:
        raise RuntimeError("Credenciais do Supabase nao encontradas em Secrets.")

    try:
        options = ClientOptions(flow_type="pkce")
        return create_client(url, key, options=options)
    except Exception:
        return create_client(url, key)


def testar_conexao() -> dict:
    if not is_supabase_configured():
        return {"ok": False, "erro": "Credenciais nao configuradas."}
    try:
        sb = get_supabase()
        result = sb.table("adquirentes").select("nome, codigo_interno, ativa").execute()
        return {"ok": True, "detalhes": {
            "registros_lidos": len(result.data) if result.data else 0,
            "dados": result.data,
        }}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}
