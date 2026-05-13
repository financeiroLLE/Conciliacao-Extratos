"""
Conciliação principal: match exato por (Data, Valor, Conta).

Esta é a chave de conciliação escolhida pelo usuário.

Algoritmo:
1. Para cada lançamento do banco, procura no sistema lançamentos com
   MESMA DATA, MESMO VALOR e MESMA CONTA.
2. Faz match 1-pra-1 (cada lançamento do banco casa com 1 do sistema).
3. Se houver N lançamentos iguais nos dois lados, casa os N.
4. Se houver desbalanceamento (3 no banco × 2 no sistema), 2 casam e
   1 fica como pendência.

Saídas:
- conciliados: lançamentos que casaram
- pendentes_banco: estão no banco mas não no sistema (FALTA BAIXAR)
- pendentes_sistema: estão no sistema mas não no banco (LANÇAMENTO INDEVIDO)
"""

from __future__ import annotations

import pandas as pd


def conciliar_exato(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Conciliação por (Data, Valor, Conta) com match 1-pra-1.

    Parameters
    ----------
    banco : DataFrame normalizado do extrato bancário
    sistema : DataFrame normalizado do relatório do sistema

    Returns
    -------
    dict com chaves:
        - 'conciliados': DataFrame com pares casados
        - 'pendentes_banco': lançamentos do banco sem contrapartida
        - 'pendentes_sistema': lançamentos do sistema sem contrapartida
    """
    if banco.empty and sistema.empty:
        return {
            "conciliados": pd.DataFrame(),
            "pendentes_banco": banco.copy(),
            "pendentes_sistema": sistema.copy(),
        }

    # Cria a chave de conciliação
    banco = banco.copy()
    sistema = sistema.copy()

    banco["_chave"] = (
        banco["data"].dt.strftime("%Y-%m-%d")
        + "|"
        + banco["valor"].round(2).astype(str)
        + "|"
        + banco["conta"].astype(str)
    )
    sistema["_chave"] = (
        sistema["data"].dt.strftime("%Y-%m-%d")
        + "|"
        + sistema["valor"].round(2).astype(str)
        + "|"
        + sistema["conta"].astype(str)
    )

    # Cria índice posicional dentro de cada chave para fazer match 1-pra-1
    banco["_ordem"] = banco.groupby("_chave").cumcount()
    sistema["_ordem"] = sistema.groupby("_chave").cumcount()

    # Merge interno: casa banco × sistema pela chave + ordem
    merged = banco.merge(
        sistema,
        on=["_chave", "_ordem"],
        how="outer",
        suffixes=("_banco", "_sistema"),
        indicator=True,
    )

    conciliados = merged[merged["_merge"] == "both"].copy()
    so_banco = merged[merged["_merge"] == "left_only"].copy()
    so_sistema = merged[merged["_merge"] == "right_only"].copy()

    # Monta DataFrames de saída
    conciliados_out = pd.DataFrame(
        {
            "data": conciliados["data_banco"],
            "valor": conciliados["valor_banco"],
            "conta": conciliados["conta_banco"],
            "historico_banco": conciliados["historico_banco"],
            "historico_sistema": conciliados["historico_sistema"],
            "documento_banco": conciliados.get("documento", ""),
            "num_unico_bancario": conciliados.get("num_unico_bancario", ""),
            "num_documento_sistema": conciliados.get("num_documento", ""),
            "usuario_sistema": conciliados.get("usuario", ""),
            "tipo_movimento": conciliados.get("tipo_movimento", ""),
            "_row_id_banco": conciliados["_row_id_banco"],
            "_row_id_sistema": conciliados["_row_id_sistema"],
        }
    ).reset_index(drop=True)

    pendentes_banco = banco[banco["_row_id"].isin(so_banco["_row_id_banco"])].drop(
        columns=["_chave", "_ordem"]
    ).reset_index(drop=True)

    pendentes_sistema = sistema[
        sistema["_row_id"].isin(so_sistema["_row_id_sistema"])
    ].drop(columns=["_chave", "_ordem"]).reset_index(drop=True)

    return {
        "conciliados": conciliados_out,
        "pendentes_banco": pendentes_banco,
        "pendentes_sistema": pendentes_sistema,
    }
