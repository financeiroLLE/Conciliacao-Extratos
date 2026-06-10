"""Tarifas de adquirente descontadas (TARIFA ALUGUEL GETNET) — v5.28.

CONTEXTO:
- Quando a empresa recebe pagamentos via cartão pela GETNET, o valor que entra no
  banco JÁ VEM com a tarifa descontada.
- No Sankhya, no entanto, a tarifa é lançada como uma linha separada.
- Por exemplo:
  - Sankhya: GETNET ELO -R$ 1.000,00 (venda bruta) + TARIFA ALUGUEL -R$ 69,37
  - Banco:   GETNET ELO -R$ 930,63 (líquido, já descontou a tarifa)
- Resultado: a linha TARIFA ALUGUEL no Sankhya NÃO TEM PAR no banco.

REGRA:
- Identifica lançamentos no Sankhya com histórico contendo padrões de tarifa de
  adquirente (GETNET por enquanto): 'TARIFA ALUGUEL', 'Trans Excedentes', 'Plat Digital'.
- Remove esses lançamentos das pendências do Sankhya (eles JAMAIS terão par no banco).
- Eles são contabilizados num grupo próprio "Tarifas de adquirente já descontadas".

EXPANSÃO FUTURA:
- Quando ampliar pra Cielo, Rede, Stone etc, adicionar palavras-chave aqui.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


# Palavras-chave que identificam tarifa de adquirente já descontada
# (case-insensitive, busca por contains)
TERMOS_TARIFA_ADQUIRENTE = [
    "tarifa aluguel",       # GETNET: "TARIFA ALUGUEL- Aluguel/Tarifa..."
    "trans excedentes",     # GETNET: "...Trans Excedentes..."
    "plat digital",         # GETNET: "...Plat Digital..."
    "plataforma digital",   # variante
]


@dataclass
class ResultadoTarifasAdquirente:
    linhas_sem_par: pd.DataFrame = field(default_factory=pd.DataFrame)
    indices_sankhya_consumidos: set[int] = field(default_factory=set)

    @property
    def qtd(self) -> int:
        return len(self.linhas_sem_par)

    @property
    def valor_total(self) -> float:
        if self.linhas_sem_par.empty or "valor" not in self.linhas_sem_par.columns:
            return 0.0
        return float(self.linhas_sem_par["valor"].abs().sum())


def _eh_tarifa_adquirente(historico: str) -> bool:
    """True se o histórico indica tarifa de adquirente."""
    if not isinstance(historico, str):
        return False
    h = historico.lower()
    return any(termo in h for termo in TERMOS_TARIFA_ADQUIRENTE)


def detectar_tarifas_adquirente(
    pend_sistema: pd.DataFrame,
) -> ResultadoTarifasAdquirente:
    """Identifica tarifas de adquirente (TARIFA ALUGUEL GETNET) sem par no banco.

    Args:
        pend_sistema: pendências do Sankhya após match e outros agrupamentos.

    Returns:
        ResultadoTarifasAdquirente com as linhas pra remover das pendências.
    """
    resultado = ResultadoTarifasAdquirente()

    if pend_sistema.empty or "historico" not in pend_sistema.columns:
        return resultado

    ps = pend_sistema.reset_index(drop=True).copy()

    mask = ps["historico"].apply(_eh_tarifa_adquirente)
    if not mask.any():
        return resultado

    linhas_sem_par = ps[mask].copy()
    linhas_sem_par["motivo_tarifa_adquirente"] = (
        "Tarifa GETNET já descontada do valor líquido recebido no banco "
        "(sem par individual no extrato)"
    )

    resultado.linhas_sem_par = linhas_sem_par
    resultado.indices_sankhya_consumidos = set(linhas_sem_par.index.tolist())
    return resultado
