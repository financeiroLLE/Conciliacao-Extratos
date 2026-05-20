"""Conciliação por agrupamento — TOP 1722 (cartão de crédito).

Regra:
- Banco recebe valores compactados (1 crédito = soma de várias vendas)
- Sankhya com TOP DE BAIXA = "1722" mostra as vendas individuais por cliente
- O sistema agrupa as linhas Sankhya TOP 1722 (mesma data, ±N dias)
  e tenta casar com 1 crédito do banco

Critérios:
- Valor: soma EXATA (sem tolerância de centavo)
- Data: tolerância configurável (padrão ±2 dias)
- Só roda em linhas que ainda não casaram no match exato 1-pra-1
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import pandas as pd


TOP_CARTAO_CREDITO = "1722"
JANELA_DIAS_DEFAULT = 2
MAX_COMBINACOES = 12  # acima disso, subset-sum explode


@dataclass
class ResultadoTop1722:
    """Resultado da conciliação por agrupamento TOP 1722."""
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Linhas do banco (1 por crédito) casadas por agrupamento.
    Colunas: data_banco, conta, historico_banco, valor_banco, qtd_sankhya,
             ids_sankhya, valor_sankhya_total, taxa_implicita, status"""

    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Linhas individuais do Sankhya que foram para algum agrupamento.
    Inclui id_grupo pra cruzar com grupos_conciliados."""

    com_diferenca: pd.DataFrame = field(default_factory=pd.DataFrame)
    """Créditos banco com candidatos TOP 1722 mas a soma não fechou.
    Marcado como 'TOP 1722 com Diferença' — usuário decide."""

    indices_banco_casados: set[int] = field(default_factory=set)
    """Índices do banco que foram consumidos por agrupamento."""

    indices_sankhya_casados: set[int] = field(default_factory=set)
    """Índices do sankhya (TOP 1722) consumidos por agrupamento."""

    @property
    def qtd_grupos(self) -> int:
        return len(self.grupos_conciliados)

    @property
    def valor_total_conciliado(self) -> float:
        if self.grupos_conciliados.empty:
            return 0.0
        return float(self.grupos_conciliados["valor_banco"].sum())


def detectar_top_1722(
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    janela_dias: int = JANELA_DIAS_DEFAULT,
) -> ResultadoTop1722:
    """Detecta créditos bancários que correspondem à soma de N linhas
    TOP 1722 do Sankhya, dentro da janela de data.

    Args:
        pendentes_banco: linhas do banco que NÃO casaram no match 1-pra-1
        pendentes_sistema: linhas do Sankhya que não casaram (precisa ter coluna 'top_baixa')
        janela_dias: tolerância em dias entre data banco e data Sankhya

    Returns:
        ResultadoTop1722.
    """
    if pendentes_banco.empty or pendentes_sistema.empty:
        return ResultadoTop1722()
    if "top_baixa" not in pendentes_sistema.columns:
        return ResultadoTop1722()

    # Filtra créditos banco (valor > 0)
    banco = pendentes_banco.copy().reset_index(drop=True)
    banco["_idx_banco"] = banco.index
    banco["data"] = pd.to_datetime(banco["data"], errors="coerce")
    banco["valor"] = pd.to_numeric(banco["valor"], errors="coerce")
    creditos = banco[(banco["valor"] > 0) & banco["data"].notna()].copy()
    if creditos.empty:
        return ResultadoTop1722()

    # Filtra Sankhya TOP 1722
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
    linhas_casadas = []
    com_diff = []
    indices_banco_casados = set()
    indices_sis_casados = set()
    proximo_id_grupo = 1

    # Ordena créditos banco por data ascendente
    creditos = creditos.sort_values("data").reset_index(drop=True)

    for _, credito in creditos.iterrows():
        idx_b = int(credito["_idx_banco"])
        valor_alvo = round(float(credito["valor"]), 2)
        data_b = credito["data"]
        conta_b = credito.get("conta", "")

        # Candidatos: mesma conta + dentro da janela + ainda não consumidos
        cand = top1722[
            (top1722["conta"] == conta_b)
            & (~top1722["_idx_sis"].isin(indices_sis_casados))
        ].copy()
        cand["_dias"] = (cand["data"] - data_b).dt.days.abs()
        cand = cand[cand["_dias"] <= janela_dias].copy()
        if cand.empty:
            continue

        # Tenta achar subset que soma = valor_alvo
        valores = cand["valor"].round(2).tolist()
        idxs = cand["_idx_sis"].tolist()
        subset = _encontrar_subset_soma(valores, valor_alvo)

        if subset is not None:
            # Conciliou!
            idxs_grupo = [idxs[i] for i in subset]
            valores_grupo = [valores[i] for i in subset]
            soma = round(sum(valores_grupo), 2)

            id_grupo = f"G{proximo_id_grupo:04d}"
            proximo_id_grupo += 1

            grupos.append({
                "id_grupo": id_grupo,
                "data_banco": data_b,
                "conta": conta_b,
                "historico_banco": credito.get("historico", ""),
                "valor_banco": valor_alvo,
                "qtd_sankhya": len(idxs_grupo),
                "valor_sankhya_total": soma,
                "taxa_implicita_rs": 0.0,  # = bruto pq bateu exato
                "status": "Conciliado por Agrupamento — Cartão TOP 1722",
            })
            # Linhas Sankhya casadas
            for ix_sis in idxs_grupo:
                linha_sis = sis[sis["_idx_sis"] == ix_sis].iloc[0]
                linhas_casadas.append({
                    "id_grupo": id_grupo,
                    "data_banco": data_b,
                    "valor_banco": valor_alvo,
                    "data_sankhya": linha_sis["data"],
                    "cliente_historico": linha_sis.get("historico", ""),
                    "documento": linha_sis.get("documento", ""),
                    "valor_sankhya": float(linha_sis["valor"]),
                    "conta": conta_b,
                    "top_baixa": TOP_CARTAO_CREDITO,
                })
            indices_banco_casados.add(idx_b)
            indices_sis_casados.update(int(i) for i in idxs_grupo)
        else:
            # Não fechou — registra como "TOP 1722 com Diferença"
            # (mas só se houver pelo menos 1 candidato na janela)
            soma_cands = round(sum(valores), 2)
            if soma_cands > 0:
                com_diff.append({
                    "data_banco": data_b,
                    "conta": conta_b,
                    "historico_banco": credito.get("historico", ""),
                    "valor_banco": valor_alvo,
                    "qtd_candidatos_top1722": len(valores),
                    "soma_candidatos": soma_cands,
                    "diferenca": round(valor_alvo - soma_cands, 2),
                    "status": "Cartão TOP 1722 com Diferença",
                    "motivo": (
                        f"Banco R$ {valor_alvo:.2f} × Sankhya R$ {soma_cands:.2f} "
                        f"({len(valores)} candidatos TOP 1722 na janela ±{janela_dias}d)"
                    ),
                })

    return ResultadoTop1722(
        grupos_conciliados=pd.DataFrame(grupos),
        linhas_sankhya_casadas=pd.DataFrame(linhas_casadas),
        com_diferenca=pd.DataFrame(com_diff),
        indices_banco_casados=indices_banco_casados,
        indices_sankhya_casados=indices_sis_casados,
    )


def _encontrar_subset_soma(valores: list[float], alvo: float) -> list[int] | None:
    """Encontra um subset cujos valores somam EXATAMENTE alvo.

    Retorna lista de índices ou None se não houver subset.
    Para até MAX_COMBINACOES elementos, testa por combinações exatas.
    Acima, usa heurística greedy (não garante optimal).
    """
    n = len(valores)
    if n == 0:
        return None
    EPS = 0.005

    # Caso especial: 1 lançamento bate exato (já deveria ter casado no match 1-pra-1,
    # mas pode acontecer se a data divergiu por mais que a tolerância padrão)
    for i, v in enumerate(valores):
        if abs(v - alvo) < EPS:
            return [i]

    # Soma total tem que >= alvo (impossível agrupar pra cima)
    if sum(valores) < alvo - EPS:
        return None

    if n <= MAX_COMBINACOES:
        # Tenta combinações de 2 até n elementos
        for k in range(2, n + 1):
            for combo in combinations(range(n), k):
                soma = sum(valores[i] for i in combo)
                if abs(soma - alvo) < EPS:
                    return list(combo)
        return None

    # Heurística pra muitos elementos: greedy ordenado decrescente
    # (não garante optimal mas resolve maioria dos casos)
    ordenados = sorted(range(n), key=lambda i: -valores[i])
    selecionados = []
    soma_atual = 0.0
    for i in ordenados:
        if soma_atual + valores[i] <= alvo + EPS:
            selecionados.append(i)
            soma_atual += valores[i]
            if abs(soma_atual - alvo) < EPS:
                return selecionados
    return None
