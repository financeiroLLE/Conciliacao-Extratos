"""Orquestrador da conciliação — versão 3.

Mudanças sobre v2:
- "Total Movimentado no Banco" (renomeado de "Total Extrato Bancário") agora INCLUI
  aplicações e resgates. Só EXCLUI linhas de SALDO.
- Auditoria nova: detecta excesso de lançamentos no Sankhya em relação ao banco.
- Cards "Receitas Absolutas" e "Despesas Absolutas" foram removidos do dashboard.
- Cards de "Aplicações" e "Resgates" foram unificados em um único card "Investimentos".
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
    detectar_excesso_sankhya,
    detectar_excesso_sankhya_pos_match,
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
    excesso_sankhya: pd.DataFrame  # v3: lançamentos a mais no Sankhya
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
            self.excesso_sankhya,
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
            _filtrar_conta(self.excesso_sankhya, conta),
        )

    def divergencias_sankhya_banco(self, conta: str | None = None) -> pd.DataFrame:
        """v3.4: Visão consolidada de divergências entre Sankhya e Banco.

        Une 3 origens:
        - 'Sem par no banco': lançamentos do Sankhya com Conciliado=Não ou pendentes pós-match
        - 'Excesso no Sankhya': Sankhya tem N>M lançamentos com mesma data+valor+conta
        - 'Valor diferente': mesma chave (data+hist+conta), valor diferente

        Deduplica por (data, valor, hist, conta) — uma linha pode aparecer em vários grupos.
        """
        frames = []

        # 1) Sem par no banco
        # v3.11 BUGFIX: se a fonte é 'Conciliado=Não do Sankhya', precisamos REMOVER
        # as linhas que JÁ casaram no nosso match automático. Caso contrário, uma
        # linha pode aparecer ao mesmo tempo como 'Conciliada' (porque bateu com o
        # banco) e como 'Divergência - Sem par no banco' (porque o Sankhya marca
        # ela como Conciliado=Não no campo do ERP).
        if self.usa_conciliado_sankhya and not self.falta_lancar_sankhya.empty:
            df_origem = _eh_movimentado(self.falta_lancar_sankhya)
            # Remove linhas que aparecem em 'conciliados' (lado sistema)
            if not self.conciliados.empty and not df_origem.empty:
                # Identifica chaves (data, valor, conta) que já casaram
                sis_cols = [c for c in self.conciliados.columns if c.startswith("sistema_")]
                if sis_cols:
                    chaves_casadas = set()
                    for _, row in self.conciliados.iterrows():
                        data_v = row.get("sistema_data")
                        valor_v = row.get("sistema_valor")
                        conta_v = row.get("sistema_conta")
                        hist_v = row.get("sistema_historico", "")
                        if data_v is not None and valor_v is not None:
                            chaves_casadas.add(
                                (str(data_v), round(float(valor_v), 2),
                                 str(conta_v), str(hist_v))
                            )
                    def _esta_casada(linha):
                        return (
                            str(linha.get("data")),
                            round(float(linha.get("valor", 0)), 2),
                            str(linha.get("conta", "")),
                            str(linha.get("historico", "")),
                        ) in chaves_casadas
                    df_origem = df_origem[~df_origem.apply(_esta_casada, axis=1)]
            df = df_origem
        else:
            df = _eh_movimentado(self.pendentes_sistema)
        if not df.empty:
            d = df[["data", "valor", "historico", "conta"]].copy()
            d["documento"] = df.get("documento", "")
            d["origem_divergencia"] = "Sem par no banco"
            frames.append(d)

        # 2) Excesso no Sankhya
        if not self.excesso_sankhya.empty:
            d = self.excesso_sankhya[["data", "valor", "historico", "conta"]].copy()
            d["documento"] = self.excesso_sankhya.get("documento", "")
            d["origem_divergencia"] = "Excesso no Sankhya"
            frames.append(d)

        # 3) Valor diferente
        if not self.divergencias.empty and "valor_sistema" in self.divergencias.columns:
            d = self.divergencias[["data", "valor_sistema", "historico_sistema"]].copy()
            d.columns = ["data", "valor", "historico"]
            d["conta"] = self.divergencias.get("conta", "")
            d["documento"] = self.divergencias.get("documento_sistema", "")
            d["origem_divergencia"] = "Valor diferente"
            frames.append(d)

        if not frames:
            return pd.DataFrame(columns=[
                "data", "valor", "historico", "documento", "conta", "origem_divergencia"
            ])
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["data", "valor", "historico", "conta"])
        out = out.reset_index(drop=True)

        if conta is not None:
            out = out[out["conta"] == conta].copy()
        return out

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

    def excesso_sankhya_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conta(self.excesso_sankhya, conta)

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

        # v3: movimentação líquida considera TUDO que é movimentado (movimentacao+aplic+resgate)
        movimentado = banco[banco["categoria_mov"] != "saldo"]
        mov_liquida = float(movimentado["valor"].sum()) if not movimentado.empty else 0.0

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


def _eh_movimentado(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra linhas que contam como movimentação financeira (v3).

    REGRA v3: inclui movimentação normal + aplicações + resgates + investimentos.
    SÓ exclui linhas de SALDO (saldo inicial/final/bloqueado/aplic auto etc).
    """
    if df.empty or "categoria_mov" not in df.columns:
        return df
    return df[df["categoria_mov"] != "saldo"]


def _calcular_kpis(
    conciliados: pd.DataFrame,
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    divergencias: pd.DataFrame,
    banco_completo: pd.DataFrame,
    sistema_completo: pd.DataFrame,
    falta_lancar_sankhya: pd.DataFrame,
    usa_conciliado_sankhya: bool,
    excesso_sankhya: pd.DataFrame | None = None,
) -> dict[str, Any]:
    banco_mov = _eh_movimentado(banco_completo)
    sistema_mov = _eh_movimentado(sistema_completo)

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
    pb_mov = _eh_movimentado(pendentes_banco)
    falta_conciliar = _soma_abs(pb_mov)
    if not pb_mov.empty:
        falta_conciliar_receitas = float(pb_mov[pb_mov["valor"] > 0]["valor"].sum())
        falta_conciliar_despesas = float(pb_mov[pb_mov["valor"] < 0]["valor"].abs().sum())
    else:
        falta_conciliar_receitas = falta_conciliar_despesas = 0.0

    # v3.4: DIVERGÊNCIA (Sankhya × Banco) — consolida 3 origens:
    #   1. Sankhya com Conciliado=Não OU pendentes pós-match (Sankhya sem par no banco)
    #   2. Excesso no Sankhya (mesma data+valor+conta, Sankhya tem mais que o banco)
    #   3. Divergência de valor (mesma chave, valor diferente)
    # As 3 podem se sobrepor, então deduplicamos pelo conjunto (data, valor, hist, conta).

    # v3.11 BUGFIX: linhas do Sankhya com 'Conciliado=Não' que JÁ casaram no nosso
    # match não devem entrar em 'Sem par no banco'. Caso comum: lançamentos
    # contabilmente "não conciliados" no ERP mas que batem 1-pra-1 com o banco.
    chaves_casadas_sis = set()
    if not conciliados.empty:
        for _, row in conciliados.iterrows():
            d_v = row.get("sistema_data")
            v_v = row.get("sistema_valor")
            c_v = row.get("sistema_conta")
            h_v = row.get("sistema_historico", "")
            if d_v is not None and v_v is not None:
                chaves_casadas_sis.add(
                    (str(d_v), round(float(v_v), 2), str(c_v), str(h_v))
                )

    def _remover_casadas(df_sis: pd.DataFrame) -> pd.DataFrame:
        if df_sis.empty or not chaves_casadas_sis:
            return df_sis
        def _key(linha):
            return (
                str(linha.get("data")),
                round(float(linha.get("valor", 0)), 2),
                str(linha.get("conta", "")),
                str(linha.get("historico", "")),
            )
        return df_sis[~df_sis.apply(lambda r: _key(r) in chaves_casadas_sis, axis=1)]

    if usa_conciliado_sankhya and not falta_lancar_sankhya.empty:
        sem_par_banco = _remover_casadas(_eh_movimentado(falta_lancar_sankhya))
    else:
        sem_par_banco = _remover_casadas(_eh_movimentado(pendentes_sistema))

    # Junta com excesso e divergências de valor
    frames_diverg = []
    if not sem_par_banco.empty:
        d = sem_par_banco[["data", "valor", "historico", "conta"]].copy()
        d["origem_divergencia"] = "Sem par no banco"
        frames_diverg.append(d)
    if excesso_sankhya is not None and not excesso_sankhya.empty:
        d = excesso_sankhya[["data", "valor", "historico", "conta"]].copy()
        d["origem_divergencia"] = "Excesso no Sankhya"
        frames_diverg.append(d)
    if not divergencias.empty and "valor_sistema" in divergencias.columns:
        d = divergencias[["data", "valor_sistema", "historico_sistema"]].copy()
        d.columns = ["data", "valor", "historico"]
        d["conta"] = divergencias.get("conta", "")
        d["origem_divergencia"] = "Valor diferente"
        frames_diverg.append(d)

    if frames_diverg:
        divergencia_total_df = pd.concat(frames_diverg, ignore_index=True)
        # Dedup por (data, valor, hist, conta) — uma linha pode estar em 2 grupos
        divergencia_total_df = divergencia_total_df.drop_duplicates(
            subset=["data", "valor", "historico", "conta"]
        )
    else:
        divergencia_total_df = pd.DataFrame(
            columns=["data", "valor", "historico", "conta", "origem_divergencia"]
        )

    falta_lancar = float(divergencia_total_df["valor"].abs().sum()) if not divergencia_total_df.empty else 0.0
    if not divergencia_total_df.empty:
        falta_lancar_receitas = float(divergencia_total_df[divergencia_total_df["valor"] > 0]["valor"].sum())
        falta_lancar_despesas = float(divergencia_total_df[divergencia_total_df["valor"] < 0]["valor"].abs().sum())
    else:
        falta_lancar_receitas = falta_lancar_despesas = 0.0
    qtd_divergencia_total = int(len(divergencia_total_df))

    valor_divergencia = (
        float(divergencias["valor_banco"].abs().sum())
        if not divergencias.empty and "valor_banco" in divergencias.columns
        else 0.0
    )
    percentual = 100.0 * total_conciliado / total_banco if total_banco > 0 else 0.0

    return {
        # v3: renomeado de "Total Extrato Bancário" → "Total Movimentado no Banco".
        # Mantém o nome antigo como alias por retrocompatibilidade.
        "total_movimentado_banco": total_banco,
        "total_extrato_bancario": total_banco,
        "total_extrato_sistema": total_sistema,
        "total_conciliado": total_conciliado,
        "falta_conciliar": falta_conciliar,
        "falta_conciliar_receitas": falta_conciliar_receitas,
        "falta_conciliar_despesas": falta_conciliar_despesas,
        # v3.4: 'Divergência (Sankhya × Banco)' agrega 3 origens.
        # Aliases novos:
        "divergencia_sankhya_banco": falta_lancar,
        "divergencia_sankhya_banco_receitas": falta_lancar_receitas,
        "divergencia_sankhya_banco_despesas": falta_lancar_despesas,
        "qtd_divergencia_sankhya_banco": qtd_divergencia_total,
        # Aliases antigos (Falta Lançar) mantidos por retrocompat:
        "falta_lancar": falta_lancar,
        "falta_lancar_receitas": falta_lancar_receitas,
        "falta_lancar_despesas": falta_lancar_despesas,
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

    # Match exato — v3: usa TUDO que é movimentado (movimentacao + aplic + resgate + investimento).
    # Só exclui linhas de SALDO, que não são movimentação real.
    banco_mov = _eh_movimentado(banco).copy() if not banco.empty else banco
    sistema_mov = _eh_movimentado(sistema).copy() if not sistema.empty else sistema

    conciliados, pend_banco, pend_sistema = match_exato(
        banco_mov, sistema_mov, tolerancia_dias=tolerancia_dias
    )

    if not conciliados.empty:
        # Preserva a categoria_mov no resultado conciliado (pra dashboards)
        # Não força mais "movimentacao" — o valor original já vem do match
        pass

    divergencias = detectar_divergencia_valor(pend_banco, pend_sistema)
    duplicidades = detectar_duplicidades(banco_mov, sistema_mov)
    possiveis_dup = detectar_possiveis_duplicidades(banco_mov, sistema_mov)

    # v3.1: excesso_sankhya considera APENAS as pendências do sistema (o que não casou).
    # Conta quantas linhas pendentes do Sankhya excedem as pendências do banco
    # para o mesmo perfil (data + valor + conta).
    excesso_sis = detectar_excesso_sankhya_pos_match(pend_banco, pend_sistema)
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
        excesso_sankhya=excesso_sis,
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
