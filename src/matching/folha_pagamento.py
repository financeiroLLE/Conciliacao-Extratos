"""Conciliação por agrupamento — Folha de Pagamento (SISPAG SALARIOS).

Regra v5.21 (inversa ao TOP 1722):
- Banco mostra MUITOS lançamentos pequenos: SISPAG SALARIOS (um por funcionário)
- Sankhya tem 1 lançamento consolidado: "Folha de Pagamento" no valor total
- O sistema agrupa os SISPAG SALARIOS do banco por DATA + CONTA
- Soma e procura no Sankhya, na mesma data + conta, uma despesa com mesmo valor
- Se bater (com tolerância de centavo), conciliamos N→1
- Se não bater, vai pra divergência mostrando ambos os lados

Identificação dos lançamentos:
- BANCO: histórico contém "SISPAG SALARIOS" (case-insensitive, com/sem acento)
- SANKHYA: despesa na mesma data+conta com mesmo valor agregado
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


# Termos que identificam SISPAG SALARIOS no banco (case-insensitive, sem acento)
TERMOS_FOLHA_BANCO = [
    "sispag salarios",
    "sispag salario",
    "sispag salário",
    "sispag folha",
]

# Tolerância em R$ pra match exato (1 centavo)
TOLERANCIA_FOLHA = 0.01


@dataclass
class ResultadoFolhaPagamento:
    """Resultado da conciliação por agrupamento de Folha de Pagamento."""
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    """1 linha por grupo conciliado. Colunas:
    data, conta, qtd_sispag_banco, valor_banco_total, valor_sankhya,
    diferenca, status, id_grupo"""

    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Linhas do Sankhya consumidas (folha consolidada). Inclui id_grupo."""

    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    """SISPAG SALARIOS do banco consumidos pelo agrupamento."""

    indices_banco_casados: set[int] = field(default_factory=set)
    indices_sankhya_casados: set[int] = field(default_factory=set)

    @property
    def qtd_grupos(self) -> int:
        return len(self.grupos_conciliados)

    @property
    def valor_total_conciliado(self) -> float:
        if (self.grupos_conciliados.empty
                or "valor_banco_total" not in self.grupos_conciliados.columns):
            return 0.0
        return float(self.grupos_conciliados["valor_banco_total"].abs().sum())


def _eh_sispag_salarios(historico: str) -> bool:
    """True se o histórico do banco indica SISPAG SALARIOS."""
    if not isinstance(historico, str):
        return False
    h = historico.lower()
    # Remove acentos básicos
    troca = str.maketrans("áàâãéèêíìóòôõúùç", "aaaaeeeiioooouuc")
    h = h.translate(troca)
    return any(termo in h for termo in TERMOS_FOLHA_BANCO)


def detectar_folha_pagamento(
    pend_banco: pd.DataFrame,
    pend_sistema: pd.DataFrame,
) -> ResultadoFolhaPagamento:
    """Concilia SISPAG SALARIOS do banco (N linhas) com folha consolidada do Sankhya (1 linha).

    Args:
        pend_banco: pendências do banco depois do match 1-pra-1
        pend_sistema: pendências do Sankhya depois do match 1-pra-1

    Returns:
        ResultadoFolhaPagamento com grupos detectados e índices a remover das pendências.
    """
    resultado = ResultadoFolhaPagamento()

    if pend_banco.empty or pend_sistema.empty:
        return resultado

    # Garante reset_index pra trabalhar com posições
    pb = pend_banco.reset_index(drop=True).copy()
    ps = pend_sistema.reset_index(drop=True).copy()

    # === Lado BANCO: identificar SISPAG SALARIOS ===
    if "historico" not in pb.columns or "data" not in pb.columns or "valor" not in pb.columns:
        return resultado

    mask_sispag = pb["historico"].apply(_eh_sispag_salarios)
    sispag_banco = pb[mask_sispag].copy()
    if sispag_banco.empty:
        return resultado

    # SISPAG SALARIOS é DESPESA (valor < 0). Filtra só esses pra evitar pegar estornos.
    sispag_banco = sispag_banco[sispag_banco["valor"] < 0].copy()
    if sispag_banco.empty:
        return resultado

    # === Lado SANKHYA: candidatos a folha consolidada ===
    # São despesas (valor < 0). Não tem como filtrar mais — vamos procurar match por
    # valor exato dentro da mesma data.
    if "data" not in ps.columns or "valor" not in ps.columns:
        return resultado

    candidatos_sankhya = ps[ps["valor"] < 0].copy()
    if candidatos_sankhya.empty:
        return resultado

    # === Agrupa SISPAG do banco por (data, conta) ===
    conta_col = "conta" if "conta" in pb.columns else None
    if conta_col:
        chave_grupo = ["data", "conta"]
    else:
        chave_grupo = ["data"]

    grupos_banco = (
        sispag_banco.groupby(chave_grupo, dropna=False)
        .agg(
            qtd_sispag=("valor", "count"),
            valor_total=("valor", "sum"),
            indices_orig=("valor", lambda s: list(s.index)),
        )
        .reset_index()
    )

    # === Match: pra cada grupo do banco, procura no Sankhya ===
    grupos_conc_rows = []
    linhas_banco_casadas_rows = []
    linhas_sankhya_casadas_rows = []
    indices_banco_consumidos: set[int] = set()
    indices_sankhya_consumidos: set[int] = set()

    id_grupo = 0
    for _, grupo_b in grupos_banco.iterrows():
        data_g = grupo_b["data"]
        conta_g = grupo_b["conta"] if conta_col else None
        valor_banco = float(grupo_b["valor_total"])  # negativo (despesa)
        qtd_b = int(grupo_b["qtd_sispag"])

        # Filtra candidatos Sankhya com a mesma data + conta + valor compatível
        mask = candidatos_sankhya["data"] == data_g
        if conta_col and "conta" in candidatos_sankhya.columns:
            mask = mask & (candidatos_sankhya["conta"] == conta_g)
        # Tolerância em centavo
        mask = mask & (
            (candidatos_sankhya["valor"] - valor_banco).abs() <= TOLERANCIA_FOLHA
        )
        # Não pode pegar linha já consumida
        mask = mask & (~candidatos_sankhya.index.isin(indices_sankhya_consumidos))

        match_sankhya = candidatos_sankhya[mask]
        if match_sankhya.empty:
            continue  # não bateu, deixa o grupo nas pendências

        # Pega a primeira correspondência (se houver mais de uma, é caso raro de
        # múltiplas folhas no mesmo dia/conta com mesmo valor — pega a primeira)
        idx_sankhya = match_sankhya.index[0]
        linha_sankhya = match_sankhya.loc[idx_sankhya]
        valor_sankhya = float(linha_sankhya["valor"])

        id_grupo += 1

        # Marca como conciliados
        indices_banco_consumidos.update(grupo_b["indices_orig"])
        indices_sankhya_consumidos.add(idx_sankhya)

        # Adiciona ao grupo conciliado
        grupos_conc_rows.append({
            "id_grupo": id_grupo,
            "data": data_g,
            "conta": conta_g if conta_col else "—",
            "qtd_sispag_banco": qtd_b,
            "valor_banco_total": valor_banco,
            "valor_sankhya": valor_sankhya,
            "diferenca": valor_banco - valor_sankhya,
            "status": "Conciliado por folha agrupada",
            "historico_sankhya": str(linha_sankhya.get("historico", "")),
        })

        # Detalhe das linhas casadas (banco)
        for idx_b in grupo_b["indices_orig"]:
            linha_b = sispag_banco.loc[idx_b].copy()
            linha_b_dict = linha_b.to_dict()
            linha_b_dict["id_grupo"] = id_grupo
            linhas_banco_casadas_rows.append(linha_b_dict)

        # Detalhe da linha casada (sankhya)
        linha_s_dict = linha_sankhya.to_dict()
        linha_s_dict["id_grupo"] = id_grupo
        linhas_sankhya_casadas_rows.append(linha_s_dict)

    resultado.grupos_conciliados = pd.DataFrame(grupos_conc_rows)
    resultado.linhas_banco_casadas = pd.DataFrame(linhas_banco_casadas_rows)
    resultado.linhas_sankhya_casadas = pd.DataFrame(linhas_sankhya_casadas_rows)
    resultado.indices_banco_casados = indices_banco_consumidos
    resultado.indices_sankhya_casados = indices_sankhya_consumidos

    return resultado
