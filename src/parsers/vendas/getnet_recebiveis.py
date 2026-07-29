# -*- coding: utf-8 -*-
"""
Leitor do relatório Getnet "Recebíveis Completos".

Formato esperado:
- Arquivo .xls binário (D0CF11E0)
- Três abas: 'Resumo', 'Sintético por Grupo', 'Detalhado'
- Este leitor consome APENAS a aba 'Detalhado'
- Cabeçalho na linha 8 (índice 7)
- 26 colunas
- A aba mistura 4 tipos de linha (coluna [5] "TIPO DE LANÇAMENTO"):
  - "Saldo Anterior"       -> técnica, valor 0 -> IGNORAR
  - "Vendas"               -> venda individual -> ENTRA COMO VENDA
  - "Pagamento Realizado"  -> contra-partida negativa que fecha o dia -> ENTRA COMO REPASSE
  - "Cancelamento/Chargeback" -> ENTRA COMO CANCELAMENTO

Contexto MVP-A:
- KING está consolidada embaixo do CNPJ da PISA (05.953.543/0001-47)
- Separação por empresa vem do lado do Sankhya, não daqui
- Nesta fase entregamos DUAS visões:
  - df_vendas: só as linhas de venda + cancelamento
  - df_repasses: só as linhas de pagamento realizado por dia/bandeira
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd
import xlrd


NOME_ABA_DETALHADO = "Detalhado"

# Colunas críticas da aba Detalhado (26 colunas)
COL_EC_CENTRALIZADOR = 0
COL_ESTABELECIMENTO = 1
COL_CNPJ = 2
COL_DATA_VENCIMENTO = 3
COL_BANDEIRA_MODALIDADE = 4
COL_TIPO_LANCAMENTO = 5          # "Vendas" | "Saldo Anterior" | "Pagamento Realizado" | "Cancelamento/Chargeback"
COL_LANCAMENTO = 6               # detalhe: "Venda Crédito A Vista", etc
COL_VALOR_LIQUIDO = 7
COL_VALOR_LIQUIDADO = 8
COL_NUMERO_CARTAO = 9
COL_AUTORIZACAO = 10
COL_NSU = 11
COL_TERMINAL = 12
COL_DATA_VENDA = 13
COL_HORA_VENDA = 14
COL_VALOR_VENDA = 15             # valor bruto da venda
COL_PARCELAS_TXT = 16            # "1 de 1", "3 de 3"
COL_VALOR_PARCELA = 17
COL_DESCONTOS = 18               # negativo
COL_VALOR_LIQUIDO_PARCELA = 19


# Colunas de saída — VENDAS
COLUNAS_VENDAS = [
    "adquirente",
    "estabelecimento",
    "ec_centralizador",
    "cnpj_estabelecimento",
    "data_venda",
    "data_prev_pagamento",       # aqui = DATA_VENCIMENTO da parcela
    "hora_venda",
    "valor_venda_bruto",
    "valor_parcela_bruto",
    "valor_taxa",
    "valor_liquido",
    "bandeira",
    "modalidade",                # "credito_avista" | "credito_parcelado" | "debito" | "outro"
    "parcela_atual",
    "parcelas_total",
    "autorizacao",
    "nsu",
    "numero_cartao_mascarado",
    "terminal",
    "lancamento_original",
    "tipo_registro",             # "venda" | "cancelamento"
]

# Colunas de saída — REPASSES (Pagamento Realizado)
COLUNAS_REPASSES = [
    "adquirente",
    "estabelecimento",
    "ec_centralizador",
    "cnpj_estabelecimento",
    "data_pagamento",
    "bandeira",
    "modalidade",
    "valor_repasse",             # positivo (invertemos o sinal)
]


# ==============================================================================
# ABERTURA
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
        f"Getnet Recebíveis Completos deve vir como .xls binário. "
        f"Byte signature recebido: {dados[:8]!r}"
    )


# ==============================================================================
# VALIDAÇÃO
# ==============================================================================

MARCADORES_CABECALHO_GETNET = [
    "ec centralizador",
    "estabelecimento comercial",
    "cpf / cnpj",
    "data de vencimento",
    "bandeira / modalidade",
    "tipo de lançamento",
    "autorização",
]


def eh_getnet_recebiveis(dados: bytes) -> bool:
    """Detecta se é o Getnet Recebíveis Completos."""
    try:
        wb = _abrir_workbook(dados)
    except Exception:
        return False
    # Aba 'Detalhado' precisa existir
    if NOME_ABA_DETALHADO not in wb.sheet_names():
        return False
    sh = wb.sheet_by_name(NOME_ABA_DETALHADO)
    if sh.nrows < 10 or sh.ncols < 20:
        return False
    idx = _achar_cabecalho(sh)
    return idx is not None


def _achar_cabecalho(sh) -> Optional[int]:
    """Localiza a linha de cabeçalho procurando pelos marcadores."""
    limite = min(15, sh.nrows)
    for r in range(limite):
        vals = [str(sh.cell_value(r, c)).strip().lower() for c in range(min(10, sh.ncols))]
        hits = 0
        for m in MARCADORES_CABECALHO_GETNET:
            if any(m in v for v in vals):
                hits += 1
        if hits >= 5:
            return r
    return None


# ==============================================================================
# CONVERSÕES
# ==============================================================================

def _to_int(v) -> Optional[int]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        try:
            s = str(v).strip()
            return int(s) if s else None
        except Exception:
            return None


def _to_float(v) -> float:
    if v is None or v == "" or v == "-":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        s = str(v).strip()
        s = re.sub(r"[^\d,\.\-]", "", s).replace(",", ".")
        try:
            return float(s) if s else 0.0
        except ValueError:
            return 0.0


def _to_date(v, datemode: int) -> Optional[date]:
    if v is None or v == "" or v == "-":
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s or s == "-":
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
# PARSER "X de Y"
# ==============================================================================

_RE_PARCELAS = re.compile(r"(\d+)\s*de\s*(\d+)", re.IGNORECASE)


def _parsear_parcelas(txt: str) -> tuple[int, int]:
    """Extrai (atual, total) da string 'X de Y'. Default (1, 1)."""
    if not txt or txt == "-":
        return (1, 1)
    m = _RE_PARCELAS.search(str(txt))
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (1, 1)


# ==============================================================================
# CLASSIFICADORES
# ==============================================================================

def _extrair_bandeira_modalidade(txt: str) -> tuple[str, str]:
    """
    Getnet combina em uma coluna só, ex: 'Elo Crédito', 'Visa Débito', 'Mastercard Crédito'.
    Retorna (bandeira, modalidade_codigo).
    """
    if not txt:
        return ("", "outro")
    t = txt.strip()
    tl = t.lower()

    if "débito" in tl or "debito" in tl:
        modalidade = "debito"
    elif "crédito" in tl or "credito" in tl:
        modalidade = "credito"     # será refinada abaixo com o lançamento
    else:
        modalidade = "outro"

    # Bandeira é a primeira palavra
    bandeira = t.split()[0] if t.split() else ""
    return (bandeira, modalidade)


def _refinar_modalidade(modalidade_base: str, lancamento: str) -> str:
    """Refina crédito -> à vista vs parcelado usando o campo LANÇAMENTO."""
    if modalidade_base == "debito":
        return "debito"
    lanc = (lancamento or "").lower()
    if "parcel" in lanc:
        return "credito_parcelado"
    if "vista" in lanc or "a vista" in lanc:
        return "credito_avista"
    if modalidade_base == "credito":
        return "credito_avista"    # fallback
    return "outro"


# ==============================================================================
# FUNÇÃO PRINCIPAL
# ==============================================================================

@dataclass
class ResultadoLeituraGetnet:
    df_vendas: pd.DataFrame
    df_repasses: pd.DataFrame
    total_vendas: int
    total_cancelamentos: int
    total_repasses: int
    linhas_saldo_anterior_ignoradas: int
    linhas_vazias_ignoradas: int
    estabelecimentos: list
    total_bruto_vendas: float
    total_liquido_vendas: float
    total_taxa_vendas: float
    total_repassado: float


def ler(dados: bytes) -> ResultadoLeituraGetnet:
    """Lê o Getnet Recebíveis Completos, retornando visões separadas de vendas e repasses."""
    if not eh_getnet_recebiveis(dados):
        raise ValueError("Arquivo não é o Getnet Recebíveis Completos (aba 'Detalhado' inválida).")

    wb = _abrir_workbook(dados)
    sh = wb.sheet_by_name(NOME_ABA_DETALHADO)
    datemode = wb.datemode

    idx_cab = _achar_cabecalho(sh)
    if idx_cab is None:
        raise ValueError("Cabeçalho Getnet não localizado na aba Detalhado.")

    linhas_vendas = []
    linhas_repasses = []
    n_saldo = 0
    n_vazias = 0
    n_cancel = 0
    estabs_set = set()

    for r in range(idx_cab + 1, sh.nrows):
        row = sh.row_values(r)

        if not any(str(v).strip() for v in row):
            n_vazias += 1
            continue

        tipo = str(row[COL_TIPO_LANCAMENTO]).strip()
        lanc = str(row[COL_LANCAMENTO]).strip()

        if not tipo:
            n_vazias += 1
            continue

        estab = str(row[COL_ESTABELECIMENTO]).strip()
        if estab:
            estabs_set.add(estab)

        cnpj = str(row[COL_CNPJ]).strip()
        ec_centr = str(row[COL_EC_CENTRALIZADOR]).strip()
        bandeira_txt = str(row[COL_BANDEIRA_MODALIDADE]).strip()
        bandeira, modalidade_base = _extrair_bandeira_modalidade(bandeira_txt)

        if tipo == "Saldo Anterior":
            n_saldo += 1
            continue

        if tipo == "Pagamento Realizado":
            # É o repasse do dia (valor negativo no arquivo -> invertemos)
            linhas_repasses.append({
                "adquirente": "getnet",
                "estabelecimento": estab,
                "ec_centralizador": ec_centr,
                "cnpj_estabelecimento": cnpj,
                "data_pagamento": _to_date(row[COL_DATA_VENCIMENTO], datemode),
                "bandeira": bandeira,
                "modalidade": modalidade_base,
                "valor_repasse": abs(_to_float(row[COL_VALOR_LIQUIDO])),
            })
            continue

        if tipo in ("Vendas", "Cancelamento/Chargeback"):
            tipo_reg = "venda" if tipo == "Vendas" else "cancelamento"
            if tipo_reg == "cancelamento":
                n_cancel += 1

            parc_atual, parc_total = _parsear_parcelas(str(row[COL_PARCELAS_TXT]))
            modalidade = _refinar_modalidade(modalidade_base, lanc)

            valor_bruto_parc = _to_float(row[COL_VALOR_PARCELA])
            desconto = _to_float(row[COL_DESCONTOS])       # já é negativo
            valor_liq = _to_float(row[COL_VALOR_LIQUIDO_PARCELA])

            linhas_vendas.append({
                "adquirente": "getnet",
                "estabelecimento": estab,
                "ec_centralizador": ec_centr,
                "cnpj_estabelecimento": cnpj,
                "data_venda": _to_date(row[COL_DATA_VENDA], datemode),
                "data_prev_pagamento": _to_date(row[COL_DATA_VENCIMENTO], datemode),
                "hora_venda": str(row[COL_HORA_VENDA]).strip(),
                "valor_venda_bruto": _to_float(row[COL_VALOR_VENDA]),
                "valor_parcela_bruto": valor_bruto_parc,
                "valor_taxa": abs(desconto),
                "valor_liquido": valor_liq,
                "bandeira": bandeira,
                "modalidade": modalidade,
                "parcela_atual": parc_atual,
                "parcelas_total": parc_total,
                "autorizacao": str(row[COL_AUTORIZACAO]).strip(),
                "nsu": str(row[COL_NSU]).strip(),
                "numero_cartao_mascarado": str(row[COL_NUMERO_CARTAO]).strip(),
                "terminal": str(row[COL_TERMINAL]).strip(),
                "lancamento_original": lanc,
                "tipo_registro": tipo_reg,
            })
            continue

        # Tipo desconhecido -> ignorado, mas contamos
        n_vazias += 1

    df_vendas = pd.DataFrame(linhas_vendas, columns=COLUNAS_VENDAS)
    df_repasses = pd.DataFrame(linhas_repasses, columns=COLUNAS_REPASSES)

    return ResultadoLeituraGetnet(
        df_vendas=df_vendas,
        df_repasses=df_repasses,
        total_vendas=int((df_vendas["tipo_registro"] == "venda").sum()) if not df_vendas.empty else 0,
        total_cancelamentos=n_cancel,
        total_repasses=len(df_repasses),
        linhas_saldo_anterior_ignoradas=n_saldo,
        linhas_vazias_ignoradas=n_vazias,
        estabelecimentos=sorted(estabs_set),
        total_bruto_vendas=float(df_vendas["valor_parcela_bruto"].sum()) if not df_vendas.empty else 0.0,
        total_liquido_vendas=float(df_vendas["valor_liquido"].sum()) if not df_vendas.empty else 0.0,
        total_taxa_vendas=float(df_vendas["valor_taxa"].sum()) if not df_vendas.empty else 0.0,
        total_repassado=float(df_repasses["valor_repasse"].sum()) if not df_repasses.empty else 0.0,
    )
