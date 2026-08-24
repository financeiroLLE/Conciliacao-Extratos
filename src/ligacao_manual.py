# -*- coding: utf-8 -*-
"""
src/ligacao_manual.py — Bloco 1 · Ligação Manual Justificada

Persistência das ligações manuais no Supabase (tabela cv_ligacao_manual).

Convenção do projeto:
    - Usa get_supabase() e is_supabase_configured() do src/supabase_client.py
    - Se o Supabase estiver fora, funções retornam vazio de forma elegante
      (sem crashar o app).
    - Chave lógica da ligação: (adquirente, nsu, autorizacao) — a mesma
      que _chave_venda_original() do conciliacao_vendas.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

from src.supabase_client import get_supabase, is_supabase_configured


# ==============================================================================
# HELPERS
# ==============================================================================

def _norm(v) -> str:
    """Normaliza um componente da chave (aceita None, número, string)."""
    if v is None:
        return ""
    return str(v).strip()


def _chave(adquirente, nsu, autorizacao) -> Tuple[str, str, str]:
    return (_norm(adquirente), _norm(nsu), _norm(autorizacao))


def _email_usuario_logado() -> Optional[str]:
    """
    Tenta descobrir o email do usuário na sessão.

    Aceita várias convenções que o app pode ter usado ao longo do tempo:
    'usuario_email', 'user_email', 'email', dentro de 'user' etc.
    Se não achar, retorna None (e a operação vai falhar com mensagem clara).
    """
    ss = st.session_state
    # tentativas diretas
    for k in ("usuario_email", "user_email", "email", "sb_user_email"):
        v = ss.get(k)
        if v and isinstance(v, str):
            return v.strip().lower()

    # dentro de um dict 'user'
    user = ss.get("user")
    if isinstance(user, dict):
        for k in ("email", "user_email"):
            v = user.get(k)
            if v and isinstance(v, str):
                return v.strip().lower()

    # dentro de um objeto com atributo email
    for k in ("sb_user", "supabase_user", "auth_user"):
        u = ss.get(k)
        if u is None:
            continue
        v = getattr(u, "email", None) if not isinstance(u, dict) else u.get("email")
        if v and isinstance(v, str):
            return v.strip().lower()

    return None


# ==============================================================================
# LEITURA
# ==============================================================================

def listar_ativas() -> List[Dict[str, Any]]:
    """
    Retorna todas as ligações manuais ATIVAS (não desfeitas).
    Usada ao entrar na tela de conciliação para reidratar o session_state.
    """
    if not is_supabase_configured():
        return []
    try:
        sb = get_supabase()
        res = sb.table("cv_ligacao_manual") \
                .select("*") \
                .eq("ativo", True) \
                .order("criado_em", desc=True) \
                .execute()
        return list(res.data or [])
    except Exception as e:
        # Log silencioso para não quebrar a tela
        st.session_state["_cv_lig_erro_leitura"] = f"{type(e).__name__}: {e}"
        return []


def buscar_por_venda(adquirente, nsu, autorizacao) -> Optional[Dict[str, Any]]:
    """
    Busca a ligação ATIVA de uma venda específica.
    Retorna None se não existir ou se Supabase estiver indisponível.
    """
    if not is_supabase_configured():
        return None
    adq, nsu_n, auth_n = _chave(adquirente, nsu, autorizacao)
    try:
        sb = get_supabase()
        res = sb.table("cv_ligacao_manual") \
                .select("*") \
                .eq("adquirente", adq) \
                .eq("nsu", nsu_n) \
                .eq("autorizacao", auth_n) \
                .eq("ativo", True) \
                .limit(1) \
                .execute()
        dados = list(res.data or [])
        return dados[0] if dados else None
    except Exception:
        return None


def chaves_vendas_ligadas_manualmente() -> set:
    """
    Set de chaves (adquirente, nsu, autorizacao) já ligadas manualmente
    e ativas. Usado para filtrar vendas dos pills "sem par" e "ambíguos".
    """
    return {
        (_norm(r.get("adquirente")), _norm(r.get("nsu")), _norm(r.get("autorizacao")))
        for r in listar_ativas()
    }


# ==============================================================================
# ESCRITA
# ==============================================================================

def salvar(
    adquirente,
    nsu,
    autorizacao,
    justificativa: str,
    referencia_sankhya: str = "",
    venda_contexto: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Cria uma ligação manual nova.
    Se já existir ativa para essa venda, atualiza (edição).

    Args:
        adquirente, nsu, autorizacao: identificadores da venda
        justificativa: obrigatória, mínimo 10 caracteres
        referencia_sankhya: opcional
        venda_contexto: dict com valor_total, data, bandeira, modalidade, parcelas

    Returns:
        (sucesso, mensagem)
    """
    if not is_supabase_configured():
        return (False, "Supabase não configurado — ligação manual não será persistida.")

    just = (justificativa or "").strip()
    if len(just) < 10:
        return (False, "A justificativa precisa ter pelo menos 10 caracteres.")

    email = _email_usuario_logado()
    if not email:
        return (False, "Não foi possível identificar o usuário logado. "
                       "Refaça o login e tente novamente.")

    adq, nsu_n, auth_n = _chave(adquirente, nsu, autorizacao)
    ref = (referencia_sankhya or "").strip() or None
    ctx = venda_contexto or {}

    payload = {
        "adquirente": adq,
        "nsu": nsu_n,
        "autorizacao": auth_n,
        "justificativa": just,
        "referencia_sankhya": ref,
        "venda_valor_total": _to_num(ctx.get("valor_total")),
        "venda_data": _to_data_iso(ctx.get("data")),
        "venda_bandeira": _norm_or_none(ctx.get("bandeira")),
        "venda_modalidade": _norm_or_none(ctx.get("modalidade")),
        "venda_parcelas": _to_int(ctx.get("parcelas")),
        "criado_por": email,
        "ativo": True,
    }

    try:
        sb = get_supabase()

        # Se já existir ativa, faz update (edição)
        existente = buscar_por_venda(adq, nsu_n, auth_n)
        if existente:
            update_payload = {
                "justificativa": just,
                "referencia_sankhya": ref,
                "editado_por": email,
                "editado_em": "now()",
            }
            sb.table("cv_ligacao_manual") \
              .update(update_payload) \
              .eq("id", existente["id"]) \
              .execute()
            return (True, "Ligação atualizada.")

        # Nova
        sb.table("cv_ligacao_manual").insert(payload).execute()
        return (True, "Ligação registrada.")
    except Exception as e:
        return (False, f"Erro ao salvar: {type(e).__name__}: {e}")


def editar_justificativa(
    adquirente,
    nsu,
    autorizacao,
    nova_justificativa: str,
    nova_referencia: Optional[str] = None,
) -> Tuple[bool, str]:
    """Atualiza justificativa e (opcionalmente) referência de uma ligação ativa."""
    if not is_supabase_configured():
        return (False, "Supabase não configurado.")

    just = (nova_justificativa or "").strip()
    if len(just) < 10:
        return (False, "A justificativa precisa ter pelo menos 10 caracteres.")

    email = _email_usuario_logado()
    if not email:
        return (False, "Usuário não identificado.")

    existente = buscar_por_venda(adquirente, nsu, autorizacao)
    if not existente:
        return (False, "Ligação ativa não encontrada para essa venda.")

    update_payload = {
        "justificativa": just,
        "editado_por": email,
        "editado_em": "now()",
    }
    if nova_referencia is not None:
        ref = nova_referencia.strip() or None
        update_payload["referencia_sankhya"] = ref

    try:
        sb = get_supabase()
        sb.table("cv_ligacao_manual") \
          .update(update_payload) \
          .eq("id", existente["id"]) \
          .execute()
        return (True, "Justificativa atualizada.")
    except Exception as e:
        return (False, f"Erro ao editar: {type(e).__name__}: {e}")


def desfazer(
    adquirente,
    nsu,
    autorizacao,
    motivo: str = "",
) -> Tuple[bool, str]:
    """Marca a ligação como inativa (soft-delete, preserva histórico)."""
    if not is_supabase_configured():
        return (False, "Supabase não configurado.")

    email = _email_usuario_logado()
    if not email:
        return (False, "Usuário não identificado.")

    existente = buscar_por_venda(adquirente, nsu, autorizacao)
    if not existente:
        return (False, "Ligação ativa não encontrada.")

    try:
        sb = get_supabase()
        sb.table("cv_ligacao_manual") \
          .update({
              "ativo": False,
              "desfeito_por": email,
              "desfeito_em": "now()",
              "desfeito_motivo": (motivo or "").strip() or None,
          }) \
          .eq("id", existente["id"]) \
          .execute()
        return (True, "Ligação desfeita.")
    except Exception as e:
        return (False, f"Erro ao desfazer: {type(e).__name__}: {e}")


# ==============================================================================
# HELPERS DE CONVERSÃO
# ==============================================================================

def _to_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _norm_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _to_data_iso(v):
    """Converte date/datetime/Timestamp/string para YYYY-MM-DD, ou None."""
    if v is None or v == "":
        return None
    # date/datetime/Timestamp
    if hasattr(v, "strftime"):
        try:
            return v.strftime("%Y-%m-%d")
        except Exception:
            pass
    # string
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # Já ISO?
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        # dd/mm/yyyy?
        if len(s) == 10 and s[2] == "/" and s[5] == "/":
            try:
                d, m, y = s.split("/")
                return f"{y}-{m}-{d}"
            except ValueError:
                return None
    return None
