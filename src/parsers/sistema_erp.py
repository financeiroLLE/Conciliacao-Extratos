"""Leitura do relatório de Conciliação Bancária exportado do ERP (Sankhya).

Layout típico:
- Linha 1: título "Conciliação Bancária"
- Linha 2: emissão/usuário/total de registros
- Linha 3: cabeçalho
- Linha 4+: dados

Colunas obrigatórias: Dt. Lançamento, Histórico, Vlr. Lançamento, Receita/Despesa.
Coluna de conta tem nome variável (passada por parâmetro ou auto-detectada).
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .extrato_banco import _normalizar_nome_coluna, _parse_valor_brl, _parse_data_robusto


COLUNAS_ESPERADAS_SISTEMA = [
    "data", "historico", "documento", "valor", "conta",
    "tipo_movimento", "conciliado", "usuario", "num_unico_bancario",
]


def _detectar_linha_cabecalho(df: pd.DataFrame) -> int:
    """Procura a linha que contém 'Dt. Lançamento' ou 'Data Lançamento'."""
    for i in range(min(10, len(df))):
        valores = [str(v).strip().lower() for v in df.iloc[i].tolist() if pd.notna(v)]
        joined = " | ".join(valores)
        if "dt. lançamento" in joined or "dt lançamento" in joined \
           or "data lançamento" in joined or "dt. lancamento" in joined:
            return i
    return 0


def _detectar_coluna_conta(colunas: list[str]) -> str | None:
    """Tenta achar a coluna que identifica a conta bancária."""
    candidatos = [
        "contabancaria", "contabancária",
        "conta", "agenciaconta", "agconta",
        "bancoconta", "ccbancaria",
    ]
    for col in colunas:
        norm = _normalizar_nome_coluna(col)
        if norm in candidatos:
            return col
    # heurística: nome contém "conta" e não é "contábil"
    for col in colunas:
        norm = _normalizar_nome_coluna(col)
        if "conta" in norm and "contabil" not in norm:
            return col
    return None


def carregar_relatorio_sistema(
    arquivo: Any,
    coluna_conta: str | None = None,
) -> pd.DataFrame:
    """Lê o relatório do ERP e retorna DataFrame canônico.

    Args:
        arquivo: file-like (Streamlit UploadedFile) ou path.
        coluna_conta: nome exato da coluna de conta no ERP. Se None, auto-detecta.

    Retorna DataFrame com colunas canônicas (ver COLUNAS_ESPERADAS_SISTEMA).
    """
    if hasattr(arquivo, "read"):
        nome = getattr(arquivo, "name", "")
        engine = "xlrd" if nome.lower().endswith(".xls") else "openpyxl"
        try:
            arquivo.seek(0)
        except Exception:
            pass
        raw = pd.read_excel(arquivo, sheet_name=0, engine=engine, header=None, dtype=str)
    else:
        engine = "xlrd" if str(arquivo).lower().endswith(".xls") else "openpyxl"
        raw = pd.read_excel(arquivo, sheet_name=0, engine=engine, header=None, dtype=str)

    if raw.empty:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS_SISTEMA)

    linha_header = _detectar_linha_cabecalho(raw)
    header = [str(v).strip() if pd.notna(v) else f"col_{i}"
              for i, v in enumerate(raw.iloc[linha_header].tolist())]
    df = raw.iloc[linha_header + 1:].copy()
    df.columns = header
    df = df.dropna(how="all").reset_index(drop=True)

    # Mapeamento de colunas conhecidas
    mapa: dict[str, str] = {}
    aliases = {
        "data": ["dtlancamento", "datalancamento", "data"],
        "historico": ["historico", "descricao"],
        "valor": ["vlrlancamento", "valorlancamento", "valor"],
        "receita_despesa": ["receitadespesa", "tipo"],
        "documento": ["numdocumento", "numerodocumento", "documento", "doc"],
        "num_unico_bancario": ["numunicobancario", "numunico"],
        "conciliado": ["conciliado"],
        "tipo_movimento": ["tipodemovimento", "tipomovimento"],
        "usuario": ["usuario"],
        "agencia": ["agencia", "ag", "numagencia", "numeroagencia"],
        "num_conta": ["numconta", "numeroconta", "ccorrente", "contacorrente"],
        "banco_nome": ["banco", "nomebanco", "nomedobanco"],
        # v5.0: TOP é o código da operação no Sankhya (TOP 1722 = recebimento cartão de crédito)
        "top_baixa": ["topdebaixa", "top", "codtop", "codigotop", "tipooperacao", "codtipooperacao"],
    }
    for col_real in df.columns:
        norm = _normalizar_nome_coluna(str(col_real))
        for canonico, lista in aliases.items():
            if norm in lista and canonico not in mapa:
                mapa[canonico] = col_real
                break

    if "data" not in mapa or "valor" not in mapa:
        raise ValueError(
            "Relatório do sistema sem colunas obrigatórias. "
            "Esperado: Dt. Lançamento e Vlr. Lançamento. "
            f"Colunas detectadas: {list(df.columns)[:10]}"
        )

    # Detectar coluna de conta
    col_conta_real: str | None = None
    if coluna_conta:
        # match exato (com strip e case-insensitive)
        alvo = coluna_conta.strip().lower()
        for c in df.columns:
            if str(c).strip().lower() == alvo:
                col_conta_real = c
                break
    if not col_conta_real:
        col_conta_real = _detectar_coluna_conta([str(c) for c in df.columns])

    out = pd.DataFrame()
    # CRÍTICO: dayfirst=True (datas brasileiras), com fallback para ISO
    out["data"] = _parse_data_robusto(df[mapa["data"]])
    out["historico"] = (
        df[mapa["historico"]].fillna("").astype(str).str.strip()
        if "historico" in mapa else ""
    )
    out["documento"] = (
        df[mapa["documento"]].fillna("").astype(str).str.strip()
        if "documento" in mapa else ""
    )
    valor_abs = df[mapa["valor"]].apply(_parse_valor_brl)

    # Aplicar sinal: no ERP o valor vem positivo + coluna Receita/Despesa
    if "receita_despesa" in mapa:
        tipo = df[mapa["receita_despesa"]].fillna("").astype(str).str.strip().str.upper()
        sinal = tipo.apply(lambda x: -1.0 if x.startswith("D") else 1.0)
        out["valor"] = valor_abs * sinal
    else:
        out["valor"] = valor_abs

    out["conta"] = (
        df[col_conta_real].fillna("—").astype(str).str.strip()
        if col_conta_real else "—"
    )
    out["tipo_movimento"] = (
        df[mapa["tipo_movimento"]].fillna("").astype(str).str.strip()
        if "tipo_movimento" in mapa else ""
    )
    out["conciliado"] = (
        df[mapa["conciliado"]].fillna("").astype(str).str.strip()
        if "conciliado" in mapa else ""
    )
    out["usuario"] = (
        df[mapa["usuario"]].fillna("").astype(str).str.strip()
        if "usuario" in mapa else ""
    )
    out["num_unico_bancario"] = (
        df[mapa["num_unico_bancario"]].fillna("").astype(str).str.strip()
        if "num_unico_bancario" in mapa else ""
    )
    out["agencia"] = (
        df[mapa["agencia"]].fillna("").astype(str).str.strip()
        if "agencia" in mapa else ""
    )
    out["num_conta"] = (
        df[mapa["num_conta"]].fillna("").astype(str).str.strip()
        if "num_conta" in mapa else ""
    )
    out["banco_nome"] = (
        df[mapa["banco_nome"]].fillna("").astype(str).str.strip()
        if "banco_nome" in mapa else ""
    )
    # v5.0: TOP DE BAIXA (código da operação Sankhya). 1722 = cartão de crédito.
    out["top_baixa"] = (
        df[mapa["top_baixa"]].fillna("").astype(str).str.strip()
        if "top_baixa" in mapa else ""
    )

    out = out.dropna(subset=["data"]).reset_index(drop=True)
    out = out[out["valor"] != 0].reset_index(drop=True)
    out["origem"] = "sistema"
    return out
