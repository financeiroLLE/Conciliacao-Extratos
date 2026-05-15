"""Leitura do extrato bancário padronizado.

Formato esperado: planilha com colunas Data, Histórico, Documento (opcional)
e Valor (R$) — uma ou múltiplas abas (cada aba pode ser um dia).
O valor já vem com sinal: negativo para saída, positivo para entrada.
"""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd


COLUNAS_ESPERADAS_BANCO = ["data", "historico", "documento", "valor", "conta"]


def _normalizar_nome_coluna(nome: str) -> str:
    """Tira acentos, caixa, espaços e parênteses para comparar cabeçalhos."""
    if not isinstance(nome, str):
        return ""
    s = nome.strip().lower()
    s = (
        s.replace("á", "a").replace("ã", "a").replace("â", "a").replace("à", "a")
         .replace("é", "e").replace("ê", "e")
         .replace("í", "i")
         .replace("ó", "o").replace("ô", "o").replace("õ", "o")
         .replace("ú", "u").replace("ü", "u")
         .replace("ç", "c")
    )
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[()/$.\-]", "", s)
    return s


def _mapear_colunas(df: pd.DataFrame) -> dict[str, str]:
    """Mapeia colunas do arquivo para nomes canônicos."""
    canonicos = {
        "data": ["data", "datalancamento", "dtlancamento"],
        "historico": ["historico", "descricao", "memo"],
        "documento": ["documento", "doc", "numdoc", "numerodoc"],
        # "valorr" cobre 'Valor (R$)' depois da normalização que remove parênteses
        "valor": ["valor", "valorr", "valorrs", "vlrlancamento", "vlr"],
    }
    encontrados: dict[str, str] = {}
    for col_real in df.columns:
        norm = _normalizar_nome_coluna(str(col_real))
        for canonico, aliases in canonicos.items():
            if norm in aliases and canonico not in encontrados:
                encontrados[canonico] = col_real
                break
    return encontrados


def _parse_data_robusto(serie: pd.Series) -> pd.Series:
    """Parser de data que respeita formato brasileiro (DD/MM/YYYY) E formato ISO.

    Datas brasileiras: 04/05/2026 → 4 de maio.
    Datas ISO: 2026-05-04 ou 2026-05-04 00:00:00 → 4 de maio.
    Datetimes nativos passam direto.
    """
    # Se já é datetime/timestamp, retorna direto
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce")
    # Converte para string para inspeção
    str_serie = serie.astype(str).str.strip()
    # Detecta ISO (4 dígitos no começo separados por '-')
    parece_iso = str_serie.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
    if parece_iso.all():
        return pd.to_datetime(str_serie, errors="coerce")
    # Senão, usa formato brasileiro
    return pd.to_datetime(str_serie, dayfirst=True, errors="coerce")


def _parse_valor_brl(v: Any) -> float:
    """Converte string '-1.000,00' ou '1000.00' para float."""
    if pd.isna(v):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    # Remove R$
    s = s.replace("R$", "").replace(" ", "").strip()
    # Formato brasileiro: 1.234,56 → 1234.56
    if "," in s and "." in s:
        # ambos: ponto é milhar, vírgula é decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def carregar_extrato_banco(arquivo: Any, conta: str) -> pd.DataFrame:
    """Lê o(s) extrato(s) bancário(s) padronizado(s) e retorna DataFrame canônico.

    Aceita arquivo .xlsx/.xls com 1 ou mais abas. Cada aba é tratada como um pedaço
    do extrato (datas diferentes geralmente).

    Retorna DataFrame com colunas: data, historico, documento, valor, conta.
    """
    # Aceita tanto file_uploader do streamlit quanto path
    if hasattr(arquivo, "read"):
        # UploadedFile do Streamlit
        nome = getattr(arquivo, "name", "")
        engine = "xlrd" if nome.lower().endswith(".xls") else "openpyxl"
        try:
            arquivo.seek(0)
        except Exception:
            pass
        sheets = pd.read_excel(arquivo, sheet_name=None, engine=engine, dtype=str)
    else:
        engine = "xlrd" if str(arquivo).lower().endswith(".xls") else "openpyxl"
        sheets = pd.read_excel(arquivo, sheet_name=None, engine=engine, dtype=str)

    frames: list[pd.DataFrame] = []
    for _, df_aba in sheets.items():
        if df_aba.empty:
            continue
        df_aba = df_aba.dropna(how="all").reset_index(drop=True)
        if df_aba.empty:
            continue

        # Se a primeira linha contém os cabeçalhos (planilha sem header)
        # tenta detectar tentando mapear; se não rolar, usa a primeira linha como header
        mapa = _mapear_colunas(df_aba)
        if "data" not in mapa or "valor" not in mapa:
            # promove primeira linha a cabeçalho
            df_aba.columns = [str(c) for c in df_aba.iloc[0].tolist()]
            df_aba = df_aba.iloc[1:].reset_index(drop=True)
            mapa = _mapear_colunas(df_aba)

        if "data" not in mapa or "valor" not in mapa:
            # aba não parece ser extrato — pula
            continue

        out = pd.DataFrame()
        out["data"] = _parse_data_robusto(df_aba[mapa["data"]])
        out["historico"] = df_aba[mapa["historico"]].fillna("") if "historico" in mapa else ""
        out["documento"] = (
            df_aba[mapa["documento"]].fillna("") if "documento" in mapa else ""
        )
        out["valor"] = df_aba[mapa["valor"]].apply(_parse_valor_brl)
        out["conta"] = conta

        # remove linhas sem data ou valor zero/sem valor
        out = out.dropna(subset=["data"])
        out = out[out["valor"] != 0].reset_index(drop=True)

        frames.append(out)

    if not frames:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS_BANCO)

    resultado = pd.concat(frames, ignore_index=True)
    resultado["historico"] = resultado["historico"].astype(str).str.strip()
    resultado["documento"] = resultado["documento"].astype(str).str.strip()
    resultado["origem"] = "banco"
    return resultado
