"""Orquestrador da conciliação — versão 2.

Mudanças sobre v1:
- Total Extrato Bancário EXCLUI linhas de saldo, aplicação e resgate.
- KPIs separam Receitas e Despesas (absolutos, não compensados).
- "Falta Lançar" usa coluna 'Conciliado=Não' do Sankhya quando ela existir e tiver
  valores válidos; senão usa a regra antiga (pendentes pós-match).
- Possíveis duplicidades (3 de 4 campos) em DataFrame separado.
- Aplicações e Resgates ficam disponíveis em DataFrame próprio.
- Saldo final calculado quando a conta está 100% conciliada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from .matching import (
    detectar_divergencia_valor,
    detectar_duplicidades,
    detectar_possiveis_duplicidades,
    detectar_nao_pertence,
    match_exato,
    sugerir_matches_fuzzy,
)
from .classificacao import (
    adicionar_classificacao,
    adicionar_categoria_movimento,
)


@dataclass
class ResultadoConciliacao:
    """Container com todos os DataFrames e metadados da conciliação."""

    conciliados: pd.DataFrame
    pendentes_banco: pd.DataFrame
    pendentes_sistema: pd.DataFrame
    divergencias: pd.DataFrame
    duplicidades: pd.DataFrame
    possiveis_duplicidades: pd.DataFrame
    nao_pertence: pd.DataFrame
    sugestoes_fuzzy: pd.DataFrame
    aplicacoes_resgates: pd.DataFrame
    falta_lancar_sankhya: pd.DataFrame  # quando Sankhya tem Conciliado=Não preenchido

    banco_completo: pd.DataFrame
    sistema_completo: pd.DataFrame

    data_referencia: datetime
    contas_processadas: list[str]
    tolerancia_dias: int
    usa_conciliado_sankhya: bool

    def kpis_globais(self) -> dict[str, Any]:
        return _calcular_kpis(
            self.conciliados,
            self.pendentes_banco,
            self.pendentes_sistema,
            self.divergencias,
            self.banco_completo,
            self.sistema_completo,
            self.falta_lancar_sankhya,
            self.usa_conciliado_sankhya,
        )

    def kpis_por_banco(self) -> dict[str, dict[str, Any]]:
        return {conta: self.kpis_da_conta(conta) for conta in self.contas_processadas}

    def kpis_da_conta(self, conta: str) -> dict[str, Any]:
        return _calcular_kpis(
            _filtrar_conciliados(self.conciliados, conta),
            _filtrar_conta(self.pendentes_banco, conta),
            _filtrar_conta(self.pendentes_sistema, conta),
            _filtrar_divergencias(self.divergencias, conta),
            _filtrar_conta(self.banco_completo, conta),
            _filtrar_conta(self.sistema_completo, conta),
            _filtrar_conta(self.falta_lancar_sankhya, conta) if self.usa_conciliado_sankhya else pd.DataFrame(),
            self.usa_conciliado_sankhya,
        )

    def conciliados_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conciliados(self.conciliados, conta)

    def divergencias_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_divergencias(self.divergencias, conta)

    def nao_pertence_da_conta(self, conta: str) -> pd.DataFrame:
        if self.nao_pertence.empty:
            return self.nao_pertence
        return self.nao_pertence[self.nao_pertence["conta_atual"] == conta].copy()

    def aplicacoes_resgates_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conta(self.aplicacoes_resgates, conta)

    def possiveis_duplicidades_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conta(self.possiveis_duplicidades, conta)

    def falta_lancar_da_conta(self, conta: str) -> pd.DataFrame:
        if self.usa_conciliado_sankhya:
            return _filtrar_conta(self.falta_lancar_sankhya, conta)
        return _filtrar_conta(self.pendentes_sistema, conta)

    def saldo_final_da_conta(self, conta: str) -> dict[str, Any] | None:
        """Retorna info de saldo final se a conta estiver 100% conciliada."""
        kpis = self.kpis_da_conta(conta)
        if kpis["percentual_conciliado"] < 99.99:
            return None

        banco = _filtrar_conta(self.banco_completo, conta)
        if banco.empty or "categoria_mov" not in banco.columns:
            return None

        saldos = banco[banco["categoria_mov"] == "saldo"].copy()
        saldo_inicial = saldo_final = None
        if not saldos.empty:
            saldos_ord = saldos.sort_values("data")
            try:
                saldo_inicial = float(saldos_ord.iloc[0]["valor"])
                saldo_final = float(saldos_ord.iloc[-1]["valor"])
            except Exception:
                pass

        mov_real = banco[banco["categoria_mov"] == "movimentacao"]
        mov_liquida = float(mov_real["valor"].sum()) if not mov_real.empty else 0.0

        return {
            "conta": conta,
            "saldo_inicial": saldo_inicial,
            "saldo_final": saldo_final,
            "movimentacao_liquida": mov_liquida,
            "periodo_de": banco["data"].min() if not banco.empty else None,
            "periodo_ate": banco["data"].max() if not banco.empty else None,
            "tem_saldo_no_extrato": saldo_final is not None,
        }


# ===========================================================================
# Helpers
# ===========================================================================

def _filtrar_conta(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty or "conta" not in df.columns:
        return df
    return df[df["conta"] == conta].copy()


def _filtrar_conciliados(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty:
        return df
    if "banco_conta" in df.columns:
        return df[df["banco_conta"] == conta].copy()
    return df


def _filtrar_divergencias(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty:
        return df
    if "conta" in df.columns:
        return df[df["conta"] == conta].copy()
    return df


def _soma_abs(df: pd.DataFrame, col: str = "valor") -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(df[col].abs().sum())


def _movimentacao_real(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra só linhas com categoria_mov == 'movimentacao'."""
    if df.empty or "categoria_mov" not in df.columns:
        return df
    return df[df["categoria_mov"] == "movimentacao"]


def _calcular_kpis(
    conciliados: pd.DataFrame,
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    divergencias: pd.DataFrame,
    banco_completo: pd.DataFrame,
    sistema_completo: pd.DataFrame,
    falta_lancar_sankhya: pd.DataFrame,
    usa_conciliado_sankhya: bool,
) -> dict[str, Any]:
    banco_mov = _movimentacao_real(banco_completo)
    sistema_mov = _movimentacao_real(sistema_completo)

    total_banco = _soma_abs(banco_mov)
    total_sistema = _soma_abs(sistema_mov)

    # Receitas e Despesas absolutas
    if not banco_mov.empty:
        receitas_banco = float(banco_mov[banco_mov["valor"] > 0]["valor"].sum())
        despesas_banco = float(banco_mov[banco_mov["valor"] < 0]["valor"].abs().sum())
    else:
        receitas_banco = despesas_banco = 0.0

    if not sistema_mov.empty:
        receitas_sistema = float(sistema_mov[sistema_mov["valor"] > 0]["valor"].sum())
        despesas_sistema = float(sistema_mov[sistema_mov["valor"] < 0]["valor"].abs().sum())
    else:
        receitas_sistema = despesas_sistema = 0.0

    # Conciliados
    if conciliados.empty:
        total_conciliado = 0.0
        receitas_conciliadas = despesas_conciliadas = 0.0
    else:
        c = conciliados
        total_conciliado = float(c["banco_valor"].abs().sum())
        receitas_conciliadas = float(c[c["banco_valor"] > 0]["banco_valor"].sum())
        despesas_conciliadas = float(c[c["banco_valor"] < 0]["banco_valor"].abs().sum())

    # Falta Conciliar (pendentes do banco, só movimentação)
    pb_mov = _movimentacao_real(pendentes_banco)
    falta_conciliar = _soma_abs(pb_mov)
    if not pb_mov.empty:
        falta_conciliar_receitas = float(pb_mov[pb_mov["valor"] > 0]["valor"].sum())
        falta_conciliar_despesas = float(pb_mov[pb_mov["valor"] < 0]["valor"].abs().sum())
    else:
        falta_conciliar_receitas = falta_conciliar_despesas = 0.0

    # Falta Lançar (Sankhya Conciliado=Não OU pendentes do match)
    if usa_conciliado_sankhya and not falta_lancar_sankhya.empty:
        fl_mov = _movimentacao_real(falta_lancar_sankhya)
        falta_lancar = _soma_abs(fl_mov)
    else:
        ps_mov = _movimentacao_real(pendentes_sistema)
        falta_lancar = _soma_abs(ps_mov)

    valor_divergencia = (
        float(divergencias["valor_banco"].abs().sum())
        if not divergencias.empty and "valor_banco" in divergencias.columns
        else 0.0
    )
    percentual = 100.0 * total_conciliado / total_banco if total_banco > 0 else 0.0

    return {
        "total_extrato_bancario": total_banco,
        "total_extrato_sistema": total_sistema,
        "total_conciliado": total_conciliado,
        "falta_conciliar": falta_conciliar,
        "falta_conciliar_receitas": falta_conciliar_receitas,
        "falta_conciliar_despesas": falta_conciliar_despesas,
        "falta_lancar": falta_lancar,
        "valor_divergencia": valor_divergencia,
        "percentual_conciliado": percentual,
        "receitas_banco": receitas_banco,
        "despesas_banco": despesas_banco,
        "receitas_sistema": receitas_sistema,
        "despesas_sistema": despesas_sistema,
        "receitas_conciliadas": receitas_conciliadas,
        "despesas_conciliadas": despesas_conciliadas,
        "total_absoluto_processado": total_banco + total_sistema,
        "qtd_registros_banco": int(len(banco_completo)),
        "qtd_registros_sistema": int(len(sistema_completo)),
        "qtd_movimentacoes_banco": int(len(banco_mov)),
        "qtd_movimentacoes_sistema": int(len(sistema_mov)),
        "qtd_conciliados": int(len(conciliados)),
        "qtd_pendentes_banco": int(len(pendentes_banco)),
        "qtd_pendentes_sistema": int(len(pendentes_sistema)),
        "qtd_divergencias": int(len(divergencias)),
        "qtd_total_processado": int(len(banco_completo) + len(sistema_completo)),
        "fonte_falta_lancar": (
            "sankhya_conciliado_nao" if usa_conciliado_sankhya else "pendentes_pos_match"
        ),
    }


# ===========================================================================
# Detecção de "Conciliado=Não" no Sankhya
# ===========================================================================

def _coluna_conciliado_util(df: pd.DataFrame) -> bool:
    if df.empty or "conciliado" not in df.columns:
        return False
    valores = df["conciliado"].dropna().astype(str).str.strip().str.upper()
    valores = valores[valores != ""]
    if valores.empty:
        return False
    valores_validos = valores.isin({"SIM", "NAO", "NÃO", "S", "N", "TRUE", "FALSE", "1", "0"})
    return bool(valores_validos.any())


def _filtrar_conciliado_nao(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "conciliado" not in df.columns:
        return df
    valores = df["conciliado"].fillna("").astype(str).str.strip().str.upper()
    return df[~valores.isin({"SIM", "S", "TRUE", "1"})].copy()


# ===========================================================================
# Extração de Aplicações e Resgates
# ===========================================================================

def _extrair_aplicacoes_resgates(banco: pd.DataFrame, sistema: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for nome, df in [("Banco", banco), ("Sankhya", sistema)]:
        if df.empty or "categoria_mov" not in df.columns:
            continue
        d = df[df["categoria_mov"].isin(
            ["aplicacao", "resgate", "investimento_outro"]
        )].copy()
        if d.empty:
            continue
        d["origem"] = nome
        d["tipo_aplicacao"] = d["categoria_mov"].map({
            "aplicacao": "Aplicação",
            "resgate": "Resgate",
            "investimento_outro": "Investimento",
        }).fillna("Indefinido")
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ===========================================================================
# Pipeline principal
# ===========================================================================

def executar_pipeline(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    data_referencia: datetime | None = None,
    tolerancia_dias: int = 2,
    rodar_fuzzy: bool = True,
) -> ResultadoConciliacao:
    if data_referencia is None:
        data_referencia = datetime.now()

    banco = adicionar_classificacao(banco)
    banco = adicionar_categoria_movimento(banco)
    sistema = adicionar_classificacao(sistema)
    sistema = adicionar_categoria_movimento(sistema)

    # Match exato usa SÓ movimentações reais (evita casar saldo×saldo, aplicação×aplicação)
    banco_mov = banco[banco["categoria_mov"] == "movimentacao"].copy() if not banco.empty else banco
    sistema_mov = sistema[sistema["categoria_mov"] == "movimentacao"].copy() if not sistema.empty else sistema

    conciliados, pend_banco, pend_sistema = match_exato(
        banco_mov, sistema_mov, tolerancia_dias=tolerancia_dias
    )

    if not conciliados.empty:
        conciliados["banco_categoria_mov"] = "movimentacao"
        conciliados["sistema_categoria_mov"] = "movimentacao"

    divergencias = detectar_divergencia_valor(pend_banco, pend_sistema)
    duplicidades = detectar_duplicidades(banco_mov, sistema_mov)
    possiveis_dup = detectar_possiveis_duplicidades(banco_mov, sistema_mov)
    nao_pertence = detectar_nao_pertence(pend_banco, pend_sistema, tolerancia_dias)
    sugestoes = sugerir_matches_fuzzy(pend_banco, pend_sistema) if rodar_fuzzy else pd.DataFrame()
    aplicacoes_resgates = _extrair_aplicacoes_resgates(banco, sistema)

    usa_conciliado = _coluna_conciliado_util(sistema)
    if usa_conciliado:
        falta_lancar_df = _filtrar_conciliado_nao(sistema)
        if "categoria_mov" in falta_lancar_df.columns:
            falta_lancar_df = falta_lancar_df[falta_lancar_df["categoria_mov"] == "movimentacao"]
    else:
        falta_lancar_df = pd.DataFrame()

    contas = sorted(set(banco["conta"].unique()) | set(sistema["conta"].unique()))
    contas = [c for c in contas if c and c != "—"]

    return ResultadoConciliacao(
        conciliados=conciliados,
        pendentes_banco=pend_banco,
        pendentes_sistema=pend_sistema,
        divergencias=divergencias,
        duplicidades=duplicidades,
        possiveis_duplicidades=possiveis_dup,
        nao_pertence=nao_pertence,
        sugestoes_fuzzy=sugestoes,
        aplicacoes_resgates=aplicacoes_resgates,
        falta_lancar_sankhya=falta_lancar_df,
        banco_completo=banco,
        sistema_completo=sistema,
        data_referencia=data_referencia,
        contas_processadas=contas,
        tolerancia_dias=tolerancia_dias,
        usa_conciliado_sankhya=usa_conciliado,
    )
