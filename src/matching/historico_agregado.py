"""Match agregado por histórico igual — v6.31.

CONTEXTO:
- O banco costuma quebrar um lançamento em várias linhas com o MESMO histórico
  (ex.: 3× TAR SISPAG SALARIO de -0,30 · -0,30 · -0,60), enquanto o Sankhya
  lança o consolidado numa única linha com o mesmo histórico (1× TAR SISPAG
  SALARIO de -1,20). Os valores individuais não batem 1-a-1, mas a SOMA
  bate e o HISTÓRICO é literalmente o mesmo dos dois lados.

REGRA:
- Para cada (data, conta, histórico_normalizado) com pelo menos 1 linha
  do banco E pelo menos 1 do Sankhya:
  - Se a soma dos valores dos dois lados bate (tolerância 1 centavo) e há
    pluralidade em pelo menos um dos lados (senão o match_exato já resolveu),
    casa N-para-M em bloco.
- Normalização do histórico: lowercase, sem acento, só palavras (ignora
  números, códigos, IDs, símbolos) e espaços colapsados. Assim
  "TAR SISPAG SALARIO" bate com "TAR SISPAG SALARIO" mesmo se um lado
  tem um número de documento no meio.
- SÓ casa quando o histórico normalizado é LITERALMENTE o mesmo dos dois
  lados. Não faz "fuzzy" nem inferência de sinônimos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import pandas as pd


TOL_VALOR = 0.01

# Regex que extrai só palavras alfabéticas (sem números/símbolos)
_TOKEN_RE = re.compile(r"[a-z]+")


@dataclass
class ResultadoHistoricoAgregado:
    grupos_conciliados: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_banco_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    linhas_sankhya_casadas: pd.DataFrame = field(default_factory=pd.DataFrame)

    indices_banco_casados: set[int] = field(default_factory=set)
    indices_sankhya_casados: set[int] = field(default_factory=set)

    @property
    def qtd_grupos(self) -> int:
        return len(self.grupos_conciliados)


def _normalizar_historico(h) -> str:
    """Normaliza histórico para chave de agrupamento: lowercase + sem acento
    + só palavras alfabéticas + espaço único. Descarta números e símbolos.
    """
    if not isinstance(h, str) or not h.strip():
        return ""
    s = h.lower()
    troca = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüç", "aaaaaeeeeiiiiooooouuuuc")
    s = s.translate(troca)
    tokens = _TOKEN_RE.findall(s)
    # exige pelo menos 2 caracteres em cada token pra evitar ruído de sílabas
    tokens = [t for t in tokens if len(t) >= 2]
    return " ".join(tokens)


def detectar_agrupamento_por_historico(
    pend_banco: pd.DataFrame,
    pend_sistema: pd.DataFrame,
) -> ResultadoHistoricoAgregado:
    """Casa N banco → M Sankhya quando o histórico normalizado é o mesmo
    dos dois lados e as somas batem.

    Args:
        pend_banco: pendências do banco após o match_exato (e regras anteriores).
        pend_sistema: pendências do Sankhya idem.
    """
    resultado = ResultadoHistoricoAgregado()

    if pend_banco.empty or pend_sistema.empty:
        return resultado
    for c in ("data", "valor", "historico"):
        if c not in pend_banco.columns or c not in pend_sistema.columns:
            return resultado

    pb = pend_banco.reset_index(drop=True).copy()
    ps = pend_sistema.reset_index(drop=True).copy()
    pb["data"] = pd.to_datetime(pb["data"], errors="coerce")
    ps["data"] = pd.to_datetime(ps["data"], errors="coerce")
    pb["valor"] = pd.to_numeric(pb["valor"], errors="coerce")
    ps["valor"] = pd.to_numeric(ps["valor"], errors="coerce")
    pb = pb[pb["data"].notna() & pb["valor"].notna()].copy()
    ps = ps[ps["data"].notna() & ps["valor"].notna()].copy()
    if pb.empty or ps.empty:
        return resultado

    pb["_hist_norm"] = pb["historico"].apply(_normalizar_historico)
    ps["_hist_norm"] = ps["historico"].apply(_normalizar_historico)
    # descarta linhas sem histórico normalizado utilizável (poucas letras)
    pb = pb[pb["_hist_norm"].str.len() > 0].copy()
    ps = ps[ps["_hist_norm"].str.len() > 0].copy()
    if pb.empty or ps.empty:
        return resultado

    tem_conta = "conta" in pb.columns and "conta" in ps.columns
    chave = ["data", "_hist_norm"] + (["conta"] if tem_conta else [])

    indices_b_consumidos: set[int] = set()
    indices_s_consumidos: set[int] = set()
    grupos_rows = []
    linhas_b_rows = []
    linhas_s_rows = []
    id_grupo = 0

    grupos_b = pb.groupby(chave, dropna=False)
    # pré-agrupa o Sankhya para consulta O(1)
    grupos_s_dict = {
        k: g for k, g in ps.groupby(chave, dropna=False)
    }

    for k, g_b in grupos_b:
        g_s = grupos_s_dict.get(k)
        if g_s is None or g_s.empty:
            continue
        # pluralidade em pelo menos um lado (senão é 1-a-1 e o match_exato
        # já resolveu — ou vai resolver na 2ª passagem)
        if len(g_b) < 2 and len(g_s) < 2:
            continue
        soma_b = round(float(g_b["valor"].sum()), 2)
        soma_s = round(float(g_s["valor"].sum()), 2)
        if abs(soma_b - soma_s) > TOL_VALOR:
            continue
        # exige mesmo sinal do total (compensação sem paridade de sinal
        # não é agrupamento — é outra coisa)
        if (soma_b > 0) != (soma_s > 0) and abs(soma_b) > TOL_VALOR:
            continue

        id_grupo += 1
        idx_b_orig = g_b.index.tolist()
        idx_s_orig = g_s.index.tolist()
        indices_b_consumidos.update(idx_b_orig)
        indices_s_consumidos.update(idx_s_orig)

        data_g = k[0]
        hist_g = k[1]
        conta_g = k[2] if tem_conta else "—"

        grupos_rows.append({
            "id_grupo": id_grupo,
            "data": data_g,
            "conta": conta_g,
            "historico_normalizado": hist_g,
            "qtd_linhas_banco": len(g_b),
            "qtd_linhas_sankhya": len(g_s),
            "valor_banco_total": soma_b,
            "valor_sankhya_total": soma_s,
            "diferenca": round(soma_b - soma_s, 2),
            "historico_banco_amostra": str(g_b.iloc[0].get("historico", ""))[:80],
            "historico_sankhya_amostra": str(g_s.iloc[0].get("historico", ""))[:80],
            "status": "Conciliado por histórico igual (N pra M)",
        })
        for idx_b in idx_b_orig:
            d = pb.loc[idx_b].to_dict()
            d["id_grupo"] = id_grupo
            linhas_b_rows.append(d)
        for idx_s in idx_s_orig:
            d = ps.loc[idx_s].to_dict()
            d["id_grupo"] = id_grupo
            linhas_s_rows.append(d)

    resultado.grupos_conciliados = pd.DataFrame(grupos_rows)
    resultado.linhas_banco_casadas = pd.DataFrame(linhas_b_rows)
    resultado.linhas_sankhya_casadas = pd.DataFrame(linhas_s_rows)
    resultado.indices_banco_casados = indices_b_consumidos
    resultado.indices_sankhya_casados = indices_s_consumidos
    return resultado
