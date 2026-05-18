"""Leitura da aba 'Pendências Consolidadas' do relatório gerado em dias anteriores.

Essa aba é o "estado" persistente do sistema — sobe-se no próximo dia
para acompanhar há quantos dias cada pendência está em aberto.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def carregar_pendencias_anteriores(arquivo: Any) -> pd.DataFrame:
    """Lê a aba 'Pendências Consolidadas' do relatório de dias anteriores.

    Retorna DataFrame vazio se o arquivo for None.
    """
    if arquivo is None:
        return pd.DataFrame()

    if hasattr(arquivo, "read"):
        try:
            arquivo.seek(0)
        except Exception:
            pass
        sheets = pd.read_excel(arquivo, sheet_name=None, engine="openpyxl")
    else:
        sheets = pd.read_excel(arquivo, sheet_name=None, engine="openpyxl")

    # Procura aba com nome "Pendências Consolidadas" (case-insensitive)
    aba_alvo = None
    for nome in sheets:
        if "pendênc" in nome.lower() and "consolid" in nome.lower():
            aba_alvo = nome
            break
        if "pendenc" in nome.lower() and "consolid" in nome.lower():
            aba_alvo = nome
            break

    if not aba_alvo:
        return pd.DataFrame()

    df = sheets[aba_alvo]
    if df.empty:
        return pd.DataFrame()

    # Normalização leve dos nomes
    df.columns = [str(c).strip() for c in df.columns]

    # Converte coluna de data se existir
    for col in df.columns:
        if "data" in col.lower():
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    return df.reset_index(drop=True)
