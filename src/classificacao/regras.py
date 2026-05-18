"""Classifica lançamentos por tipo (Boleto, Pix, Tarifa, ...) a partir do histórico.

Regras editáveis abaixo. A ordem importa: a primeira regra que casa vence.
Lançamentos não classificados ficam como 'Outros'.
"""

from __future__ import annotations

import re

import pandas as pd


# (nome_tipo, regex case-insensitive) — ordem importa
REGRAS: list[tuple[str, str]] = [
    ("Pix", r"\bPIX\b"),
    # Tarifa primeiro: "TAR LIQ COB" é tarifa de cobrança, não boleto.
    ("Tarifa", r"\b(TAR(IFA)?|IOF|JUROS|MULTA)\b"),
    ("Boleto", r"\b(BOLETO|COB(R(AN(C|Ç)A)?)?|LIQ(UIDA[CÇ]AO)?\s+COB|TIT(ULO)?|BAIXA\s+API)\b"),
    ("TED/DOC", r"\b(TED|DOC)\b"),
    ("Débito Automático", r"\b(D[ÉE]BITO\s+AUT|DA\s)\b"),
    ("Cartão", r"\b(CART[ÃA]O|VISA|MASTERCARD|ELO)\b"),
    ("Salário/Folha", r"\b(SAL[ÁA]RIO|FOLHA|PAGTO\s+FOLHA)\b"),
    ("Imposto", r"\b(DARF|DAS|IPVA|IPTU|GPS|FGTS|IMPOSTO|TRIBUTO)\b"),
    ("Transferência", r"\b(TRANSF|TRANSFER[ÊE]NCIA)\b"),
]


def classificar_tipo(historico: str) -> str:
    """Retorna o tipo do lançamento baseado no histórico."""
    if not isinstance(historico, str) or not historico.strip():
        return "Outros"
    texto = historico.upper()
    for nome, padrao in REGRAS:
        if re.search(padrao, texto):
            return nome
    return "Outros"


def classificar_natureza(valor: float) -> str:
    """Pagamento (saída) ou Recebimento (entrada)."""
    if valor is None or pd.isna(valor):
        return "Indefinido"
    return "Pagamento" if float(valor) < 0 else "Recebimento"


def adicionar_classificacao(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas 'tipo' e 'natureza' a um DataFrame com 'historico' e 'valor'."""
    if df.empty:
        df = df.copy()
        df["tipo"] = pd.Series(dtype=str)
        df["natureza"] = pd.Series(dtype=str)
        return df
    out = df.copy()
    out["tipo"] = out["historico"].apply(classificar_tipo)
    out["natureza"] = out["valor"].apply(classificar_natureza)
    return out


TIPOS_PRINCIPAIS = ["Boleto", "Pix", "Tarifa", "TED/DOC", "Débito Automático", "Cartão"]
