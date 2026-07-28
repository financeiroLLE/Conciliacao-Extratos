"""
src/supabase_client.py

Cliente Supabase para a Plataforma de Conciliacao Financeira.

Filosofia:
- Uma instancia unica (cacheada) por sessao Streamlit.
- Credenciais vem dos Secrets do Streamlit Cloud (nunca em codigo).
- Funciona sem quebrar o app se Supabase estiver indisponivel.
- Erros de conexao sao tratados com mensagem clara para o usuario.

Uso basico:
    from src.supabase_client import get_supabase, is_supabase_configured

    if is_supabase_configured():
        sb = get_supabase()
        result = sb.table("adquirentes").select("*").execute()
"""

from __future__ import annotations

import streamlit as st

try:
    from supabase import Client, create_client
    _SUPABASE_LIB_OK = True
except ImportError:
    Client = None  # type: ignore
    create_client = None  # type: ignore
    _SUPABASE_LIB_OK = False


def is_supabase_configured() -> bool:
    """
    Retorna True se os Secrets do Streamlit tem as credenciais do Supabase.
    Nao levanta excecao se nao tiver — devolve False silenciosamente.
    """
    if not _SUPABASE_LIB_OK:
        return False
    try:
        cfg = st.secrets.get("supabase", {})
        return bool(cfg.get("url") and cfg.get("anon_key"))
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    """
    Retorna cliente Supabase inicializado.
    Cacheado por sessao (nao recria a cada rerun).

    Levanta RuntimeError se as credenciais nao estiverem configuradas.
    """
    if not _SUPABASE_LIB_OK:
        raise RuntimeError(
            "Biblioteca 'supabase' nao instalada. "
            "Verificar requirements.txt."
        )

    cfg = st.secrets.get("supabase", {})
    url = cfg.get("url")
    key = cfg.get("anon_key")

    if not url or not key:
        raise RuntimeError(
            "Credenciais do Supabase nao encontradas em Secrets. "
            "Adicione [supabase] url e anon_key no painel do Streamlit Cloud."
        )

    return create_client(url, key)


def testar_conexao() -> dict:
    """
    Testa a conexao com Supabase fazendo uma consulta simples.
    Retorna dict com resultado:
        {"ok": True, "detalhes": {...}}
        {"ok": False, "erro": "mensagem"}
    """
    if not is_supabase_configured():
        return {
            "ok": False,
            "erro": "Credenciais nao configuradas nos Secrets do Streamlit.",
        }

    try:
        sb = get_supabase()
        # Consulta simples que qualquer usuario anonimo autenticado pode fazer:
        # ler adquirentes (SELECT tem policy 'true' pra authenticated).
        # Como estamos como anon, essa query pode falhar por RLS — o que ja
        # confirma que o Supabase esta respondendo.
        result = sb.table("adquirentes").select("nome, codigo_interno, ativa").execute()

        return {
            "ok": True,
            "detalhes": {
                "registros_lidos": len(result.data) if result.data else 0,
                "dados": result.data,
            },
        }
    except Exception as e:
        return {
            "ok": False,
            "erro": f"{type(e).__name__}: {e}",
        }
