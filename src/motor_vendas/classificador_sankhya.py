# -*- coding: utf-8 -*-
"""
Classificador de linhas do Sankhya — Fase 4 · MVP-A Conciliação de Vendas.

Recebe o DataFrame normalizado pelo leitor `src.parsers.vendas.financeiro_sankhya`
e adiciona colunas derivadas que o motor de match consome:

    classe                        -> "adiantamento" | "nota_fiscal" | "outro"
    adquirente_sankhya            -> "getnet" | "cielo" | "pagseguro" | None
    bandeira_sankhya              -> "visa" | "master" | "elo" | "vis_mas" | None
    modalidade_sankhya            -> "debito" | "credito_avista" | "credito_parcelado" | None
    parcelas_sankhya              -> int (1 = à vista, N = parcelado em N)
    nro_nota_referenciada         -> int | None (parseado do histórico "REF NF XXXX")
    referencia_acordo             -> str | None (parseado do histórico "REF ACORDO ...")
    tipo_referencia               -> "nota" | "acordo" | None
    situacao                      -> "em_aberto" | "baixado_cartao" | "compensada" | "outro"

Regras invioláveis (aprendidas com Débora, memória 30/07/2026):

  1. Adiantamento é IDENTIFICADO pelo TOP_OP=1654 + natureza "Adiantamentos/Credito
     para Clientes". Isso é DETERMINÍSTICO. Nunca confundir com nota fiscal.

  2. Nota fiscal tem natureza "Vendas notas fiscais". A ADQUIRENTE vem do
     Tipo de Título (col 22):
       - "GETNET" no nome              -> Getnet
       - " PS " no nome (delimitado)   -> PagSeguro
       - "CREDITO A DISTANCIA" (TOP 118) -> Cielo link (configuração temporária)

  3. Motor só olha títulos em aberto (TOP baixa 0) e já baixados por cartão
     (TOP 1722). Ignora TOP 1731/1732 (compensadas) e outros TOPs.

  4. "CRED PARC N" ou "TEF NX" com N >= 2 = parcelado em N vezes (NÃO significa
     "N-ésima parcela").
     "TEF 1X" ou "CRED PARC 1X" = crédito à vista.
     "DEBITO" no nome = débito.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd


# ==============================================================================
# CONSTANTES
# ==============================================================================

# Códigos usados no Sankhya (validados contra o arquivo real de 30/07/2026)
TOP_OP_CARTAO_RECEITA_ADIANT = 1654
TOPS_OP_VENDA = {1131, 1101}  # 1131 = VENDA PISA, 1101 = VENDA (KING/PISA sem sufixo)
TOPS_OP_DEVOLUCAO = {1205}     # DEVOLUÇÃO DE VENDA WMS
TOP_BAIXA_EM_ABERTO = 0
TOP_BAIXA_CARTAO = 1722
TOPS_BAIXA_COMPENSADA = {1731, 1732, 1716, 1707}

NATUREZA_NOTA_FISCAL = "Vendas notas fiscais"
NATUREZA_ADIANTAMENTO = "Adiantamentos/Credito para Clientes"

# ==============================================================================
# REGEX DE EXTRAÇÃO
# ==============================================================================

# "REF NF 1138204" no histórico do adiantamento — chave forte pra ligar à nota original
_RE_REF_NF = re.compile(r"REF\s+NF\s+(\d+)", re.IGNORECASE)

# "REF ACORDO R$ 40.000,00" — adiantamento vinculado a parcelamento de dívida antigo
# Aceita variações: "REF ACORDO", "RE ACORDO" (typo real da Débora), com ou sem R$
_RE_REF_ACORDO = re.compile(r"R[EF]{1,2}\s+ACORDO\s+(.+)", re.IGNORECASE)

# Tipo de Título: número de parcelas explícito
#   "CRED PARC 2 - ..."          -> parcelado 2x
#   "GETNET TEF 3X - ..."        -> parcelado 3x
#   "CRED PARC 2 A 6 - ..."      -> parcelado 2 a 6x (faixa; motor trata como parcelado)
#   "TEF 1X" ou "CRED PARC 1X"   -> crédito à vista
_RE_PARC_NX = re.compile(r"\b(?:TEF|CRED\s+PARC|CRED\s+TEF)\s+(\d+)X?\b", re.IGNORECASE)
_RE_PARC_FAIXA = re.compile(r"\bCRED\s+PARC\s+(\d+)\s+A\s+(\d+)\b", re.IGNORECASE)

# "PS" ISOLADO — delimitado por espaços/traços/fim de string (não pega "APS", "PSA")
_RE_PS_ISOLADO = re.compile(r"(?:^|[\s\-/])PS(?:[\s\-/]|$)", re.IGNORECASE)


# ==============================================================================
# HELPERS DE CLASSIFICAÇÃO
# ==============================================================================

def _classificar_classe(row: pd.Series) -> str:
    """
    Adiantamento vs Nota fiscal vs Outro.

    Regra determinística confirmada nos dados reais da Débora:
      - tipo_operacao == 1654 (CARTAO-Receita Adiantamento) -> ADIANTAMENTO
      - tipo_operacao em {1131 (VENDA PISA), 1101 (VENDA)}  -> NOTA FISCAL
      - Qualquer outro (1205 devolução, etc)                -> outro (fora do escopo de match)
    """
    top_op = row.get("tipo_operacao")
    if top_op == TOP_OP_CARTAO_RECEITA_ADIANT:
        return "adiantamento"
    if top_op in TOPS_OP_VENDA:
        return "nota_fiscal"
    return "outro"


def _identificar_adquirente(row: pd.Series, classe: str) -> Optional[str]:
    """Inferir adquirente pela descrição do Tipo de Título."""
    desc = str(row.get("tipo_titulo_desc") or "").upper()
    if not desc:
        return None

    # Getnet é o mais explícito
    if "GETNET" in desc:
        return "getnet"

    # PagSeguro — "PS" isolado
    if _RE_PS_ISOLADO.search(desc):
        return "pagseguro"

    # Cielo link — quando é nota fiscal com TOP 118 (CREDITO A DISTANCIA)
    tipo_cod = row.get("tipo_titulo")
    if classe == "nota_fiscal" and tipo_cod == 118:
        return "cielo"

    return None


def _identificar_bandeira(desc: str) -> Optional[str]:
    """VISA / MASTER / ELO / VIS_MAS a partir do Tipo de Título."""
    d = desc.upper()
    if not d:
        return None
    if "VIS/MAS" in d or "MAS/ELO" in d and "MAS" in d and "ELO" in d:
        # "MAS/ELO" pode incluir ELO — vamos ser mais preciso abaixo
        pass
    if "VIS/MAS" in d:
        return "vis_mas"
    if "MAS/ELO" in d:
        return "mas_elo"
    if "MASTER" in d or " MAS " in f" {d} " or d.endswith(" MAS"):
        return "master"
    if "VISA" in d or " VIS " in f" {d} " or d.endswith(" VIS"):
        return "visa"
    if "ELO" in d:
        return "elo"
    return None


def _identificar_modalidade_e_parcelas(desc: str) -> tuple[Optional[str], int]:
    """Retorna (modalidade, parcelas). Modalidade: debito, credito_avista, credito_parcelado."""
    d = desc.upper()
    if not d:
        return (None, 1)

    # Débito é explícito
    if "DEBITO" in d or "DÉBITO" in d or "DEB TEF" in d or d.startswith("DEB "):
        return ("debito", 1)

    # Parcelado (faixa "CRED PARC 2 A 6")
    m_faixa = _RE_PARC_FAIXA.search(d)
    if m_faixa:
        # motor considera como parcelado (parcelas do meio; usar valor min = 2 é seguro)
        return ("credito_parcelado", int(m_faixa.group(1)))

    # Parcelado explícito "TEF NX" ou "CRED PARC N"
    m = _RE_PARC_NX.search(d)
    if m:
        n = int(m.group(1))
        if n == 1:
            return ("credito_avista", 1)
        return ("credito_parcelado", n)

    # "CREDITO A DISTANCIA" (Cielo link) → NÃO distingue à vista vs parcelado.
    # Retornamos None pra modalidade — assim o motor não bloqueia match por modalidade.
    if "CREDITO A DISTANCIA" in d:
        return (None, 1)

    # "CREDITO A VISTA"
    if "CREDITO A VISTA" in d:
        return ("credito_avista", 1)

    # "CREDITO" genérico
    if "CREDITO" in d or "CRÉDITO" in d:
        return ("credito_avista", 1)

    return (None, 1)


def _extrair_ref_nf(historico: str) -> Optional[int]:
    """Parseia 'REF NF 1138204' do histórico do adiantamento."""
    if not historico:
        return None
    m = _RE_REF_NF.search(str(historico))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, TypeError):
        return None


def _extrair_ref_acordo(historico: str) -> Optional[str]:
    """Parseia 'REF ACORDO R$ 40.000,00' do histórico do adiantamento."""
    if not historico:
        return None
    m = _RE_REF_ACORDO.search(str(historico))
    if not m:
        return None
    return m.group(1).strip()


def _classificar_situacao(top_baixa) -> str:
    """em_aberto / baixado_cartao / compensada / outro"""
    try:
        top_int = int(top_baixa) if top_baixa is not None else None
    except (ValueError, TypeError):
        return "outro"
    if top_int == TOP_BAIXA_EM_ABERTO:
        return "em_aberto"
    if top_int == TOP_BAIXA_CARTAO:
        return "baixado_cartao"
    if top_int in TOPS_BAIXA_COMPENSADA:
        return "compensada"
    return "outro"


# ==============================================================================
# FUNÇÃO PRINCIPAL
# ==============================================================================

def classificar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adiciona colunas de classificação ao DataFrame retornado pelo leitor Sankhya.

    Args:
        df: DataFrame da função `financeiro_sankhya.ler()`, com as colunas:
            top_baixa, top_baixa_desc, tipo_titulo, tipo_titulo_desc,
            tipo_operacao, receita_despesa, historico, ...

    Returns:
        DataFrame com colunas adicionais:
            classe, adquirente_sankhya, bandeira_sankhya, modalidade_sankhya,
            parcelas_sankhya, nro_nota_referenciada, situacao
    """
    if df is None or df.empty:
        # Devolve DataFrame vazio mas com as colunas certas
        cols_extra = [
            "classe", "adquirente_sankhya", "bandeira_sankhya",
            "modalidade_sankhya", "parcelas_sankhya",
            "nro_nota_referenciada", "situacao",
        ]
        vazio = df.copy() if df is not None else pd.DataFrame()
        for c in cols_extra:
            vazio[c] = pd.Series(dtype="object")
        return vazio

    out = df.copy()

    classes = []
    adquirentes = []
    bandeiras = []
    modalidades = []
    parcelas = []
    ref_nfs = []
    ref_acordos = []
    tipos_ref = []
    situacoes = []

    for _, row in out.iterrows():
        classe = _classificar_classe(row)
        desc = str(row.get("tipo_titulo_desc") or "")
        adquirente = _identificar_adquirente(row, classe)
        bandeira = _identificar_bandeira(desc)
        modalidade, parc = _identificar_modalidade_e_parcelas(desc)
        historico = str(row.get("historico") or "")
        ref_nf = _extrair_ref_nf(historico)
        ref_acordo = _extrair_ref_acordo(historico)
        tipo_ref = "nota" if ref_nf else ("acordo" if ref_acordo else None)
        situacao = _classificar_situacao(row.get("top_baixa"))

        classes.append(classe)
        adquirentes.append(adquirente)
        bandeiras.append(bandeira)
        modalidades.append(modalidade)
        parcelas.append(parc)
        ref_nfs.append(ref_nf)
        ref_acordos.append(ref_acordo)
        tipos_ref.append(tipo_ref)
        situacoes.append(situacao)

    out["classe"] = classes
    out["adquirente_sankhya"] = adquirentes
    out["bandeira_sankhya"] = bandeiras
    out["modalidade_sankhya"] = modalidades
    out["parcelas_sankhya"] = parcelas
    out["nro_nota_referenciada"] = ref_nfs
    out["referencia_acordo"] = ref_acordos
    out["tipo_referencia"] = tipos_ref
    out["situacao"] = situacoes

    return out


# ==============================================================================
# HELPERS DE SUBCONJUNTOS (usados pelo motor)
# ==============================================================================

def filtrar_elegiveis_para_match(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retorna apenas as linhas que o motor considera pra fazer match com adquirente:
      - Adiantamentos em aberto
      - Notas fiscais em aberto
      - Adiantamentos já baixados por cartão (para Grupo 2 · auditoria)
      - Notas fiscais já baixadas por cartão (para Grupo 2 · auditoria)

    Ignora:
      - Compensadas (TOP 1731/1732/1716/1707) — nota já foi baixada internamente
      - Outros
    """
    if df is None or df.empty:
        return df
    mask = (
        df["situacao"].isin(["em_aberto", "baixado_cartao"])
        & df["classe"].isin(["adiantamento", "nota_fiscal"])
    )
    return df[mask].copy()
