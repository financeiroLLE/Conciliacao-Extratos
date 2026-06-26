"""Conciliação por agrupamento — TOP 1702 (boleto).

Irmão do `cartao_top1722` (cartão). Mesma mecânica de SOMA TOTAL por conta:
- O banco recebe os boletos compactados em poucos créditos de cobrança
  (`CREDITO DE COBRANCA`, `COB COMPENSACAO`) = soma de vários boletos.
- O Sankhya, com TOP DE BAIXA = "1702", mostra os boletos individuais (desmembrado).
- Soma TODAS as linhas TOP 1702 do Sankhya por conta.
- Soma TODOS os créditos de cobrança do banco da mesma conta.
- Agrupa como bloco conciliado. A diferença (ex.: boleto pago por PIX QR, que entra
  no banco como PIX e não como cobrança) fica VISÍVEL pra investigação — não force
  "exato", e não espalha as milhares de linhas individuais em Pendentes/Divergência.

Diferença vs 1722: aqui SEMPRE agrupa quando os dois lados existem (a usuária pediu
para sempre considerar 1702 como recebimento de boleto e investigar a diferença),
em vez de ter um teto de tolerância que recusa o agrupamento.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


TOP_BOLETO = "1702"

# Termos no histórico do banco que indicam recebimento de boleto (cobrança).
TERMOS_BOLETO_BANCO = [
    "cobranc",        # CREDITO DE COBRANCA EM DINHEIRO
    "compensac",      # COB COMPENSACAO - DISPONIVEL / CR COB COMPENSACAO
]


@dataclass
class ResultadoTop1702:
    """Resultado da conciliação por agrupamento TOP 1702 (boleto)."""
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    """1 linha por conta agrupada. Colunas:
    conta, qtd_creditos_banco, valor_banco_total, qtd_linhas_sankhya,
    valor_sankhya_total, diferenca, percentual_diferenca, status, id_grupo"""

    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    com_diferenca: pd.DataFrame = field(default_factory=pd.DataFrame)

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


def _eh_boleto_no_banco(historico: str) -> bool:
    """True se o histórico do banco indica recebimento de boleto (cobrança)."""
    if not isinstance(historico, str):
        return False
    h = historico.lower()
    troca = str.maketrans("áàâãéèêíìóòôõúùç", "aaaaeeeiioooouuc")
    h = h.translate(troca)
    return any(termo in h for termo in TERMOS_BOLETO_BANCO)


def detectar_top_1702(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    janela_dias: int = 2,
) -> ResultadoTop1702:
    """Detecta agrupamento TOP 1702 (boleto) por conta usando SOMA TOTAL.

    Args:
        pendentes_banco: linhas do banco que NÃO casaram no match 1-a-1.
        pendentes_sistema: linhas do Sankhya que não casaram. Precisa de 'top_baixa'.
        janela_dias: mantido por compatibilidade (não usado nesta regra).
    """
    if pendentes_banco.empty or pendentes_sistema.empty:
        return ResultadoTop1702()
    if "top_baixa" not in pendentes_sistema.columns:
        return ResultadoTop1702()

    banco = pendentes_banco.copy().reset_index(drop=True)
    banco["_idx_banco"] = banco.index
    banco["data"] = pd.to_datetime(banco["data"], errors="coerce")
    banco["valor"] = pd.to_numeric(banco["valor"], errors="coerce")
    banco = banco[banco["data"].notna() & banco["valor"].notna()].copy()
    if banco.empty:
        return ResultadoTop1702()

    sis = pendentes_sistema.copy().reset_index(drop=True)
    sis["_idx_sis"] = sis.index
    sis["data"] = pd.to_datetime(sis["data"], errors="coerce")
    sis["valor"] = pd.to_numeric(sis["valor"], errors="coerce")
    sis["top_baixa_norm"] = sis["top_baixa"].astype(str).str.strip().str.replace(
        r"\.0$", "", regex=True
    )
    top1702 = sis[
        (sis["top_baixa_norm"] == TOP_BOLETO)
        & (sis["valor"] > 0)
        & sis["data"].notna()
    ].copy()
    if top1702.empty:
        return ResultadoTop1702()

    grupos = []
    com_diff = []
    linhas_sankhya_casadas = []
    linhas_banco_casadas = []
    indices_banco_casados: set[int] = set()
    indices_sankhya_casados: set[int] = set()
    proximo_id_grupo = 1

    contas_com_top1702 = sorted(top1702["conta"].astype(str).unique().tolist())

    for conta in contas_com_top1702:
        sis_conta = top1702[top1702["conta"].astype(str) == conta].copy()
        if sis_conta.empty:
            continue
        soma_sankhya = round(float(sis_conta["valor"].sum()), 2)

        banco_conta = banco[banco["conta"].astype(str) == conta].copy()
        if banco_conta.empty:
            continue
        creditos_boleto = banco_conta[
            (banco_conta["valor"] > 0)
            & banco_conta["historico"].fillna("").apply(_eh_boleto_no_banco)
        ].copy()
        if creditos_boleto.empty:
            continue
        soma_banco = round(float(creditos_boleto["valor"].sum()), 2)

        diferenca = round(soma_banco - soma_sankhya, 2)
        pct_diff = abs(diferenca) / soma_sankhya if soma_sankhya > 0 else 0.0

        id_grupo = f"B{proximo_id_grupo:04d}"
        proximo_id_grupo += 1

        if abs(diferenca) < 0.005:
            status = "Conciliado por Agrupamento — Boleto TOP 1702"
            grupos.append({
                "id_grupo": id_grupo,
                "conta": conta,
                "qtd_creditos_banco": len(creditos_boleto),
                "valor_banco_total": soma_banco,
                "qtd_linhas_sankhya": len(sis_conta),
                "valor_sankhya_total": soma_sankhya,
                "diferenca": diferenca,
                "percentual_diferenca": 0.0,
                "status": status,
            })
        else:
            # Sempre agrupa (regra do boleto), mas registra a diferença pra investigar.
            # A maior parte da diferença esperada é boleto pago por PIX QR (entra como
            # PIX no banco, não como cobrança) — por isso não tem teto de tolerância.
            com_diff.append({
                "id_grupo": id_grupo,
                "conta": conta,
                "qtd_creditos_banco": len(creditos_boleto),
                "valor_banco_total": soma_banco,
                "qtd_linhas_sankhya": len(sis_conta),
                "valor_sankhya_total": soma_sankhya,
                "diferenca": diferenca,
                "percentual_diferenca": round(pct_diff * 100, 3),
                "status": "Boleto TOP 1702 com Diferença (a investigar)",
                "motivo": (
                    f"Sankhya R$ {soma_sankhya:.2f} × Banco cobrança R$ {soma_banco:.2f}. "
                    f"Diferença R$ {abs(diferenca):.2f} ({pct_diff*100:.2f}%). "
                    f"Provável boleto pago por PIX QR (entra como PIX, não como cobrança) "
                    f"ou resíduo a investigar."
                ),
            })

        # Consome as linhas dos dois lados (sai de Pendentes/Divergência), exato ou não.
        indices_banco_casados.update(int(i) for i in creditos_boleto["_idx_banco"].tolist())
        indices_sankhya_casados.update(int(i) for i in sis_conta["_idx_sis"].tolist())

        for _, row in creditos_boleto.iterrows():
            linhas_banco_casadas.append({
                "id_grupo": id_grupo,
                "data": row["data"],
                "conta": conta,
                "historico": row.get("historico", ""),
                "documento": row.get("documento", ""),
                "valor": float(row["valor"]),
            })
        for _, row in sis_conta.iterrows():
            linhas_sankhya_casadas.append({
                "id_grupo": id_grupo,
                "data": row["data"],
                "conta": conta,
                "historico": row.get("historico", ""),
                "documento": row.get("documento", ""),
                "valor": float(row["valor"]),
                "top_baixa": TOP_BOLETO,
            })

    return ResultadoTop1702(
        grupos_conciliados=pd.DataFrame(grupos),
        linhas_sankhya_casadas=pd.DataFrame(linhas_sankhya_casadas),
        linhas_banco_casadas=pd.DataFrame(linhas_banco_casadas),
        com_diferenca=pd.DataFrame(com_diff),
        indices_banco_casados=indices_banco_casados,
        indices_sankhya_casados=indices_sankhya_casados,
    )
