# -*- coding: utf-8 -*-
"""
Motor de conciliação de vendas — Fase 4 · MVP-A · v2 (data flexível + passada permissiva).

Cruza vendas das adquirentes (Cielo, Getnet) com títulos do Sankhya
(notas fiscais + adiantamentos) e organiza em 4 grupos + "a analisar".

MUDANÇAS v2 (31/07/2026):
    1. Comparação de data usa a MELHOR data do título disponível:
       - Título em aberto: dt_vencimento (só ela existe)
       - Título baixado (TOP 1722): min(diff(dt_vencimento), diff(data_baixa))
       Motivo: quando o Sankhya baixou o título por cartão, a "data_baixa"
       é quando a adquirente efetivamente pagou — bate exato com a
       data_prev_pagamento da venda, ao passo que dt_vencimento é a
       projeção contábil e pode divergir alguns dias.

    2. Segunda passada permissiva para títulos BAIXADO_CARTAO restantes:
       Se depois da primeira passada uma venda ficou sem par E um título
       baixado por cartão ficou órfão E as características fortes casam
       (valor + adquirente + bandeira + modalidade), CASA MESMO SEM DATA.
       Motivo: o Sankhya já baixou → já tem certeza de recebimento.
       Não faz sentido gerar "a analisar" pra algo que ele já resolveu.

Regras invioláveis (aprendidas com Débora, memória 30-31/07/2026):
    - Zero falso positivo (matches ambíguos vão pra "a analisar")
    - Motor NUNCA escolhe entre múltiplos candidatos
    - "Conciliado" (bancário) ≠ "baixa de título" — não confundir
    - Núm. Documento nunca é chave de identidade — usar data+valor+histórico

Entrada:
    df_sankhya_classificado : DataFrame de classificador_sankhya.classificar()
    df_cielo                : DataFrame do leitor cielo_recebiveis.ler()
    df_getnet_vendas        : DataFrame do leitor getnet_recebiveis.ler().df_vendas
    tolerancia_dias         : int (default 2, usado só na 1ª passada)

Saída: ResultadoMotor dataclass com 7 DataFrames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd


# ==============================================================================
# NORMALIZAÇÃO DE BANDEIRA
# ==============================================================================

_MAPA_BANDEIRA = {
    "mastercard": "master", "master": "master", "mas": "master",
    "visa": "visa", "vis": "visa",
    "elo": "elo",
    "hipercard": "hipercard",
    "amex": "amex", "american express": "amex",
}


def _normalizar_bandeira(b) -> Optional[str]:
    if b is None:
        return None
    s = str(b).strip().lower()
    return _MAPA_BANDEIRA.get(s)


def _is_none_or_nan(v) -> bool:
    if v is None:
        return True
    try:
        return pd.isna(v)
    except (TypeError, ValueError):
        return False


def _bandeiras_compativeis(banda_venda, banda_sk) -> bool:
    """Cenário C · aprovado com Débora em 31/07/2026.

    A bandeira do Sankhya não é confiável — é rótulo de convenção de cadastro
    (ex: "MASTER/ELO" pode receber venda VISA na prática). Modalidade continua
    rigorosa (débito nunca casa com crédito), mas bandeira agora só é pista
    informativa, não filtro.

    Testado no dataset real: relaxar bandeira ganhou +20 auto-conciliações
    sem introduzir NENHUM ambíguo/falso positivo.
    """
    return True


def _modalidades_compativeis(mod_venda, mod_sk) -> bool:
    if _is_none_or_nan(mod_venda) or _is_none_or_nan(mod_sk):
        return True
    return mod_venda == mod_sk


def _adquirentes_compativeis(adq_venda, adq_sk) -> bool:
    if _is_none_or_nan(adq_venda):
        return False  # venda sempre tem adquirente
    if _is_none_or_nan(adq_sk):
        return True   # Sankhya sem inferência não bloqueia
    return adq_venda == adq_sk


def _to_date(v) -> Optional[date]:
    """Converte para `date` puro (sem hora).

    IMPORTANTE: `pd.Timestamp` herda de `datetime.date`, então `isinstance(v, date)`
    retorna True mesmo pra Timestamp — sem conversão explícita, o motor tentaria
    subtrair `date - Timestamp` e falharia com TypeError.
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    # Timestamp ou datetime → chama .date() explicitamente
    if hasattr(v, "date") and callable(getattr(v, "date", None)):
        try:
            d = v.date()
            if isinstance(d, date):
                return d
        except Exception:
            pass
    # Se já é date puro (sem herança de datetime), retorna direto
    if isinstance(v, date):
        return v
    # Fallback: parse via pandas
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def _melhor_diff_dias(data_venda, dt_vencimento, data_baixa) -> Optional[int]:
    """
    Retorna a MENOR diferença de dias entre a data prevista da venda
    e qualquer das duas datas do título (dt_vencimento e data_baixa).

    Se apenas dt_vencimento existe, usa ela.
    Se ambas existem (título baixado), usa a de menor diferença.
    Se nenhuma existe, retorna None.
    """
    dv = _to_date(data_venda)
    if dv is None:
        return None

    diffs = []
    dt_v = _to_date(dt_vencimento)
    if dt_v is not None:
        diffs.append(abs((dv - dt_v).days))

    dt_b = _to_date(data_baixa)
    if dt_b is not None:
        diffs.append(abs((dv - dt_b).days))

    if not diffs:
        return None
    return min(diffs)


# ==============================================================================
# PREPARAÇÃO DAS VENDAS
# ==============================================================================

def _preparar_vendas(df_cielo: pd.DataFrame, df_getnet: pd.DataFrame) -> pd.DataFrame:
    """Junta Cielo e Getnet numa visão canônica pro matcher.

    Propaga tanto `data_venda` (data real da transação, imutável — usada nos
    cards da tela pra exibir "Vendido em X") quanto `data_prev_pagamento`
    (data prevista de recebimento da parcela — usada no motor pra bater com
    dt_vencimento/data_baixa do Sankhya).

    Também propaga `valor_bruto_venda_total` (valor total da venda, útil
    quando a parcela é 1/N — pra mostrar contexto no card).
    """
    linhas = []

    if df_cielo is not None and not df_cielo.empty:
        for idx, r in df_cielo.iterrows():
            valor_parcela = r["valor_bruto"]
            parc_total = r.get("parcelas_total") or 1
            # Cielo tem valor_bruto_venda_total (total da venda) explícito
            valor_total = r.get("valor_bruto_venda_total")
            if valor_total is None or (isinstance(valor_total, float) and pd.isna(valor_total)):
                try:
                    valor_total = round(float(valor_parcela) * int(parc_total), 2)
                except (ValueError, TypeError):
                    valor_total = valor_parcela

            linhas.append({
                "origem_venda": idx,
                "origem_tipo": "cielo",
                "adquirente": "cielo",
                "valor_match": valor_parcela,
                "valor_bruto_venda_total": valor_total,
                "data_venda": r.get("data_venda"),
                "data_prev_pagamento": r["data_prev_pagamento"],
                "bandeira": _normalizar_bandeira(r["bandeira"]),
                "modalidade": r["modalidade"],
                "parcela_atual": r["parcela_atual"],
                "parcelas_total": parc_total,
                "nsu": r.get("nsu", ""),
                "autorizacao": r.get("autorizacao", ""),
                "tipo_registro": "venda",
            })

    if df_getnet is not None and not df_getnet.empty:
        for idx, r in df_getnet.iterrows():
            valor_parcela = r["valor_parcela_bruto"]
            parc_total = r.get("parcelas_total") or 1
            # Getnet tem valor_venda_bruto (total da venda)
            valor_total = r.get("valor_venda_bruto")
            if valor_total is None or (isinstance(valor_total, float) and pd.isna(valor_total)):
                try:
                    valor_total = round(float(valor_parcela) * int(parc_total), 2)
                except (ValueError, TypeError):
                    valor_total = valor_parcela

            linhas.append({
                "origem_venda": idx,
                "origem_tipo": "getnet",
                "adquirente": "getnet",
                "valor_match": valor_parcela,
                "valor_bruto_venda_total": valor_total,
                "data_venda": r.get("data_venda"),
                "data_prev_pagamento": r["data_prev_pagamento"],
                "bandeira": _normalizar_bandeira(r["bandeira"]),
                "modalidade": r["modalidade"],
                "parcela_atual": r["parcela_atual"],
                "parcelas_total": parc_total,
                "nsu": r.get("nsu", ""),
                "autorizacao": r.get("autorizacao", ""),
                "tipo_registro": r.get("tipo_registro", "venda"),
            })

    return pd.DataFrame(linhas)


# ==============================================================================
# BUSCA DE CANDIDATOS — PRIMEIRA PASSADA (estrita, com data flexível)
# ==============================================================================

def _buscar_candidatos_estrito(
    venda_row: pd.Series,
    df_sk_elegiveis: pd.DataFrame,
    tolerancia_dias: int,
) -> pd.DataFrame:
    """
    Filtros aplicados na PRIMEIRA passada (todos precisam bater):
      1. valor_match == vlr_desdobramento (ao centavo)
      2. MELHOR data (min entre dt_vencimento e data_baixa quando aplicável)
         dentro da tolerância
      3. adquirente compatível
      4. bandeira compatível (se ambos lados conhecidos)
      5. modalidade compatível (se ambos lados conhecidos)
    """
    if df_sk_elegiveis.empty:
        return df_sk_elegiveis

    valor_venda = venda_row["valor_match"]
    data_venda = venda_row["data_prev_pagamento"]

    # Filtro 1: valor ao centavo
    mask_valor = (df_sk_elegiveis["vlr_desdobramento"].round(2) == round(float(valor_venda), 2))
    candidatos = df_sk_elegiveis[mask_valor].copy()
    if candidatos.empty:
        return candidatos

    # Filtro 2: data — usa MELHOR das duas quando disponível
    tem_data_baixa = "data_baixa" in candidatos.columns

    def _data_ok(row):
        dt_venc = row.get("dt_vencimento")
        dt_bai = row.get("data_baixa") if tem_data_baixa else None
        diff = _melhor_diff_dias(data_venda, dt_venc, dt_bai)
        if diff is None:
            return False
        return diff <= tolerancia_dias

    mask_data = candidatos.apply(_data_ok, axis=1)
    candidatos = candidatos[mask_data]
    if candidatos.empty:
        return candidatos

    # Filtro 3: adquirente
    adq_venda = venda_row["adquirente"]
    mask_adq = candidatos["adquirente_sankhya"].apply(
        lambda a: _adquirentes_compativeis(adq_venda, a)
    )
    candidatos = candidatos[mask_adq]
    if candidatos.empty:
        return candidatos

    # Filtro 4: bandeira
    banda_venda = venda_row["bandeira"]
    mask_ban = candidatos["bandeira_sankhya"].apply(
        lambda b: _bandeiras_compativeis(banda_venda, b)
    )
    candidatos = candidatos[mask_ban]
    if candidatos.empty:
        return candidatos

    # Filtro 5: modalidade
    mod_venda = venda_row["modalidade"]
    mask_mod = candidatos["modalidade_sankhya"].apply(
        lambda m: _modalidades_compativeis(mod_venda, m)
    )
    candidatos = candidatos[mask_mod]

    return candidatos


# ==============================================================================
# BUSCA DE CANDIDATOS — SEGUNDA PASSADA (permissiva, SÓ para baixados)
# ==============================================================================

def _buscar_candidatos_permissivo(
    venda_row: pd.Series,
    df_baixados_orfaos: pd.DataFrame,
) -> pd.DataFrame:
    """
    Segunda passada · SÓ para títulos baixado_cartao restantes.
    Regras: valor exato + adquirente + bandeira + modalidade.
    DATA É IGNORADA — se o Sankhya baixou, já validou.
    """
    if df_baixados_orfaos.empty:
        return df_baixados_orfaos

    valor_venda = venda_row["valor_match"]
    mask_valor = (df_baixados_orfaos["vlr_desdobramento"].round(2) == round(float(valor_venda), 2))
    candidatos = df_baixados_orfaos[mask_valor].copy()
    if candidatos.empty:
        return candidatos

    adq_venda = venda_row["adquirente"]
    mask_adq = candidatos["adquirente_sankhya"].apply(
        lambda a: _adquirentes_compativeis(adq_venda, a)
    )
    candidatos = candidatos[mask_adq]
    if candidatos.empty:
        return candidatos

    banda_venda = venda_row["bandeira"]
    mask_ban = candidatos["bandeira_sankhya"].apply(
        lambda b: _bandeiras_compativeis(banda_venda, b)
    )
    candidatos = candidatos[mask_ban]
    if candidatos.empty:
        return candidatos

    mod_venda = venda_row["modalidade"]
    mask_mod = candidatos["modalidade_sankhya"].apply(
        lambda m: _modalidades_compativeis(mod_venda, m)
    )
    candidatos = candidatos[mask_mod]

    return candidatos


# ==============================================================================
# MONTA REGISTRO DE MATCH
# ==============================================================================

def _montar_match(venda_row: pd.Series, candidato: pd.Series, match_permissivo: bool = False) -> dict:
    """Constrói o dict do match (Grupo 1 ou Grupo 2).

    Inclui campos enriquecidos com Cabeçalho da Nota (Entrega 2, 31/07/2026),
    se disponíveis. Para adiantamentos ou títulos sem NF, esses campos ficam None.
    """
    def _safe_get(row, col, default=None):
        if col not in row.index:
            return default
        v = row[col]
        try:
            if pd.isna(v):
                return default
        except (TypeError, ValueError):
            pass
        return v

    return {
        **venda_row.to_dict(),
        "sk_idx": candidato["idx_sankhya"],
        "sk_nro_unico": candidato["nro_unico"],
        "sk_nro_nota": candidato["nro_nota"],
        "sk_empresa_nome": candidato["empresa_nome"],
        "sk_nome_parceiro": candidato["nome_parceiro"],
        "sk_vlr_desdobramento": candidato["vlr_desdobramento"],
        "sk_dt_vencimento": candidato["dt_vencimento"],
        "sk_data_baixa": _safe_get(candidato, "data_baixa"),
        "sk_classe": candidato["classe"],
        "sk_tipo_titulo_desc": candidato["tipo_titulo_desc"],
        "sk_historico": candidato["historico"],
        "sk_ref_nf": candidato["nro_nota_referenciada"],
        "sk_ref_acordo": _safe_get(candidato, "referencia_acordo"),
        "sk_situacao": candidato["situacao"],
        # Enriquecimento via Cabeçalho da Nota (Entrega 2 · 31/07/2026)
        "sk_cab_dt_negociacao": _safe_get(candidato, "cabecalho_dt_negociacao"),
        "sk_cab_vlr_nota_total": _safe_get(candidato, "cabecalho_vlr_nota_total"),
        "sk_cab_descricao_tipo_negociacao": _safe_get(candidato, "cabecalho_descricao_tipo_negociacao"),
        "sk_cab_status_nfe": _safe_get(candidato, "cabecalho_status_nfe"),
        "match_permissivo": match_permissivo,
    }


# ==============================================================================
# MOTOR PRINCIPAL
# ==============================================================================

@dataclass
class ResultadoMotor:
    grupo_1_conciliadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    grupo_2_ja_baixadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    grupo_3_aguardando: pd.DataFrame = field(default_factory=pd.DataFrame)
    grupo_4_devolucoes: pd.DataFrame = field(default_factory=pd.DataFrame)
    a_analisar_ambiguos: pd.DataFrame = field(default_factory=pd.DataFrame)
    a_analisar_venda_sem_titulo: pd.DataFrame = field(default_factory=pd.DataFrame)
    a_analisar_titulo_sem_venda: pd.DataFrame = field(default_factory=pd.DataFrame)

    def resumo(self) -> dict:
        return {
            "grupo_1_conciliadas": len(self.grupo_1_conciliadas),
            "grupo_2_ja_baixadas": len(self.grupo_2_ja_baixadas),
            "grupo_3_aguardando": len(self.grupo_3_aguardando),
            "grupo_4_devolucoes": len(self.grupo_4_devolucoes),
            "a_analisar_ambiguos": len(self.a_analisar_ambiguos),
            "a_analisar_venda_sem_titulo": len(self.a_analisar_venda_sem_titulo),
            "a_analisar_titulo_sem_venda": len(self.a_analisar_titulo_sem_venda),
            "total_a_analisar": (
                len(self.a_analisar_ambiguos)
                + len(self.a_analisar_venda_sem_titulo)
                + len(self.a_analisar_titulo_sem_venda)
            ),
        }


def rodar(
    df_sankhya_classificado: pd.DataFrame,
    df_cielo: Optional[pd.DataFrame],
    df_getnet_vendas: Optional[pd.DataFrame],
    tolerancia_dias: int = 2,
) -> ResultadoMotor:
    """Cruza vendas × títulos e retorna resultado organizado em grupos."""
    # 1. Preparar vendas em visão canônica
    df_vendas = _preparar_vendas(df_cielo, df_getnet_vendas)

    # 2. Separar devoluções (Grupo 4)
    if not df_vendas.empty and "tipo_registro" in df_vendas.columns:
        mask_dev = df_vendas["tipo_registro"] == "cancelamento"
        grupo_4 = df_vendas[mask_dev].copy()
        df_vendas = df_vendas[~mask_dev].copy()
    else:
        grupo_4 = pd.DataFrame()

    # 3. Filtrar títulos elegíveis do Sankhya
    df_sk = df_sankhya_classificado.copy()
    mask_elegivel = (
        df_sk["situacao"].isin(["em_aberto", "baixado_cartao"])
        & df_sk["classe"].isin(["adiantamento", "nota_fiscal"])
    )
    df_elegiveis = df_sk[mask_elegivel].copy()
    df_elegiveis = df_elegiveis.reset_index(drop=False).rename(columns={"index": "idx_sankhya"})

    # 4. PRIMEIRA PASSADA — matching estrito com data flexível
    matches_grupo_1 = []
    matches_grupo_2 = []
    ambiguos = []
    venda_sem_titulo_pass1 = []
    titulos_casados_ids = set()

    for _, venda in df_vendas.iterrows():
        candidatos = _buscar_candidatos_estrito(venda, df_elegiveis, tolerancia_dias)
        n = len(candidatos)

        if n == 0:
            venda_sem_titulo_pass1.append(venda)
            continue

        if n == 1:
            candidato = candidatos.iloc[0]
            idx_sk = candidato["idx_sankhya"]
            match = _montar_match(venda, candidato, match_permissivo=False)
            titulos_casados_ids.add(idx_sk)
            if candidato["situacao"] == "em_aberto":
                matches_grupo_1.append(match)
            else:  # baixado_cartao
                matches_grupo_2.append(match)
            continue

        # n >= 2 → ambíguo
        ambiguos.append({
            **venda.to_dict(),
            "n_candidatos": n,
            "candidatos": candidatos.to_dict(orient="records"),
        })

    # 5. SEGUNDA PASSADA — permissiva SÓ para baixados restantes
    # Vendas que ficaram sem par tentam bater com títulos baixado_cartao órfãos,
    # ignorando tolerância de data. Se o Sankhya baixou, já validou.
    df_baixados_orfaos = df_elegiveis[
        (df_elegiveis["situacao"] == "baixado_cartao")
        & (~df_elegiveis["idx_sankhya"].isin(titulos_casados_ids))
    ].copy()

    venda_sem_titulo_final = []

    for venda in venda_sem_titulo_pass1:
        if df_baixados_orfaos.empty:
            venda_sem_titulo_final.append(venda.to_dict() if hasattr(venda, "to_dict") else dict(venda))
            continue

        candidatos = _buscar_candidatos_permissivo(venda, df_baixados_orfaos)
        n = len(candidatos)

        if n == 0:
            venda_sem_titulo_final.append(venda.to_dict() if hasattr(venda, "to_dict") else dict(venda))
            continue

        if n == 1:
            candidato = candidatos.iloc[0]
            idx_sk = candidato["idx_sankhya"]
            match = _montar_match(venda, candidato, match_permissivo=True)
            titulos_casados_ids.add(idx_sk)
            matches_grupo_2.append(match)
            # Remove do pool
            df_baixados_orfaos = df_baixados_orfaos[df_baixados_orfaos["idx_sankhya"] != idx_sk]
            continue

        # n >= 2 → ambíguo (candidatas são todas baixadas)
        ambiguos.append({
            **venda.to_dict(),
            "n_candidatos": n,
            "candidatos": candidatos.to_dict(orient="records"),
            "fonte_ambiguidade": "passada_permissiva",
        })

    # 6. Grupo 3 (aguardando captura): títulos em aberto que ninguém casou
    df_em_aberto = df_elegiveis[df_elegiveis["situacao"] == "em_aberto"]
    mask_orfaos = ~df_em_aberto["idx_sankhya"].isin(titulos_casados_ids)
    grupo_3 = df_em_aberto[mask_orfaos].copy()

    return ResultadoMotor(
        grupo_1_conciliadas=pd.DataFrame(matches_grupo_1),
        grupo_2_ja_baixadas=pd.DataFrame(matches_grupo_2),
        grupo_3_aguardando=grupo_3,
        grupo_4_devolucoes=grupo_4,
        a_analisar_ambiguos=pd.DataFrame(ambiguos),
        a_analisar_venda_sem_titulo=pd.DataFrame(venda_sem_titulo_final),
        a_analisar_titulo_sem_venda=pd.DataFrame(),
    )
