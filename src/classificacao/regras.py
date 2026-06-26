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
    # v5.11: D\u00e9bito Autom\u00e1tico mais espec\u00edfico. Antes `DA\s` casava com
    # "DA SILVA", "DA COSTA", etc. Agora exige "D\u00c9BITO AUT" expl\u00edcito ou
    # "DEB AUT" / "DEBAUT" / "DEB.AUT".
    ("Débito Automático", r"\b(D[ÉE]B(ITO)?\.?\s*AUT(OM[ÁA]TICO)?)\b"),
    # v5.11: Cart\u00e3o expandido com adquirentes e bandeiras abreviadas.
    # MAST (Mastercard abreviado pela Getnet), GETNET, PAGSEGURO, etc.
    ("Cartão", r"\b(CART[ÃA]O|VISA|MASTERCARD|MASTER|MAST|ELO|HIPERCARD|AMEX|GETNET|CIELO|STONE|REDE\s*(?:VAREJO)?|PAGSEGURO|PAG\s*SEGURO|PAGBANK|MERCADO\s*PAGO|MERCADOPAGO|ADQUIRENTE)\b"),
    ("Salário/Folha", r"\b(SAL[ÁA]RIO|FOLHA|PAGTO\s+FOLHA|SISPAG)\b"),
    ("Fornecedor", r"\b(FORNECEDOR(ES)?|PGTO\s+FORN|PAG(AMENTO)?\s+FORN)\b"),
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
    """Adiciona colunas 'tipo' e 'natureza' a um DataFrame com 'historico' e 'valor'.

    v5.11.1: linhas com top_baixa='1722' (recebimento de cartão de crédito no
    Sankhya) são forçadas para tipo='Cartão' independente do histórico, porque
    no Sankhya o histórico é o nome do cliente/NF (não menciona bandeira).
    """
    if df.empty:
        df = df.copy()
        df["tipo"] = pd.Series(dtype=str)
        df["natureza"] = pd.Series(dtype=str)
        return df
    out = df.copy()
    out["tipo"] = out["historico"].apply(classificar_tipo)
    out["natureza"] = out["valor"].apply(classificar_natureza)

    # v5.11.1: override por TOP 1722 (Sankhya = recebimento de cart\u00e3o)
    if "top_baixa" in out.columns:
        mask_1722 = out["top_baixa"].astype(str).str.strip() == "1722"
        out.loc[mask_1722, "tipo"] = "Cartão"

    return out


TIPOS_PRINCIPAIS = ["Boleto", "Pix", "Tarifa", "TED/DOC", "Débito Automático", "Cartão", "Salário/Folha", "Fornecedor", "Imposto", "Transferência", "Outros"]
