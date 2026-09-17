"""Salários pagos avulsos N→M — v5.28.

CONTEXTO:
- A regra de folha N→1 (folha_pagamento.py) tenta casar N SISPAG SALARIOS do banco
  com 1 lançamento FOLHA DE PAGAMENTO consolidado no Sankhya.
- MAS às vezes o Sankhya não consolida — lança cada salário individualmente.
- Exemplo (dia 28/05):
  - Banco: 6 SISPAG SALARIOS somando -R$ 16.892,49
  - Sankhya: BRENDA -R$ 7.724,22 + ADRIANO -R$ 9.168,27 = -R$ 16.892,49

PROBLEMA:
- A regra de folha não casa (não tem FOLHA CONSOLIDADA no Sankhya).
- A regra de match exato 1-pra-1 não casa (valores diferentes em cada lado).
- A regra de depósitos abertos não casa (essa é 1-para-N, não N-para-M).

REGRA APLICADA:
- Pra cada data que tem SISPAG SALARIOS no banco sem par:
  - Soma todos os SISPAG SALARIOS daquela data.
  - Procura no Sankhya, na mesma data, combinações de despesas (até 5 linhas) cuja
    soma seja igual ao total do banco.
  - Se achar, marca o casamento N→M e tira de ambas as pendências.

OBSERVAÇÕES:
- Limite de 5 combinações pra evitar explosão combinatória.
- Tolerância de 1 centavo.
- Mesma data exata.
- Não exige histórico igual (no Sankhya os nomes são pessoas, no banco é só SISPAG).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import pandas as pd


TOL_VALOR = 0.01
MAX_COMBINACAO = 5  # máximo de linhas Sankhya por combinação

# v6.29: marcadores que caracterizam pessoa jurídica no histórico do Sankhya.
# Salário é SEMPRE pessoa física — se o histórico traz um destes termos, a
# linha é despesa a fornecedor/prestador e NÃO pode ser candidata de folha.
# Sem esta trava, a busca combinatória (até 5 despesas somando o total dos
# SISPAG SALARIOS do dia) casava fornecedores por coincidência de soma —
# caso real ITAU PISA 11/09/2026: SEU AMIGO + SD FAMILIA + JLC GOMES
# (R$ 12.159,24 + R$ 13.119,45 + R$ 520,00 = R$ 25.798,69) somava o total
# de folha do dia e sumia das pendências, deixando três pagamentos SISPAG
# DIVERSOS do banco órfãos.
TERMOS_PJ_HISTORICO = [
    " ltda", " ltda.", "ltda ", "ltda.",
    " s.a", " s/a", " s a ", " sa ", " sa.",
    " me ", " me.", " epp ", " epp.",
    " eireli", " eirl",
    "representacoes", "representações",
    "representacao", "representação",
    "repres comer", "repres com ", "repres. com",
    "comercial ", "comercio ", "comércio ",
    "industria", "indústria", "industrial",
    "distribuidora", "distribuicao", "distribuição", "distrib ",
    "transportes", "transportadora", "logistica", "logística",
    "servicos", "serviços",
    "engenharia", "arquitetura", "construcao", "construção", "construtora",
    "propaganda", "marketing", "publicidade",
    "consultoria", "assessoria", "contabilidade",
    "informatica", "informática", "tecnologia", "sistemas",
    "hoteis", "hotéis", "restaurante",
    "farmacia", "farmácia", "drogaria",
    "supermercado", "atacadista", "atacado",
    "materiais", "confeccoes", "confecções",
    "franchising", "franquia",
    "grupo ",
    "cia ", "cia. ", "companhia ",
    # instituições financeiras / bancos
    "caixa economica", "caixa econômica",
    " banco ", "banco do brasil", "banco bradesco", "banco itau", "banco santander",
    "instituicao financeira", "instituição financeira",
    "financeira ", "cooperativa ",
    # entes públicos e sindicatos
    "prefeitura", "municipio", "município",
    "receita federal", "secretaria da fazenda", "estado do ",
    "sindicato ",
    "fundacao", "fundação", "associacao", "associação",
]


def _eh_pessoa_juridica(historico: str) -> bool:
    """True se o histórico do Sankhya identifica claramente uma pessoa jurídica.

    Usado para EXCLUIR fornecedores/prestadores do pool de candidatos a folha
    de pagamento (que é sempre pessoa física).
    """
    if not isinstance(historico, str) or not historico.strip():
        return False
    h = historico.lower()
    troca = str.maketrans("áàâãéèêíìóòôõúùç", "aaaaeeeiioooouuc")
    h = h.translate(troca)
    # Espaços nas laterais para pegar sufixos isolados sem falso positivo em
    # nomes ("Melo", "Alameda" etc.)
    h_pad = " " + h + " "
    return any(termo in h_pad for termo in TERMOS_PJ_HISTORICO)


@dataclass
class ResultadoSalariosNM:
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)

    indices_banco_casados: set[int] = field(default_factory=set)
    indices_sankhya_casados: set[int] = field(default_factory=set)

    @property
    def qtd_grupos(self) -> int:
        return len(self.grupos_conciliados)


def _eh_sispag_salarios(historico: str) -> bool:
    """True se o histórico do banco indica SISPAG SALARIOS."""
    if not isinstance(historico, str):
        return False
    return "sispag salarios" in historico.lower() or "sispag salario" in historico.lower()


def _buscar_combinacao_que_soma(
    valores: list[float], alvo: float, max_size: int = MAX_COMBINACAO
) -> list[int] | None:
    """Acha combinação de valores que somam o alvo (tolerância 1 centavo)."""
    n = len(valores)
    if n == 0:
        return None
    # Tenta 1 elemento primeiro (caso 1-pra-1)
    for i, v in enumerate(valores):
        if abs(v - alvo) <= TOL_VALOR:
            return [i]
    # Depois tamanhos crescentes
    limite = min(n, max_size)
    for tam in range(2, limite + 1):
        for combo in combinations(range(n), tam):
            soma = sum(valores[i] for i in combo)
            if abs(soma - alvo) <= TOL_VALOR:
                return list(combo)
    return None


def detectar_salarios_n_m(
    pend_banco: pd.DataFrame,
    pend_sistema: pd.DataFrame,
) -> ResultadoSalariosNM:
    """Concilia SISPAG SALARIOS do banco com combinações de lançamentos no Sankhya.

    Args:
        pend_banco: pendências do banco após folha N→1 e outras regras.
        pend_sistema: pendências do Sankhya idem.

    Returns:
        ResultadoSalariosNM com os grupos conciliados.
    """
    resultado = ResultadoSalariosNM()

    if pend_banco.empty or pend_sistema.empty:
        return resultado

    pb = pend_banco.reset_index(drop=True).copy()
    ps = pend_sistema.reset_index(drop=True).copy()

    if "historico" not in pb.columns or "data" not in pb.columns or "valor" not in pb.columns:
        return resultado

    # 1. Identifica SISPAG SALARIOS no banco
    mask_salarios = pb["historico"].apply(_eh_sispag_salarios)
    salarios_banco = pb[mask_salarios & (pb["valor"] < 0)].copy()
    if salarios_banco.empty:
        return resultado

    # 2. Pra cada data com SISPAG SALARIOS no banco, soma e busca no Sankhya
    tem_conta = "conta" in pb.columns and "conta" in ps.columns
    chave_grupo = ["data", "conta"] if tem_conta else ["data"]

    grupos_banco = (
        salarios_banco.groupby(chave_grupo, dropna=False)
        .agg(
            qtd=("valor", "count"),
            total=("valor", "sum"),
            indices=("valor", lambda s: list(s.index)),
        )
        .reset_index()
    )

    indices_banco_consumidos: set[int] = set()
    indices_sankhya_consumidos: set[int] = set()
    grupos_rows = []
    linhas_banco_rows = []
    linhas_sankhya_rows = []
    id_grupo = 0

    for _, grupo_b in grupos_banco.iterrows():
        data_g = grupo_b["data"]
        valor_alvo = float(grupo_b["total"])  # negativo
        conta_g = grupo_b["conta"] if tem_conta else None

        # Filtra Sankhya: mesma data, sinal negativo (despesa), não consumido
        mask = (ps["data"] == data_g) & (ps["valor"] < 0)
        if tem_conta and "conta" in ps.columns:
            mask = mask & (ps["conta"] == conta_g)
        mask = mask & (~ps.index.isin(indices_sankhya_consumidos))
        # v6.29: exclui despesas cujo histórico identifica pessoa jurídica
        # (fornecedor/prestador). Folha é sempre pessoa física — sem esta
        # trava a busca combinatória casava fornecedores por coincidência
        # de soma. Ver docstring de _eh_pessoa_juridica.
        if "historico" in ps.columns:
            mask = mask & (~ps["historico"].fillna("").apply(_eh_pessoa_juridica))

        candidatos = ps[mask].copy()
        if candidatos.empty:
            continue

        valores = candidatos["valor"].astype(float).tolist()
        idx_originais = candidatos.index.tolist()

        # Não vale pra 1 elemento (já seria 1-pra-1 caso fosse pra casar)
        if len(valores) == 1 and abs(valores[0] - valor_alvo) <= TOL_VALOR:
            # Pula — se 1 SISPAG no banco bate com 1 no sankhya, já deveria ter casado
            # antes ou aparecer como folha. Não force.
            continue

        # v6.30: se cada SISPAG SALARIOS PRÓPRIO do banco (excluindo as
        # linhas de tarifa "TAR SISPAG SALARIO") já tem par 1-a-1 exato
        # disponível no Sankhya, deixa o match_exato pegar. Sem esta trava,
        # a busca combinatória consumia despesas do Sankhya com valores
        # diferentes (que somavam o total do banco) por coincidência, mesmo
        # com os pares 1-a-1 corretos ao alcance. Caso real ITAU PISA
        # 11/09/2026: os 4 SISPAG SALARIOS individuais (9.744,59 · 1.054,18
        # · 7.303,72 · 7.695,00) tinham par exato no Sankhya
        # (ERIKA · JOAO · GISELLE · LUCAS), mas a regra pescava
        # KLOBER + VENTURA + FABIO + GABRIEL + CARLOS por soma casada
        # (25.798,69), deixando a folha real fora e cinco SISPAG DIVERSOS
        # do banco órfãos. A checagem ignora as TAR SISPAG SALARIO — que
        # muitas vezes aparecem consolidadas no Sankhya numa única linha
        # e não têm 1-a-1 individual — porque a evidência de folha real
        # está nos SISPAG SALARIOS principais.
        def _eh_tar(h):
            return isinstance(h, str) and "tar" in h.lower() and "salario" in h.lower().replace("á","a")
        _idx_indiv_principais = [
            i for i in grupo_b["indices"]
            if not _eh_tar(salarios_banco.at[i, "historico"])
        ]
        if _idx_indiv_principais:
            _valores_indiv = salarios_banco.loc[_idx_indiv_principais, "valor"].astype(float).tolist()
            _todos_tem_1a1 = True
            _pool = list(valores)
            for _v_ind in _valores_indiv:
                _achou = False
                for _pi, _pv in enumerate(_pool):
                    if abs(_pv - _v_ind) <= TOL_VALOR:
                        _pool.pop(_pi)
                        _achou = True
                        break
                if not _achou:
                    _todos_tem_1a1 = False
                    break
            if _todos_tem_1a1:
                # match_exato resolve sozinho — não força N→M
                continue

        subset = _buscar_combinacao_que_soma(valores, valor_alvo)
        if subset is None:
            continue
        if len(subset) < 1:
            continue

        # Sucesso
        id_grupo += 1
        idx_b_final = list(grupo_b["indices"])
        idx_s_final = [idx_originais[i] for i in subset]

        indices_banco_consumidos.update(idx_b_final)
        indices_sankhya_consumidos.update(idx_s_final)

        soma_s = sum(valores[i] for i in subset)
        hist_s = " | ".join(
            str(candidatos.loc[idx, "historico"])[:50] for idx in idx_s_final
        )[:200]

        grupos_rows.append({
            "id_grupo": id_grupo,
            "data": data_g,
            "conta": conta_g if tem_conta else "—",
            "qtd_sispag_banco": int(grupo_b["qtd"]),
            "qtd_linhas_sankhya": len(idx_s_final),
            "valor_banco_total": valor_alvo,
            "valor_sankhya_total": round(soma_s, 2),
            "diferenca": round(valor_alvo - soma_s, 2),
            "historico_sankhya": hist_s,
            "status": "Conciliado por salários avulsos (N→M)",
        })

        for idx_b in idx_b_final:
            d = salarios_banco.loc[idx_b].to_dict()
            d["id_grupo"] = id_grupo
            linhas_banco_rows.append(d)
        for idx_s in idx_s_final:
            d = candidatos.loc[idx_s].to_dict()
            d["id_grupo"] = id_grupo
            linhas_sankhya_rows.append(d)

    resultado.grupos_conciliados = pd.DataFrame(grupos_rows)
    resultado.linhas_banco_casadas = pd.DataFrame(linhas_banco_rows)
    resultado.linhas_sankhya_casadas = pd.DataFrame(linhas_sankhya_rows)
    resultado.indices_banco_casados = indices_banco_consumidos
    resultado.indices_sankhya_casados = indices_sankhya_consumidos
    return resultado
