"""Match exato entre extrato bancário e relatório do sistema.

REGRAS (atualizadas conforme briefing de produto):
- Valor: precisa ser EXATAMENTE igual (sem tolerância de centavos).
- Data: aceita tolerância de ±N dias corridos (default 2 — cobre fim de semana e
  feriados curtos). Quando há múltiplos candidatos dentro da janela, prefere o
  de menor diferença absoluta de dias.
- Conta: igual.
- Matching é 1-pra-1: cada lançamento do banco casa com no máximo um do sistema.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd


def _normalizar_valor(v: float) -> int:
    """Converte valor em centavos inteiros para comparação exata sem float drift."""
    return round(float(v) * 100)


def match_exato(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    tolerancia_dias: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Executa o match exato.

    Args:
        banco: DataFrame canônico do extrato bancário.
        sistema: DataFrame canônico do relatório do ERP.
        tolerancia_dias: dias corridos de tolerância na data (default 2).

    Returns:
        Tupla (conciliados, pendentes_banco, pendentes_sistema):
        - conciliados: DataFrame com pares casados (colunas com prefixo banco_ e sistema_).
        - pendentes_banco: linhas do banco sem casamento.
        - pendentes_sistema: linhas do sistema sem casamento.
    """
    if banco.empty and sistema.empty:
        return (
            pd.DataFrame(),
            banco.copy() if not banco.empty else pd.DataFrame(),
            sistema.copy() if not sistema.empty else pd.DataFrame(),
        )

    banco = banco.reset_index(drop=True).copy()
    sistema = sistema.reset_index(drop=True).copy()

    banco["_idx"] = banco.index
    sistema["_idx"] = sistema.index
    banco["_valor_centavos"] = banco["valor"].apply(_normalizar_valor)
    sistema["_valor_centavos"] = sistema["valor"].apply(_normalizar_valor)

    consumidos_sistema: set[int] = set()
    pares: list[tuple[int, int, int]] = []  # (idx_banco, idx_sistema, dias_diff)

    # Para cada linha do banco, busca o melhor candidato no sistema dentro da tolerância
    # Agrupa o sistema por (valor_centavos, conta) para acelerar.
    sistema_grupo = sistema.groupby(["_valor_centavos", "conta"])

    for _, linha_b in banco.iterrows():
        chave = (linha_b["_valor_centavos"], linha_b["conta"])
        if chave not in sistema_grupo.groups:
            continue
        idxs = sistema_grupo.groups[chave]
        candidatos = sistema.loc[idxs]
        candidatos = candidatos[~candidatos["_idx"].isin(consumidos_sistema)]
        if candidatos.empty:
            continue

        # Diferença de dias
        diffs = (candidatos["data"] - linha_b["data"]).abs().dt.days
        dentro_janela = candidatos[diffs <= tolerancia_dias].copy()
        if dentro_janela.empty:
            continue

        dentro_janela["_diff"] = (
            (dentro_janela["data"] - linha_b["data"]).abs().dt.days
        )
        # Menor diferença de dias primeiro; em empate, mantém ordem original
        dentro_janela = dentro_janela.sort_values(by=["_diff", "_idx"])
        escolhido = dentro_janela.iloc[0]
        idx_s = int(escolhido["_idx"])
        consumidos_sistema.add(idx_s)
        pares.append((int(linha_b["_idx"]), idx_s, int(escolhido["_diff"])))

    # Montagem dos DataFrames de saída
    if pares:
        idxs_banco = [p[0] for p in pares]
        idxs_sistema = [p[1] for p in pares]
        diffs_dias = [p[2] for p in pares]
        b = banco.loc[idxs_banco].reset_index(drop=True).drop(
            columns=["_idx", "_valor_centavos"]
        )
        s = sistema.loc[idxs_sistema].reset_index(drop=True).drop(
            columns=["_idx", "_valor_centavos"]
        )
        b = b.add_prefix("banco_")
        s = s.add_prefix("sistema_")
        conciliados = pd.concat([b, s], axis=1)
        conciliados["dias_diferenca"] = diffs_dias
        conciliados["status"] = "Conciliada"
        conciliados["motivo"] = conciliados["dias_diferenca"].apply(
            lambda d: "Match exato" if d == 0
            else f"Match com tolerância de data ({d} dia(s))"
        )
    else:
        conciliados = pd.DataFrame()

    idxs_b_consumidos = {p[0] for p in pares}
    pendentes_banco = (
        banco[~banco["_idx"].isin(idxs_b_consumidos)]
        .drop(columns=["_idx", "_valor_centavos"])
        .reset_index(drop=True)
    )
    pendentes_sistema = (
        sistema[~sistema["_idx"].isin(consumidos_sistema)]
        .drop(columns=["_idx", "_valor_centavos"])
        .reset_index(drop=True)
    )

    return conciliados, pendentes_banco, pendentes_sistema
