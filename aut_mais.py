"""Tratamento de aplicações/resgates AUT MAIS sem par no banco — v5.24.

CONTEXTO:
- O XLS do Itaú NÃO exporta as linhas `APL APLIC AUT MAIS` e `RES APLIC AUT MAIS`.
- Só exporta `REND PAGO APLIC AUT MAIS` (rendimentos de centavos) e `SDO CTA/APL`.
- O PDF mensal completo TEM essas linhas, mas o usuário usa o XLS.
- O Sankhya, por outro lado, registra as 3 movimentações (aplicação, resgate, rendimento).

EFEITO COLATERAL ANTES DESTA REGRA:
- 23 lançamentos APLIC./RESG. AUT MAIS no Sankhya ficavam em "Divergência sem par no banco".
- Eram falsos positivos: o XLS só não exporta, não é divergência real.

REGRA APLICADA:
- Identifica lançamentos no Sankhya com `categoria_mov in (aplicacao, resgate)`.
- Para cada um, verifica se existe par no banco (data+valor próximos).
- Se NÃO existir par no banco: marca como "Movimentação interna" e remove das pendências.
- Esses lançamentos sobem para o card "Investimentos" (que já existe).
- O usuário precisa saber: essas movimentações NÃO são divergência — o banco
  simplesmente não exporta no formato XLS que o Itaú gera.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


# Tolerância em centavos pra match exato com o banco (caso exista)
TOL_VALOR = 0.01


@dataclass
class ResultadoAutMais:
    """Lançamentos AUT MAIS do Sankhya sem par no banco — vão pro card Investimentos."""
    linhas_sem_par: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Linhas do Sankhya marcadas como movimentação interna (aplicação/resgate sem
    par no banco). Têm coluna `motivo_aut_mais` explicativa."""

    indices_sankhya_consumidos: set[int] = field(default_factory=set)
    """Posições (em pend_sistema reset_index) que devem sair das pendências."""

    @property
    def qtd(self) -> int:
        return len(self.linhas_sem_par)

    @property
    def valor_total(self) -> float:
        if self.linhas_sem_par.empty or "valor" not in self.linhas_sem_par.columns:
            return 0.0
        return float(self.linhas_sem_par["valor"].abs().sum())


def detectar_aut_mais_sem_par(
    pend_banco: pd.DataFrame,
    pend_sistema: pd.DataFrame,
) -> ResultadoAutMais:
    """Detecta APLIC./RESG. AUT MAIS no Sankhya que não têm par no banco.

    Args:
        pend_banco: pendências do banco após match 1-pra-1 e agrupamentos.
        pend_sistema: pendências do Sankhya após match 1-pra-1 e agrupamentos.

    Returns:
        ResultadoAutMais com as linhas pra mover pra Investimentos.
    """
    resultado = ResultadoAutMais()

    if pend_sistema.empty or "categoria_mov" not in pend_sistema.columns:
        return resultado

    ps = pend_sistema.reset_index(drop=True).copy()

    # Filtra apenas aplicação ou resgate (NÃO inclui REND PAGO — esses são receita normal)
    mask_aut = ps["categoria_mov"].isin(["aplicacao", "resgate"])
    candidatos = ps[mask_aut].copy()
    if candidatos.empty:
        return resultado

    # Pra cada candidato, verifica se existe par no banco com valor próximo na mesma data.
    # Se não existir, marca como "sem par".
    indices_sem_par: list[int] = []

    if pend_banco.empty or "data" not in pend_banco.columns or "valor" not in pend_banco.columns:
        # Banco vazio → todos os AUT MAIS estão sem par
        indices_sem_par = candidatos.index.tolist()
    else:
        for idx, linha in candidatos.iterrows():
            data_s = linha["data"]
            valor_s = float(linha["valor"])
            # Procura no banco lançamentos com mesma data e valor próximo
            mask = (
                (pend_banco["data"] == data_s)
                & ((pend_banco["valor"] - valor_s).abs() <= TOL_VALOR)
            )
            if not mask.any():
                indices_sem_par.append(idx)

    if not indices_sem_par:
        return resultado

    linhas_sem_par = candidatos.loc[indices_sem_par].copy()

    # Adiciona explicação visível ao usuário
    def _motivo(row):
        cat = row.get("categoria_mov", "")
        if cat == "aplicacao":
            return "Aplicação automática AUT MAIS — banco não exporta no XLS"
        if cat == "resgate":
            return "Resgate automático AUT MAIS — banco não exporta no XLS"
        return "Movimentação interna de investimento"

    linhas_sem_par["motivo_aut_mais"] = linhas_sem_par.apply(_motivo, axis=1)

    resultado.linhas_sem_par = linhas_sem_par
    resultado.indices_sankhya_consumidos = set(indices_sem_par)
    return resultado
