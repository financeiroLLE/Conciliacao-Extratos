"""Parsers de extrato de ADQUIRENTE (cartão) — GetNet e PagBank/PagSeguro.

Módulo NOVO e independente: não altera nenhuma tela nem parser existente.
Serve pra, quando a pessoa subir (OPCIONALMENTE) o extrato da adquirente,
dar NOME à diferença de cartão (aluguel, tarifa, estorno...) e, mais tarde,
alimentar a Auditoria de Cartões.

Esquema de saída comum (uma linha por lançamento):
    data        : datetime  (quando cai/vence no banco)
    adquirente  : 'GetNet' | 'PagBank'
    bandeira    : str  (Elo Crédito, Mastercard Débito, ... ou '')
    tipo        : str  (rótulo cru da adquirente)
    descricao   : str  (lançamento cru)
    valor       : float (sinal como no arquivo)
    categoria   : 'venda'|'estorno'|'aluguel'|'tarifa'|'repasse'|'saldo'|'outros'

Regra de honestidade: nada é inventado. A categoria vem SEMPRE de um texto
que está no arquivo; o que não encaixa vira 'outros' (nunca é forçado).
"""
from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

COLUNAS_SAIDA = ["data", "adquirente", "bandeira", "tipo", "descricao", "valor", "categoria"]


# ------------------------------------------------------------------ util
def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _num_br(v) -> float:
    """'−1.234,56' / '1.234,56' / '-4,05' -> float. Vazio -> 0.0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except Exception:
            return 0.0
    s = str(v).strip()
    if not s or s in {"-", "—"}:
        return 0.0
    s = s.replace("R$", "").replace(" ", "")
    # já veio no padrão americano (do openpyxl)?
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        return float(s)
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _bytes(arquivo) -> bytes:
    if hasattr(arquivo, "getvalue"):
        return arquivo.getvalue()
    if hasattr(arquivo, "read"):
        return arquivo.read()
    with open(arquivo, "rb") as fh:
        return fh.read()


def _nome(arquivo) -> str:
    return getattr(arquivo, "name", "") or (arquivo if isinstance(arquivo, str) else "")


# ------------------------------------------------------------- categorizar
def _categoria_getnet(tipo: str, lanc: str) -> str:
    t, l = _sem_acento(tipo), _sem_acento(lanc)
    if "cancelamento" in t or "chargeback" in t or "cancelamento" in l or "estorno" in l:
        return "estorno"
    # Aluguel × Tarifa: o TIPO cru costuma ser o genérico "Aluguel/Tarifa", então
    # a distinção tem que sair do LANÇAMENTO específico (ex.: "Aluguel Maio/2026"
    # vs "Trans Excedentes Plat Digital"). Só cai em tarifa se NÃO for aluguel.
    if "aluguel/tarifa" in t or "tarifa" in t:
        return "aluguel" if "aluguel" in l else "tarifa"
    if "aluguel" in l:
        return "aluguel"
    if "excedente" in l or "tarifa" in l:
        return "tarifa"
    if "venda" in t or "venda" in l:
        return "venda"
    if "pagamento realizado" in t or "valor liquidado" in l:
        return "repasse"
    if "saldo" in t or "saldo" in l:
        return "saldo"
    return "outros"


def _categoria_pagbank(desc: str) -> str:
    d = _sem_acento(desc)
    if "estorno" in d or "cancelamento" in d or "devolucao" in d or "chargeback" in d:
        return "estorno"
    if "aluguel" in d:
        return "aluguel"
    if "taxa" in d or "tarifa" in d or "intermediacao" in d or "antecipacao" in d:
        return "tarifa"
    if "venda" in d:
        return "venda"
    if "saque" in d or "pagamento liberado" in d or "reserva de saldo" in d or "liberado" in d:
        return "repasse"
    if "saldo" in d:
        return "saldo"
    return "outros"


# ------------------------------------------------------------------ GetNet
def _achar_header_getnet(raw: pd.DataFrame) -> int | None:
    """Acha a linha de cabeçalho (a que tem 'DATA DE VENCIMENTO' / 'TIPO DE LANÇAMENTO')."""
    for i in range(min(20, len(raw))):
        linha = " | ".join(_sem_acento(x) for x in raw.iloc[i].tolist())
        if "tipo de lancamento" in linha or "data de vencimento" in linha:
            return i
    return None


def carregar_getnet_recebiveis(arquivo) -> pd.DataFrame:
    conteudo = _bytes(arquivo)
    xl = pd.ExcelFile(io.BytesIO(conteudo))
    aba = "Detalhado" if "Detalhado" in xl.sheet_names else xl.sheet_names[-1]
    raw = xl.parse(aba, header=None)
    h = _achar_header_getnet(raw)
    if h is None:
        return pd.DataFrame(columns=COLUNAS_SAIDA)
    df = xl.parse(aba, header=h)
    df.columns = [_sem_acento(c) for c in df.columns]

    def col(*alvos):
        for c in df.columns:
            if any(a in c for a in alvos):
                return c
        return None

    c_data = col("data de vencimento", "vencimento")
    c_band = col("bandeira", "modalidade")
    c_tipo = col("tipo de lancamento")
    # 'lancamento' cru colide com 'tipo de lancamento' — pega a coluna EXATA
    # 'lancamento' (ou uma que tenha 'lancamento' sem 'tipo').
    c_lanc = next((c for c in df.columns if c.strip() == "lancamento"), None)
    if c_lanc is None:
        c_lanc = next(
            (c for c in df.columns if "lancamento" in c and "tipo" not in c), None
        )
    c_val = col("valor liquido", "valor liquidado", "valor")

    out = pd.DataFrame()
    out["data"] = pd.to_datetime(df[c_data], errors="coerce") if c_data else pd.NaT
    out["bandeira"] = df[c_band].astype(str).str.strip() if c_band else ""
    out["tipo"] = df[c_tipo].astype(str).str.strip() if c_tipo else ""
    out["descricao"] = df[c_lanc].astype(str).str.strip() if c_lanc else ""
    out["valor"] = df[c_val].map(_num_br) if c_val else 0.0
    out["adquirente"] = "GetNet"
    out["categoria"] = [
        _categoria_getnet(t, l) for t, l in zip(out["tipo"], out["descricao"])
    ]
    # tira linhas de cabeçalho repetido / saldo anterior vazio
    out = out[out["data"].notna()].copy()
    return out[COLUNAS_SAIDA].reset_index(drop=True)


# ------------------------------------------------------------------ PagBank
def carregar_pagbank(arquivo) -> pd.DataFrame:
    conteudo = _bytes(arquivo)
    texto = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except Exception:
            continue
    if texto is None:
        return pd.DataFrame(columns=COLUNAS_SAIDA)
    linhas = texto.splitlines()
    # o cabeçalho de dados é a linha que começa com 'DATA;' (a 1ª costuma ser 'CNPJ:')
    inicio = 0
    for i, ln in enumerate(linhas[:5]):
        if _sem_acento(ln).startswith("data;") or "codigo da transacao" in _sem_acento(ln):
            inicio = i
            break
    df = pd.read_csv(
        io.StringIO("\n".join(linhas[inicio:])), sep=";", engine="python", dtype=str
    )
    df.columns = [_sem_acento(c) for c in df.columns]

    def col(*alvos):
        for c in df.columns:
            if any(a in c for a in alvos):
                return c
        return None

    c_data = col("data")
    c_desc = col("descricao")
    c_val = col("valor")
    c_conta = col("conta")

    out = pd.DataFrame()
    # data pode vir "01/06/2026 02:37:05" ou "01/06/2026"
    out["data"] = pd.to_datetime(
        df[c_data].astype(str).str.slice(0, 10), format="%d/%m/%Y", errors="coerce"
    ) if c_data else pd.NaT
    out["bandeira"] = df[c_conta].astype(str).str.strip() if c_conta else ""  # bucket Disponível/A receber
    out["tipo"] = df[c_desc].astype(str).str.strip() if c_desc else ""
    out["descricao"] = df[c_desc].astype(str).str.strip() if c_desc else ""
    out["valor"] = df[c_val].map(_num_br) if c_val else 0.0
    out["adquirente"] = "PagBank"
    out["categoria"] = [_categoria_pagbank(d) for d in out["descricao"]]
    out = out[out["data"].notna()].copy()
    return out[COLUNAS_SAIDA].reset_index(drop=True)


# ------------------------------------------------------------- detecção/roteamento
def _categoria_cielo(tipo: str) -> str:
    """Categoria a partir do 'Tipo de lançamento' da Cielo. Nada é inventado."""
    t = _sem_acento(tipo)
    if "cancelamento" in t or "chargeback" in t or "estorno" in t:
        return "estorno"
    if "venda" in t:
        return "venda"
    if "aluguel" in t:
        return "aluguel"
    if "tarifa" in t or "taxa" in t:
        return "tarifa"
    if "saldo" in t:
        return "saldo"
    return "outros"


def _achar_header_cielo(raw: pd.DataFrame) -> int | None:
    """Header do 'Recebíveis Detalhado' da Cielo: linha com 'Data de pagamento'
    e 'Valor líquido' (59 colunas)."""
    for i in range(min(20, len(raw))):
        blob = _sem_acento(" ".join(str(x) for x in raw.iloc[i].tolist()))
        if "data de pagamento" in blob and "valor liquido" in blob:
            return i
    return None


def carregar_cielo_recebiveis(arquivo) -> pd.DataFrame:
    """Relatório 'Recebíveis Detalhado' da Cielo (xls/xlsx, 59 colunas).

    Cada linha é UMA venda sendo paga. O que bate com o banco é o VALOR
    LÍQUIDO somado por dia de pagamento e bandeira (Visa cai como 'VENDA
    CARTAO DE CREDITO'; Master/Elo como 'CIELO VDA CREDITO ...'). O Sankhya
    baixa pelo líquido — validado ao centavo com dados reais (v5.53).
    """
    conteudo = _bytes(arquivo)
    try:
        xl = pd.ExcelFile(io.BytesIO(conteudo))
    except Exception:
        return pd.DataFrame(columns=COLUNAS_SAIDA)
    raw = xl.parse(xl.sheet_names[0], header=None)
    h = _achar_header_cielo(raw)
    if h is None:
        return pd.DataFrame(columns=COLUNAS_SAIDA)
    df = xl.parse(xl.sheet_names[0], header=h)
    df.columns = [_sem_acento(str(c)) for c in df.columns]

    def col(*alvos):
        for c in df.columns:
            if any(a in c for a in alvos):
                return c
        return None

    c_data = col("data de pagamento")
    c_band = col("bandeira")
    c_tipo = col("tipo de lancamento")
    c_forma = col("forma de pagamento")
    c_liq = col("valor liquido")
    c_bruto = col("valor bruto")
    c_taxa = col("taxa/tarifa")
    if c_data is None or c_liq is None:
        return pd.DataFrame(columns=COLUNAS_SAIDA)

    out = pd.DataFrame()
    out["data"] = pd.to_datetime(df[c_data], format="%d/%m/%Y", errors="coerce")
    out["bandeira"] = df[c_band].astype(str).str.strip() if c_band else ""
    out["tipo"] = df[c_tipo].astype(str).str.strip() if c_tipo else ""
    _forma = df[c_forma].astype(str).str.strip() if c_forma else ""
    _bruto = df[c_bruto].map(_num_br) if c_bruto else 0.0
    _taxa = df[c_taxa].map(_num_br) if c_taxa else 0.0
    out["descricao"] = [
        (f"{f} · bruto R$ {b:,.2f} · taxa R$ {abs(t):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        for f, b, t in zip(
            _forma if c_forma else [""] * len(df),
            _bruto if c_bruto else [0.0] * len(df),
            _taxa if c_taxa else [0.0] * len(df),
        )
    ]
    out["valor"] = df[c_liq].map(_num_br)  # LÍQUIDO — é o que entra no banco
    out["adquirente"] = "Cielo"
    out["categoria"] = [_categoria_cielo(t) for t in out["tipo"]]
    out = out[out["data"].notna() & out["valor"].notna()].copy()
    return out[COLUNAS_SAIDA].reset_index(drop=True)


def detectar_adquirente(arquivo) -> str:
    nome = _sem_acento(_nome(arquivo))
    # v5.53: 'cielo' ANTES de 'recebivel' — o relatório da Cielo se chama
    # "Recebiveis_cielo_detalhe" e caía no GetNet pelo termo 'recebivel'.
    if "cielo" in nome:
        return "cielo"
    if "getnet" in nome or "recebivel" in nome:
        return "getnet"
    if "pagbank" in nome or "pagseguro" in nome:
        return "pagbank"
    # sniff pelo conteúdo
    try:
        conteudo = _bytes(arquivo)
    except Exception:
        return "desconhecido"
    cabeca = conteudo[:4000]
    if cabeca[:4] == b"PK\x03\x04":  # xlsx (zip)
        try:
            raw = pd.read_excel(io.BytesIO(conteudo), header=None, nrows=12)
            blob = _sem_acento(" ".join(str(x) for x in raw.values.ravel()))
            if "cielo" in blob or ("data de pagamento" in blob and "valor liquido" in blob):
                return "cielo"
            if "tipo de lancamento" in blob or "recebimentos" in blob or "ec centralizador" in blob:
                return "getnet"
        except Exception:
            pass
        return "desconhecido"
    # v5.53: xls antigo (BIFF) não decodifica em latin-1 — sniff via pandas
    try:
        raw = pd.read_excel(io.BytesIO(conteudo), header=None, nrows=12)
        blob = _sem_acento(" ".join(str(x) for x in raw.values.ravel()))
        if "cielo" in blob or ("data de pagamento" in blob and "valor liquido" in blob):
            return "cielo"
        if "tipo de lancamento" in blob or "recebimentos" in blob or "ec centralizador" in blob:
            return "getnet"
    except Exception:
        pass
    txt = _sem_acento(cabeca.decode("latin-1", errors="ignore"))
    if "codigo da transacao" in txt or ("data;" in txt and "descricao" in txt):
        return "pagbank"
    return "desconhecido"


def carregar_extrato_adquirente(arquivo) -> pd.DataFrame:
    """Roteia pro parser certo. Devolve DataFrame no esquema comum (ou vazio)."""
    tipo = detectar_adquirente(arquivo)
    if tipo == "cielo":
        return carregar_cielo_recebiveis(arquivo)
    if tipo == "getnet":
        return carregar_getnet_recebiveis(arquivo)
    if tipo == "pagbank":
        return carregar_pagbank(arquivo)
    return pd.DataFrame(columns=COLUNAS_SAIDA)


def resumo_por_categoria(df: pd.DataFrame) -> pd.DataFrame:
    """Soma por categoria (valor absoluto) — base pro 'mapa de cartão'."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["categoria", "qtd", "total"])
    g = (
        df.assign(_abs=df["valor"].abs())
        .groupby("categoria")
        .agg(qtd=("valor", "size"), total=("_abs", "sum"))
        .reset_index()
        .sort_values("total", ascending=False)
    )
    return g
