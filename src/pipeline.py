"""
Pipeline principal de conciliação.

Encapsula todo o fluxo:
    1. Carrega extrato bancário
    2. Carrega relatório do sistema
    3. Carrega pendências anteriores (opcional)
    4. Roda conciliação exata
    5. Roda auditorias (duplicidades, divergências, banco errado)
    6. Roda fuzzy matching (sugestões)
    7. Gera relatório Excel

Pode ser usado tanto pelo app Streamlit quanto por scripts CLI / testes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from src.matching import (
    conciliar_exato,
    detectar_banco_errado,
    detectar_divergencia_valor,
    detectar_duplicidades,
    sugestoes_fuzzy,
)


@dataclass
class ResultadoConciliacao:
    """Resultado completo de uma execução do pipeline."""

    conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    pendentes_banco: pd.DataFrame = field(default_factory=pd.DataFrame)
    pendentes_sistema: pd.DataFrame = field(default_factory=pd.DataFrame)
    divergencia_valor: pd.DataFrame = field(default_factory=pd.DataFrame)
    duplicidades: pd.DataFrame = field(default_factory=pd.DataFrame)
    banco_errado: pd.DataFrame = field(default_factory=pd.DataFrame)
    sugestoes_fuzzy: pd.DataFrame = field(default_factory=pd.DataFrame)

    contas_processadas: list[str] = field(default_factory=list)
    data_referencia: datetime = field(default_factory=datetime.now)

    def as_dict(self) -> dict:
        """Converte para dict (formato esperado pelo gerador de Excel)."""
        return {
            "conciliados": self.conciliados,
            "pendentes_banco": self.pendentes_banco,
            "pendentes_sistema": self.pendentes_sistema,
            "divergencia_valor": self.divergencia_valor,
            "duplicidades": self.duplicidades,
            "banco_errado": self.banco_errado,
            "sugestoes_fuzzy": self.sugestoes_fuzzy,
        }

    def kpis(self) -> dict:
        """Retorna KPIs para o dashboard do Streamlit."""
        return {
            "total_conciliados": len(self.conciliados),
            "total_pendentes_banco": len(self.pendentes_banco),
            "total_pendentes_sistema": len(self.pendentes_sistema),
            "total_divergencias": len(self.divergencia_valor),
            "total_duplicidades": len(self.duplicidades),
            "total_banco_errado": len(self.banco_errado),
            "total_sugestoes": len(self.sugestoes_fuzzy),
            "valor_conciliado": float(self.conciliados["valor"].sum())
            if not self.conciliados.empty and "valor" in self.conciliados.columns
            else 0.0,
            "valor_pendente_banco": float(self.pendentes_banco["valor"].sum())
            if not self.pendentes_banco.empty
            else 0.0,
            "valor_pendente_sistema": float(self.pendentes_sistema["valor"].sum())
            if not self.pendentes_sistema.empty
            else 0.0,
        }


def executar_pipeline(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    data_referencia: datetime | None = None,
    rodar_fuzzy: bool = True,
) -> ResultadoConciliacao:
    """Executa todo o fluxo de conciliação.

    Parameters
    ----------
    banco : DataFrame normalizado do extrato bancário (já com coluna 'conta')
    sistema : DataFrame normalizado do relatório do sistema (já com 'conta')
    data_referencia : data da conciliação. Default = max(data) dos dois.
    rodar_fuzzy : se True, gera aba de sugestões (mais lento em datasets grandes).

    Returns
    -------
    ResultadoConciliacao
    """
    if data_referencia is None:
        datas = pd.concat([banco["data"], sistema["data"]])
        data_referencia = datas.max() if not datas.empty else datetime.now()

    # 1. Conciliação exata
    matches = conciliar_exato(banco, sistema)

    # 2. Auditorias
    dup_banco = detectar_duplicidades(banco, lado="banco")
    dup_sistema = detectar_duplicidades(sistema, lado="sistema")
    duplicidades = (
        pd.concat([dup_banco, dup_sistema], ignore_index=True)
        if not (dup_banco.empty and dup_sistema.empty)
        else pd.DataFrame()
    )

    divergencias = detectar_divergencia_valor(banco, sistema)

    banco_errado = detectar_banco_errado(
        matches["pendentes_banco"], matches["pendentes_sistema"]
    )

    # 3. Fuzzy (só nos que ainda estão pendentes)
    if rodar_fuzzy:
        # Excluir os que já foram identificados como "banco errado"
        # do conjunto de fuzzy, para não duplicar análise
        sugestoes = sugestoes_fuzzy(
            matches["pendentes_banco"],
            matches["pendentes_sistema"],
        )
    else:
        sugestoes = pd.DataFrame()

    # 4. Lista de contas processadas
    contas = sorted(
        set(banco["conta"].dropna().unique()) | set(sistema["conta"].dropna().unique())
    )

    return ResultadoConciliacao(
        conciliados=matches["conciliados"],
        pendentes_banco=matches["pendentes_banco"],
        pendentes_sistema=matches["pendentes_sistema"],
        divergencia_valor=divergencias,
        duplicidades=duplicidades,
        banco_errado=banco_errado,
        sugestoes_fuzzy=sugestoes,
        contas_processadas=contas,
        data_referencia=data_referencia if isinstance(data_referencia, datetime) else data_referencia.to_pydatetime(),
    )
