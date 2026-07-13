"""Conciliação por agrupamento — TOP 1722 (cartão de crédito).

Regra v5.2 (SIMPLIFICADA — soma total contra soma total por conta):
- Banco recebe valores compactados (poucos créditos = soma de várias vendas)
- Sankhya com TOP DE BAIXA = "1722" mostra as vendas individuais por cliente
- O sistema soma TODAS as linhas TOP 1722 do Sankhya por conta
- Soma TODOS os créditos do banco da mesma conta cujo histórico parece cartão
- Se as somas baterem (com tolerância configurável), considera tudo conciliado em bloco
- Se não bater exato, marca como "TOP 1722 com Diferença" mas AINDA assim agrupa
  (não joga as 51 linhas individuais em Pendentes/Divergência)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd
import re


TOP_CARTAO_CREDITO = "1722"
# Tolerância de diferença relativa pra ainda considerar "agrupado com taxa"
# (3.5% cobre taxas típicas de cartão de crédito)
TOLERANCIA_REL_DIFERENCA = 0.035

# Palavras-chave que indicam crédito de cartão no histórico do banco
TERMOS_CARTAO_BANCO = [
    "cartao", "cartão",
    "getnet",
    "pagseguro", "pag seguro", "pagbank",
    "cielo",
    "stone",
    "rede",
    "mercado pago", "mercadopago",
    "adquirente",
    "vendas cartao", "vendas cartão",
    "credito visa", "credito master", "credito elo",
]


@dataclass
class ResultadoTop1722:
    """Resultado da conciliação por agrupamento TOP 1722."""
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    """1 linha por conta agrupada. Colunas:
    conta, qtd_creditos_banco, valor_banco_total, qtd_linhas_sankhya,
    valor_sankhya_total, diferenca, percentual_diferenca, status, id_grupo"""

    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Linhas individuais do Sankhya consumidas pelo agrupamento.
    Inclui id_grupo pra cruzar com grupos_conciliados."""

    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Créditos do banco consumidos pelo agrupamento."""

    com_diferenca: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Grupos onde a soma não bateu exata mas foi agrupada como 'com diferença'.
    O usuário decide se aceita (taxa de cartão) ou não."""

    indices_banco_casados: set[int] = field(default_factory=set)
    indices_sankhya_casados: set[int] = field(default_factory=set)

    @property
    def qtd_grupos(self) -> int:
        return len(self.grupos_conciliados)

    @property
    def valor_total_conciliado(self) -> float:
        if self.grupos_conciliados.empty or "valor_banco_total" not in self.grupos_conciliados.columns:
            return 0.0
        return float(self.grupos_conciliados["valor_banco_total"].sum())


def _eh_cartao_no_banco(historico: str) -> bool:
    """True se o histórico do banco indica recebimento de cartão (adquirente)."""
    if not isinstance(historico, str):
        return False
    h = historico.lower()
    # Remove acentos básicos
    troca = str.maketrans("áàâãéèêíìóòôõúùç", "aaaaeeeiioooouuc")
    h = h.translate(troca)
    return any(termo in h for termo in TERMOS_CARTAO_BANCO)


def detectar_top_1722(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    janela_dias: int = 2,
) -> ResultadoTop1722:
    """Detecta agrupamento TOP 1722 por conta usando lógica de SOMA TOTAL.

    Args:
        pendentes_banco: linhas do banco que NÃO casaram no match 1-pra-1.
        pendentes_sistema: linhas do Sankhya que não casaram. Precisa ter coluna 'top_baixa'.
        janela_dias: mantido por compatibilidade (não usado nesta regra v5.2).

    Returns:
        ResultadoTop1722.
    """
    if pendentes_banco.empty or pendentes_sistema.empty:
        return ResultadoTop1722()
    if "top_baixa" not in pendentes_sistema.columns:
        return ResultadoTop1722()

    # Prepara banco
    banco = pendentes_banco.copy().reset_index(drop=True)
    banco["_idx_banco"] = banco.index
    banco["data"] = pd.to_datetime(banco["data"], errors="coerce")
    banco["valor"] = pd.to_numeric(banco["valor"], errors="coerce")
    banco = banco[banco["data"].notna() & banco["valor"].notna()].copy()
    if banco.empty:
        return ResultadoTop1722()

    # Prepara Sankhya — só linhas TOP 1722, valor > 0
    sis = pendentes_sistema.copy().reset_index(drop=True)
    sis["_idx_sis"] = sis.index
    sis["data"] = pd.to_datetime(sis["data"], errors="coerce")
    sis["valor"] = pd.to_numeric(sis["valor"], errors="coerce")
    sis["top_baixa_norm"] = sis["top_baixa"].astype(str).str.strip()
    top1722 = sis[
        (sis["top_baixa_norm"] == TOP_CARTAO_CREDITO)
        & (sis["valor"] > 0)
        & sis["data"].notna()
    ].copy()
    if top1722.empty:
        return ResultadoTop1722()

    grupos = []
    com_diff = []
    linhas_sankhya_casadas = []
    linhas_banco_casadas = []
    indices_banco_casados = set()
    indices_sankhya_casados = set()
    proximo_id_grupo = 1

    # Itera POR CONTA — cada conta tem o seu próprio agrupamento
    contas_com_top1722 = sorted(top1722["conta"].astype(str).unique().tolist())

    for conta in contas_com_top1722:
        # Sankhya TOP 1722 dessa conta
        sis_conta = top1722[top1722["conta"].astype(str) == conta].copy()
        if sis_conta.empty:
            continue
        soma_sankhya = round(float(sis_conta["valor"].sum()), 2)

        # Banco — créditos da mesma conta com histórico de cartão
        banco_conta = banco[banco["conta"].astype(str) == conta].copy()
        if banco_conta.empty:
            continue
        creditos_cartao = banco_conta[
            (banco_conta["valor"] > 0)
            & banco_conta["historico"].fillna("").apply(_eh_cartao_no_banco)
        ].copy()
        if creditos_cartao.empty:
            continue
        soma_banco = round(float(creditos_cartao["valor"].sum()), 2)

        diferenca = round(soma_banco - soma_sankhya, 2)
        pct_diff = abs(diferenca) / soma_sankhya if soma_sankhya > 0 else 0.0

        id_grupo = f"G{proximo_id_grupo:04d}"
        proximo_id_grupo += 1

        if abs(diferenca) < 0.005:
            # Bateu EXATO
            status = "Conciliado por Agrupamento — Cartão TOP 1722"
            grupos.append({
                "id_grupo": id_grupo,
                "conta": conta,
                "qtd_creditos_banco": len(creditos_cartao),
                "valor_banco_total": soma_banco,
                "qtd_linhas_sankhya": len(sis_conta),
                "valor_sankhya_total": soma_sankhya,
                "diferenca": diferenca,
                "percentual_diferenca": 0.0,
                "status": status,
            })
            # Consome todas as linhas
            indices_banco_casados.update(int(i) for i in creditos_cartao["_idx_banco"].tolist())
            indices_sankhya_casados.update(int(i) for i in sis_conta["_idx_sis"].tolist())
        else:
            # v5.53: a soma TOTAL não bateu — tenta POR DIA antes de desistir.
            # Caso real (Bradesco × Cielo): a baixa do Sankhya é pelo LÍQUIDO e a
            # soma diária fecha ao centavo com os depósitos do dia (2–3 bandeiras);
            # um único depósito fora do período (ex.: 10/07 sem Sankhya) poisonava
            # a conta inteira e jogava 60+ linhas em Pendentes. Dia que fecha
            # EXATO concilia; dia que não fecha continua visível. Zero suposição.
            _dias_b = creditos_cartao.assign(_dia=creditos_cartao["data"].dt.normalize())
            _dias_s = sis_conta.assign(_dia=sis_conta["data"].dt.normalize())
            _dias_comuns = sorted(set(_dias_b["_dia"]) & set(_dias_s["_dia"]))
            _dias_fechados = 0
            for _dia in _dias_comuns:
                _b_dia = _dias_b[_dias_b["_dia"] == _dia]
                _s_dia = _dias_s[_dias_s["_dia"] == _dia]
                _sb = round(float(_b_dia["valor"].sum()), 2)
                _ss = round(float(_s_dia["valor"].sum()), 2)
                if abs(_sb - _ss) < 0.005:
                    _idg = f"G{proximo_id_grupo:04d}"
                    proximo_id_grupo += 1
                    _dias_fechados += 1
                    grupos.append({
                        "id_grupo": _idg,
                        "conta": conta,
                        "qtd_creditos_banco": len(_b_dia),
                        "valor_banco_total": _sb,
                        "qtd_linhas_sankhya": len(_s_dia),
                        "valor_sankhya_total": _ss,
                        "diferenca": 0.0,
                        "percentual_diferenca": 0.0,
                        "status": f"Conciliado por Agrupamento — Cartão TOP 1722 (dia {_dia.strftime('%d/%m')})",
                    })
                    indices_banco_casados.update(int(i) for i in _b_dia["_idx_banco"].tolist())
                    indices_sankhya_casados.update(int(i) for i in _s_dia["_idx_sis"].tolist())
                    for _, row in _b_dia.iterrows():
                        linhas_banco_casadas.append({
                            "id_grupo": _idg, "data": row["data"], "conta": conta,
                            "historico": row.get("historico", ""),
                            "documento": row.get("documento", ""),
                            "valor": float(row["valor"]),
                        })
                    for _, row in _s_dia.iterrows():
                        linhas_sankhya_casadas.append({
                            "id_grupo": _idg, "data": row["data"], "conta": conta,
                            "historico": row.get("historico", ""),
                            "documento": row.get("documento", ""),
                            "valor": float(row["valor"]),
                            "top_baixa": row.get("top_baixa", ""),
                        })
            # o que sobrou (dias sem par exato) fica em "com diferença — a analisar"
            _rest_b = _dias_b[~_dias_b["_idx_banco"].isin(indices_banco_casados)]
            _rest_s = _dias_s[~_dias_s["_idx_sis"].isin(indices_sankhya_casados)]
            if not _rest_b.empty or not _rest_s.empty:
                _sb_r = round(float(_rest_b["valor"].sum()), 2)
                _ss_r = round(float(_rest_s["valor"].sum()), 2)
                _dif_r = round(_sb_r - _ss_r, 2)
                _pct_r = abs(_dif_r) / _ss_r if _ss_r > 0 else 0.0
                com_diff.append({
                    "id_grupo": id_grupo,
                    "conta": conta,
                    "qtd_creditos_banco": len(_rest_b),
                    "valor_banco_total": _sb_r,
                    "qtd_linhas_sankhya": len(_rest_s),
                    "valor_sankhya_total": _ss_r,
                    "diferenca": _dif_r,
                    "percentual_diferenca": round(_pct_r * 100, 3),
                    "status": "TOP 1722 com Diferença — a analisar",
                    "motivo": (
                        f"{_dias_fechados} dia(s) fecharam ao centavo e foram conciliados. "
                        f"Restou: Sankhya R$ {_ss_r:.2f} × Banco R$ {_sb_r:.2f}. "
                        f"Diferença R$ {abs(_dif_r):.2f}. "
                        f"Não confirmado como taxa — valor em aberto, a analisar. "
                        f"As linhas restantes continuam em Pendentes."
                    ),
                })
            # este ramo já registrou as próprias linhas — NUNCA cai no bloco de
            # registro do caso "total exato" abaixo.
            continue

        # Registra linhas individuais consumidas (banco)
        for _, row in creditos_cartao.iterrows():
            linhas_banco_casadas.append({
                "id_grupo": id_grupo,
                "data": row["data"],
                "conta": conta,
                "historico": row.get("historico", ""),
                "documento": row.get("documento", ""),
                "valor": float(row["valor"]),
            })
        # Registra linhas individuais consumidas (sankhya)
        for _, row in sis_conta.iterrows():
            linhas_sankhya_casadas.append({
                "id_grupo": id_grupo,
                "data": row["data"],
                "conta": conta,
                "historico": row.get("historico", ""),
                "documento": row.get("documento", ""),
                "valor": float(row["valor"]),
                "top_baixa": TOP_CARTAO_CREDITO,
            })

    return ResultadoTop1722(
        grupos_conciliados=pd.DataFrame(grupos),
        linhas_sankhya_casadas=pd.DataFrame(linhas_sankhya_casadas),
        linhas_banco_casadas=pd.DataFrame(linhas_banco_casadas),
        com_diferenca=pd.DataFrame(com_diff),
        indices_banco_casados=indices_banco_casados,
        indices_sankhya_casados=indices_sankhya_casados,
    )
