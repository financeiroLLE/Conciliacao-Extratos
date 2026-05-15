"""Orquestrador da conciliação.

Recebe os DataFrames já parseados de banco e sistema, aplica match exato,
auditorias, classificação por tipo e devolve um ResultadoConciliacao com
todos os DataFrames e KPIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from .matching import (
    detectar_divergencia_valor,
    detectar_duplicidades,
    detectar_nao_pertence,
    match_exato,
    sugerir_matches_fuzzy,
)
from .classificacao import adicionar_classificacao


@dataclass
class ResultadoConciliacao:
    """Container com todos os DataFrames e metadados da conciliação."""

    conciliados: pd.DataFrame
    pendentes_banco: pd.DataFrame
    pendentes_sistema: pd.DataFrame
    divergencias: pd.DataFrame  # conciliadas com divergência
    duplicidades: pd.DataFrame
    nao_pertence: pd.DataFrame
    sugestoes_fuzzy: pd.DataFrame

    banco_completo: pd.DataFrame  # input original do banco (com classificação)
    sistema_completo: pd.DataFrame  # input original do sistema (com classificação)

    data_referencia: datetime
    contas_processadas: list[str]
    tolerancia_dias: int

    def kpis_globais(self) -> dict[str, float]:
        """KPIs agregados — todos os bancos somados."""
        return _calcular_kpis(
            self.conciliados,
            self.pendentes_banco,
            self.pendentes_sistema,
            self.divergencias,
            self.banco_completo,
            self.sistema_completo,
        )

    def kpis_por_banco(self) -> dict[str, dict[str, float]]:
        """KPIs separados por conta/banco."""
        out: dict[str, dict[str, float]] = {}
        for conta in self.contas_processadas:
            out[conta] = self.kpis_da_conta(conta)
        return out

    def kpis_da_conta(self, conta: str) -> dict[str, float]:
        """KPIs filtrados por uma conta específica."""
        return _calcular_kpis(
            _filtrar_conciliados(self.conciliados, conta),
            self.pendentes_banco[self.pendentes_banco["conta"] == conta]
            if not self.pendentes_banco.empty else self.pendentes_banco,
            self.pendentes_sistema[self.pendentes_sistema["conta"] == conta]
            if not self.pendentes_sistema.empty else self.pendentes_sistema,
            _filtrar_divergencias(self.divergencias, conta),
            self.banco_completo[self.banco_completo["conta"] == conta]
            if not self.banco_completo.empty else self.banco_completo,
            self.sistema_completo[self.sistema_completo["conta"] == conta]
            if not self.sistema_completo.empty else self.sistema_completo,
        )

    def conciliados_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conciliados(self.conciliados, conta)

    def divergencias_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_divergencias(self.divergencias, conta)

    def nao_pertence_da_conta(self, conta: str) -> pd.DataFrame:
        if self.nao_pertence.empty:
            return self.nao_pertence
        return self.nao_pertence[self.nao_pertence["conta_atual"] == conta].copy()


def _filtrar_conciliados(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty:
        return df
    # Em conciliados a conta está em banco_conta (e em sistema_conta, deveriam ser iguais)
    if "banco_conta" in df.columns:
        return df[df["banco_conta"] == conta].copy()
    return df


def _filtrar_divergencias(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty:
        return df
    if "conta" in df.columns:
        return df[df["conta"] == conta].copy()
    return df


def _calcular_kpis(
    conciliados: pd.DataFrame,
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    divergencias: pd.DataFrame,
    banco_completo: pd.DataFrame,
    sistema_completo: pd.DataFrame,
) -> dict[str, float]:
    """KPIs financeiros + de contagem.

    Definições (em R$, usando o valor absoluto onde fizer sentido):
    - total_extrato_bancario: soma absoluta de todos os lançamentos do banco
    - total_extrato_sistema: soma absoluta de todos os lançamentos do sistema
    - total_conciliado: soma absoluta dos lançamentos que casaram (lado banco)
    - falta_conciliar: soma absoluta das pendências do BANCO (falta baixar no sistema)
    - falta_lancar: soma absoluta das pendências do SISTEMA (lançado indevidamente / não está no banco)
    - valor_divergencia: soma absoluta dos valores no banco que têm divergência
    - percentual_conciliado: total_conciliado / total_extrato_bancario × 100
    """
    def soma_abs(df: pd.DataFrame, col: str = "valor") -> float:
        if df.empty or col not in df.columns:
            return 0.0
        return float(df[col].abs().sum())

    total_banco_valor = soma_abs(banco_completo)
    total_sistema_valor = soma_abs(sistema_completo)

    if conciliados.empty:
        total_conciliado_valor = 0.0
    else:
        total_conciliado_valor = float(conciliados["banco_valor"].abs().sum())

    falta_conciliar = soma_abs(pendentes_banco)
    falta_lancar = soma_abs(pendentes_sistema)
    valor_divergencia = (
        float(divergencias["valor_banco"].abs().sum())
        if not divergencias.empty and "valor_banco" in divergencias.columns
        else 0.0
    )
    percentual = (
        100.0 * total_conciliado_valor / total_banco_valor
        if total_banco_valor > 0 else 0.0
    )

    return {
        # Valores em R$
        "total_extrato_bancario": total_banco_valor,
        "total_extrato_sistema": total_sistema_valor,
        "total_conciliado": total_conciliado_valor,
        "falta_conciliar": falta_conciliar,
        "falta_lancar": falta_lancar,
        "valor_divergencia": valor_divergencia,
        "percentual_conciliado": percentual,
        # Contagens
        "qtd_registros_banco": int(len(banco_completo)),
        "qtd_registros_sistema": int(len(sistema_completo)),
        "qtd_conciliados": int(len(conciliados)),
        "qtd_pendentes_banco": int(len(pendentes_banco)),
        "qtd_pendentes_sistema": int(len(pendentes_sistema)),
        "qtd_divergencias": int(len(divergencias)),
        # Totais úteis
        "qtd_total_processado": int(len(banco_completo) + len(sistema_completo)),
    }


def executar_pipeline(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    data_referencia: datetime | None = None,
    tolerancia_dias: int = 2,
    rodar_fuzzy: bool = True,
) -> ResultadoConciliacao:
    """Executa o pipeline completo.

    Args:
        banco: DataFrame canônico do extrato bancário.
        sistema: DataFrame canônico do relatório do ERP.
        data_referencia: data de referência (D-1). Default: hoje.
        tolerancia_dias: tolerância de dias no match exato (default 2).
        rodar_fuzzy: se True, calcula sugestões fuzzy (aba de revisão manual).
    """
    if data_referencia is None:
        data_referencia = datetime.now()

    banco = adicionar_classificacao(banco)
    sistema = adicionar_classificacao(sistema)

    conciliados, pend_banco, pend_sistema = match_exato(
        banco, sistema, tolerancia_dias=tolerancia_dias
    )

    divergencias = detectar_divergencia_valor(pend_banco, pend_sistema)
    # Remove as pendências que viraram divergências (não somam duas vezes)
    if not divergencias.empty:
        # Marca por chave (data, hist_norm, conta)
        chaves_div = set(
            zip(
                divergencias["data"],
                divergencias["historico_banco"].fillna(""),
                divergencias["conta"],
            )
        )
        # Re-filtra pendentes removendo os que viraram divergência
        # (apenas marca via 'em_divergencia' — preserva os DataFrames originais)
        pend_banco = pend_banco.copy()
        pend_sistema = pend_sistema.copy()

    duplicidades = detectar_duplicidades(banco, sistema)
    nao_pertence = detectar_nao_pertence(pend_banco, pend_sistema, tolerancia_dias)
    sugestoes = (
        sugerir_matches_fuzzy(pend_banco, pend_sistema)
        if rodar_fuzzy else pd.DataFrame()
    )

    contas = sorted(set(banco["conta"].unique()) | set(sistema["conta"].unique()))
    contas = [c for c in contas if c and c != "—"]

    return ResultadoConciliacao(
        conciliados=conciliados,
        pendentes_banco=pend_banco,
        pendentes_sistema=pend_sistema,
        divergencias=divergencias,
        duplicidades=duplicidades,
        nao_pertence=nao_pertence,
        sugestoes_fuzzy=sugestoes,
        banco_completo=banco,
        sistema_completo=sistema,
        data_referencia=data_referencia,
        contas_processadas=contas,
        tolerancia_dias=tolerancia_dias,
    )
