# -*- coding: utf-8 -*-
"""
Leitor do relatório "Cabeçalho da Nota" do Sankhya — Fase 4 · MVP-A · Entrega 2.

Este relatório traz uma linha por NOTA FISCAL emitida (170 linhas no fechamento
de 23-28/07/2026). É COMPLEMENTAR ao "Financeiro Sankhya" (Movimento Financeiro),
que já traz uma linha por título/desdobramento (271 títulos no mesmo período).

Estrutura do arquivo:
    - .xls binário CDFV2 (mesmo formato dos outros do Sankhya)
    - Linha 0: "Cabeçalho da Nota"
    - Linha 1: "Emissão:..." "Total de registros:N" "Usuário: ..."
    - Linha 2: cabeçalho das colunas
    - Linha 3+: dados

Colunas relevantes (do arquivo real da Débora):
    Nro Pedido BDTI, Pendente, CNPJ / Parceiro, Nro. Único, Nro. Nota,
    Status NF-e, Nome Parceiro (Parceiro), Descrição (Tipo de Negociação),
    Dt. Neg., Vlr. Nota, Dt. do Movimento, Dt.Hora da confirmação, ...

Uso no motor:
    - Enriquece cada título do Financeiro (via JOIN por Nro. Nota) com:
        * cabecalho_dt_negociacao   — data real da venda
        * cabecalho_vlr_nota_total  — valor total da nota fiscal
        * cabecalho_descricao_tipo_negociacao — descrição rica com bandeira/parcelas

Regra importante: o Cabeçalho NÃO tem adiantamentos (só notas fiscais formais).
Adiantamentos como o RUNTIME (TOP OP 1654) aparecem SÓ no Financeiro. O JOIN
retorna None pra essas linhas, sinalizando "sem cabeçalho" — comportamento
esperado, não é erro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd
import xlrd


COLUNAS_SAIDA = [
    "empresa",
    "cnpj_parceiro",
    "nome_parceiro",
    "nro_unico",
    "nro_nota",
    "status_nfe",
    "dt_negociacao",
    "vlr_nota_total",
    "descricao_tipo_negociacao",
    "dt_movimento",
    "dt_hora_confirmacao",
    "pendente",
    "nro_pedido_bdti",
    "origem_integracao",
    "nro_nfse",
]


def _abrir_xls(dados: bytes):
    """Verifica byte signature CDFV2 e abre com xlrd."""
    head = dados[:8]
    if not head.startswith(b"\xD0\xCF\x11\xE0"):
        raise ValueError(f"Cabeçalho da Nota deve vir como .xls binário (CDFV2). Byte signature: {head!r}")
    return xlrd.open_workbook(file_contents=dados)


def _to_float(v) -> Optional[float]:
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        try:
            s = str(v).replace(".", "").replace(",", ".")
            return float(s) if s else None
        except (ValueError, TypeError):
            return None


def _to_int(v, default=None):
    if v is None or v == "" or v == "-":
        return default
    try:
        return int(float(v))
    except (ValueError, TypeError):
        try:
            s = str(v).strip()
            return int(s) if s.isdigit() else default
        except Exception:
            return default


def _to_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _to_date(v, datemode: int) -> Optional[date]:
    if v is None or v == "" or v == "-":
        return None
    if isinstance(v, str):
        s = v.strip().split()[0] if v.strip() else ""
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
# DETECÇÃO
# ==============================================================================

_MARCADORES_CABECALHO = [
    "nro. único", "nro. nota", "dt. neg.", "vlr. nota",
    "descrição (tipo de negociação)", "nome parceiro",
]

# Marcadores do Financeiro Sankhya (pra ter certeza que NÃO é ele)
_MARCADORES_FINANCEIRO = [
    "vlr do desdobramento", "tipo operação baixa", "dt. vencimento",
    "descrição (tipo de título)",
]


def _localizar_cabecalho_de_colunas(sh, limite: int = 8) -> Optional[int]:
    """Retorna o índice da linha que contém os nomes das colunas."""
    for r in range(min(limite, sh.nrows)):
        vals = [str(sh.cell_value(r, c)).strip().lower() for c in range(min(30, sh.ncols))]
        matches = 0
        for v in vals:
            if len(v) > 80:
                continue
            for kw in _MARCADORES_CABECALHO:
                if kw in v:
                    matches += 1
                    break
        if matches >= 3:
            return r
    return None


def eh_cabecalho_nota(dados: bytes) -> bool:
    """Detecta se o arquivo é o relatório 'Cabeçalho da Nota' do Sankhya.

    Regras (todas precisam bater):
      1. Byte signature CDFV2 (.xls binário)
      2. Linha 0 ou 1 contém "cabeçalho da nota" OU linha de cabeçalho tem
         pelo menos 3 marcadores específicos do Cabeçalho
      3. NÃO tem marcadores exclusivos do Financeiro Sankhya
         (pra não confundir com aquele)
    """
    try:
        wb = _abrir_xls(dados)
    except Exception:
        return False
    if wb.nsheets < 1:
        return False
    sh = wb.sheet_by_index(0)

    # Checa "Cabeçalho da Nota" nas primeiras 2 linhas
    tem_titulo = False
    for r in range(min(2, sh.nrows)):
        for c in range(min(5, sh.ncols)):
            v = str(sh.cell_value(r, c)).strip().lower()
            if "cabeçalho da nota" in v or "cabecalho da nota" in v:
                tem_titulo = True
                break
        if tem_titulo:
            break

    # Localiza a linha de cabeçalho de colunas
    idx_cab = _localizar_cabecalho_de_colunas(sh)
    if idx_cab is None:
        return False

    # Verifica que NÃO tem marcadores do Financeiro (nas primeiras 30 colunas)
    vals_cab = [str(sh.cell_value(idx_cab, c)).strip().lower() for c in range(min(30, sh.ncols))]
    for v in vals_cab:
        for kw in _MARCADORES_FINANCEIRO:
            if kw in v:
                # É provavelmente o Financeiro, não o Cabeçalho
                return False

    return tem_titulo or idx_cab is not None


def _mapa_colunas(sh, idx_cab: int) -> dict:
    header = [str(sh.cell_value(idx_cab, c)).strip().lower() for c in range(sh.ncols)]
    return {h: i for i, h in enumerate(header) if h}


def _col(mapa: dict, *aliases: str) -> Optional[int]:
    """Busca coluna por alias exato primeiro, depois por match parcial."""
    for alias in aliases:
        a = alias.lower()
        if a in mapa:
            return mapa[a]
    for alias in aliases:
        a = alias.lower()
        for nome, idx in mapa.items():
            if a in nome:
                return idx
    return None


def _get(row, col_idx, default=""):
    if col_idx is None:
        return default
    v = row[col_idx]
    return v if v not in (None, "") else default


# ==============================================================================
# LEITURA
# ==============================================================================

@dataclass
class ResultadoLeituraCabecalho:
    df: pd.DataFrame
    total_notas: int
    linhas_ignoradas: int
    empresas: list
    parceiros_unicos: int
    total_valor: float
    periodo_inicio: Optional[date]
    periodo_fim: Optional[date]


def ler(dados: bytes) -> ResultadoLeituraCabecalho:
    """Lê o arquivo e retorna DataFrame com uma linha por nota fiscal.

    O DataFrame retornado é feito pra ser JOINADO no classificador Sankhya
    via `Nro. Nota` (que é o mesmo valor no Financeiro Sankhya como `nro_nota`).
    """
    if not eh_cabecalho_nota(dados):
        raise ValueError("Arquivo não é o Cabeçalho da Nota do Sankhya.")

    wb = _abrir_xls(dados)
    sh = wb.sheet_by_index(0)
    datemode = wb.datemode
    idx_cab = _localizar_cabecalho_de_colunas(sh)
    if idx_cab is None:
        raise ValueError("Não achei a linha de cabeçalho no Cabeçalho da Nota.")

    mapa = _mapa_colunas(sh, idx_cab)

    col_empresa = _col(mapa, "empresa")
    col_cnpj = _col(mapa, "cnpj / parceiro", "cnpj/parceiro", "cnpj")
    col_nome = _col(mapa, "nome parceiro (parceiro)", "nome parceiro", "parceiro")
    col_nro_unico = _col(mapa, "nro. único", "nro unico", "nro. unico")
    col_nro_nota = _col(mapa, "nro. nota", "nro nota", "número da nota")
    col_status = _col(mapa, "status nf-e", "status nfe", "status")
    col_dt_neg = _col(mapa, "dt. neg.", "dt neg", "data de negociação", "data neg")
    col_vlr_nota = _col(mapa, "vlr. nota", "valor da nota", "vlr nota", "total")
    col_desc_neg = _col(mapa, "descrição (tipo de negociação)", "descricao tipo de negociacao",
                        "tipo de negociação")
    col_dt_mov = _col(mapa, "dt. do movimento", "data do movimento", "dt movimento")
    col_dt_conf = _col(mapa, "dt.hora da confirmação", "dt confirmação", "data hora confirmacao")
    col_pendente = _col(mapa, "pendente")
    col_pedido_bdti = _col(mapa, "nro pedido bdti", "nro. pedido bdti")
    col_origem_int = _col(mapa, "origem integração", "origem integracao")
    col_nfse = _col(mapa, "nro. nfs-e", "nro nfse", "nfs-e")

    linhas = []
    ignoradas = 0
    empresas = set()
    parceiros = set()
    datas_neg = []
    total_valor = 0.0

    for r in range(idx_cab + 1, sh.nrows):
        row = sh.row_values(r)
        if not any(str(v).strip() for v in row):
            ignoradas += 1
            continue

        # Linha válida = tem Nro. Único E (Nro. Nota OU Vlr. Nota)
        nro_unico = _to_int(_get(row, col_nro_unico))
        if not nro_unico:
            ignoradas += 1
            continue

        nro_nota = _to_int(_get(row, col_nro_nota))
        vlr_nota = _to_float(_get(row, col_vlr_nota))

        if not nro_nota and not vlr_nota:
            ignoradas += 1
            continue

        dt_neg = _to_date(_get(row, col_dt_neg), datemode)

        empresa = _to_str(_get(row, col_empresa))
        if empresa:
            empresas.add(empresa)

        cnpj = _to_str(_get(row, col_cnpj))
        nome = _to_str(_get(row, col_nome))
        if nome:
            parceiros.add(nome)

        if vlr_nota:
            total_valor += vlr_nota
        if dt_neg:
            datas_neg.append(dt_neg)

        linhas.append({
            "empresa": empresa,
            "cnpj_parceiro": cnpj,
            "nome_parceiro": nome,
            "nro_unico": nro_unico,
            "nro_nota": nro_nota,
            "status_nfe": _to_str(_get(row, col_status)),
            "dt_negociacao": dt_neg,
            "vlr_nota_total": vlr_nota,
            "descricao_tipo_negociacao": _to_str(_get(row, col_desc_neg)),
            "dt_movimento": _to_date(_get(row, col_dt_mov), datemode),
            "dt_hora_confirmacao": _to_date(_get(row, col_dt_conf), datemode),
            "pendente": _to_str(_get(row, col_pendente)),
            "nro_pedido_bdti": _to_str(_get(row, col_pedido_bdti)),
            "origem_integracao": _to_str(_get(row, col_origem_int)),
            "nro_nfse": _to_str(_get(row, col_nfse)),
        })

    df = pd.DataFrame(linhas, columns=COLUNAS_SAIDA)

    return ResultadoLeituraCabecalho(
        df=df,
        total_notas=len(linhas),
        linhas_ignoradas=ignoradas,
        empresas=sorted(empresas),
        parceiros_unicos=len(parceiros),
        total_valor=total_valor,
        periodo_inicio=min(datas_neg) if datas_neg else None,
        periodo_fim=max(datas_neg) if datas_neg else None,
    )
