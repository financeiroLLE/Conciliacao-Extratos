"""
Fuzzy matching — APENAS para a aba de SUGESTÕES.

O usuário foi explícito: fuzzy NÃO entra na conciliação automática.
Ele aparece só como sugestão para revisão humana, em uma aba separada.

Estratégia:
- Pega pendências do banco e pendências do sistema
- Para cada pendência do banco, procura no sistema lançamentos com:
  * Mesma conta
  * Mesma data (ou ±2 dias)
  * Valor próximo (tolerância configurável)
  * Histórico com similaridade > 60% (rapidfuzz)
- Retorna pares ordenados por confiança decrescente
"""

from __future__ import annotations

import pandas as pd

try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False


def _similaridade_historico(a: str, b: str) -> float:
    """Similaridade entre dois históricos, 0-100."""
    if _HAS_RAPIDFUZZ:
        # token_set_ratio é o melhor pra históricos bancários porque
        # "PIX ENVIADO LLE FERRAGENS" vs "LLE FERRAGENS PIX" dá ~100
        return fuzz.token_set_ratio(a.upper(), b.upper())
    # Fallback simples se rapidfuzz não estiver disponível
    a_set = set(a.upper().split())
    b_set = set(b.upper().split())
    if not a_set or not b_set:
        return 0.0
    intersec = len(a_set & b_set)
    return 100 * intersec / max(len(a_set), len(b_set))


def sugestoes_fuzzy(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    tolerancia_dias: int = 2,
    tolerancia_valor: float = 0.10,
    min_similaridade: int = 60,
    max_sugestoes_por_lancamento: int = 3,
) -> pd.DataFrame:
    """Gera sugestões de conciliação baseadas em similaridade.

    Parameters
    ----------
    pendentes_banco : DataFrame de pendências do banco
    pendentes_sistema : DataFrame de pendências do sistema
    tolerancia_dias : aceita diferença de até N dias
    tolerancia_valor : tolerância em valor absoluto (R$ 0,10 por padrão)
    min_similaridade : similaridade mínima no histórico (0-100)
    max_sugestoes_por_lancamento : limite de sugestões por linha do banco

    Returns
    -------
    DataFrame ordenado por similaridade decrescente.
    """
    if pendentes_banco.empty or pendentes_sistema.empty:
        return pd.DataFrame()

    sugestoes = []

    for _, b in pendentes_banco.iterrows():
        # Janela de candidatos: mesma conta, data próxima, valor próximo
        cand = pendentes_sistema[
            (pendentes_sistema["conta"] == b["conta"])
            & ((pendentes_sistema["data"] - b["data"]).abs() <= pd.Timedelta(days=tolerancia_dias))
            & ((pendentes_sistema["valor"] - b["valor"]).abs() <= tolerancia_valor)
        ]

        if cand.empty:
            continue

        # Calcula similaridade do histórico para cada candidato
        cand = cand.copy()
        cand["_similaridade"] = cand["historico"].apply(
            lambda h: _similaridade_historico(b["historico"], h)
        )
        cand = cand[cand["_similaridade"] >= min_similaridade]
        cand = cand.nlargest(max_sugestoes_por_lancamento, "_similaridade")

        for _, s in cand.iterrows():
            sugestoes.append(
                {
                    "data_banco": b["data"],
                    "historico_banco": b["historico"],
                    "valor_banco": b["valor"],
                    "conta": b["conta"],
                    "data_sistema": s["data"],
                    "historico_sistema": s["historico"],
                    "valor_sistema": s["valor"],
                    "diferenca_dias": (s["data"] - b["data"]).days,
                    "diferenca_valor": round(s["valor"] - b["valor"], 2),
                    "similaridade_%": round(s["_similaridade"], 1),
                    "_row_id_banco": b["_row_id"],
                    "_row_id_sistema": s["_row_id"],
                }
            )

    if not sugestoes:
        return pd.DataFrame()

    return (
        pd.DataFrame(sugestoes)
        .sort_values("similaridade_%", ascending=False)
        .reset_index(drop=True)
    )
