"""
Parser do extrato bancário.

O usuário padroniza manualmente os extratos antes de subir, então o
formato esperado é fixo:

    Data  |  Histórico  |  Documento  |  Valor (R$)

O arquivo pode ter MÚLTIPLAS ABAS (uma por dia) ou UMA ÚNICA ABA.
Aceitamos os dois casos e concatenamos tudo em um DataFrame único.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUNAS_OBRIGATORIAS = ["Data", "Histórico", "Valor (R$)"]


def carregar_extrato_banco(
    arquivo: str | Path | "IO",
    conta: str,
) -> pd.DataFrame:
    """Lê um extrato bancário padronizado e retorna um DataFrame normalizado.

    Parameters
    ----------
    arquivo : caminho ou objeto file-like (do Streamlit uploader)
    conta : str
        Identificador da conta bancária a que esse extrato pertence.
        Será adicionado como coluna para permitir conciliação multi-conta.

    Returns
    -------
    DataFrame com colunas: data, historico, valor, conta, origem='banco', _row_id
    """
    # Lê todas as abas e concatena
    sheets = pd.read_excel(arquivo, sheet_name=None, dtype={"Documento": str})

    dfs = []
    for nome_aba, df in sheets.items():
        if df.empty:
            continue
        # Mantém apenas colunas que existem (tolerante a "Documento" ausente)
        cols_presentes = [c for c in COLUNAS_OBRIGATORIAS if c in df.columns]
        faltando = set(COLUNAS_OBRIGATORIAS) - set(cols_presentes)
        if faltando:
            raise ValueError(
                f"Aba '{nome_aba}' do extrato não tem as colunas obrigatórias: "
                f"{faltando}. Colunas presentes: {df.columns.tolist()}"
            )
        df = df[cols_presentes + ([] if "Documento" not in df.columns else ["Documento"])]
        df["_aba_origem"] = nome_aba
        dfs.append(df)

    if not dfs:
        raise ValueError("Extrato bancário vazio — nenhuma aba com dados.")

    bruto = pd.concat(dfs, ignore_index=True)

    # Normaliza
    out = pd.DataFrame()
    out["data"] = pd.to_datetime(bruto["Data"], dayfirst=True, errors="coerce").dt.normalize()
    out["historico"] = bruto["Histórico"].astype(str).str.strip()
    out["valor"] = pd.to_numeric(bruto["Valor (R$)"], errors="coerce").round(2)
    out["documento"] = (
        bruto["Documento"].astype(str).str.strip()
        if "Documento" in bruto.columns
        else ""
    )
    out["conta"] = conta
    out["origem"] = "banco"
    out["_aba_origem"] = bruto["_aba_origem"].values

    # Remove linhas sem data ou valor (rodapés/cabeçalhos perdidos)
    out = out.dropna(subset=["data", "valor"]).reset_index(drop=True)
    out["_row_id"] = [f"BCO-{conta}-{i:06d}" for i in range(len(out))]

    return out
