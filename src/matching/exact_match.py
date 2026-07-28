"""Match exato entre extrato bancário e relatório do sistema.

REGRAS (atualizadas conforme briefing de produto):
- Valor: precisa ser EXATAMENTE igual (sem tolerância de centavos).
- Data: aceita tolerância de ±N dias corridos (default 2 — cobre fim de semana e
  feriados curtos). Quando há múltiplos candidatos dentro da janela, prefere o
  de menor diferença absoluta de dias.
- Conta: igual (com normalização de espaços múltiplos e trim — v5.90).
- Matching é 1-pra-1: cada lançamento do banco casa com no máximo um do sistema.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd


def _normalizar_valor(v: float) -> int:
    """Converte valor em centavos inteiros para comparação exata sem float drift."""
    return round(float(v) * 100)


def _normalizar_conta(v) -> str:
    """v5.90: normaliza nome da conta para comparação tolerante.

    Colapsa espaços múltiplos em um único (o Sankhya às vezes exporta com
    espaço duplo — ex.: 'ITAU INOV AG. 0023  C/C 54016-4' — e o usuário
    digita no upload do banco com um espaço só ou copy/paste com dois. Sem
    esta normalização, contas idênticas na intenção ficam diferentes na
    comparação e o match cai a zero).

    - Preserva o valor original nos DataFrames (usado só na chave interna).
    - Aplica strip para tolerar espaços no início/fim.
    - Não altera case: mantém sensibilidade a maiúsculas/minúsculas para
      evitar merge acidental de contas que só diferem por caixa.
    """
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    # " ".join(str.split()) colapsa qualquer whitespace (espaços, tabs)
    # em um único espaço e faz strip nas pontas
    return " ".join(str(v).split())


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

    # v3.6: força tipos consistentes pra evitar erros em datetime arithmetic e merges
    for df in (banco, sistema):
        if "data" in df.columns:
            df["data"] = pd.to_datetime(df["data"], errors="coerce")
        if "valor" in df.columns:
            df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)

    banco["_idx"] = banco.index
    sistema["_idx"] = sistema.index
    banco["_valor_centavos"] = banco["valor"].apply(_normalizar_valor)
    sistema["_valor_centavos"] = sistema["valor"].apply(_normalizar_valor)

    consumidos_sistema: set[int] = set()
    pares: list[tuple[int, int, int]] = []  # (idx_banco, idx_sistema, dias_diff)

    # v5.33: mesma lógica do match guloso 1-a-1 (mesma chave valor+conta, dentro da
    # tolerância de dias, menor diferença de dias e, no empate, menor índice original),
    # mas em estruturas Python puras — sem o custo do Pandas por linha. Em volume
    # (milhares de linhas) isso é dezenas de vezes mais rápido, com resultado idêntico.
    NS_DIA = 86_400_000_000_000

    b_idx = banco["_idx"].to_numpy()
    b_cent = banco["_valor_centavos"].to_numpy()
    # v5.90: normaliza conta antes de comparar (colapsa espaços múltiplos e faz strip).
    # Sem isso, digitação com espaço duplo/simples diferente do que veio do Sankhya
    # zerava o match. Ver docstring de _normalizar_conta.
    b_conta = banco["conta"].apply(_normalizar_conta).to_numpy()
    b_ns = banco["data"].to_numpy(dtype="datetime64[ns]").astype("int64")
    b_nat = banco["data"].isna().to_numpy()

    s_idx = sistema["_idx"].to_numpy()
    s_cent = sistema["_valor_centavos"].to_numpy()
    s_conta = sistema["conta"].apply(_normalizar_conta).to_numpy()
    s_ns = sistema["data"].to_numpy(dtype="datetime64[ns]").astype("int64")
    s_nat = sistema["data"].isna().to_numpy()

    # candidatos do sistema por chave (valor_centavos, conta), em ordem original
    candidatos_por_chave: dict[tuple, list[int]] = {}
    for pos in range(len(s_idx)):
        candidatos_por_chave.setdefault((s_cent[pos], s_conta[pos]), []).append(pos)

    for pos_b in range(len(b_idx)):
        if b_nat[pos_b]:
            continue
        lista = candidatos_por_chave.get((b_cent[pos_b], b_conta[pos_b]))
        if not lista:
            continue
        ns_b = int(b_ns[pos_b])
        melhor_pos = -1
        melhor_diff = None
        for pos_s in lista:  # em ordem de índice original → empate fica no menor índice
            if s_nat[pos_s]:
                continue
            idx_s = int(s_idx[pos_s])
            if idx_s in consumidos_sistema:
                continue
            diff = abs(ns_b - int(s_ns[pos_s])) // NS_DIA
            if diff <= tolerancia_dias and (melhor_diff is None or diff < melhor_diff):
                melhor_diff = diff
                melhor_pos = pos_s
        if melhor_pos >= 0:
            idx_s = int(s_idx[melhor_pos])
            consumidos_sistema.add(idx_s)
            pares.append((int(b_idx[pos_b]), idx_s, int(melhor_diff)))

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
