"""
Auditorias adicionais que rodam em cima dos dados normalizados.

Tipos implementados (todos solicitados pelo usuário):

1. DUPLICIDADES — mesmo (data, valor, histórico, conta) aparecendo +1x
   no MESMO LADO (banco ou sistema). Detecta lançamentos contábeis
   duplicados que podem distorcer o caixa.

2. DIVERGÊNCIA DE VALOR — mesma (data, histórico-similar, conta) mas
   com valores DIFERENTES entre banco e sistema. Útil para pegar erros
   de digitação ou diferenças de centavos.

3. BANCO BAIXADO NO BANCO ERRADO — mesmo (data, valor) aparece no
   banco da conta A e no sistema da conta B. Indica que a equipe
   lançou na conta errada.
"""

from __future__ import annotations

import pandas as pd


def detectar_duplicidades(df: pd.DataFrame, lado: str) -> pd.DataFrame:
    """Encontra registros duplicados em (data, valor, historico, conta).

    Parameters
    ----------
    df : DataFrame de banco ou sistema
    lado : 'banco' ou 'sistema' (apenas para rotular)

    Returns
    -------
    DataFrame com as linhas duplicadas (todas as ocorrências), incluindo
    coluna '_qtd_duplicatas'.
    """
    if df.empty:
        return df.assign(_qtd_duplicatas=pd.Series(dtype=int), _lado=lado)

    chaves = ["data", "valor", "historico", "conta"]
    grupos = df.groupby(chaves).size().reset_index(name="_qtd_duplicatas")
    duplicados = grupos[grupos["_qtd_duplicatas"] > 1]

    if duplicados.empty:
        return df.iloc[0:0].assign(_qtd_duplicatas=0, _lado=lado)

    result = df.merge(duplicados, on=chaves, how="inner")
    result["_lado"] = lado
    return result.sort_values(chaves).reset_index(drop=True)


def detectar_divergencia_valor(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    tolerancia_centavos: float = 0.01,
) -> pd.DataFrame:
    """Encontra lançamentos com mesma data + conta + histórico similar mas
    valores diferentes entre banco e sistema.

    Usa similaridade de histórico com substring match simples (primeiros
    20 caracteres). É deliberadamente conservador — diferenças entre
    "PIX ENVIADO GRUPO LLE" e "LLE FERRAGENS" NÃO viram divergência.
    """
    if banco.empty or sistema.empty:
        return pd.DataFrame()

    # Considera apenas histórico bem parecido (mesmos primeiros 15 caracteres)
    b = banco.copy()
    s = sistema.copy()
    b["_hist_prefix"] = b["historico"].str.upper().str.slice(0, 15)
    s["_hist_prefix"] = s["historico"].str.upper().str.slice(0, 15)

    merged = b.merge(
        s,
        on=["data", "conta", "_hist_prefix"],
        suffixes=("_banco", "_sistema"),
    )

    if merged.empty:
        return pd.DataFrame()

    diferentes = merged[
        (merged["valor_banco"] - merged["valor_sistema"]).abs() > tolerancia_centavos
    ].copy()

    if diferentes.empty:
        return pd.DataFrame()

    diferentes["diferenca"] = (
        diferentes["valor_banco"] - diferentes["valor_sistema"]
    ).round(2)

    return diferentes[
        [
            "data",
            "conta",
            "historico_banco",
            "valor_banco",
            "historico_sistema",
            "valor_sistema",
            "diferenca",
        ]
    ].reset_index(drop=True)


def detectar_banco_errado(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
) -> pd.DataFrame:
    """Detecta lançamentos baixados na conta errada.

    Lógica:
    - Para cada lançamento PENDENTE no banco (conta A), procura no
      sistema lançamentos com mesma (data, valor) mas conta DIFERENTE.
    - Se encontrar, é forte indício de que o operador baixou na conta
      errada.

    Recebe os DataFrames JÁ FILTRADOS por pendência (idealmente os
    resultados de conciliar_exato).
    """
    if banco.empty or sistema.empty:
        return pd.DataFrame()

    merged = banco.merge(
        sistema,
        on=["data", "valor"],
        suffixes=("_banco", "_sistema"),
    )

    suspeitos = merged[merged["conta_banco"] != merged["conta_sistema"]].copy()

    if suspeitos.empty:
        return pd.DataFrame()

    return suspeitos[
        [
            "data",
            "valor",
            "conta_banco",
            "historico_banco",
            "conta_sistema",
            "historico_sistema",
            "usuario",
        ]
    ].rename(
        columns={
            "conta_banco": "conta_correta_banco",
            "conta_sistema": "conta_baixada_sistema",
            "usuario": "usuario_que_baixou",
        }
    ).reset_index(drop=True)
