"""Detecção de estornos (pares pagamento/recebimento + estorno dentro do banco).

Regra: dentro do MESMO extrato bancário, procura pares onde:
- valor absoluto é exatamente igual
- sinais são opostos (um positivo, um negativo)
- histórico do estorno contém palavra-chave (estorno, devolução, chargeback, etc)
- janela de data: estorno até 7 dias depois do lançamento original
- mesma conta

Quando saldo líquido = 0 → "Anulado por Estorno" (sai dos cálculos)
Quando saldo líquido ≠ 0 → "Estorno Parcial" (diferença volta pra análise)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd
import re


# Palavras-chave que identificam estorno (case/acento insensitive)
TERMOS_ESTORNO = [
    "estorno",
    "estornado",
    "estornada",
    "devolucao",
    "devol de titulo",
    "devol titulo",
    "devol de cheque",
    "devolvido",
    "devolvida",
    "cancelamento",
    "cancelado",
    "cancelada",
    "reversao",
    "revertido",
    "revertida",
    "chargeback",
    "reembolso",
    "reembolsado",
    "ajuste de credito",
    "ajuste de debito",
    "pagamento estornado",
    "recebimento estornado",
]

# Janela máxima de data entre lançamento original e estorno
JANELA_DIAS = 7


@dataclass
class ResultadoEstornos:
    """Pares anulados e parciais encontrados."""
    anulados: pd.DataFrame = field(default_factory=pd.DataFrame)
    parciais: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Índices do banco que devem ser removidos do fluxo principal
    indices_anulados: set[int] = field(default_factory=set)
    # Pra estornos parciais: índices removidos + linha sintética "saldo restante" adicionada
    indices_parciais_removidos: set[int] = field(default_factory=set)
    saldos_parciais: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def qtd_anulados(self) -> int:
        return len(self.anulados)

    @property
    def qtd_parciais(self) -> int:
        return len(self.parciais)

    @property
    def valor_bruto_anulado(self) -> float:
        if self.anulados.empty or "valor_original" not in self.anulados.columns:
            return 0.0
        return float(self.anulados["valor_original"].abs().sum())

    @property
    def saldo_liquido_parciais(self) -> float:
        if self.parciais.empty or "saldo_liquido" not in self.parciais.columns:
            return 0.0
        return float(self.parciais["saldo_liquido"].sum())


def _normalizar(s: str) -> str:
    """Lowercase, sem acento, sem símbolo."""
    if not isinstance(s, str):
        return ""
    s = s.lower()
    troca = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")
    return s.translate(troca)


def _eh_estorno_historico(historico: str) -> bool:
    """True se o histórico contém alguma palavra-chave de estorno."""
    norm = _normalizar(historico)
    return any(termo in norm for termo in TERMOS_ESTORNO)


def detectar_estornos(banco: pd.DataFrame) -> ResultadoEstornos:
    """Detecta pares de estorno no extrato bancário.

    Args:
        banco: DataFrame do extrato com colunas data, valor, historico, conta.

    Returns:
        ResultadoEstornos com anulados (saldo zero) e parciais (saldo != zero).
    """
    if banco.empty or "valor" not in banco.columns:
        return ResultadoEstornos()

    df = banco.copy().reset_index(drop=True)
    df["_idx_orig"] = df.index

    # Garantir tipos
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df.dropna(subset=["data", "valor"])
    if df.empty:
        return ResultadoEstornos()

    # Marca quais linhas TÊM histórico de estorno
    df["_eh_estorno"] = df["historico"].fillna("").apply(_eh_estorno_historico)

    estornos = df[df["_eh_estorno"]].copy()
    candidatos = df[~df["_eh_estorno"]].copy()  # lançamentos originais

    if estornos.empty or candidatos.empty:
        return ResultadoEstornos()

    anulados_rows = []
    parciais_rows = []
    indices_anulados = set()
    indices_parciais = set()
    saldos_restantes = []
    estornos_usados = set()  # evita reutilizar mesmo estorno em vários pares

    # Pra cada estorno, procura o lançamento original
    # Critério: mesma conta, sinal oposto, valor absoluto = idêntico, data <= 7 dias antes
    for idx_est, est in estornos.iterrows():
        if idx_est in estornos_usados:
            continue
        sinal_est = 1 if est["valor"] > 0 else -1
        # Procura candidatos: mesma conta + sinal oposto
        cand = candidatos[
            (candidatos["conta"] == est["conta"])
            & (np.sign(candidatos["valor"]) == -sinal_est)
            & (~candidatos["_idx_orig"].isin(indices_anulados))
            & (~candidatos["_idx_orig"].isin(indices_parciais))
        ].copy()

        if cand.empty:
            continue

        # Janela de data: lançamento original <= estorno + JANELA_DIAS, >= estorno - JANELA_DIAS
        data_est = est["data"]
        cand["_dias"] = (data_est - cand["data"]).dt.days
        cand = cand[(cand["_dias"] >= -JANELA_DIAS) & (cand["_dias"] <= JANELA_DIAS)]
        if cand.empty:
            continue

        # Pega o candidato mais próximo em data com valor EXATAMENTE igual em módulo
        cand["_diff_valor"] = (cand["valor"].abs() - abs(est["valor"])).abs()
        cand_exato = cand[cand["_diff_valor"] < 0.005]  # diferença < meio centavo

        if not cand_exato.empty:
            # Anulação total
            cand_exato = cand_exato.sort_values("_dias", key=lambda x: x.abs())
            par = cand_exato.iloc[0]
            anulados_rows.append({
                "data_original": par["data"],
                "data_estorno": est["data"],
                "conta": est["conta"],
                "historico_original": par.get("historico", ""),
                "historico_estorno": est.get("historico", ""),
                "documento_original": par.get("documento", ""),
                "documento_estorno": est.get("documento", ""),
                "valor_original": float(par["valor"]),
                "valor_estornado": float(est["valor"]),
                "saldo_liquido": round(float(par["valor"]) + float(est["valor"]), 2),
                "tipo": _classificar_tipo(par.get("historico", "")),
                "motivo": _motivo_estorno(est.get("historico", "")),
                "status": "Anulado por Estorno",
            })
            indices_anulados.add(int(par["_idx_orig"]))
            indices_anulados.add(int(est["_idx_orig"]))
            estornos_usados.add(idx_est)
        else:
            # Estorno parcial: valor estornado != valor original
            # Pega o candidato com valor absoluto MAIOR que o do estorno
            # (caso clássico: pagamento R$ 1000, estorno parcial R$ 300, saldo R$ 700)
            cand_maior = cand[cand["valor"].abs() > abs(est["valor"]) + 0.005]
            if cand_maior.empty:
                continue
            cand_maior = cand_maior.sort_values("_dias", key=lambda x: x.abs())
            par = cand_maior.iloc[0]
            saldo_liq = round(float(par["valor"]) + float(est["valor"]), 2)
            parciais_rows.append({
                "data_original": par["data"],
                "data_estorno": est["data"],
                "conta": est["conta"],
                "historico_original": par.get("historico", ""),
                "historico_estorno": est.get("historico", ""),
                "documento_original": par.get("documento", ""),
                "documento_estorno": est.get("documento", ""),
                "valor_original": float(par["valor"]),
                "valor_estornado": float(est["valor"]),
                "saldo_liquido": saldo_liq,
                "tipo": _classificar_tipo(par.get("historico", "")),
                "motivo": _motivo_estorno(est.get("historico", "")),
                "status": "Estorno Parcial",
            })
            # Estorno parcial: REMOVE par e estorno; ADICIONA linha sintética com saldo_liq
            indices_parciais.add(int(par["_idx_orig"]))
            indices_parciais.add(int(est["_idx_orig"]))
            saldos_restantes.append({
                "data": par["data"],
                "valor": saldo_liq,
                "historico": f"[ESTORNO PARCIAL] {par.get('historico', '')}",
                "documento": par.get("documento", ""),
                "conta": par["conta"],
                "origem": "banco",
            })
            estornos_usados.add(idx_est)

    anulados_df = pd.DataFrame(anulados_rows) if anulados_rows else pd.DataFrame()
    parciais_df = pd.DataFrame(parciais_rows) if parciais_rows else pd.DataFrame()
    saldos_df = pd.DataFrame(saldos_restantes) if saldos_restantes else pd.DataFrame()

    return ResultadoEstornos(
        anulados=anulados_df,
        parciais=parciais_df,
        indices_anulados=indices_anulados,
        indices_parciais_removidos=indices_parciais,
        saldos_parciais=saldos_df,
    )


def _classificar_tipo(historico: str) -> str:
    """Classifica o tipo do lançamento original pelo histórico."""
    norm = _normalizar(historico)
    if "cartao" in norm or "cartão" in norm.lower() or "stone" in norm or "cielo" in norm or "rede" in norm:
        return "Cartão"
    if "pix" in norm:
        return "Pix"
    if "boleto" in norm:
        return "Boleto"
    if "ted" in norm or "doc" in norm:
        return "TED/DOC"
    if "tarifa" in norm or "tar liq" in norm or "tar cob" in norm:
        return "Tarifa"
    if "pagamento" in norm or "sispag" in norm:
        return "Pagamento"
    if "recebimento" in norm or "credito" in norm:
        return "Recebimento"
    return "Outro"


def _motivo_estorno(historico_estorno: str) -> str:
    """Identifica qual palavra-chave foi usada no histórico do estorno."""
    norm = _normalizar(historico_estorno)
    for termo in TERMOS_ESTORNO:
        if termo in norm:
            return termo.capitalize()
    return "Estorno"


# Import lazy do numpy (só usado em uma linha)
import numpy as np
