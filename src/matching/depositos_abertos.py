"""Match agrupado N (Sankhya) → 1 (Banco) — v5.24.

CONTEXTO:
- Banco recebe 1 lançamento (ex: PIX TRANSF de R$ 89,97).
- Sankhya abre esse depósito em VÁRIOS lançamentos individuais (cada NFD, cada parcela).
- O match 1-pra-1 não acha par; ficam ambos em pendências.
- Mas se a SOMA das pendências Sankhya (na mesma data + conta) bater com o valor
  do banco, é casamento — só está aberto em mais linhas no Sankhya.

REGRA:
- Pra cada lançamento pendente do banco (com valor positivo OU negativo):
  - Procura combinações de pendências Sankhya com:
    - Mesma data + mesma conta + mesmo sinal (receita/despesa).
    - Que somem o valor do banco com tolerância de 1 centavo.
- Se achar, agrupa. Como pode haver muitas combinações, limita o subconjunto a
  no máximo 8 linhas pra não explodir combinatoriamente.

OBSERVAÇÃO sobre direção:
- Esta regra é DIFERENTE da folha_pagamento (N banco → 1 sankhya): aqui é o oposto.
- Ela trata o caso em que o ERP detalha o que o banco consolida (ex: abertura de notas).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import pandas as pd


TOL_VALOR = 0.01
MAX_LINHAS_COMBINACAO = 8  # limite de busca combinatória


@dataclass
class ResultadoDepositosAbertos:
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)

    indices_banco_casados: set[int] = field(default_factory=set)
    indices_sankhya_casados: set[int] = field(default_factory=set)

    @property
    def qtd(self) -> int:
        return len(self.grupos_conciliados)


def _buscar_subset_soma(
    valores: list[float], alvo: float, max_subset_size: int = MAX_LINHAS_COMBINACAO
) -> list[int] | None:
    """Acha um subset de índices em `valores` cuja soma == alvo (com tolerância)."""
    n = len(valores)
    if n == 0:
        return None
    # Tenta primeiro um único elemento (1-pra-1 valor exato)
    for i, v in enumerate(valores):
        if abs(v - alvo) <= TOL_VALOR:
            return [i]
    # Depois combinações de tamanho crescente
    limite = min(n, max_subset_size)
    for tam in range(2, limite + 1):
        for combo in combinations(range(n), tam):
            soma = sum(valores[i] for i in combo)
            if abs(soma - alvo) <= TOL_VALOR:
                return list(combo)
    return None


def detectar_depositos_abertos(
    pend_banco: pd.DataFrame,
    pend_sistema: pd.DataFrame,
) -> ResultadoDepositosAbertos:
    """Agrupa pendências do Sankhya cuja SOMA bate com 1 lançamento do banco.

    Casa por: mesma data + mesma conta + mesmo sinal (receita/despesa).
    """
    resultado = ResultadoDepositosAbertos()

    if pend_banco.empty or pend_sistema.empty:
        return resultado

    pb = pend_banco.reset_index(drop=True).copy()
    ps = pend_sistema.reset_index(drop=True).copy()

    if "data" not in pb.columns or "valor" not in pb.columns:
        return resultado

    # Conta opcional — se existir, usa; senão considera todas mesma conta
    tem_conta = "conta" in pb.columns and "conta" in ps.columns

    indices_banco_consumidos: set[int] = set()
    indices_sankhya_consumidos: set[int] = set()
    grupos_rows = []
    linhas_banco_rows = []
    linhas_sankhya_rows = []
    id_grupo = 0

    for idx_b, linha_b in pb.iterrows():
        if idx_b in indices_banco_consumidos:
            continue
        data_b = linha_b["data"]
        valor_b = float(linha_b["valor"])
        if pd.isna(data_b) or pd.isna(valor_b):
            continue
        # Filtra candidatos Sankhya
        mask = (ps["data"] == data_b) & (~ps.index.isin(indices_sankhya_consumidos))
        if tem_conta:
            mask = mask & (ps["conta"] == linha_b.get("conta"))
        # Mesmo sinal
        if valor_b > 0:
            mask = mask & (ps["valor"] > 0)
        elif valor_b < 0:
            mask = mask & (ps["valor"] < 0)
        else:
            continue

        candidatos = ps[mask].copy()
        if candidatos.empty:
            continue

        valores = candidatos["valor"].astype(float).tolist()
        idx_originais = candidatos.index.tolist()

        # Tenta subset que some valor_b. Pula se já existia match 1-pra-1 (não
        # deveria ter chegado aqui se exact_match já casou — mas por segurança).
        if any(abs(v - valor_b) <= TOL_VALOR for v in valores) and len(valores) == 1:
            # 1-pra-1: o exact_match deveria ter pegado. Mas se chegou aqui é porque
            # tinha algum bloqueio (talvez já estava consumido). Pula.
            continue

        subset = _buscar_subset_soma(valores, valor_b)
        if subset is None:
            continue

        # Sucesso! Marca consumo
        id_grupo += 1
        indices_banco_consumidos.add(idx_b)
        indices_sankhya_dessa_combinacao = [idx_originais[i] for i in subset]
        indices_sankhya_consumidos.update(indices_sankhya_dessa_combinacao)

        # Coleta histórico do Sankhya (limita string)
        hist_sankhya = candidatos.loc[indices_sankhya_dessa_combinacao, "historico"].astype(str).tolist()
        hist_resumido = " | ".join(hist_sankhya)[:200]

        grupos_rows.append({
            "id_grupo": id_grupo,
            "data": data_b,
            "conta": linha_b.get("conta", "—") if tem_conta else "—",
            "valor_banco": valor_b,
            "qtd_linhas_sankhya": len(indices_sankhya_dessa_combinacao),
            "valor_sankhya_total": round(sum(valores[i] for i in subset), 2),
            "diferenca": round(valor_b - sum(valores[i] for i in subset), 2),
            "historico_banco": str(linha_b.get("historico", ""))[:100],
            "historico_sankhya_combinado": hist_resumido,
            "status": "Conciliado por agrupamento de notas (1→N)",
        })

        # Detalhe banco
        b_dict = linha_b.to_dict()
        b_dict["id_grupo"] = id_grupo
        linhas_banco_rows.append(b_dict)
        # Detalhe sankhya (cada linha)
        for idx_s in indices_sankhya_dessa_combinacao:
            s_dict = ps.loc[idx_s].to_dict()
            s_dict["id_grupo"] = id_grupo
            linhas_sankhya_rows.append(s_dict)

    resultado.grupos_conciliados = pd.DataFrame(grupos_rows)
    resultado.linhas_banco_casadas = pd.DataFrame(linhas_banco_rows)
    resultado.linhas_sankhya_casadas = pd.DataFrame(linhas_sankhya_rows)
    resultado.indices_banco_casados = indices_banco_consumidos
    resultado.indices_sankhya_casados = indices_sankhya_consumidos
    return resultado
