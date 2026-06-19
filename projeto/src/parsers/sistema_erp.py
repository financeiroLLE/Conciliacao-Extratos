"""Leitura do relatório de Conciliação Bancária exportado do ERP (Sankhya).

Layout típico (relatório "Conciliação Bancária" da LLE):
- Linha 1: título
- Linha 2: emissão/usuário/total de registros
- Linha 3: cabeçalho
- Linha 4+: dados

Colunas: Tipo | Dt Lançamento | Conta | Descrição | Receita/Despesa | NUBCO |
         Vlr. Lançamento | Cód.Usuário | Usuário | TOPBAIXA | Dh.Conciliação |
         Histórico | Saldo Bco | Saldo Real | Conciliado

Pontos de atenção desse layout:
- "Conta"      → NÚMERO interno da conta no ERP (ex.: 4)
- "Descrição"  → NOME do banco/conta (ex.: "ITAU PISA")  ← é a chave que casa com o extrato
- "Histórico"  → memo do lançamento (cliente/fornecedor)
- "Receita/Despesa" → sinal do valor (o Vlr. Lançamento pode vir com ou sem sinal)
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from .extrato_banco import _normalizar_nome_coluna, _parse_valor_brl, _parse_data_robusto


COLUNAS_ESPERADAS_SISTEMA = [
    "data", "historico", "documento", "valor", "conta", "conta_numero",
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
    """Tenta achar a coluna do NÚMERO da conta no ERP (coluna 'Conta')."""
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


def _achar_coluna(colunas: list[str], alvos: set[str]) -> str | None:
    for col in colunas:
        if _normalizar_nome_coluna(str(col)) in alvos:
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

    # Mapeamento de colunas conhecidas.
    # ATENÇÃO: 'historico' e 'conta' (nome/número) NÃO entram aqui — são detectados
    # separadamente mais abaixo, porque neste relatório existem DUAS colunas
    # "descritivas" (Histórico = memo; Descrição = nome da conta) e o alias genérico
    # confundia uma com a outra (Descrição era capturada como histórico).
    mapa: dict[str, str] = {}
    aliases = {
        "data": ["dtlancamento", "datalancamento", "data"],
        "valor": ["vlrlancamento", "valorlancamento", "valor"],
        # v5.19: NÃO usar alias "tipo" — a coluna "Tipo" do Sankhya é "Financeiro",
        # não Receita/Despesa.
        "receita_despesa": ["receitadespesa"],
        "documento": ["numdocumento", "numerodocumento", "documento", "doc"],
        "num_unico_bancario": ["numunicobancario", "numunico", "nubco"],
        "conciliado": ["conciliado"],
        "tipo_movimento": ["tipodemovimento", "tipomovimento"],
        "usuario": ["usuario"],
        "agencia": ["agencia", "ag", "numagencia", "numeroagencia"],
        "num_conta": ["numconta", "numeroconta", "ccorrente", "contacorrente"],
        "banco_nome": ["banco", "nomebanco", "nomedobanco"],
        # v5.0/v5.10: TOP de baixa. 1722 = recebimento cartão de crédito.
        "top_baixa": ["topdebaixa", "topbaixa", "top", "codtop", "codigotop", "tipooperacao", "codtipooperacao"],
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

    # --- Histórico (memo) vs Descrição (nome da conta) -----------------------
    # Regra: se existem AS DUAS colunas → Histórico=memo e Descrição=nome da conta.
    #        se existe só "Descrição"  → ela é o memo (layout antigo, sem nome de conta).
    col_historico = _achar_coluna(list(df.columns), {"historico"})
    col_descricao = _achar_coluna(list(df.columns), {"descricao"})
    if col_historico is not None and col_descricao is not None:
        col_memo = col_historico
        col_conta_nome = col_descricao
    elif col_descricao is not None:
        col_memo = col_descricao
        col_conta_nome = None
    else:
        col_memo = col_historico
        col_conta_nome = None

    # --- Número da conta (coluna "Conta") ------------------------------------
    col_conta_num: str | None = None
    if coluna_conta:
        alvo = coluna_conta.strip().lower()
        for c in df.columns:
            if str(c).strip().lower() == alvo:
                col_conta_num = c
                break
    if not col_conta_num:
        col_conta_num = _detectar_coluna_conta([str(c) for c in df.columns])

    out = pd.DataFrame()
    # CRÍTICO: parser de data robusto (trata ISO e BR linha a linha — ver bugfix
    # em extrato_banco._parse_data_robusto).
    out["data"] = _parse_data_robusto(df[mapa["data"]])
    out["historico"] = (
        df[col_memo].fillna("").astype(str).str.strip()
        if col_memo is not None else ""
    )
    out["documento"] = (
        df[mapa["documento"]].fillna("").astype(str).str.strip()
        if "documento" in mapa else ""
    )

    valor_parsed = df[mapa["valor"]].apply(_parse_valor_brl)

    # Detecção da coluna Receita/Despesa por CONTEÚDO, caso o alias não tenha casado
    # (defesa contra variações de cabeçalho). Usa posição (iloc) por segurança.
    receita_despesa_idx: int | None = None
    if "receita_despesa" not in mapa:
        for i in range(len(df.columns)):
            try:
                serie = df.iloc[:, i]
                valores = (
                    serie.dropna().astype(str).str.strip().str.lower().unique()
                )
                valores_rd = [v for v in valores if v in ("receita", "despesa")]
                if len(valores_rd) >= 1 and len(valores) <= 5:
                    receita_despesa_idx = i
                    break
            except Exception:
                continue

    # Sinal a partir de Receita/Despesa.
    # BUGFIX recorrente: aplicamos o sinal sobre |valor| (abs). Assim o resultado é
    # correto INDEPENDENTE de o Vlr. Lançamento já vir com sinal ou não. A versão
    # anterior multiplicava o valor "como veio": quando o ERP já exportava despesa
    # negativa, o ×(-1) reinvertia para POSITIVO, zerando o card Despesas e
    # transformando tudo em Receita.
    if "receita_despesa" in mapa:
        tipo = df[mapa["receita_despesa"]].fillna("").astype(str).str.strip().str.upper()
        sinal = tipo.apply(lambda x: -1.0 if x.startswith("D") else 1.0)
        out["valor"] = valor_parsed.abs() * sinal
    elif receita_despesa_idx is not None:
        tipo = df.iloc[:, receita_despesa_idx].fillna("").astype(str).str.strip().str.upper()
        sinal = tipo.apply(lambda x: -1.0 if x.startswith("D") else 1.0)
        out["valor"] = valor_parsed.abs() * sinal
    else:
        # Sem coluna Receita/Despesa: confia no sinal que veio no valor.
        out["valor"] = valor_parsed

    # --- Conta: usa o NOME (Descrição) como chave, casando com o extrato bancário.
    #     O número interno do ERP fica em 'conta_numero' para referência/exibição.
    n = len(df)
    serie_num = (
        df[col_conta_num].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        if col_conta_num else pd.Series([""] * n, index=df.index)
    )
    serie_nome = (
        df[col_conta_nome].fillna("").astype(str).str.strip().map(lambda x: " ".join(x.split()))
        if col_conta_nome else pd.Series([""] * n, index=df.index)
    )
    out["conta_numero"] = serie_num.values
    conta_final = serie_nome.where(serie_nome.str.len() > 0, serie_num).replace("", "—")
    out["conta"] = conta_final.values

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
    out["top_baixa"] = (
        df[mapa["top_baixa"]].fillna("").astype(str).str.strip()
        if "top_baixa" in mapa else ""
    )

    out = out.dropna(subset=["data"]).reset_index(drop=True)
    out = out[out["valor"] != 0].reset_index(drop=True)
    out["origem"] = "sistema"
    return out
