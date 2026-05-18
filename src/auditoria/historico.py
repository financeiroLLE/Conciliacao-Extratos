"""Persistência de execuções e reprocessamentos em arquivos locais.

- Cada execução gera um diretório data/outputs/execucoes/{ID}/ com:
    - inputs_banco.parquet         (snapshot do DF banco)
    - inputs_sistema.parquet       (snapshot do DF sistema)
    - resultado.xlsx               (relatório completo)
    - parametros.json              (data_ref, tolerância, contas, fuzzy on/off)
    - log.json                     (qtde linhas, status, mensagens)

- Um único data/outputs/auditoria.jsonl funciona como índice append-only.
  NUNCA é sobrescrito — só recebe linhas novas.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# Diretórios padrão (criados sob demanda)
DIR_BASE = Path("data/outputs")
DIR_EXECUCOES = DIR_BASE / "execucoes"
ARQ_INDICE = DIR_BASE / "auditoria.jsonl"


def _garantir_dirs():
    DIR_EXECUCOES.mkdir(parents=True, exist_ok=True)


def novo_id_execucao() -> str:
    """ID legível: YYYYMMDD-HHMMSS-xxxx."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    sufixo = uuid.uuid4().hex[:4]
    return f"{ts}-{sufixo}"


def registrar_execucao(
    id_exec: str,
    data_referencia: datetime,
    contas: list[str],
    tolerancia_dias: int,
    kpis: dict[str, Any],
    arquivos_inputs: list[str],
    status: str = "processado",
    usuario: str | None = None,
    versao: int = 1,
    id_origem: str | None = None,
) -> dict[str, Any]:
    """Adiciona uma linha no índice JSONL de auditoria. Append-only.

    Args:
        id_exec: identificador único desta execução.
        id_origem: se for reprocessamento, ID da execução original.
        versao: número da versão (1 para original, 2+ para reprocessamentos).
    """
    _garantir_dirs()
    registro = {
        "id": id_exec,
        "timestamp": datetime.now().isoformat(),
        "data_referencia": data_referencia.isoformat() if isinstance(data_referencia, datetime) else str(data_referencia),
        "contas": list(contas),
        "qtd_contas": len(contas),
        "tolerancia_dias": tolerancia_dias,
        "kpis": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in kpis.items()},
        "arquivos_inputs": list(arquivos_inputs),
        "status": status,
        "usuario": usuario or "",
        "versao": versao,
        "id_origem": id_origem or "",
    }
    with ARQ_INDICE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro


def listar_execucoes() -> list[dict[str, Any]]:
    """Lê o JSONL inteiro e retorna a lista de registros (mais recentes primeiro)."""
    if not ARQ_INDICE.exists():
        return []
    registros = []
    with ARQ_INDICE.open(encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                continue
    return list(reversed(registros))


def salvar_snapshot(
    id_exec: str,
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    parametros: dict[str, Any],
    relatorio_xlsx: bytes | None = None,
):
    """Grava os DataFrames de input e os parâmetros usados naquela execução."""
    _garantir_dirs()
    dir_exec = DIR_EXECUCOES / id_exec
    dir_exec.mkdir(parents=True, exist_ok=True)

    if not banco.empty:
        banco.to_parquet(dir_exec / "inputs_banco.parquet", index=False)
    if not sistema.empty:
        sistema.to_parquet(dir_exec / "inputs_sistema.parquet", index=False)

    # parametros: converte datetime para iso
    params_serial = {}
    for k, v in parametros.items():
        if isinstance(v, datetime):
            params_serial[k] = v.isoformat()
        else:
            params_serial[k] = v
    (dir_exec / "parametros.json").write_text(
        json.dumps(params_serial, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if relatorio_xlsx is not None:
        (dir_exec / "resultado.xlsx").write_bytes(relatorio_xlsx)


def carregar_snapshot_relatorio(id_exec: str) -> bytes | None:
    arq = DIR_EXECUCOES / id_exec / "resultado.xlsx"
    if not arq.exists():
        return None
    return arq.read_bytes()
