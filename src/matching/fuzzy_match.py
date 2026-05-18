"""Fuzzy matching de histórico — apenas para a aba 'Sugestões'.

NÃO entra na conciliação automática.
"""

from __future__ import annotations

import pandas as pd

try:
    from rapidfuzz import fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False


def sugerir_matches_fuzzy(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    score_minimo: int = 80,
) -> pd.DataFrame:
    """Para cada pendência de um lado, sugere o histórico mais similar do outro lado
    com mesmo valor (exato) e mesma conta.

    Args:
        score_minimo: 0-100. Filtra sugestões com similaridade abaixo desse limite.
    """
    if not _HAS_RAPIDFUZZ:
        return pd.DataFrame()
    if pendentes_banco.empty or pendentes_sistema.empty:
        return pd.DataFrame()

    sugestoes = []
    s = pendentes_sistema.copy()
    s["_centavos"] = (s["valor"] * 100).round().astype(int)
    s_por_chave = s.groupby(["_centavos", "conta"])

    for _, linha_b in pendentes_banco.iterrows():
        chave = (round(float(linha_b["valor"]) * 100), linha_b["conta"])
        if chave not in s_por_chave.groups:
            continue
        candidatos = s.loc[s_por_chave.groups[chave]]
        hist_b = str(linha_b["historico"])
        for _, linha_s in candidatos.iterrows():
            score = fuzz.token_set_ratio(hist_b, str(linha_s["historico"]))
            if score >= score_minimo:
                sugestoes.append({
                    "data_banco": linha_b["data"],
                    "data_sistema": linha_s["data"],
                    "conta": linha_b["conta"],
                    "valor": linha_b["valor"],
                    "historico_banco": hist_b,
                    "historico_sistema": linha_s["historico"],
                    "score": score,
                })

    if not sugestoes:
        return pd.DataFrame()
    return pd.DataFrame(sugestoes).sort_values("score", ascending=False).reset_index(drop=True)
