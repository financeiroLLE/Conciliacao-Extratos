# -*- coding: utf-8 -*-
"""
Leitor do relatório Financeiro do Sankhya (MVP-A Conciliação de Vendas).

Formato esperado:
- Arquivo .xls binário (D0CF11E0) — Sankhya exporta xls binário mesmo, não xlsx disfarçado
- Uma única aba
- Linha 1 (índice 0): título "Financeiro"
- Linha 2 (índice 1): metadados de emissão/usuário/total
- Linha 3 (índice 2): cabeçalho (92 colunas)
- Linha 4+ (índice 3+): dados

Retorna DataFrame com colunas normalizadas para o motor consumir.

Empresas conhecidas no MVP-A:
- 1 -> PISA
- 2 -> KING
- (TRIO fora do escopo de cartão nesta fase)

TOPs de Baixa relevantes (coluna [20] "Tipo Operação Baixa"):
- 0    -> aguardando captura (sem baixa ainda)
- 1722 -> CARTAO-Recebimento com cartão (Normal)
- 1731 -> RECEITA COMP VENDA x CRÉDITOS (Compensada)
- 1732 -> RECEITA COMP VENDA x ADIANTAMENTO C.CREDITO (Compensada)
- 1707 -> Compensação Despesa
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd
import xlrd


# ==============================================================================
# CONSTANTES
# ==============================================================================

# Índices das colunas críticas no cabeçalho de 92 colunas
COL_EMPRESA = 1
COL_PARCEIRO_COD = 2
COL_CNPJ = 3
COL_NOME_PARCEIRO = 4
COL_NRO_UNICO = 5
COL_NRO_NOTA = 6
COL_DESDOB = 7
COL_DT_NEGOCIACAO = 8
COL_DT_VENCIMENTO = 9
COL_DATA_BAIXA = 10
COL_DT_CONCILIACAO = 11
COL_VLR_DESDOBRAMENTO = 13
COL_VLR_BAIXA = 16
COL_VLR_LIQUIDO = 17
COL_TAXA_ADM = 18
COL_TOP_BAIXA = 20             # "Tipo Operação Baixa"
COL_TIPO_TITULO = 21
COL_TIPO_TITULO_DESC = 22
COL_HISTORICO = 23
COL_CONTA_BANC_DESC = 27
COL_CONTA_BANC = 42
COL_TOP_OPERACAO = 66          # "Tipo Operação" (não é o de baixa)
COL_TOP_OPERACAO_DESC = 63
COL_RECEITA_DESPESA = 67
COL_TOP_BAIXA_DESC = 76

# Mapa Empresa -> Nome
MAP_EMPRESA = {
    1: "PISA",
    2: "KING",
}

# TOPs de Baixa agrupados por natureza
TOP_BAIXA_NORMAL = {0, 1722}          # 0 = ainda em aberto; 1722 = já baixado normal
TOP_BAIXA_COMPENSADA = {1731, 1732, 1716}
TOP_BAIXA_DEVOLUCAO = set()            # a definir com dados reais
TOP_BAIXA_DESPESA = {1707}

# Colunas de saída padronizadas
COLUNAS_SAIDA = [
    "nro_unico",
    "nro_nota",
    "empresa_cod",
    "empresa_nome",
    "parceiro_cod",
    "cnpj",
    "nome_parceiro",
    "dt_negociacao",
    "dt_vencimento",
    "data_baixa",
    "dt_conciliacao",
    "vlr_desdobramento",
    "vlr_baixa",
    "valor_liquido",
    "taxa_administradora",
    "top_baixa",
    "top_baixa_desc",
    "grupo_top_baixa",           # "normal" | "compensada" | "devolucao" | "despesa" | "outro"
    "tipo_titulo",
    "tipo_titulo_desc",
    "historico",
    "conta_bancaria_desc",
    "tipo_operacao",
    "tipo_operacao_desc",
    "receita_despesa",
    "adquirente_inferida",       # "cielo" | "getnet" | "pagbank" | "pagseguro" | None
    "modalidade_inferida",       # "debito" | "credito_avista" | "credito_parcelado" | None
    "esta_baixado",
    "esta_conciliado",
]


# ==============================================================================
# DETECÇÃO E ABERTURA
# ==============================================================================

def _detectar_signature(dados: bytes) -> str:
    """Retorna 'xls' (binário OLE), 'xlsx' (zip), ou 'outro'."""
    head = dados[:8]
    if head.startswith(b"\xD0\xCF\x11\xE0"):
        return "xls"
    if head.startswith(b"PK\x03\x04"):
        return "xlsx"
    return "outro"


def _abrir_workbook(dados: bytes):
    """Abre workbook usando o engine correto conforme o byte signature."""
    sig = _detectar_signature(dados)
    if sig == "xls":
        return xlrd.open_workbook(file_contents=dados)
    if sig == "xlsx":
        raise NotImplementedError(
            "Financeiro do Sankhya deve vir como .xls binário. "
            "Recebido: .xlsx (não suportado neste leitor)."
        )
    raise ValueError(f"Formato desconhecido; byte signature inicial: {dados[:8]!r}")


# ==============================================================================
# VALIDAÇÃO DE CABEÇALHO
# ==============================================================================

# Palavras-chave que o cabeçalho DEVE conter para o arquivo ser reconhecido como Financeiro do Sankhya.
# Usar substring case-insensitive nas 5 primeiras colunas.
MARCADORES_CABECALHO = [
    "código do acordo",
    "empresa",
    "parceiro",
    "cnpj",
    "nro único",
]


def eh_financeiro_sankhya(dados: bytes) -> bool:
    """Detecta se o arquivo é o Financeiro do Sankhya, olhando apenas conteúdo (não nome)."""
    try:
        wb = _abrir_workbook(dados)
    except Exception:
        return False
    if wb.nsheets < 1:
        return False
    sh = wb.sheet_by_index(0)
    if sh.nrows < 3 or sh.ncols < 90:
        return False
    # Linha 1 costuma trazer o título "Financeiro" na coluna 0
    l0 = str(sh.cell_value(0, 0)).strip().lower()
    if "financeiro" not in l0:
        return False
    # Cabeçalho na linha 3 (índice 2); confere primeiros marcadores
    header = [str(sh.cell_value(2, c)).strip().lower() for c in range(min(5, sh.ncols))]
    hits = sum(1 for m in MARCADORES_CABECALHO if any(m in h for h in header))
    return hits >= 4


# ==============================================================================
# HELPERS DE CONVERSÃO
# ==============================================================================

def _to_int(v) -> Optional[int]:
    """Converte float 'inteiro-like' para int (Sankhya exporta tudo como float)."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
        return int(f)
    except (ValueError, TypeError):
        return None


def _to_float(v) -> float:
    """Converte para float, tratando '' e None como 0.0."""
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _to_date(v, datemode: int) -> Optional[date]:
    """Converte serial de data xlrd para date. Retorna None se vazio/inválido."""
    if v is None or v == "":
        return None
    if isinstance(v, str):
        # Alguns campos podem vir como string dd/mm/yyyy
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


def _norm_cnpj(v) -> str:
    """Normaliza CNPJ/CPF removendo tudo que não é dígito."""
    if v is None:
        return ""
    s = str(v)
    return re.sub(r"\D", "", s)


def _grupo_top_baixa(top: Optional[int]) -> str:
    if top is None:
        return "outro"
    if top in TOP_BAIXA_NORMAL:
        return "normal"
    if top in TOP_BAIXA_COMPENSADA:
        return "compensada"
    if top in TOP_BAIXA_DEVOLUCAO:
        return "devolucao"
    if top in TOP_BAIXA_DESPESA:
        return "despesa"
    return "outro"


# ==============================================================================
# INFERÊNCIA DE ADQUIRENTE / MODALIDADE
# ==============================================================================

# Padrões para detectar adquirente pela descrição do Tipo de Título
# (só usados como pista; a fonte oficial é o cruzamento com o repasse depois)
_RE_GETNET = re.compile(r"\bgetnet\b", re.IGNORECASE)
_RE_CIELO = re.compile(r"\bcielo\b", re.IGNORECASE)
_RE_PAGBANK = re.compile(r"\bpagbank\b|\bpag\s*bank\b", re.IGNORECASE)
_RE_PAGSEGURO = re.compile(r"\bpag\s*seguro\b|\bpagseguro\b|\bps\b", re.IGNORECASE)

_RE_PARCELADO = re.compile(r"\bparc\b|\bcred\s*parc\b|\btef\s*[2-9]\d*x\b", re.IGNORECASE)
_RE_DEBITO = re.compile(r"\bdebito\b|\bdébito\b|\bdeb\b", re.IGNORECASE)
_RE_AVISTA = re.compile(r"\ba\s*vista\b|\bà\s*vista\b|\bcreditto\s*a\s*vista\b|\btef\s*1x\b", re.IGNORECASE)


def _inferir_adquirente(desc: str) -> Optional[str]:
    if not desc:
        return None
    if _RE_GETNET.search(desc):
        return "getnet"
    if _RE_CIELO.search(desc):
        return "cielo"
    if _RE_PAGBANK.search(desc):
        return "pagbank"
    if _RE_PAGSEGURO.search(desc):
        return "pagseguro"
    # Descrições comuns terminam em " PS " (PagSeguro)
    if re.search(r"\bps\b", desc, re.IGNORECASE):
        return "pagseguro"
    return None


def _inferir_modalidade(desc: str) -> Optional[str]:
    if not desc:
        return None
    if _RE_DEBITO.search(desc):
        return "debito"
    if _RE_PARCELADO.search(desc):
        return "credito_parcelado"
    if _RE_AVISTA.search(desc) or re.search(r"\btef\s*1x\b|\bcreditto\s*a\s*vista\b", desc, re.IGNORECASE):
        return "credito_avista"
    return None


# ==============================================================================
# FUNÇÃO PRINCIPAL
# ==============================================================================

@dataclass
class ResultadoLeitura:
    df: pd.DataFrame
    total_linhas: int
    linhas_ignoradas: int
    empresas_encontradas: list
    resumo_top_baixa: dict


def ler(dados: bytes) -> ResultadoLeitura:
    """
    Lê o Financeiro do Sankhya e retorna DataFrame normalizado + resumo.

    Args:
        dados: bytes do arquivo .xls

    Raises:
        ValueError: se não for reconhecido como Financeiro do Sankhya
    """
    if not eh_financeiro_sankhya(dados):
        raise ValueError("Arquivo não é o Financeiro do Sankhya (cabeçalho não bate).")

    wb = _abrir_workbook(dados)
    sh = wb.sheet_by_index(0)
    datemode = wb.datemode

    linhas = []
    ignoradas = 0
    empresas_set = set()
    resumo_top = {}

    for r in range(3, sh.nrows):
        row = sh.row_values(r)

        # Linha totalmente vazia -> ignora
        if not any(str(v).strip() for v in row):
            ignoradas += 1
            continue

        empresa_cod = _to_int(row[COL_EMPRESA])
        if empresa_cod is None:
            ignoradas += 1
            continue

        empresas_set.add(empresa_cod)

        nro_unico = _to_int(row[COL_NRO_UNICO])
        nro_nota = _to_int(row[COL_NRO_NOTA])
        top_baixa = _to_int(row[COL_TOP_BAIXA])
        top_baixa_desc = str(row[COL_TOP_BAIXA_DESC]).strip()
        tipo_titulo = _to_int(row[COL_TIPO_TITULO])
        tipo_titulo_desc = str(row[COL_TIPO_TITULO_DESC]).strip()

        data_baixa = _to_date(row[COL_DATA_BAIXA], datemode)
        dt_conciliacao = _to_date(row[COL_DT_CONCILIACAO], datemode)

        adq = _inferir_adquirente(tipo_titulo_desc)
        mod = _inferir_modalidade(tipo_titulo_desc)
        grp = _grupo_top_baixa(top_baixa)

        # Contagem por top_baixa para o resumo
        chave_resumo = (top_baixa, top_baixa_desc, grp)
        resumo_top[chave_resumo] = resumo_top.get(chave_resumo, 0) + 1

        linhas.append({
            "nro_unico": nro_unico,
            "nro_nota": nro_nota,
            "empresa_cod": empresa_cod,
            "empresa_nome": MAP_EMPRESA.get(empresa_cod, f"EMP{empresa_cod}"),
            "parceiro_cod": _to_int(row[COL_PARCEIRO_COD]),
            "cnpj": _norm_cnpj(row[COL_CNPJ]),
            "nome_parceiro": str(row[COL_NOME_PARCEIRO]).strip(),
            "dt_negociacao": _to_date(row[COL_DT_NEGOCIACAO], datemode),
            "dt_vencimento": _to_date(row[COL_DT_VENCIMENTO], datemode),
            "data_baixa": data_baixa,
            "dt_conciliacao": dt_conciliacao,
            "vlr_desdobramento": _to_float(row[COL_VLR_DESDOBRAMENTO]),
            "vlr_baixa": _to_float(row[COL_VLR_BAIXA]),
            "valor_liquido": _to_float(row[COL_VLR_LIQUIDO]),
            "taxa_administradora": _to_float(row[COL_TAXA_ADM]),
            "top_baixa": top_baixa,
            "top_baixa_desc": top_baixa_desc,
            "grupo_top_baixa": grp,
            "tipo_titulo": tipo_titulo,
            "tipo_titulo_desc": tipo_titulo_desc,
            "historico": str(row[COL_HISTORICO]).strip(),
            "conta_bancaria_desc": str(row[COL_CONTA_BANC_DESC]).strip(),
            "tipo_operacao": _to_int(row[COL_TOP_OPERACAO]),
            "tipo_operacao_desc": str(row[COL_TOP_OPERACAO_DESC]).strip(),
            "receita_despesa": str(row[COL_RECEITA_DESPESA]).strip(),
            "adquirente_inferida": adq,
            "modalidade_inferida": mod,
            "esta_baixado": data_baixa is not None,
            "esta_conciliado": dt_conciliacao is not None,
        })

    df = pd.DataFrame(linhas, columns=COLUNAS_SAIDA)

    return ResultadoLeitura(
        df=df,
        total_linhas=len(linhas),
        linhas_ignoradas=ignoradas,
        empresas_encontradas=sorted(empresas_set),
        resumo_top_baixa=resumo_top,
    )
