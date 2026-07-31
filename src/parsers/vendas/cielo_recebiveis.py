# -*- coding: utf-8 -*-
"""
Leitor Cielo — suporta AMBOS os formatos:

  Formato ANTIGO ("Recebíveis Detalhado - Lançamentos"):
    - 59 colunas, cabeçalho L9
    - Uma linha por parcela

  Formato NOVO ("Detalhado de vendas Cielo"):
    - 44 colunas, cabeçalho L9
    - Uma linha por venda (parcelas expandidas virtualmente pelo leitor)
    - Traz VALOR BRUTO TOTAL da venda — dividimos por N parcelas p/ bater com Sankhya
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import xlrd


def _add_meses(dt: date, n: int) -> date:
    """Adiciona N meses mantendo o mesmo dia (com clamp para último dia do mês novo).

    Necessário porque parcelas do Sankhya vencem no MESMO DIA de meses seguintes
    (ex: venda em 23/07 → parc 1 vence 25/08, parc 2 vence 25/09, parc 3 vence
    25/10...), não a cada +30 dias linear (que acumula erro por causa de meses
    de 28-31 dias e leva parcelas distantes a divergirem em 3-5 dias do Sankhya,
    ficando fora da tolerância de match).

    Ex: _add_meses(date(2026,8,24), 3) → date(2026,11,24)
        _add_meses(date(2026,1,31), 1) → date(2026,2,28)  (clamp)
    """
    if dt is None or n == 0:
        return dt
    mes = dt.month - 1 + n
    ano = dt.year + mes // 12
    mes = mes % 12 + 1
    ultimo_dia = monthrange(ano, mes)[1]
    dia = min(dt.day, ultimo_dia)
    return date(ano, mes, dia)


COLUNAS_SAIDA = [
    "adquirente", "estabelecimento",
    "data_venda", "data_pagamento", "data_prev_pagamento",
    "valor_bruto", "valor_bruto_venda_total", "valor_taxa", "valor_liquido",
    "bandeira", "modalidade", "canal",
    "parcela_atual", "parcelas_total",
    "autorizacao", "nsu", "codigo_venda", "tid",
    "numero_pedido", "nota_fiscal",
    "forma_pagamento_original", "taxa_mdr_pct", "status_pagamento",
    "formato",
]


def _abrir_xls(dados: bytes):
    head = dados[:8]
    if not head.startswith(b"\xD0\xCF\x11\xE0"):
        raise ValueError(f"Cielo deve vir como .xls binário. Byte signature: {head!r}")
    return xlrd.open_workbook(file_contents=dados)


def _to_float(v) -> float:
    if v is None or v == "" or v == "-":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        s = re.sub(r"[^\d,\.\-]", "", str(v)).replace(",", ".")
        try:
            return float(s) if s else 0.0
        except ValueError:
            return 0.0


def _to_int(v, default: int = 1) -> int:
    if v is None or v == "" or v == "-":
        return default
    try:
        return int(float(v))
    except (ValueError, TypeError):
        try:
            s = str(v).strip()
            return int(s) if s else default
        except Exception:
            return default


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


_MARCADORES_CIELO = ["estabelecimento", "bandeira", "valor bruto", "valor líquido", "data"]


def _localizar_cabecalho(sh, limite: int = 15) -> Optional[int]:
    for r in range(min(limite, sh.nrows)):
        vals = [str(sh.cell_value(r, c)).strip().lower() for c in range(min(20, sh.ncols))]
        celulas_ok = 0
        for v in vals:
            if len(v) > 60:
                continue
            for kw in _MARCADORES_CIELO:
                if kw in v:
                    celulas_ok += 1
                    break
        if celulas_ok >= 4:
            return r
    return None


def _mapa_colunas(sh, idx_cab: int) -> dict:
    header = [str(sh.cell_value(idx_cab, c)).strip().lower() for c in range(sh.ncols)]
    return {h: i for i, h in enumerate(header) if h}


def _col(mapa: dict, *aliases: str) -> Optional[int]:
    for alias in aliases:
        a = alias.lower()
        if a in mapa:
            return mapa[a]
        for nome, idx in mapa.items():
            if a in nome:
                return idx
    return None


def eh_cielo(dados: bytes) -> bool:
    try:
        wb = _abrir_xls(dados)
    except Exception:
        return False
    if wb.nsheets < 1:
        return False
    sh = wb.sheet_by_index(0)
    return _localizar_cabecalho(sh) is not None


def eh_cielo_recebiveis(dados: bytes) -> bool:
    return eh_cielo(dados)


_RE_DEBITO = re.compile(r"\bd[eé]bito\b", re.IGNORECASE)
_RE_PARCEL = re.compile(r"\bparcel", re.IGNORECASE)
_RE_AVISTA = re.compile(r"\b(à|a)\s*vista\b|\bavista\b", re.IGNORECASE)
_RE_PIX = re.compile(r"\bpix\b", re.IGNORECASE)


def _classificar_modalidade(forma_pgto: str, parcelas: int) -> str:
    fp = (forma_pgto or "").lower()
    if _RE_PIX.search(fp):
        return "pix"
    if _RE_DEBITO.search(fp):
        return "debito"
    if _RE_PARCEL.search(fp) or parcelas > 1:
        return "credito_parcelado"
    if _RE_AVISTA.search(fp) or "credito" in fp or "crédito" in fp:
        return "credito_avista"
    return "outro"


def _classificar_canal(modalidade_txt: str, canal_venda: str) -> str:
    for src in (canal_venda, modalidade_txt):
        s = (src or "").lower()
        if "link" in s:
            return "link_pagamento"
        if "e-commerce" in s or "ecommerce" in s or "e commerce" in s:
            return "ecommerce"
        if "presencial" in s or "pos" in s:
            return "presencial"
    return "outro"


@dataclass
class ResultadoLeituraCielo:
    df: pd.DataFrame
    total_linhas: int
    linhas_ignoradas: int
    estabelecimentos: list
    total_bruto: float
    total_taxa: float
    total_liquido: float
    formato_detectado: str


def _get(row, col_idx, default=""):
    if col_idx is None:
        return default
    v = row[col_idx]
    return v if v not in (None, "") else default


def ler(dados: bytes) -> ResultadoLeituraCielo:
    if not eh_cielo(dados):
        raise ValueError("Arquivo não é o Cielo.")

    wb = _abrir_xls(dados)
    sh = wb.sheet_by_index(0)
    datemode = wb.datemode
    idx_cab = _localizar_cabecalho(sh)
    mapa = _mapa_colunas(sh, idx_cab)

    col_data_venda = _col(mapa, "data da venda")
    col_data_pgto = _col(mapa, "data de pagamento")
    col_data_prev = _col(mapa, "data prevista do pagamento", "data prevista de pagamento", "data de pagamento")
    col_estab = _col(mapa, "estabelecimento")
    col_forma_pgto = _col(mapa, "forma de pagamento")
    col_bandeira = _col(mapa, "bandeira")
    col_valor_bruto = _col(mapa, "valor bruto")
    col_valor_taxa = _col(mapa, "taxa/tarifa", "total de taxas", "taxa")
    col_valor_liq = _col(mapa, "valor líquido", "valor liquido")
    col_status = _col(mapa, "status da venda", "status do pagamento", "status")
    col_autoriza = _col(mapa, "código de autorização", "codigo de autorizacao", "autorização")
    col_nsu = _col(mapa, "nsu", "nsu/doc")
    col_cod_venda = _col(mapa, "código da venda", "codigo da venda")
    col_tid = _col(mapa, "tid")
    col_nro_pedido = _col(mapa, "número do pedido", "numero do pedido")
    col_nota_fiscal = _col(mapa, "nota fiscal")
    col_parc_total = _col(mapa, "quantidade total de parcelas")
    col_parc_num = _col(mapa, "número da parcela", "numero da parcela")
    col_modalidade = _col(mapa, "modalidade")
    col_canal = _col(mapa, "canal da venda", "canal")
    col_taxa_mdr = _col(mapa, "taxa administrativa (mdr)", "taxa mdr")

    # Formato NOVO: tem "quantidade total de parcelas" mas NÃO tem "número da parcela"
    is_novo = col_parc_total is not None and col_parc_num is None
    formato = "novo" if is_novo else "antigo"

    linhas = []
    ignoradas = 0
    estabs = set()

    for r in range(idx_cab + 1, sh.nrows):
        row = sh.row_values(r)
        if not any(str(v).strip() for v in row):
            ignoradas += 1
            continue

        estab = str(_get(row, col_estab, "")).strip()
        if not estab:
            ignoradas += 1
            continue

        valor_bruto_raw = _to_float(_get(row, col_valor_bruto, 0))
        if valor_bruto_raw == 0:
            ignoradas += 1
            continue

        # FILTRO STATUS · Ignora vendas Negadas/Canceladas/Não Autorizadas.
        # Mesmo bug que apareceu no Getnet em 31/07/2026: vendas não aprovadas
        # não geram título no Sankhya, então precisam sair do dataset.
        # No arquivo real da Débora hoje o Cielo só traz Aprovadas, mas
        # filtramos por segurança pra funcionar se um dia trazer outros status.
        status_raw = str(_get(row, col_status, "")).strip().lower()
        if status_raw and status_raw not in ("aprovada", "aprovado", ""):
            ignoradas += 1
            continue

        estabs.add(estab)

        forma_pgto = str(_get(row, col_forma_pgto, "")).strip()
        bandeira = str(_get(row, col_bandeira, "")).strip()
        modalidade_txt = str(_get(row, col_modalidade, "")).strip()
        canal_txt = str(_get(row, col_canal, "")).strip()

        parc_total = _to_int(_get(row, col_parc_total, 1), 1) or 1
        parc_num_raw = _to_int(_get(row, col_parc_num, 1), 1) or 1
        valor_parcela = round(valor_bruto_raw / parc_total, 2) if parc_total > 0 else valor_bruto_raw

        data_venda = _to_date(_get(row, col_data_venda), datemode)
        data_prev = _to_date(_get(row, col_data_prev), datemode)
        data_pgto = _to_date(_get(row, col_data_pgto), datemode)

        modalidade = _classificar_modalidade(forma_pgto, parc_total)
        canal = _classificar_canal(modalidade_txt, canal_txt)

        valor_taxa_row = _to_float(_get(row, col_valor_taxa, 0))
        valor_liq_row = _to_float(_get(row, col_valor_liq, 0))
        taxa_mdr = _to_float(_get(row, col_taxa_mdr, 0))
        status = str(_get(row, col_status, "")).strip()

        # No formato novo, taxa e líquido também são totais da venda — dividir por N
        if is_novo and parc_total > 1:
            valor_taxa_parcela = round(valor_taxa_row / parc_total, 2)
            valor_liq_parcela = round(valor_liq_row / parc_total, 2)
        else:
            valor_taxa_parcela = valor_taxa_row
            valor_liq_parcela = valor_liq_row

        base = dict(
            adquirente="cielo",
            estabelecimento=estab,
            data_venda=data_venda,
            data_pagamento=data_pgto,
            valor_bruto_venda_total=valor_bruto_raw,
            valor_taxa=abs(valor_taxa_parcela),
            valor_liquido=valor_liq_parcela,
            bandeira=bandeira,
            modalidade=modalidade,
            canal=canal,
            parcelas_total=parc_total,
            autorizacao=str(_get(row, col_autoriza, "")).strip(),
            nsu=str(_get(row, col_nsu, "")).strip(),
            codigo_venda=str(_get(row, col_cod_venda, "")).strip(),
            tid=str(_get(row, col_tid, "")).strip(),
            numero_pedido=str(_get(row, col_nro_pedido, "")).strip(),
            nota_fiscal=str(_get(row, col_nota_fiscal, "")).strip(),
            forma_pagamento_original=forma_pgto,
            taxa_mdr_pct=taxa_mdr,
            status_pagamento=status,
            formato=formato,
        )

        if is_novo and parc_total > 1:
            # Explode em N parcelas. Cada parcela vence no MESMO DIA de meses
            # seguintes a partir da data prevista da 1ª parcela (regra real do
            # Sankhya). Antes usávamos +30d linear, o que gerava divergência
            # de 3-5 dias em parcelas distantes (fora da tolerância de match).
            # A ÚLTIMA parcela ajusta o centavo pra fechar o total exato
            # (ex: 2008,07 / 3 = 669,3566... → parcelas 1 e 2 = 669,36,
            #  parcela 3 = 2008,07 - 669,36 - 669,36 = 669,35). Sem isso,
            # meu total ficaria 2008,08 e a estratégia agregada não bateria.
            soma_anteriores = 0.0
            for n in range(1, parc_total + 1):
                dt_prev_n = data_prev
                if data_prev is not None and n > 1:
                    dt_prev_n = _add_meses(data_prev, n - 1)
                if n < parc_total:
                    vlr_n = valor_parcela
                    soma_anteriores = round(soma_anteriores + vlr_n, 2)
                else:
                    vlr_n = round(valor_bruto_raw - soma_anteriores, 2)
                linhas.append({**base,
                    "data_prev_pagamento": dt_prev_n,
                    "valor_bruto": vlr_n,
                    "parcela_atual": n,
                })
        else:
            linhas.append({**base,
                "data_prev_pagamento": data_prev,
                "valor_bruto": valor_parcela,
                "parcela_atual": parc_num_raw,
            })

    df = pd.DataFrame(linhas, columns=COLUNAS_SAIDA)

    return ResultadoLeituraCielo(
        df=df,
        total_linhas=len(linhas),
        linhas_ignoradas=ignoradas,
        estabelecimentos=sorted(estabs),
        total_bruto=float(df["valor_bruto"].sum()) if not df.empty else 0.0,
        total_taxa=float(df["valor_taxa"].sum()) if not df.empty else 0.0,
        total_liquido=float(df["valor_liquido"].sum()) if not df.empty else 0.0,
        formato_detectado=formato,
    )
