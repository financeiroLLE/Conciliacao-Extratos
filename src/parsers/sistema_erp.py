"""
Parser do relatório do SISTEMA (ERP) — formato "Conciliação Bancária".

Este parser foi calibrado com base no arquivo de teste real. Características:

- A linha 1 do Excel é o título "Conciliação Bancária"
- A linha 2 traz Emissão / Total de registros / Usuário
- A linha 3 é o cabeçalho real
- A última linha do arquivo é um total agregado (sem data, sem histórico)

Colunas relevantes para conciliação:
    Dt. Lançamento, Histórico, Vlr. Lançamento, Receita/Despesa,
    Núm. Único Bancário, Núm. Documento, Conciliado, Tipo de Movimento, Usuário

Sobre o sinal do valor:
    No sistema, o valor vem POSITIVO e o sinal é dado pela coluna
    Receita/Despesa. Para conciliar contra o extrato (que tem sinal),
    multiplicamos por -1 quando for Despesa.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# A coluna que identifica a CONTA bancária no sistema.
# O usuário disse que existe — o nome exato deve ser ajustado quando
# os dados reais forem usados. Por padrão, tentamos uma lista de nomes
# comuns; se nenhum for encontrado, exigimos que o usuário escolha.
CANDIDATOS_COLUNA_CONTA = [
    "Conta Bancária",
    "Conta Bancaria",
    "Conta",
    "Banco",
    "Conta/Banco",
    "Agência/Conta",
    "Agencia/Conta",
]


def detectar_coluna_conta(df: pd.DataFrame) -> str | None:
    """Tenta detectar automaticamente qual coluna identifica a conta."""
    for cand in CANDIDATOS_COLUNA_CONTA:
        if cand in df.columns:
            return cand
    return None


def carregar_relatorio_sistema(
    arquivo: str | Path | "IO",
    coluna_conta: str | None = None,
    filtrar_conta: str | None = None,
) -> pd.DataFrame:
    """Lê o relatório do sistema (ERP) e retorna DataFrame normalizado.

    Parameters
    ----------
    arquivo : caminho ou objeto file-like
    coluna_conta : nome da coluna que identifica a conta no sistema.
        Se None, tenta detectar automaticamente.
    filtrar_conta : se informado, filtra apenas lançamentos dessa conta.

    Returns
    -------
    DataFrame com colunas: data, historico, valor, conta, num_unico_bancario,
                            num_documento, conciliado, tipo_movimento, usuario,
                            origem='sistema', _row_id
    """
    # Detecta extensão para escolher engine
    nome = str(getattr(arquivo, "name", arquivo)).lower()
    engine = "xlrd" if nome.endswith(".xls") else None

    # Header está na linha 3 (índice 2)
    df = pd.read_excel(arquivo, header=2, engine=engine)

    # Verifica colunas obrigatórias
    obrigatorias = [
        "Dt. Lançamento",
        "Histórico",
        "Vlr. Lançamento",
        "Receita/Despesa",
    ]
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError(
            f"Relatório do sistema não tem as colunas obrigatórias: {faltando}. "
            f"Colunas presentes: {df.columns.tolist()}"
        )

    # Coluna de conta
    if coluna_conta is None:
        coluna_conta = detectar_coluna_conta(df)

    # Remove linha de total no final (sem data)
    df = df[df["Dt. Lançamento"].notna()].copy()

    out = pd.DataFrame()
    # IMPORTANTE: usar dayfirst=True (formato brasileiro DD/MM/AAAA).
    # Sem isso, "04/05/2026" seria interpretado como 5 de abril.
    out["data"] = pd.to_datetime(
        df["Dt. Lançamento"], dayfirst=True, errors="coerce"
    ).dt.normalize()
    out["historico"] = df["Histórico"].astype(str).str.strip()

    # Aplica sinal: Despesa vira negativo
    valor_abs = pd.to_numeric(df["Vlr. Lançamento"], errors="coerce").round(2)
    sinal = df["Receita/Despesa"].astype(str).str.strip().str.lower().map(
        lambda x: -1 if x == "despesa" else 1
    )
    out["valor"] = (valor_abs * sinal).round(2)

    out["num_unico_bancario"] = (
        df["Núm. Único Bancário"].astype(str).str.strip()
        if "Núm. Único Bancário" in df.columns
        else ""
    )
    out["num_documento"] = (
        df["Núm. Documento"].astype(str).str.strip()
        if "Núm. Documento" in df.columns
        else ""
    )
    out["conciliado"] = (
        df["Conciliado"].astype(str).str.strip()
        if "Conciliado" in df.columns
        else "Sim"
    )
    out["tipo_movimento"] = (
        df["Tipo de Movimento"].astype(str).str.strip()
        if "Tipo de Movimento" in df.columns
        else ""
    )
    out["usuario"] = (
        df["Usuário"].astype(str).str.strip()
        if "Usuário" in df.columns
        else ""
    )

    if coluna_conta and coluna_conta in df.columns:
        out["conta"] = df[coluna_conta].astype(str).str.strip()
    else:
        # Sem coluna de conta: assume conta única (será sobrescrita externamente)
        out["conta"] = "—"

    out["origem"] = "sistema"
    out = out.dropna(subset=["data", "valor"]).reset_index(drop=True)
    out["_row_id"] = [f"SIS-{i:06d}" for i in range(len(out))]

    if filtrar_conta is not None:
        out = out[out["conta"] == filtrar_conta].reset_index(drop=True)

    return out
