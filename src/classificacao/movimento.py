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


def _normalizar_para_classificacao(s: str) -> str:
    """Normaliza histórico para matching robusto.

    1. Caixa alta.
    2. Colapsa espaços múltiplos.
    3. Junta sequências de letras únicas separadas por espaço:
       'S A L D O' → 'SALDO'.
    """
    if not isinstance(s, str):
        return ""
    s = s.upper().strip()
    s = re.sub(r"\s+", " ", s)
    # 'S A L D O' → 'SALDO': junta sequências de 3+ letras separadas por espaço
    s = re.sub(
        r"\b((?:[A-Z]\s){2,}[A-Z])\b",
        lambda m: m.group(1).replace(" ", ""),
        s,
    )
    return s


# Termos que identificam linha que é SALDO (não movimentação)
RE_SALDO = re.compile(
    r"\b("
    r"SALDO|"
    r"SDO|"               # SDO ANT, SDO ATUAL, SDO APLIC etc — qualquer SDO é saldo
    r"POSI[CÇ][AÃ]O|"
    r"COBERTURA"
    r")\b",
    re.IGNORECASE,
)

# Aplicação financeira (saída para investimento)
RE_APLICACAO = re.compile(
    r"\b("
    r"APLIC(A[CÇ][AÃ]O)?\.?\s+AUT|"  # APLIC AUT, APLIC. AUT (v5.26), APLICAÇÃO AUTOM
    r"APLIC\.?\s*AUTOM|"             # APLIC.AUTOM.INVESTFACIL (Bradesco, ponto sem espaço)
    r"APLIC\.?\s*FINANC|"            # APLIC.FINANC (Sicredi)
    r"APLIC\.?\s*INVEST|"           # APLIC.INVEST FACIL (Bradesco)
    r"INVEST\.?\s*F[AÁ]CIL|"        # INVESTFACIL / INVEST FACIL (Bradesco, aplicação automática)
    r"APLICA[CÇ][AÃ]O|"
    r"INVESTIMENTO|"
    r"COMPRA\s+(CDB|RDB|LCI|LCA|TESOURO)|"
    r"COMPRA\s+T[IÍ]TULO|"
    r"POUPAN[CÇ]A\s+AUTOM"
    r")\b",
    re.IGNORECASE,
)

# Resgate (volta de investimento para conta)
RE_RESGATE = re.compile(
    r"\b("
    r"RESGATE|"
    r"RESG\.?\s*AUT|"      # RESG. AUT, RESG AUT, RESGATE AUT
    r"RESG\.?\s*APLIC|"    # RESG.APLIC.FIN (Sicredi)
    r"RES\s+APLIC|"        # RES APLIC AUT (do extrato Itaú)
    r"VENDA\s+(CDB|RDB|LCI|LCA|TESOURO)|"
    r"VENDA\s+T[IÍ]TULO|"
    r"VENC(IMENTO)?\s+(CDB|RDB|APLIC)"
    r")\b",
    re.IGNORECASE,
)

# Rendimento creditado em conta — é RECEITA, não investimento!
# 'REND PAGO APLIC AUT' = juros recebidos do CDB. Conta como movimentação normal.
RE_RENDIMENTO = re.compile(
    r"\b("
    r"REND\s+PAGO|"
    r"RENTAB\.?\s*INVEST|"   # RENTAB.INVEST FACILCRED (Bradesco) — rendimento creditado
    r"RENDIMENTO\s+PAGO|"
    r"CR[EÉ]DITO\s+RENDIMENTO|"
    r"JUROS\s+(CRED|RECEB)"
    r")\b",
    re.IGNORECASE,
)

# Genérico investimento (sem direção clara — fica em 'investimento_outro' só se nada acima casar)
RE_INVESTIMENTO_OUTRO = re.compile(
    r"\b("
    r"FUNDO\s+DE\s+INVESTIMENTO|"
    r"\bCDB\b|\bRDB\b|\bLCI\b|\bLCA\b|TESOURO\s+DIRETO"
    r")\b",
    re.IGNORECASE,
)


def is_saldo(historico: str) -> bool:
    if not isinstance(historico, str):
        return False
    return bool(RE_SALDO.search(_normalizar_para_classificacao(historico)))


def classificar_movimentacao(historico: str) -> str:
    """Retorna 'aplicacao', 'resgate', 'investimento_outro', 'saldo' ou 'movimentacao'.

    'movimentacao' = lançamento normal (entra no Total).
    'saldo' = linha de posição/extrato. ÚNICA categoria EXCLUÍDA do total (v3).
    Demais entram no total mas aparecem em aba específica.
    """
    if not isinstance(historico, str) or not historico.strip():
        return "movimentacao"

    # Normaliza ('S A L D O' → 'SALDO') antes de testar
    norm = _normalizar_para_classificacao(historico)

    # ORDEM IMPORTA:
    # 1. SALDO primeiro (cobre 'SDO APLIC AUT' que tem APLIC mas é saldo)
    if RE_SALDO.search(norm):
        return "saldo"
    # 2. RENDIMENTO (REND PAGO) — v5.26: categoria própria, não conta no Total Movimentado
    if RE_RENDIMENTO.search(norm):
        return "rendimento"
    # 3. Resgate antes de aplicação ('RES APLIC' tem ambos, mas é resgate)
    if RE_RESGATE.search(norm):
        return "resgate"
    if RE_APLICACAO.search(norm):
        return "aplicacao"
    if RE_INVESTIMENTO_OUTRO.search(norm):
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
