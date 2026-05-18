"""Auditorias complementares ao match exato.

- **Divergência de valor**: mesma data + histórico (após normalização) + conta,
  mas valores diferentes — só dispara quando a chave coincide e o valor não.
- **Duplicidades**: SÓ quando data + histórico + valor + documento são todos
  iguais entre múltiplos lançamentos. Valores iguais sozinhos NÃO são duplicidade.
- **Não pertence à conta**: lançamento existe na ponta "errada" — está em uma conta,
  mas tem candidato perfeito (data + valor) em OUTRA conta.
"""

from __future__ import annotations

import re

import pandas as pd


def _normalizar_historico(s: str) -> str:
    """Caixa alta + colapsa espaços em branco."""
    if not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s.strip().upper())


def _centavos(v: float) -> int:
    return round(float(v) * 100)


def detectar_divergencia_valor(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
) -> pd.DataFrame:
    """Pares que têm mesma data + histórico (normalizado) + conta mas valores diferentes.

    Rodado SOBRE PENDÊNCIAS (linhas que não casaram no match exato).
    """
    if pendentes_banco.empty or pendentes_sistema.empty:
        return pd.DataFrame()

    b = pendentes_banco.copy()
    s = pendentes_sistema.copy()
    b["_hist_norm"] = b["historico"].apply(_normalizar_historico)
    s["_hist_norm"] = s["historico"].apply(_normalizar_historico)

    merged = b.merge(
        s,
        left_on=["data", "_hist_norm", "conta"],
        right_on=["data", "_hist_norm", "conta"],
        suffixes=("_banco", "_sistema"),
        how="inner",
    )
    # Só interessa se o valor for diferente
    merged = merged[merged["valor_banco"] != merged["valor_sistema"]].copy()
    if merged.empty:
        return pd.DataFrame()

    merged["diferenca"] = merged["valor_banco"] - merged["valor_sistema"]
    merged["status"] = "Conciliada com Divergência"
    merged["motivo"] = "Mesma data/histórico/conta com valores diferentes"
    return merged.drop(columns=["_hist_norm"]).reset_index(drop=True)


def detectar_duplicidades(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
) -> pd.DataFrame:
    """Duplicidades ESTRITAS: data + histórico + valor + documento todos iguais.

    Para cada lado, agrupa por (data, histórico normalizado, valor, documento) e
    sinaliza quando o mesmo grupo aparece MAIS DE UMA VEZ.

    Returns:
        DataFrame com colunas: origem, data, historico, documento, valor, ocorrencias.
        Linha por grupo duplicado (não por lançamento individual).
    """
    resultados = []
    for nome, df in [("banco", banco), ("sistema", sistema)]:
        if df.empty:
            continue
        d = df.copy()
        d["_hist_norm"] = d["historico"].apply(_normalizar_historico)
        d["_doc_norm"] = d["documento"].fillna("").astype(str).str.strip().str.upper()
        # Apenas lançamentos COM documento (sem documento ≠ duplicidade — é tarifa avulsa, etc)
        d_com_doc = d[d["_doc_norm"].str.len() > 0]
        if d_com_doc.empty:
            continue
        agrupado = d_com_doc.groupby(
            ["data", "_hist_norm", "valor", "_doc_norm", "conta"]
        ).size().reset_index(name="ocorrencias")
        duplicados = agrupado[agrupado["ocorrencias"] > 1].copy()
        if duplicados.empty:
            continue
        duplicados["origem"] = nome
        duplicados = duplicados.rename(
            columns={"_hist_norm": "historico", "_doc_norm": "documento"}
        )
        resultados.append(duplicados)

    if not resultados:
        return pd.DataFrame()
    return pd.concat(resultados, ignore_index=True)[
        ["origem", "data", "conta", "historico", "documento", "valor", "ocorrencias"]
    ]


def detectar_nao_pertence(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    tolerancia_dias: int = 2,
) -> pd.DataFrame:
    """Pendências que parecem ter sido lançadas na conta ERRADA.

    Para cada pendência em uma conta, busca um candidato com mesma data±tolerância
    e mesmo valor em OUTRA conta na ponta oposta.

    Returns:
        DataFrame com colunas: origem, data, conta_atual, conta_sugerida, historico,
        documento, valor.
    """
    suspeitos = []

    for origem, lado, oposto in [
        ("banco", pendentes_banco, pendentes_sistema),
        ("sistema", pendentes_sistema, pendentes_banco),
    ]:
        if lado.empty or oposto.empty:
            continue
        oposto = oposto.copy()
        oposto["_centavos"] = oposto["valor"].apply(_centavos)
        op_por_valor = oposto.groupby("_centavos")

        for _, linha in lado.iterrows():
            cent = _centavos(linha["valor"])
            if cent not in op_por_valor.groups:
                continue
            candidatos = oposto.loc[op_por_valor.groups[cent]]
            # Mesma data ± tolerância, mas conta DIFERENTE
            candidatos = candidatos[
                (candidatos["conta"] != linha["conta"])
                & ((candidatos["data"] - linha["data"]).abs().dt.days <= tolerancia_dias)
            ]
            if candidatos.empty:
                continue
            # Escolhe a melhor (menor diff de dia)
            candidatos = candidatos.copy()
            candidatos["_diff"] = (candidatos["data"] - linha["data"]).abs().dt.days
            melhor = candidatos.sort_values("_diff").iloc[0]
            suspeitos.append({
                "origem": origem,
                "data": linha["data"],
                "conta_atual": linha["conta"],
                "conta_sugerida": melhor["conta"],
                "historico": linha["historico"],
                "documento": linha.get("documento", ""),
                "valor": linha["valor"],
                "dias_diff": int(melhor["_diff"]),
            })

    if not suspeitos:
        return pd.DataFrame()
    return pd.DataFrame(suspeitos)
