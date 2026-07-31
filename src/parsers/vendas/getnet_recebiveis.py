# -*- coding: utf-8 -*-
"""
Leitor Getnet — suporta AMBOS os formatos:

  Formato ANTIGO ("Recebíveis Completos"):
    - 3 abas: Resumo, Sintético por Grupo, Detalhado
    - Cabeçalho na linha 8 da aba Detalhado (26 colunas)
    - Mistura vendas + pagamentos realizados + saldos

  Formato NOVO ("Extrato de Vendas Cartões - Detalhado"):
    - Múltiplas abas por tipo: CARTÕES, PIX, RECARGA, VAN, VOUCHER
    - Aba CARTÕES: cabeçalho na linha 8 (23 colunas), só vendas
    - Traz VALOR BRUTO TOTAL da venda — motor divide por N parcelas
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd
import xlrd


def _add_meses(dt: date, n: int) -> date:
    """Adiciona N meses mantendo o mesmo dia (com clamp para último dia do mês).

    Necessário porque parcelas do Sankhya vencem no MESMO DIA de meses
    seguintes (ex: venda em 23/07 com 1a parcela em 24/08 → parc 2 em
    24/09, parc 3 em 24/10, parc 4 em 24/11...), não a cada +30 dias
    linear (que acumulava erro em parcelas distantes).
    """
    if dt is None or n == 0:
        return dt
    mes = dt.month - 1 + n
    ano = dt.year + mes // 12
    mes = mes % 12 + 1
    ultimo_dia = monthrange(ano, mes)[1]
    dia = min(dt.day, ultimo_dia)
    return date(ano, mes, dia)


NOME_ABA_DETALHADO = "Detalhado"
NOME_ABA_CARTOES = "CARTÕES"


COLUNAS_VENDAS = [
    "adquirente", "estabelecimento", "ec_centralizador", "cnpj_estabelecimento",
    "data_venda", "data_prev_pagamento", "hora_venda",
    "valor_venda_bruto", "valor_parcela_bruto", "valor_taxa", "valor_liquido",
    "bandeira", "modalidade",
    "parcela_atual", "parcelas_total",
    "autorizacao", "nsu", "numero_cartao_mascarado", "terminal",
    "lancamento_original", "tipo_registro",
    "formato",
]

COLUNAS_REPASSES = [
    "adquirente", "estabelecimento", "ec_centralizador", "cnpj_estabelecimento",
    "data_pagamento", "bandeira", "modalidade", "valor_repasse",
]


def _abrir_xls(dados: bytes):
    head = dados[:8]
    if not head.startswith(b"\xD0\xCF\x11\xE0"):
        raise ValueError(f"Getnet deve vir como .xls binário. Byte signature: {head!r}")
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


def _localizar_cabecalho(sh, palavras_chave: list, limite: int = 15) -> Optional[int]:
    for r in range(min(limite, sh.nrows)):
        vals = [str(sh.cell_value(r, c)).strip().lower() for c in range(min(15, sh.ncols))]
        ok = 0
        for v in vals:
            if len(v) > 60:
                continue
            for kw in palavras_chave:
                if kw in v:
                    ok += 1
                    break
        if ok >= 4:
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


def eh_getnet_recebiveis(dados: bytes) -> bool:
    """Reconhece AMBOS formatos: Recebíveis Completos + Extrato de Vendas Cartões."""
    try:
        wb = _abrir_xls(dados)
    except Exception:
        return False
    abas = wb.sheet_names()
    return NOME_ABA_DETALHADO in abas or NOME_ABA_CARTOES in abas


_MARCADORES_ANTIGO = [
    "ec centralizador", "estabelecimento", "cpf / cnpj",
    "bandeira / modalidade", "tipo de lançamento", "autorização",
]

_MARCADORES_NOVO = [
    "estabelecimento comercial", "cpf / cnpj",
    "bandeira", "modalidade", "forma de pagamento",
    "data/hora da venda", "número de autorização",
]


_RE_PARCELAS_XdeY = re.compile(r"(\d+)\s*de\s*(\d+)", re.IGNORECASE)


def _parsear_parcelas_XdeY(txt: str) -> tuple:
    if not txt or txt == "-":
        return (1, 1)
    m = _RE_PARCELAS_XdeY.search(str(txt))
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (1, 1)


def _extrair_bandeira_e_modalidade(band_txt: str, forma_pgto: str = "", modalidade_txt: str = "") -> tuple:
    """
    Retorna (bandeira_str, modalidade_codigo).

    Bandeira: primeira palavra ('Elo', 'Mastercard', 'Visa')
    Modalidade codigo: debito, credito_avista, credito_parcelado, outro
    """
    src = " ".join([band_txt or "", forma_pgto or "", modalidade_txt or ""]).lower()
    if "débito" in src or "debito" in src:
        modalidade = "debito"
    elif "parcel" in src:
        modalidade = "credito_parcelado"
    elif "vista" in src or "à vista" in src or "a vista" in src:
        modalidade = "credito_avista"
    elif "crédito" in src or "credito" in src:
        modalidade = "credito_avista"
    else:
        modalidade = "outro"

    # bandeira = primeira palavra do campo bandeira/modalidade original
    if band_txt:
        primeira = band_txt.strip().split()[0] if band_txt.strip() else ""
        return (primeira, modalidade)
    return ("", modalidade)


@dataclass
class ResultadoLeituraGetnet:
    df_vendas: pd.DataFrame = field(default_factory=pd.DataFrame)
    df_repasses: pd.DataFrame = field(default_factory=pd.DataFrame)
    total_vendas: int = 0
    total_cancelamentos: int = 0
    total_repasses: int = 0
    linhas_saldo_anterior_ignoradas: int = 0
    linhas_vazias_ignoradas: int = 0
    estabelecimentos: list = field(default_factory=list)
    total_bruto_vendas: float = 0.0
    total_liquido_vendas: float = 0.0
    total_taxa_vendas: float = 0.0
    total_repassado: float = 0.0
    formato_detectado: str = ""


# ==============================================================================
# LEITURA - FORMATO ANTIGO (Recebíveis Completos)
# ==============================================================================

def _ler_formato_antigo(wb) -> ResultadoLeituraGetnet:
    sh = wb.sheet_by_name(NOME_ABA_DETALHADO)
    datemode = wb.datemode
    idx_cab = _localizar_cabecalho(sh, _MARCADORES_ANTIGO)
    if idx_cab is None:
        raise ValueError("Cabeçalho Getnet Recebíveis Completos não localizado.")
    mapa = _mapa_colunas(sh, idx_cab)

    col_ec = _col(mapa, "ec centralizador")
    col_estab = _col(mapa, "estabelecimento comercial")
    col_cnpj = _col(mapa, "cpf / cnpj")
    col_venc = _col(mapa, "data de vencimento")
    col_bmod = _col(mapa, "bandeira / modalidade")
    col_tipo_lanc = _col(mapa, "tipo de lançamento")
    col_lanc = _col(mapa, "lançamento")
    col_vlr_liquido = _col(mapa, "valor líquido")
    col_num_cartao = _col(mapa, "número do cartão")
    col_autoriza = _col(mapa, "autorização")
    col_nsu = _col(mapa, "nsu", "número comprovante")
    col_terminal = _col(mapa, "terminal")
    col_data_venda = _col(mapa, "data da venda")
    col_hora_venda = _col(mapa, "hora da venda")
    col_vlr_venda = _col(mapa, "valor da venda")
    col_parcelas = _col(mapa, "parcelas")
    col_vlr_parcela = _col(mapa, "valor da parcela")
    col_descontos = _col(mapa, "descontos")
    col_vlr_liq_parc = _col(mapa, "valor liquido da parcela", "valor líquido da parcela")

    linhas_vendas = []
    linhas_repasses = []
    n_saldo, n_vazias, n_cancel = 0, 0, 0
    estabs = set()

    def _get(row, ci, dv=""):
        return row[ci] if ci is not None else dv

    for r in range(idx_cab + 1, sh.nrows):
        row = sh.row_values(r)
        if not any(str(v).strip() for v in row):
            n_vazias += 1
            continue

        tipo = str(_get(row, col_tipo_lanc, "")).strip()
        lanc = str(_get(row, col_lanc, "")).strip()

        if not tipo:
            n_vazias += 1
            continue

        estab = str(_get(row, col_estab, "")).strip()
        if estab:
            estabs.add(estab)
        cnpj = str(_get(row, col_cnpj, "")).strip()
        ec = str(_get(row, col_ec, "")).strip()

        band_txt = str(_get(row, col_bmod, "")).strip()
        bandeira, modalidade = _extrair_bandeira_e_modalidade(band_txt, forma_pgto=lanc)

        if tipo == "Saldo Anterior":
            n_saldo += 1
            continue

        if tipo == "Pagamento Realizado":
            linhas_repasses.append({
                "adquirente": "getnet",
                "estabelecimento": estab,
                "ec_centralizador": ec,
                "cnpj_estabelecimento": cnpj,
                "data_pagamento": _to_date(_get(row, col_venc), datemode),
                "bandeira": bandeira,
                "modalidade": modalidade,
                "valor_repasse": abs(_to_float(_get(row, col_vlr_liquido, 0))),
            })
            continue

        if tipo in ("Vendas", "Cancelamento/Chargeback"):
            tipo_reg = "venda" if tipo == "Vendas" else "cancelamento"
            if tipo_reg == "cancelamento":
                n_cancel += 1
            parc_atual, parc_total = _parsear_parcelas_XdeY(str(_get(row, col_parcelas, "")))
            vlr_parc_bruto = _to_float(_get(row, col_vlr_parcela, 0))
            desconto = _to_float(_get(row, col_descontos, 0))
            vlr_liq = _to_float(_get(row, col_vlr_liq_parc, 0))

            linhas_vendas.append({
                "adquirente": "getnet",
                "estabelecimento": estab,
                "ec_centralizador": ec,
                "cnpj_estabelecimento": cnpj,
                "data_venda": _to_date(_get(row, col_data_venda), datemode),
                "data_prev_pagamento": _to_date(_get(row, col_venc), datemode),
                "hora_venda": str(_get(row, col_hora_venda, "")).strip(),
                "valor_venda_bruto": _to_float(_get(row, col_vlr_venda, 0)),
                "valor_parcela_bruto": vlr_parc_bruto,
                "valor_taxa": abs(desconto),
                "valor_liquido": vlr_liq,
                "bandeira": bandeira,
                "modalidade": modalidade,
                "parcela_atual": parc_atual,
                "parcelas_total": parc_total,
                "autorizacao": str(_get(row, col_autoriza, "")).strip(),
                "nsu": str(_get(row, col_nsu, "")).strip(),
                "numero_cartao_mascarado": str(_get(row, col_num_cartao, "")).strip(),
                "terminal": str(_get(row, col_terminal, "")).strip(),
                "lancamento_original": lanc,
                "tipo_registro": tipo_reg,
                "formato": "antigo",
            })
            continue

        n_vazias += 1

    df_v = pd.DataFrame(linhas_vendas, columns=COLUNAS_VENDAS)
    df_r = pd.DataFrame(linhas_repasses, columns=COLUNAS_REPASSES)
    return ResultadoLeituraGetnet(
        df_vendas=df_v, df_repasses=df_r,
        total_vendas=int((df_v["tipo_registro"] == "venda").sum()) if not df_v.empty else 0,
        total_cancelamentos=n_cancel,
        total_repasses=len(df_r),
        linhas_saldo_anterior_ignoradas=n_saldo,
        linhas_vazias_ignoradas=n_vazias,
        estabelecimentos=sorted(estabs),
        total_bruto_vendas=float(df_v["valor_parcela_bruto"].sum()) if not df_v.empty else 0.0,
        total_liquido_vendas=float(df_v["valor_liquido"].sum()) if not df_v.empty else 0.0,
        total_taxa_vendas=float(df_v["valor_taxa"].sum()) if not df_v.empty else 0.0,
        total_repassado=float(df_r["valor_repasse"].sum()) if not df_r.empty else 0.0,
        formato_detectado="antigo",
    )


# ==============================================================================
# LEITURA - FORMATO NOVO (Extrato de Vendas Cartões)
# ==============================================================================

def _ler_formato_novo(wb) -> ResultadoLeituraGetnet:
    sh = wb.sheet_by_name(NOME_ABA_CARTOES)
    datemode = wb.datemode
    idx_cab = _localizar_cabecalho(sh, _MARCADORES_NOVO)
    if idx_cab is None:
        raise ValueError("Cabeçalho Getnet Extrato de Vendas não localizado.")
    mapa = _mapa_colunas(sh, idx_cab)

    col_estab = _col(mapa, "estabelecimento comercial")
    col_cnpj = _col(mapa, "cpf / cnpj")
    col_bandeira = _col(mapa, "bandeira")
    col_modalidade = _col(mapa, "modalidade")
    col_forma_pgto = _col(mapa, "forma de pagamento")
    col_data_venda = _col(mapa, "data/hora da venda", "data da venda")
    col_status = _col(mapa, "status da transação", "status")
    col_parcelas = _col(mapa, "parcelas")
    col_data_prev = _col(mapa, "data prevista do 1º pagamento", "data prevista")
    col_num_cartao = _col(mapa, "número do cartão")
    col_autoriza = _col(mapa, "número de autorização", "aut")
    col_cv_nsu = _col(mapa, "número do comprovante de vendas", "cv", "nsu")
    col_terminal = _col(mapa, "número do terminal", "terminal")
    col_vlr_bruto = _col(mapa, "valor bruto")
    col_vlr_taxa = _col(mapa, "valor taxa")
    col_vlr_liquido = _col(mapa, "valor líquido", "valor liquido")

    linhas_vendas = []
    n_vazias = 0
    estabs = set()

    def _get(row, ci, dv=""):
        return row[ci] if ci is not None else dv

    for r in range(idx_cab + 1, sh.nrows):
        row = sh.row_values(r)
        if not any(str(v).strip() for v in row):
            n_vazias += 1
            continue

        estab_raw = _get(row, col_estab, "")
        if not str(estab_raw).strip():
            n_vazias += 1
            continue

        estab = str(estab_raw).strip()
        vlr_bruto = _to_float(_get(row, col_vlr_bruto, 0))
        if vlr_bruto == 0:
            n_vazias += 1
            continue

        # FILTRO STATUS · Ignora vendas Negadas (só entram as Aprovadas).
        # Bug identificado em 31/07/2026: o arquivo Getnet traz TODAS as tentativas
        # (aprovadas + negadas), e sem esse filtro as negadas viravam cards
        # "sem par no Sankhya" fantasmas — porque negada obviamente não gera
        # título no Sankhya.
        status_raw = str(_get(row, col_status, "")).strip().lower()
        if status_raw and status_raw != "aprovada":
            n_vazias += 1
            continue

        estabs.add(estab)
        cnpj = str(_get(row, col_cnpj, "")).strip()
        forma_pgto = str(_get(row, col_forma_pgto, "")).strip()
        band_txt = str(_get(row, col_bandeira, "")).strip()
        modalidade_txt = str(_get(row, col_modalidade, "")).strip()
        bandeira, modalidade = _extrair_bandeira_e_modalidade(
            band_txt, forma_pgto=forma_pgto, modalidade_txt=modalidade_txt
        )
        parc_total = _to_int(_get(row, col_parcelas, 1), 1) or 1
        vlr_parc = round(vlr_bruto / parc_total, 2) if parc_total > 0 else vlr_bruto

        data_venda = _to_date(_get(row, col_data_venda), datemode)
        data_prev_1a = _to_date(_get(row, col_data_prev), datemode)

        vlr_taxa = _to_float(_get(row, col_vlr_taxa, 0))
        vlr_liq_total = _to_float(_get(row, col_vlr_liquido, 0))
        # taxa por parcela e líquido por parcela
        vlr_taxa_parc = round(vlr_taxa / parc_total, 2) if parc_total > 0 else vlr_taxa
        vlr_liq_parc = round(vlr_liq_total / parc_total, 2) if parc_total > 0 else vlr_liq_total

        base = dict(
            adquirente="getnet",
            estabelecimento=estab,
            ec_centralizador=estab,
            cnpj_estabelecimento=cnpj,
            data_venda=data_venda,
            hora_venda="",
            valor_venda_bruto=vlr_bruto,
            valor_parcela_bruto=vlr_parc,
            valor_taxa=abs(vlr_taxa_parc),
            valor_liquido=vlr_liq_parc,
            bandeira=bandeira,
            modalidade=modalidade,
            parcelas_total=parc_total,
            autorizacao=str(_get(row, col_autoriza, "")).strip(),
            nsu=str(_get(row, col_cv_nsu, "")).strip(),
            numero_cartao_mascarado=str(_get(row, col_num_cartao, "")).strip(),
            terminal=str(_get(row, col_terminal, "")).strip(),
            lancamento_original=forma_pgto,
            tipo_registro="venda",
            formato="novo",
        )

        # Expandir parcelas: 1 linha por parcela vencendo no MESMO DIA de meses
        # seguintes a partir da data prevista da 1a parcela (regra real Sankhya).
        # Antes era +30d linear, que divergia 3-5 dias em parcelas distantes.
        # A ÚLTIMA parcela ajusta centavo pra fechar o total exato (aplica em
        # valor_parcela_bruto, valor_taxa e valor_liquido) — sem isso o valor
        # agregado da venda pelo motor não bate com o Sankhya (ex: 2008,08 vs 2008,07).
        soma_bruto = 0.0
        soma_taxa = 0.0
        soma_liq = 0.0
        for n in range(1, parc_total + 1):
            dt_n = data_prev_1a
            if data_prev_1a is not None and n > 1:
                dt_n = _add_meses(data_prev_1a, n - 1)
            if n < parc_total:
                vlr_p = vlr_parc
                vlr_t = abs(vlr_taxa_parc)
                vlr_l = vlr_liq_parc
                soma_bruto = round(soma_bruto + vlr_p, 2)
                soma_taxa = round(soma_taxa + vlr_t, 2)
                soma_liq = round(soma_liq + vlr_l, 2)
            else:
                vlr_p = round(vlr_bruto - soma_bruto, 2)
                vlr_t = round(abs(vlr_taxa) - soma_taxa, 2)
                vlr_l = round(vlr_liq_total - soma_liq, 2)
            linha = {**base,
                "data_prev_pagamento": dt_n,
                "parcela_atual": n,
                "valor_parcela_bruto": vlr_p,
                "valor_taxa": vlr_t,
                "valor_liquido": vlr_l,
            }
            linhas_vendas.append(linha)

    df_v = pd.DataFrame(linhas_vendas, columns=COLUNAS_VENDAS)
    return ResultadoLeituraGetnet(
        df_vendas=df_v,
        df_repasses=pd.DataFrame(columns=COLUNAS_REPASSES),
        total_vendas=len(df_v),
        total_cancelamentos=0,
        total_repasses=0,
        linhas_saldo_anterior_ignoradas=0,
        linhas_vazias_ignoradas=n_vazias,
        estabelecimentos=sorted(estabs),
        total_bruto_vendas=float(df_v["valor_parcela_bruto"].sum()) if not df_v.empty else 0.0,
        total_liquido_vendas=float(df_v["valor_liquido"].sum()) if not df_v.empty else 0.0,
        total_taxa_vendas=float(df_v["valor_taxa"].sum()) if not df_v.empty else 0.0,
        total_repassado=0.0,
        formato_detectado="novo",
    )


def ler(dados: bytes) -> ResultadoLeituraGetnet:
    """Detecta formato automaticamente e delega pro leitor específico."""
    if not eh_getnet_recebiveis(dados):
        raise ValueError("Arquivo não é Getnet (nem 'Detalhado' nem 'CARTÕES' encontrados).")
    wb = _abrir_xls(dados)
    if NOME_ABA_CARTOES in wb.sheet_names():
        return _ler_formato_novo(wb)
    return _ler_formato_antigo(wb)
