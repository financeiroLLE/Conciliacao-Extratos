"""
src/rodadas.py — Gerenciamento de rodadas de conciliação no Supabase

Uma "rodada" = uma sessão completa de conciliação com:
- Arquivos brutos (Cielo, Getnet, Sankhya, Auttar, bancários)
- Resultado processado (opcional)
- Métricas de progresso

Retenção automática de 60 dias (via trigger no Supabase).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import streamlit as st


# ==============================================================================
# CONSTANTES
# ==============================================================================
BUCKET = "conciliacao-arquivos"
TABELA = "cv_rodadas"


# ==============================================================================
# DTO
# ==============================================================================
@dataclass
class Rodada:
    id: str
    data_rodada: date
    criada_em: datetime
    criada_por: str
    criada_por_email: str
    modulo: str
    status: str
    total_vendas_adq: int
    valor_total_adq: float
    conciliadas_n: int
    valor_conciliado: float
    pendentes_n: int
    valor_pendente: float
    resolvido_pct: float
    arquivos_json: List[Dict[str, Any]]
    expira_em: datetime
    metadata: Dict[str, Any]


# ==============================================================================
# HELPERS
# ==============================================================================
def _sb():
    """Retorna client Supabase atual (deve estar autenticado)."""
    from src.supabase_client import get_supabase
    sb = get_supabase()
    if sb is None:
        raise RuntimeError("Supabase não conectado — faça login antes.")
    return sb


def _user() -> Dict[str, Any]:
    """Retorna dict do usuário logado."""
    from src.auth_supabase import current_user
    u = current_user()
    if u is None:
        raise RuntimeError("Usuário não autenticado.")
    return u


def _uid() -> str:
    return _user()["id"]


def _email() -> str:
    return _user().get("email", "")


def _path_rodada(rodada_id: str) -> str:
    """Prefixo no bucket para essa rodada."""
    return f"rodadas/{_uid()}/{rodada_id}"


# ==============================================================================
# CRIAR RODADA
# ==============================================================================
def criar_rodada(
    data_rodada: Optional[date] = None,
    modulo: str = "vendas",
) -> Rodada:
    """Cria uma rodada nova (status 'aberta'). Retorna o DTO."""
    if data_rodada is None:
        data_rodada = date.today()

    sb = _sb()
    payload = {
        "data_rodada": data_rodada.isoformat(),
        "criada_por": _uid(),
        "criada_por_email": _email(),
        "modulo": modulo,
        "status": "aberta",
        "arquivos_json": [],
        "metadata": {},
    }
    resp = sb.table(TABELA).insert(payload).execute()
    if not resp.data:
        raise RuntimeError("Falha ao criar rodada.")
    return _row_to_dto(resp.data[0])


# ==============================================================================
# LISTAR RODADAS
# ==============================================================================
def listar_rodadas(
    modulo: Optional[str] = None,
    incluir_arquivadas: bool = False,
    limite: int = 30,
) -> List[Rodada]:
    """Lista rodadas do usuário atual (mais recentes primeiro)."""
    sb = _sb()
    q = sb.table(TABELA).select("*").eq("criada_por", _uid())
    if modulo:
        q = q.eq("modulo", modulo)
    if not incluir_arquivadas:
        q = q.neq("status", "arquivada")
    q = q.order("criada_em", desc=True).limit(limite)

    resp = q.execute()
    return [_row_to_dto(r) for r in (resp.data or [])]


def buscar_rodada(rodada_id: str) -> Optional[Rodada]:
    """Busca uma rodada pelo id."""
    sb = _sb()
    resp = (
        sb.table(TABELA)
        .select("*")
        .eq("id", rodada_id)
        .eq("criada_por", _uid())
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    return _row_to_dto(resp.data[0])


# ==============================================================================
# ATUALIZAR MÉTRICAS
# ==============================================================================
def atualizar_metricas(
    rodada_id: str,
    total_vendas_adq: int,
    valor_total_adq: float,
    conciliadas_n: int,
    valor_conciliado: float,
    pendentes_n: int,
    valor_pendente: float,
) -> None:
    """Atualiza métricas de progresso da rodada."""
    sb = _sb()
    pct = (
        round(valor_conciliado / valor_total_adq * 100, 2)
        if valor_total_adq > 0
        else 0.0
    )
    sb.table(TABELA).update({
        "total_vendas_adq": total_vendas_adq,
        "valor_total_adq": valor_total_adq,
        "conciliadas_n": conciliadas_n,
        "valor_conciliado": valor_conciliado,
        "pendentes_n": pendentes_n,
        "valor_pendente": valor_pendente,
        "resolvido_pct": pct,
    }).eq("id", rodada_id).eq("criada_por", _uid()).execute()


def fechar_rodada(rodada_id: str) -> None:
    """Marca rodada como fechada."""
    sb = _sb()
    sb.table(TABELA).update({"status": "fechada"}).eq("id", rodada_id).eq(
        "criada_por", _uid()
    ).execute()


def deletar_rodada(rodada_id: str) -> None:
    """Deleta a rodada + arquivos do storage."""
    # 1) Deleta arquivos
    sb = _sb()
    prefixo = _path_rodada(rodada_id) + "/"
    try:
        objs = sb.storage.from_(BUCKET).list(_path_rodada(rodada_id))
        if objs:
            paths = [f"{_path_rodada(rodada_id)}/{o['name']}" for o in objs]
            sb.storage.from_(BUCKET).remove(paths)
    except Exception:
        pass  # continua mesmo se falhar

    # 2) Deleta linha
    sb.table(TABELA).delete().eq("id", rodada_id).eq("criada_por", _uid()).execute()


# ==============================================================================
# UPLOAD DE ARQUIVOS
# ==============================================================================
def upload_arquivo(
    rodada_id: str,
    categoria: str,        # 'vendas' | 'bancario' | 'resultado'
    nome_arquivo: str,     # ex: 'cielo_2026-08.xls'
    conteudo: bytes,
    mime: str = "application/octet-stream",
) -> str:
    """Envia arquivo pro Storage. Retorna path no bucket."""
    if categoria not in ("vendas", "bancario", "resultado"):
        raise ValueError(f"Categoria inválida: {categoria}")

    sb = _sb()
    path = f"{_path_rodada(rodada_id)}/{categoria}/{nome_arquivo}"

    # Upload (upsert=True permite sobrescrever se rodar de novo)
    sb.storage.from_(BUCKET).upload(
        path=path,
        file=conteudo,
        file_options={"contentType": mime, "upsert": "true"},
    )

    # Atualiza lista de arquivos na rodada
    rd = buscar_rodada(rodada_id)
    if rd:
        arquivos = list(rd.arquivos_json)
        arquivos = [a for a in arquivos if a.get("path") != path]  # dedup
        arquivos.append({
            "path": path,
            "categoria": categoria,
            "nome": nome_arquivo,
            "tamanho": len(conteudo),
            "mime": mime,
            "enviado_em": datetime.utcnow().isoformat(),
        })
        sb.table(TABELA).update({"arquivos_json": arquivos}).eq(
            "id", rodada_id
        ).eq("criada_por", _uid()).execute()

    return path


def baixar_arquivo(rodada_id: str, path: str) -> bytes:
    """Baixa um arquivo específico da rodada."""
    sb = _sb()
    # Confirma que o path pertence à rodada do usuário
    if not path.startswith(_path_rodada(rodada_id)):
        raise PermissionError("Path não pertence a essa rodada/usuário.")
    return sb.storage.from_(BUCKET).download(path)


def baixar_rodada_zip(rodada_id: str) -> bytes:
    """Baixa TODOS os arquivos da rodada em um ZIP."""
    import zipfile

    rd = buscar_rodada(rodada_id)
    if rd is None:
        raise RuntimeError("Rodada não encontrada.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Info da rodada como JSON
        info = {
            "id": rd.id,
            "data_rodada": rd.data_rodada.isoformat(),
            "criada_em": rd.criada_em.isoformat(),
            "criada_por": rd.criada_por_email,
            "modulo": rd.modulo,
            "total_vendas_adq": rd.total_vendas_adq,
            "valor_total_adq": rd.valor_total_adq,
            "conciliadas_n": rd.conciliadas_n,
            "valor_conciliado": rd.valor_conciliado,
            "pendentes_n": rd.pendentes_n,
            "valor_pendente": rd.valor_pendente,
            "resolvido_pct": rd.resolvido_pct,
        }
        zf.writestr("rodada_info.json", json.dumps(info, indent=2, ensure_ascii=False))

        # Cada arquivo
        for arq in rd.arquivos_json:
            try:
                conteudo = baixar_arquivo(rd.id, arq["path"])
                nome_zip = f"{arq['categoria']}/{arq['nome']}"
                zf.writestr(nome_zip, conteudo)
            except Exception as e:
                # Registra o erro dentro do ZIP em vez de abortar
                zf.writestr(
                    f"_ERRO_{arq.get('nome','desconhecido')}.txt",
                    f"Erro ao baixar: {e}",
                )

    buf.seek(0)
    return buf.read()


# ==============================================================================
# CONVERSÃO
# ==============================================================================
def _row_to_dto(row: Dict[str, Any]) -> Rodada:
    def _to_date(v):
        if v is None:
            return date.today()
        if isinstance(v, date):
            return v
        return date.fromisoformat(str(v)[:10])

    def _to_dt(v):
        if v is None:
            return datetime.utcnow()
        if isinstance(v, datetime):
            return v
        s = str(v).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return datetime.utcnow()

    arquivos = row.get("arquivos_json") or []
    if isinstance(arquivos, str):
        try:
            arquivos = json.loads(arquivos)
        except Exception:
            arquivos = []

    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}

    return Rodada(
        id=str(row["id"]),
        data_rodada=_to_date(row.get("data_rodada")),
        criada_em=_to_dt(row.get("criada_em")),
        criada_por=str(row.get("criada_por", "")),
        criada_por_email=str(row.get("criada_por_email", "")),
        modulo=row.get("modulo", "vendas"),
        status=row.get("status", "aberta"),
        total_vendas_adq=int(row.get("total_vendas_adq") or 0),
        valor_total_adq=float(row.get("valor_total_adq") or 0),
        conciliadas_n=int(row.get("conciliadas_n") or 0),
        valor_conciliado=float(row.get("valor_conciliado") or 0),
        pendentes_n=int(row.get("pendentes_n") or 0),
        valor_pendente=float(row.get("valor_pendente") or 0),
        resolvido_pct=float(row.get("resolvido_pct") or 0),
        arquivos_json=arquivos,
        expira_em=_to_dt(row.get("expira_em")),
        metadata=metadata,
    )
