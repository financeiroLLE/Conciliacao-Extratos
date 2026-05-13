"""
Parser do relatório de PENDÊNCIAS gerado em dias anteriores.

Como o sistema não usa banco de dados, o usuário sobe o Excel de
pendências do dia anterior para que pendências antigas sejam
reconciliadas com os novos lançamentos do dia.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def carregar_pendencias_anteriores(
    arquivo: str | Path | "IO" | None,
) -> pd.DataFrame:
    """Lê a aba 'Pendências Consolidadas' do relatório de pendências anterior.

    Retorna DataFrame vazio se arquivo for None ou se a aba não existir.
    """
    if arquivo is None:
        return pd.DataFrame(
            columns=[
                "data",
                "historico",
                "valor",
                "conta",
                "origem",
                "tipo_pendencia",
                "data_primeira_deteccao",
                "dias_pendente",
            ]
        )

    try:
        df = pd.read_excel(arquivo, sheet_name="Pendências Consolidadas")
    except (ValueError, KeyError):
        # Aba não existe
        return pd.DataFrame(
            columns=[
                "data",
                "historico",
                "valor",
                "conta",
                "origem",
                "tipo_pendencia",
                "data_primeira_deteccao",
                "dias_pendente",
            ]
        )

    # Mapeamento de nomes amigáveis para nomes internos
    rename_map = {
        "Data": "data",
        "Histórico": "historico",
        "Valor": "valor",
        "Conta": "conta",
        "Origem": "origem",
        "Tipo de Pendência": "tipo_pendencia",
        "Data 1ª Detecção": "data_primeira_deteccao",
        "Dias Pendente": "dias_pendente",
    }
    df = df.rename(columns=rename_map)

    if "data" in df.columns:
        df["data"] = pd.to_datetime(df["data"], errors="coerce").dt.normalize()
    if "data_primeira_deteccao" in df.columns:
        df["data_primeira_deteccao"] = pd.to_datetime(
            df["data_primeira_deteccao"], errors="coerce"
        ).dt.normalize()
    if "valor" in df.columns:
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce").round(2)

    return df.dropna(subset=["data", "valor"]).reset_index(drop=True)
