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
        elif pct_diff <= TOLERANCIA_REL_DIFERENCA:
            # Bateu COM DIFERENÇA (provavelmente taxa)
            status = "TOP 1722 com Diferença (provável taxa)"
            com_diff.append({
                "id_grupo": id_grupo,
                "conta": conta,
                "qtd_creditos_banco": len(creditos_cartao),
                "valor_banco_total": soma_banco,
                "qtd_linhas_sankhya": len(sis_conta),
                "valor_sankhya_total": soma_sankhya,
                "diferenca": diferenca,
                "percentual_diferenca": round(pct_diff * 100, 3),
                "status": status,
                "motivo": (
                    f"Sankhya R$ {soma_sankhya:.2f} × Banco R$ {soma_banco:.2f}. "
                    f"Diferença R$ {abs(diferenca):.2f} ({pct_diff*100:.2f}%). "
                    f"Provável taxa de cartão."
                ),
            })
            # Mesmo "com diferença", consome as linhas pra elas saírem de Pendentes/Divergência
            indices_banco_casados.update(int(i) for i in creditos_cartao["_idx_banco"].tolist())
            indices_sankhya_casados.update(int(i) for i in sis_conta["_idx_sis"].tolist())
        else:
            # Diferença grande demais (> 3.5%) — não agrupa, mas registra pra análise
            com_diff.append({
                "id_grupo": id_grupo,
                "conta": conta,
                "qtd_creditos_banco": len(creditos_cartao),
                "valor_banco_total": soma_banco,
                "qtd_linhas_sankhya": len(sis_conta),
                "valor_sankhya_total": soma_sankhya,
                "diferenca": diferenca,
                "percentual_diferenca": round(pct_diff * 100, 3),
                "status": "TOP 1722 com Diferença Grande (NÃO agrupado)",
                "motivo": (
                    f"Sankhya R$ {soma_sankhya:.2f} × Banco R$ {soma_banco:.2f}. "
                    f"Diferença R$ {abs(diferenca):.2f} ({pct_diff*100:.2f}%) excede o "
                    f"limite de {TOLERANCIA_REL_DIFERENCA*100:.1f}%. "
                    f"Linhas continuam em Pendentes."
                ),
            })
            # NÃO consome — deixa pra análise manual
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
