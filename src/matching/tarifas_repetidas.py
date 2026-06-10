"""Match de tarifas/pagamentos repetidos N pra N — v5.27.

PROBLEMA RESOLVIDO:
- Banco tem N linhas iguais (mesma data + histórico + valor):
  ex: 4× TAR C/C SISPAG -R$ 0,32 no dia 28/05
- Sankhya tem M linhas iguais (mesma data + valor) — histórico pode variar:
  ex: 4× TAR C/C SISPAG -R$ 0,32 no dia 28/05
- O app antigo marcava como "Possíveis Duplicidades" só porque tinha repetição.
- NÃO É DUPLICIDADE: são tarifas/pagamentos legítimos repetidos.

REGRA APLICADA (rodada ANTES de detectar duplicidades):
- Acha grupos de linhas idênticas (data + valor) no banco.
- Pra cada grupo, verifica se o Sankhya tem **a mesma quantidade** na mesma data + valor.
- Se as quantidades batem: concilia N pra N e remove de ambas as pendências.
- Se não batem (banco tem 4, sankhya tem 2): apenas a quantidade que sobra pode ser
  "possível duplicidade".

OBSERVAÇÃO sobre histórico:
- O histórico do banco e do Sankhya pode ser diferente — não exigimos casamento de
  histórico. O critério é data + valor + sinal.
- Isso atende casos como "TAR C/C SISPAG" no banco vs "Tarifa bancária" no Sankhya.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd


TOL_VALOR = 0.01


@dataclass
class ResultadoTarifasRepetidas:
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)

    indices_banco_casados: set[int] = field(default_factory=set)
    indices_sankhya_casados: set[int] = field(default_factory=set)

    @property
    def qtd_grupos(self) -> int:
        return len(self.grupos_conciliados)

    @property
    def valor_total(self) -> float:
        if self.grupos_conciliados.empty or "valor" not in self.grupos_conciliados.columns:
            return 0.0
        return float(self.grupos_conciliados["valor"].abs().sum())


def detectar_tarifas_repetidas(
    pend_banco: pd.DataFrame,
    pend_sistema: pd.DataFrame,
) -> ResultadoTarifasRepetidas:
    """Concilia linhas repetidas N pra N entre banco e Sankhya.

    Args:
        pend_banco: pendências do banco após match 1-pra-1 e outros agrupamentos.
        pend_sistema: pendências do Sankhya após match 1-pra-1 e outros agrupamentos.

    Returns:
        ResultadoTarifasRepetidas com os grupos conciliados.
    """
    resultado = ResultadoTarifasRepetidas()

    if pend_banco.empty or pend_sistema.empty:
        return resultado

    if "data" not in pend_banco.columns or "valor" not in pend_banco.columns:
        return resultado
    if "data" not in pend_sistema.columns or "valor" not in pend_sistema.columns:
        return resultado

    pb = pend_banco.reset_index(drop=True).copy()
    ps = pend_sistema.reset_index(drop=True).copy()

    # Conta é opcional — se existir, usa
    tem_conta = "conta" in pb.columns and "conta" in ps.columns

    # Arredonda valor pra evitar diferenças de ponto flutuante
    pb["_valor_round"] = pb["valor"].round(2)
    ps["_valor_round"] = ps["valor"].round(2)

    # Constrói chave (data, valor, conta)
    if tem_conta:
        chave_b = pb.groupby(["data", "_valor_round", "conta"])
    else:
        chave_b = pb.groupby(["data", "_valor_round"])

    indices_banco_consumidos: set[int] = set()
    indices_sankhya_consumidos: set[int] = set()
    grupos_rows = []
    linhas_banco_rows = []
    linhas_sankhya_rows = []
    id_grupo = 0

    for chave, grupo_b in chave_b:
        if len(grupo_b) < 2:
            continue  # só interessa quando tem repetição (>= 2 linhas idênticas)

        if tem_conta:
            data_g, valor_g, conta_g = chave
            mask_s = (
                (ps["data"] == data_g)
                & (ps["_valor_round"] == valor_g)
                & (ps["conta"] == conta_g)
            )
        else:
            data_g, valor_g = chave
            mask_s = (ps["data"] == data_g) & (ps["_valor_round"] == valor_g)

        # Remove já consumidos
        mask_s = mask_s & (~ps.index.isin(indices_sankhya_consumidos))
        grupo_s = ps[mask_s]

        if grupo_s.empty:
            continue

        qtd_b = len(grupo_b)
        qtd_s = len(grupo_s)
        qtd_casar = min(qtd_b, qtd_s)  # casa o que dá

        if qtd_casar < 2:
            continue  # se sobrou só 1 pra casar, não vale (deixa o exact_match cuidar)

        # Pega as primeiras qtd_casar de cada lado
        idx_b_casar = grupo_b.index[:qtd_casar].tolist()
        idx_s_casar = grupo_s.index[:qtd_casar].tolist()

        # Filtra já consumidos do lado banco
        idx_b_disponivel = [i for i in idx_b_casar if i not in indices_banco_consumidos]
        idx_s_disponivel = [i for i in idx_s_casar if i not in indices_sankhya_consumidos]

        qtd_real = min(len(idx_b_disponivel), len(idx_s_disponivel))
        if qtd_real < 2:
            continue

        idx_b_final = idx_b_disponivel[:qtd_real]
        idx_s_final = idx_s_disponivel[:qtd_real]

        id_grupo += 1
        indices_banco_consumidos.update(idx_b_final)
        indices_sankhya_consumidos.update(idx_s_final)

        # Adiciona ao resumo
        grupos_rows.append({
            "id_grupo": id_grupo,
            "data": data_g,
            "conta": conta_g if tem_conta else "—",
            "valor": float(valor_g),
            "qtd_banco_casado": qtd_real,
            "qtd_sankhya_casado": qtd_real,
            "qtd_banco_total": qtd_b,
            "qtd_sankhya_total": qtd_s,
            "historico_banco": str(grupo_b.iloc[0].get("historico", ""))[:80],
            "historico_sankhya": str(grupo_s.iloc[0].get("historico", ""))[:80],
            "status": "Conciliado por linhas repetidas (N pra N)",
        })

        # Detalhe banco
        for idx_b in idx_b_final:
            b_dict = pb.loc[idx_b].to_dict()
            b_dict["id_grupo"] = id_grupo
            linhas_banco_rows.append(b_dict)
        # Detalhe sankhya
        for idx_s in idx_s_final:
            s_dict = ps.loc[idx_s].to_dict()
            s_dict["id_grupo"] = id_grupo
            linhas_sankhya_rows.append(s_dict)

    resultado.grupos_conciliados = pd.DataFrame(grupos_rows)
    resultado.linhas_banco_casadas = pd.DataFrame(linhas_banco_rows)
    resultado.linhas_sankhya_casadas = pd.DataFrame(linhas_sankhya_rows)
    resultado.indices_banco_casados = indices_banco_consumidos
    resultado.indices_sankhya_casados = indices_sankhya_consumidos
    return resultado
