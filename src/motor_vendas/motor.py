# -*- coding: utf-8 -*-
"""
Motor de conciliação de vendas — Fase 4 · MVP-A.

Cruza vendas das adquirentes (Cielo, Getnet) com títulos do Sankhya
(notas fiscais + adiantamentos) e organiza em 4 grupos + "a analisar".

Entrada:
    df_sankhya_classificado : DataFrame retornado por
                              classificador_sankhya.classificar()
    df_cielo                : DataFrame de vendas Cielo
                              (leitor cielo_recebiveis.ler())
    df_getnet_vendas        : DataFrame de vendas Getnet
                              (leitor getnet_recebiveis.ler().df_vendas)
    tolerancia_dias         : int (default 2)

Saída: dict com DataFrames dos 4 grupos + "a_analisar".

Regras (memória 30/07/2026):
    - Adiantamento (TOP_OP 1654) e nota fiscal em aberto (TOP 0) são candidatos
    - Nunca há ambos com mesmo cliente+valor abertos (0 casos ambíguos nos dados)
    - Match por: valor exato + data compatível + adquirente + bandeira + modalidade
    - Parcelas do parcelado tratadas como vendas independentes
    - Match único → auto-concilia (Grupo 1); múltiplos → "a analisar"; zero → "a analisar"
    - Ignora TOP 1731/1732 (compensadas — já resolvidas)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd


# ==============================================================================
# NORMALIZAÇÃO DE BANDEIRA
# ==============================================================================

# Mapa Adquirente -> código curto usado pelo classificador Sankhya
_MAPA_BANDEIRA = {
    "mastercard": "master",
    "master": "master",
    "mas": "master",
    "visa": "visa",
    "vis": "visa",
    "elo": "elo",
    "hipercard": "hipercard",
    "amex": "amex",
    "american express": "amex",
}


def _normalizar_bandeira(b) -> Optional[str]:
    """Retorna código curto ('master', 'visa', 'elo', ...) ou None."""
    if b is None:
        return None
    s = str(b).strip().lower()
    return _MAPA_BANDEIRA.get(s)


def _is_none_or_nan(v) -> bool:
    """True se v é None ou NaN do pandas."""
    if v is None:
        return True
    try:
        return pd.isna(v)
    except (TypeError, ValueError):
        return False


def _bandeiras_compativeis(banda_venda, banda_sk) -> bool:
    """
    True se as bandeiras batem, considerando 'VIS/MAS' e 'MAS/ELO' como coringas do Sankhya.
    Se qualquer lado for None/NaN, retorna True (não impede match — pista fraca).
    """
    if _is_none_or_nan(banda_venda) or _is_none_or_nan(banda_sk):
        return True
    if banda_sk == banda_venda:
        return True
    if banda_sk == "vis_mas" and banda_venda in ("visa", "master"):
        return True
    if banda_sk == "mas_elo" and banda_venda in ("master", "elo"):
        return True
    return False


def _modalidades_compativeis(mod_venda, mod_sk) -> bool:
    """True se as modalidades batem. None/NaN em qualquer lado não bloqueia."""
    if _is_none_or_nan(mod_venda) or _is_none_or_nan(mod_sk):
        return True
    return mod_venda == mod_sk


def _adquirentes_compativeis(adq_venda, adq_sk) -> bool:
    """True se as adquirentes batem. None/NaN do lado Sankhya não bloqueia (pista fraca)."""
    if _is_none_or_nan(adq_venda):
        return False  # venda tem que ter adquirente conhecida
    if _is_none_or_nan(adq_sk):
        return True   # Sankhya sem inferência = não bloqueia
    return adq_venda == adq_sk


def _datas_compativeis(dt_venda: date, dt_titulo: date, tolerancia_dias: int) -> bool:
    """True se |dt_venda - dt_titulo| <= tolerância."""
    if dt_venda is None or dt_titulo is None:
        return False
    if not isinstance(dt_venda, date):
        try:
            dt_venda = pd.to_datetime(dt_venda).date()
        except Exception:
            return False
    if not isinstance(dt_titulo, date):
        try:
            dt_titulo = pd.to_datetime(dt_titulo).date()
        except Exception:
            return False
    return abs((dt_venda - dt_titulo).days) <= tolerancia_dias


# ==============================================================================
# PREPARAÇÃO DAS VENDAS (visão canônica única)
# ==============================================================================

def _preparar_vendas(df_cielo: pd.DataFrame, df_getnet: pd.DataFrame) -> pd.DataFrame:
    """
    Junta Cielo e Getnet numa visão canônica pro matcher.

    Colunas:
        origem_venda       : índice no DataFrame original (pra rastrear depois)
        origem_tipo        : 'cielo' | 'getnet'
        adquirente         : 'cielo' | 'getnet'
        valor_match        : valor da parcela a bater com o título Sankhya
        data_prev_pagamento
        bandeira           : código curto ('master', 'visa', 'elo', None)
        modalidade         : 'debito' | 'credito_avista' | 'credito_parcelado'
        parcela_atual, parcelas_total
        chaves de rastreio : nsu, autorizacao, tipo_registro
    """
    linhas = []

    if df_cielo is not None and not df_cielo.empty:
        for idx, r in df_cielo.iterrows():
            linhas.append({
                "origem_venda": idx,
                "origem_tipo": "cielo",
                "adquirente": "cielo",
                "valor_match": r["valor_bruto"],
                "data_prev_pagamento": r["data_prev_pagamento"],
                "bandeira": _normalizar_bandeira(r["bandeira"]),
                "modalidade": r["modalidade"],
                "parcela_atual": r["parcela_atual"],
                "parcelas_total": r["parcelas_total"],
                "nsu": r.get("nsu", ""),
                "autorizacao": r.get("autorizacao", ""),
                "tipo_registro": "venda",
            })

    if df_getnet is not None and not df_getnet.empty:
        for idx, r in df_getnet.iterrows():
            linhas.append({
                "origem_venda": idx,
                "origem_tipo": "getnet",
                "adquirente": "getnet",
                "valor_match": r["valor_parcela_bruto"],
                "data_prev_pagamento": r["data_prev_pagamento"],
                "bandeira": _normalizar_bandeira(r["bandeira"]),
                "modalidade": r["modalidade"],
                "parcela_atual": r["parcela_atual"],
                "parcelas_total": r["parcelas_total"],
                "nsu": r.get("nsu", ""),
                "autorizacao": r.get("autorizacao", ""),
                "tipo_registro": r.get("tipo_registro", "venda"),
            })

    return pd.DataFrame(linhas)


# ==============================================================================
# BUSCA DE CANDIDATOS SANKHYA PARA UMA VENDA
# ==============================================================================

def _buscar_candidatos(
    venda_row: pd.Series,
    df_sk_elegiveis: pd.DataFrame,
    tolerancia_dias: int,
) -> pd.DataFrame:
    """
    Pra uma venda, retorna os títulos Sankhya que podem casar.

    Filtros aplicados (todos precisam bater):
        1. valor_match == vlr_desdobramento (ao centavo, tolerância R$ 0,01)
        2. |data_prev_pagamento - dt_vencimento| <= tolerancia_dias
        3. adquirente compatível
        4. bandeira compatível (se ambos lados conhecidos)
        5. modalidade compatível (se ambos lados conhecidos)
    """
    if df_sk_elegiveis.empty:
        return df_sk_elegiveis

    valor_venda = venda_row["valor_match"]
    data_venda = venda_row["data_prev_pagamento"]

    # Filtro 1: valor exato ao centavo (usar arredondamento pra evitar imprecisão float)
    mask_valor = (df_sk_elegiveis["vlr_desdobramento"].round(2) == round(float(valor_venda), 2))
    candidatos = df_sk_elegiveis[mask_valor].copy()
    if candidatos.empty:
        return candidatos

    # Filtro 2: data compatível
    def _data_ok(dt_sk):
        return _datas_compativeis(data_venda, dt_sk, tolerancia_dias)
    mask_data = candidatos["dt_vencimento"].apply(_data_ok)
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
# MOTOR PRINCIPAL
# ==============================================================================

@dataclass
class ResultadoMotor:
    """Resultado da rodada de conciliação organizado em grupos."""
    grupo_1_conciliadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    grupo_2_ja_baixadas: pd.DataFrame = field(default_factory=pd.DataFrame)
    grupo_3_aguardando: pd.DataFrame = field(default_factory=pd.DataFrame)
    grupo_4_devolucoes: pd.DataFrame = field(default_factory=pd.DataFrame)
    a_analisar_ambiguos: pd.DataFrame = field(default_factory=pd.DataFrame)
    a_analisar_venda_sem_titulo: pd.DataFrame = field(default_factory=pd.DataFrame)
    a_analisar_titulo_sem_venda: pd.DataFrame = field(default_factory=pd.DataFrame)

    def resumo(self) -> dict:
        """Contadores pros KPIs da tela."""
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
    """
    Cruza vendas × títulos e retorna o resultado organizado em grupos.

    Args:
        df_sankhya_classificado: saída de classificador_sankhya.classificar()
        df_cielo: DataFrame de vendas Cielo (pode ser None)
        df_getnet_vendas: DataFrame de vendas Getnet (pode ser None)
        tolerancia_dias: janela de tolerância de data em dias (default 2)

    Returns:
        ResultadoMotor com os 4 grupos + "a analisar".
    """
    # 1. Preparar vendas em visão canônica
    df_vendas = _preparar_vendas(df_cielo, df_getnet_vendas)

    # 2. Separar devoluções (Grupo 4) — vendas com tipo_registro = "cancelamento"
    if not df_vendas.empty and "tipo_registro" in df_vendas.columns:
        mask_dev = df_vendas["tipo_registro"] == "cancelamento"
        grupo_4 = df_vendas[mask_dev].copy()
        df_vendas = df_vendas[~mask_dev].copy()
    else:
        grupo_4 = pd.DataFrame()

    # 3. Filtrar títulos elegíveis do Sankhya (em aberto + baixados por cartão)
    df_sk = df_sankhya_classificado.copy()
    mask_elegivel = (
        df_sk["situacao"].isin(["em_aberto", "baixado_cartao"])
        & df_sk["classe"].isin(["adiantamento", "nota_fiscal"])
    )
    df_elegiveis = df_sk[mask_elegivel].copy()

    # Reset index pra ter índices únicos consistentes
    df_elegiveis = df_elegiveis.reset_index(drop=False).rename(
        columns={"index": "idx_sankhya"}
    )

    # 4. Pra cada venda, buscar candidatos
    matches_grupo_1 = []   # em_aberto, match único
    matches_grupo_2 = []   # baixado_cartao, match único (auditoria)
    ambiguos = []
    venda_sem_titulo = []
    titulos_casados_ids = set()

    for _, venda in df_vendas.iterrows():
        candidatos = _buscar_candidatos(venda, df_elegiveis, tolerancia_dias)
        n = len(candidatos)

        if n == 0:
            venda_sem_titulo.append(venda.to_dict())
            continue

        if n == 1:
            candidato = candidatos.iloc[0]
            idx_sk = candidato["idx_sankhya"]
            match = {
                **venda.to_dict(),
                "sk_idx": idx_sk,
                "sk_nro_unico": candidato["nro_unico"],
                "sk_nro_nota": candidato["nro_nota"],
                "sk_empresa_nome": candidato["empresa_nome"],
                "sk_nome_parceiro": candidato["nome_parceiro"],
                "sk_vlr_desdobramento": candidato["vlr_desdobramento"],
                "sk_dt_vencimento": candidato["dt_vencimento"],
                "sk_classe": candidato["classe"],
                "sk_tipo_titulo_desc": candidato["tipo_titulo_desc"],
                "sk_historico": candidato["historico"],
                "sk_ref_nf": candidato["nro_nota_referenciada"],
                "sk_ref_acordo": candidato["referencia_acordo"],
                "sk_situacao": candidato["situacao"],
            }
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

    # 5. Grupo 3 (aguardando captura) e "titulo_sem_venda":
    # Títulos em aberto que nenhuma venda casou.
    df_em_aberto = df_elegiveis[df_elegiveis["situacao"] == "em_aberto"]
    mask_orfaos = ~df_em_aberto["idx_sankhya"].isin(titulos_casados_ids)
    titulos_orfaos = df_em_aberto[mask_orfaos].copy()

    # Regra: se o título tem adquirente identificada e ainda estamos no período previsto,
    # cai em "aguardando captura". Se identificamos como órfão (adquirente sem venda), fica
    # em "titulo_sem_venda".
    # Por simplicidade: todos os órfãos em aberto vão pra Grupo 3, e a Débora pode filtrar
    # pela adquirente na tela. O "titulo_sem_venda" fica reservado pra casos claros de erro
    # (ex: título com data de vencimento no passado sem venda casando).
    grupo_3 = titulos_orfaos

    # Títulos baixados por cartão sem venda casando também são anômalos —
    # mas raros e ficam no Grupo 2 vazio. Simplifica: só titulos_orfaos em_aberto.

    return ResultadoMotor(
        grupo_1_conciliadas=pd.DataFrame(matches_grupo_1),
        grupo_2_ja_baixadas=pd.DataFrame(matches_grupo_2),
        grupo_3_aguardando=grupo_3,
        grupo_4_devolucoes=grupo_4,
        a_analisar_ambiguos=pd.DataFrame(ambiguos),
        a_analisar_venda_sem_titulo=pd.DataFrame(venda_sem_titulo),
        a_analisar_titulo_sem_venda=pd.DataFrame(),  # reservado, ainda não usado
    )
