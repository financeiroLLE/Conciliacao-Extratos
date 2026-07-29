# -*- coding: utf-8 -*-
"""
Leitor do relatório Cielo "Recebíveis Detalhado - Lançamentos".

Formato esperado:
- Arquivo .xls binário (D0CF11E0)
- Uma única aba
- Linhas 0-8: metadados (título, filtros, totalizador)
- Linha 9 (índice 9): cabeçalho (59 colunas)
- Linha 10+: dados

Contexto MVP-A:
- Todas as vendas Cielo do Grupo LLE são "Link de pagamento" (não há POS)
- Estabelecimento único: 1116384474
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd
import xlrd


# ==============================================================================
# CONSTANTES
# ==============================================================================

# Colunas críticas do cabeçalho de 59 colunas (Cielo)
COL_DATA_PAGAMENTO = 0
COL_DATA_LANCAMENTO = 1
COL_ESTABELECIMENTO = 2
COL_TIPO_LANCAMENTO = 3          # "Venda crédito", "Venda parcelada", etc.
COL_FORMA_PAGAMENTO = 4          # "Crédito à vista", "Crédito parcelado loja", "Débito"
COL_BANDEIRA = 5
COL_VALOR_BRUTO = 6
COL_TAXA_TARIFA = 7              # negativo (desconto)
COL_VALOR_LIQUIDO = 8
COL_STATUS_PAGAMENTO = 9
COL_DESCRICAO = 10
COL_DATA_VENDA = 11
COL_HORA_VENDA = 12
COL_DATA_PREV_PAGAMENTO = 13
COL_AUTORIZACAO = 15
COL_NSU_DOC = 16
COL_CODIGO_VENDA = 17            # chave única mais confiável no Cielo
COL_TID = 18
COL_NUMERO_PEDIDO = 24
COL_PARCELA_NUM = 27             # "01"
COL_PARCELAS_TOTAL = 28          # "02"
COL_MODALIDADE = 30              # "Link de pagamento", "Presencial", etc.
COL_TAXA_TOTAL_PCT = 36
COL_TAXA_MDR_PCT = 37
COL_TAXA_PRAZO_PCT = 38
COL_VALOR_TAXA_MDR = 39
COL_VALOR_TAXA_PRAZO = 40

# Colunas de saída padronizadas para o motor
COLUNAS_SAIDA = [
    "adquirente",
    "estabelecimento",
    "data_venda",
    "data_pagamento",
    "data_prev_pagamento",
    "valor_bruto",
    "valor_taxa",
    "valor_liquido",
    "bandeira",
    "modalidade",                # "credito_avista" | "credito_parcelado" | "debito" | "pix"
    "canal",                     # "link_pagamento" | "presencial" | "ecommerce" | "outro"
    "parcela_atual",             # int, 1 quando à vista
    "parcelas_total",            # int, 1 quando à vista
    "autorizacao",
    "nsu",
    "codigo_venda",
    "tid",
    "numero_pedido",
    "tipo_lancamento",
    "forma_pagamento_original",  # texto original da Cielo
    "modalidade_original",       # texto original da Cielo
    "taxa_mdr_pct",
    "taxa_prazo_pct",
    "status_pagamento",
]


# ==============================================================================
# HELPERS
# ==============================================================================

def _detectar_signature(dados: bytes) -> str:
    head = dados[:8]
    if head.startswith(b"\xD0\xCF\x11\xE0"):
        return "xls"
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    return "outro"


def _abrir_workbook(dados: bytes):
    sig = _detectar_signature(dados)
    if sig == "xls":
        return xlrd.open_workbook(file_contents=dados)
    raise ValueError(
        f"Cielo Recebíveis Detalhe deve vir como .xls binário. "
        f"Byte signature recebido: {dados[:8]!r}"
    )


# ==============================================================================
# VALIDAÇÃO DE CABEÇALHO
# ==============================================================================

MARCADORES_CABECALHO_CIELO = [
    "data de pagamento",
    "data do lançamento",
    "estabelecimento",
    "tipo de lançamento",
    "forma de pagamento",
    "bandeira",
]


def eh_cielo_recebiveis(dados: bytes) -> bool:
    """Detecta se o arquivo é o Cielo Recebíveis Detalhe."""
    try:
        wb = _abrir_workbook(dados)
    except Exception:
        return False
    if wb.nsheets < 1:
        return False
    sh = wb.sheet_by_index(0)
    if sh.nrows < 12 or sh.ncols < 40:
        return False

    # Procurar linha de cabeçalho nas primeiras 15 linhas
    idx_cab = _achar_cabecalho(sh)
    return idx_cab is not None


def _achar_cabecalho(sh) -> Optional[int]:
    """
    Localiza a linha de cabeçalho.

    A linha 3 do arquivo Cielo contém um bloco "Filtros:\\nData de pagamento: ...\\n
    Estabelecimento: ...\\n..." dentro de UMA SÓ célula — que tem todas as palavras-chave
    e pode confundir um detector ingênuo. Portanto: exigimos que cada marcador esteja
    numa CÉLULA DIFERENTE (igualdade exata, ou pelo menos comece com o marcador).
    """
    limite = min(15, sh.nrows)
    for r in range(limite):
        vals = [str(sh.cell_value(r, c)).strip().lower() for c in range(min(10, sh.ncols))]
        # Contar quantas células BATEM (uma célula = um marcador no máximo)
        celulas_marcadas = 0
        for v in vals:
            # Exigimos que a célula seja EXATAMENTE o marcador ou comece com ele
            # (não seja um bloco longo que contém o marcador como substring)
            if len(v) > 50:
                continue
            for m in MARCADORES_CABECALHO_CIELO:
                if v == m or v.startswith(m):
                    celulas_marcadas += 1
                    break
        if celulas_marcadas >= 5:
            return r
    return None


# ==============================================================================
# CONVERSÕES
# ==============================================================================

def _to_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        # Cielo põe parcelas como "01", "02" — string com zero à esquerda
        try:
            s = str(v).strip()
            return int(s) if s else None
        except Exception:
            return None


def _to_float(v) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        # às vezes vem "R$ 1.234,56"
        s = str(v).strip()
        s = re.sub(r"[^\d,\-]", "", s).replace(",", ".")
        try:
            return float(s) if s else 0.0
        except ValueError:
            return 0.0


def _to_date(v, datemode: int) -> Optional[date]:
    if v is None or v == "":
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None
    try:
        f = float(v)
        if f <= 0:
            return None
        tup = xlrd.xldate_as_tuple(f, datemode)
        return date(tup[0], tup[1], tup[2])
    except Exception:
        return None


# ==============================================================================
# CLASSIFICAÇÃO DE MODALIDADE E CANAL
# ==============================================================================

def _classificar_modalidade(forma_pagamento: str, tipo_lancamento: str) -> str:
    """Mapeia o texto da Cielo para um código curto."""
    fp = (forma_pagamento or "").lower()
    tl = (tipo_lancamento or "").lower()

    if "débito" in fp or "debito" in fp:
        return "debito"
    if "parcel" in fp or "parcel" in tl:
        return "credito_parcelado"
    if "crédito" in fp or "credito" in fp or "vista" in fp:
        return "credito_avista"
    if "pix" in fp or "pix" in tl:
        return "pix"
    return "outro"


def _classificar_canal(modalidade_txt: str) -> str:
    """Classifica o canal (link/presencial/etc.)."""
    m = (modalidade_txt or "").lower()
    if "link" in m:
        return "link_pagamento"
    if "presencial" in m or "pos" in m:
        return "presencial"
    if "e-commerce" in m or "ecommerce" in m or "e commerce" in m:
        return "ecommerce"
    return "outro"


# ==============================================================================
# FUNÇÃO PRINCIPAL
# ==============================================================================

@dataclass
class ResultadoLeituraCielo:
    df: pd.DataFrame
    total_linhas: int
    linhas_ignoradas: int
    estabelecimentos: list
    total_bruto: float
    total_taxa: float
    total_liquido: float


def ler(dados: bytes) -> ResultadoLeituraCielo:
    """Lê o Cielo Recebíveis Detalhe e retorna DataFrame normalizado."""
    if not eh_cielo_recebiveis(dados):
        raise ValueError("Arquivo não é o Cielo Recebíveis Detalhe (cabeçalho não bate).")

    wb = _abrir_workbook(dados)
    sh = wb.sheet_by_index(0)
    datemode = wb.datemode

    idx_cab = _achar_cabecalho(sh)
    if idx_cab is None:
        raise ValueError("Cabeçalho Cielo não localizado.")

    linhas = []
    ignoradas = 0
    estabs_set = set()

    for r in range(idx_cab + 1, sh.nrows):
        row = sh.row_values(r)

        if not any(str(v).strip() for v in row):
            ignoradas += 1
            continue

        tipo_lanc = str(row[COL_TIPO_LANCAMENTO]).strip()
        forma_pgto = str(row[COL_FORMA_PAGAMENTO]).strip()

        # Filtrar apenas linhas de venda (Cielo não repete "Saldo Anterior" no detalhe)
        if not tipo_lanc:
            ignoradas += 1
            continue

        estab = str(row[COL_ESTABELECIMENTO]).strip()
        if estab:
            estabs_set.add(estab)

        parc_atual = _to_int(row[COL_PARCELA_NUM]) or 1
        parc_total = _to_int(row[COL_PARCELAS_TOTAL]) or 1

        modalidade_txt = str(row[COL_MODALIDADE]).strip()

        linhas.append({
            "adquirente": "cielo",
            "estabelecimento": estab,
            "data_venda": _to_date(row[COL_DATA_VENDA], datemode),
            "data_pagamento": _to_date(row[COL_DATA_PAGAMENTO], datemode),
            "data_prev_pagamento": _to_date(row[COL_DATA_PREV_PAGAMENTO], datemode),
            "valor_bruto": _to_float(row[COL_VALOR_BRUTO]),
            "valor_taxa": abs(_to_float(row[COL_TAXA_TARIFA])),  # armazenar positivo
            "valor_liquido": _to_float(row[COL_VALOR_LIQUIDO]),
            "bandeira": str(row[COL_BANDEIRA]).strip(),
            "modalidade": _classificar_modalidade(forma_pgto, tipo_lanc),
            "canal": _classificar_canal(modalidade_txt),
            "parcela_atual": parc_atual,
            "parcelas_total": parc_total,
            "autorizacao": str(row[COL_AUTORIZACAO]).strip(),
            "nsu": str(row[COL_NSU_DOC]).strip(),
            "codigo_venda": str(row[COL_CODIGO_VENDA]).strip(),
            "tid": str(row[COL_TID]).strip(),
            "numero_pedido": str(row[COL_NUMERO_PEDIDO]).strip(),
            "tipo_lancamento": tipo_lanc,
            "forma_pagamento_original": forma_pgto,
            "modalidade_original": modalidade_txt,
            "taxa_mdr_pct": _to_float(row[COL_TAXA_MDR_PCT]),
            "taxa_prazo_pct": _to_float(row[COL_TAXA_PRAZO_PCT]),
            "status_pagamento": str(row[COL_STATUS_PAGAMENTO]).strip(),
        })

    df = pd.DataFrame(linhas, columns=COLUNAS_SAIDA)

    return ResultadoLeituraCielo(
        df=df,
        total_linhas=len(linhas),
        linhas_ignoradas=ignoradas,
        estabelecimentos=sorted(estabs_set),
        total_bruto=float(df["valor_bruto"].sum()) if not df.empty else 0.0,
        total_taxa=float(df["valor_taxa"].sum()) if not df.empty else 0.0,
        total_liquido=float(df["valor_liquido"].sum()) if not df.empty else 0.0,
    )
