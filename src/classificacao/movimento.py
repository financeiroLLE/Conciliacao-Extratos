"""Identifica linhas que NÃO são movimentação real:
- Saldo inicial/final
- Aplicação / Resgate (movimentação entre conta corrente e investimento)
- Posição de conta / cobertura

Usado para EXCLUIR essas linhas do Total Extrato Bancário, e para mostrá-las
em aba dedicada (Aplicações e Resgates).
"""

from __future__ import annotations

import re

import pandas as pd


# Termos que identificam linha que é SALDO (não movimentação)
RE_SALDO = re.compile(
    r"\b("
    r"SALDO|"
    r"SDO\s+(ANT|ATU|FIN|INI)|"  # SDO ANT, SDO ATUAL etc
    r"POSI[CÇ][AÃ]O|"
    r"COBERTURA"
    r")\b",
    re.IGNORECASE,
)

# Termos que identificam aplicação financeira (saída para investimento)
RE_APLICACAO = re.compile(
    r"\b("
    r"APLIC(A[CÇ][AÃ]O)?|"
    r"INVESTIMENTO|"
    r"COMPRA\s+(CDB|RDB|LCI|LCA|TESOURO)|"
    r"COMPRA\s+T[IÍ]TULO|"
    r"POUPAN[CÇ]A\s+AUTOM"
    r")\b",
    re.IGNORECASE,
)

# Termos que identificam resgate (volta de investimento para conta)
RE_RESGATE = re.compile(
    r"\b("
    r"RESGATE|"
    r"REGAS(TE)?|"
    r"VENDA\s+(CDB|RDB|LCI|LCA|TESOURO)|"
    r"VENDA\s+T[IÍ]TULO|"
    r"VENC(IMENTO)?\s+(CDB|RDB|APLIC)|"
    r"CR[EÉ]DITO\s+RENDIMENTO"
    r")\b",
    re.IGNORECASE,
)

# Genérico investimento (sem direção clara)
RE_INVESTIMENTO_OUTRO = re.compile(
    r"\b("
    r"FUNDO\s+DE\s+INVESTIMENTO|"
    r"CDB|RDB|LCI|LCA|TESOURO\s+DIRETO"
    r")\b",
    re.IGNORECASE,
)


def is_saldo(historico: str) -> bool:
    return isinstance(historico, str) and bool(RE_SALDO.search(historico))


def classificar_movimentacao(historico: str) -> str:
    """Retorna 'aplicacao', 'resgate', 'investimento_outro', 'saldo' ou 'movimentacao'.

    'movimentacao' = lançamento normal (entra no Total Extrato Bancário).
    Os demais são EXCLUÍDOS do total.
    """
    if not isinstance(historico, str) or not historico.strip():
        return "movimentacao"
    if RE_SALDO.search(historico):
        return "saldo"
    if RE_APLICACAO.search(historico):
        return "aplicacao"
    if RE_RESGATE.search(historico):
        return "resgate"
    if RE_INVESTIMENTO_OUTRO.search(historico):
        return "investimento_outro"
    return "movimentacao"


def is_movimentacao_real(historico: str) -> bool:
    """Lançamento normal que entra no Total Extrato Bancário."""
    return classificar_movimentacao(historico) == "movimentacao"


def is_aplicacao_ou_resgate(historico: str) -> bool:
    return classificar_movimentacao(historico) in {"aplicacao", "resgate", "investimento_outro"}


def adicionar_categoria_movimento(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona coluna 'categoria_mov' = movimentacao / aplicacao / resgate / saldo / investimento_outro."""
    if df.empty:
        df = df.copy()
        df["categoria_mov"] = pd.Series(dtype=str)
        return df
    out = df.copy()
    out["categoria_mov"] = out["historico"].apply(classificar_movimentacao)
    return out


def classificar_natureza_movimento(valor: float, historico: str = "") -> str:
    """Receita (entrada) ou Despesa (saída) — baseado APENAS no sinal do valor.

    NÃO conta saldo/aplicação/resgate como receita ou despesa.
    """
    if valor is None or pd.isna(valor):
        return "indefinido"
    categoria = classificar_movimentacao(historico)
    if categoria != "movimentacao":
        return "nao_aplica"  # saldo/aplic/resgate não viram receita nem despesa
    return "receita" if float(valor) > 0 else "despesa"
