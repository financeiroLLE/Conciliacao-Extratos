"""
Leitor genérico de extratos bancários em PDF — v5.31.

Objetivo (combinado com a Débora): subir QUALQUER extrato em PDF e o app se virar.
Como cada banco escreve diferente, o leitor:
  1. DETECTA o banco pelo cabeçalho da 1ª página;
  2. aplica o tratamento certo daquele layout (colunas + sinal);
  3. para um banco que não conhece, TENTA pelo padrão comum (data + dois
     números no fim da linha) e, se não tiver certeza, AVISA em vez de chutar
     (respeitando o princípio de zero falso positivo).

Devolve SEMPRE o schema canônico do app:
    data | historico | documento | valor | conta | origem
A classificação de aplicação/resgate/saldo é feita depois, pelo
`src.classificacao.movimento`, a partir do `historico` — por isso o `historico`
precisa preservar o texto original do lançamento (ex.: 'APLIC.FINANC...',
'RESGATE FUNDOS', 'DB T CESTA').

Bancos com tratamento dedicado: Sicredi, Bradesco, Caixa.
Itaú continua sendo lido pelo parser posicional dedicado (extrato_pdf_itau).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None

COLUNAS_CANONICAS = ["data", "historico", "documento", "valor", "conta", "origem"]

# Número brasileiro: 1.350,66 / -22.201,15 / 0,00
_RE_NUM = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
# Dois números no FIM da linha (valor + saldo) — assinatura de "linha de movimento"
_RE_DOIS_NUMS_FIM = re.compile(rf"({_RE_NUM})\s+({_RE_NUM})\s*$")
_RE_DATA_BR = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")
_RE_TOKEN_NUM = re.compile(rf"^{_RE_NUM}$")


def _normalizar(texto: str) -> str:
    """minúsculas + sem acento — só para detecção de banco."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def _num_br(s: str) -> float:
    """'1.350,66' -> 1350.66 ; '-22.201,15' -> -22201.15"""
    s = s.strip().replace(".", "").replace(",", ".")
    return float(s)


def detectar_banco(texto_pagina1: str) -> str:
    """Retorna 'itau' | 'sicredi' | 'bradesco' | 'caixa' | 'desconhecido'."""
    t = _normalizar(texto_pagina1)
    if "itauempresas" in t or "itau empresas" in t or "ag./origem" in t:
        return "itau"
    if "sicredi" in t or ("cooperativa" in t and "associado" in t):
        return "sicredi"
    # Bradesco: o logo costuma ser imagem (não extrai 'bradesco' no texto),
    # então detecta pela coluna dupla Crédito/Débito ou termos próprios.
    if (
        "bradesco" in t
        or ("credito (r$)" in t and "debito (r$)" in t)
        or "invest facil" in t
        or "cp empresarial" in t
    ):
        return "bradesco"
    if "caixa" in t or "gerenciador" in t:
        return "caixa"
    return "desconhecido"


def _ler_paginas(arquivo: Any) -> list[str]:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber não disponível para ler PDF.")
    paginas: list[str] = []
    with pdfplumber.open(arquivo) as pdf:
        for p in pdf.pages:
            paginas.append(p.extract_text() or "")
    return paginas


def _df(linhas: list[dict], conta: str) -> pd.DataFrame:
    if not linhas:
        df = pd.DataFrame(columns=COLUNAS_CANONICAS)
    else:
        df = pd.DataFrame(linhas)
    for c in COLUNAS_CANONICAS:
        if c not in df.columns:
            df[c] = None
    df["conta"] = conta
    df["origem"] = "Banco"
    return df[COLUNAS_CANONICAS]


# --------------------------------------------------------------------------
# SICREDI — Data Descrição Documento Valor Saldo  (sinal no valor)
# Doc: PIX_CRED / PIX_DEB / CAPTACAO / CX...  |  invest: APLIC.FINANC / RESG.APLIC.FIN
# --------------------------------------------------------------------------
def _parse_sicredi(paginas: list[str], conta: str) -> pd.DataFrame:
    linhas: list[dict] = []
    for txt in paginas:
        for raw in txt.split("\n"):
            ln = raw.strip()
            m = _RE_DATA_BR.match(ln)
            if not m:
                continue
            mv = _RE_DOIS_NUMS_FIM.search(ln)
            if not mv:
                continue  # SALDO ANTERIOR tem só 1 número -> ignora
            valor = _num_br(mv.group(1))
            corpo = ln[m.end():mv.start()].strip()  # descrição + documento
            # documento = último token (PIX_CRED/PIX_DEB/CAPTACAO/CX...)
            partes = corpo.rsplit(" ", 1)
            documento = partes[1] if len(partes) == 2 else ""
            dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
            linhas.append({
                "data": pd.Timestamp(int(yyyy), int(mm), int(dd)),
                "historico": corpo,         # preserva 'APLIC.FINANC...' p/ classificação
                "documento": documento,
                "valor": valor,
            })
    return _df(linhas, conta)


# --------------------------------------------------------------------------
# CAIXA — Data Doc Histórico Valor[ D|C] Saldo[ D|C]  (sinal no sufixo D/C)
# --------------------------------------------------------------------------
_RE_CAIXA = re.compile(
    rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(\d+)\s+(.+?)\s+({_RE_NUM})\s+([DC])\s+{_RE_NUM}\s+[DC]\s*$"
)


def _parse_caixa(paginas: list[str], conta: str) -> pd.DataFrame:
    linhas: list[dict] = []
    for txt in paginas:
        for raw in txt.split("\n"):
            ln = raw.strip()
            m = _RE_CAIXA.match(ln)
            if not m:
                continue
            data_s, doc, hist, val_s, dc = m.groups()
            valor = _num_br(val_s)
            if dc == "D":
                valor = -abs(valor)
            dd, mm, yyyy = data_s.split("/")
            linhas.append({
                "data": pd.Timestamp(int(yyyy), int(mm), int(dd)),
                "historico": hist.strip(),
                "documento": doc,
                "valor": valor,
            })
    return _df(linhas, conta)


# --------------------------------------------------------------------------
# BRADESCO — Data Lançamento(multilinha) Dcto Crédito Débito Saldo
# O texto extraído já traz o sinal no valor (débito negativo). A data vale
# para várias transações abaixo; a descrição vem na(s) linha(s) ao redor.
# Linha de movimento = termina em DOIS números (valor + saldo).
# --------------------------------------------------------------------------
def _parse_bradesco(paginas: list[str], conta: str) -> pd.DataFrame:
    linhas: list[dict] = []
    data_corrente: pd.Timestamp | None = None
    desc_pendente: list[str] = []
    PARAR = ("total ", "os dados acima", "saldos invest", "ultimos lancamentos",
             "data lancamento", "extrato de:", "agencia | conta")
    for txt in paginas:
        for raw in txt.split("\n"):
            ln = raw.strip()
            if not ln:
                continue
            low = _normalizar(ln)
            if any(low.startswith(p) or p in low for p in PARAR):
                continue
            mv = _RE_DOIS_NUMS_FIM.search(ln)
            md = _RE_DATA_BR.match(ln)
            if not mv:
                # não é linha de movimento -> ou é só data, ou é fragmento de descrição
                if md and len(ln) <= 12:
                    dd, mm, yyyy = md.group(1), md.group(2), md.group(3)
                    data_corrente = pd.Timestamp(int(yyyy), int(mm), int(dd))
                else:
                    desc_pendente.append(ln)
                continue
            # linha de movimento (termina em valor + saldo)
            valor = _num_br(mv.group(1))
            resto = ln[:mv.start()].strip()
            if md:  # tem data no começo -> atualiza data corrente
                dd, mm, yyyy = md.group(1), md.group(2), md.group(3)
                data_corrente = pd.Timestamp(int(yyyy), int(mm), int(dd))
                resto = resto[md.end():].strip()
            # documento = último token se for numérico
            documento = ""
            toks = resto.split()
            if toks and toks[-1].isdigit():
                documento = toks[-1]
                resto = " ".join(toks[:-1]).strip()
            hist = (" ".join(desc_pendente) + " " + resto).strip()
            desc_pendente = []
            if data_corrente is None:
                continue  # sem data não dá pra conciliar
            # ignora "SALDO ANTERIOR" que escapou (1 número já é filtrado, mas por garantia)
            if "saldo anterior" in _normalizar(hist):
                continue
            linhas.append({
                "data": data_corrente,
                "historico": hist,
                "documento": documento,
                "valor": valor,
            })
    return _df(linhas, conta)


# --------------------------------------------------------------------------
# GENÉRICO (banco desconhecido) — TENTA o padrão comum, mas AVISA.
# --------------------------------------------------------------------------
def _parse_generico_incerto(paginas: list[str], conta: str) -> pd.DataFrame:
    linhas: list[dict] = []
    for txt in paginas:
        for raw in txt.split("\n"):
            ln = raw.strip()
            m = _RE_DATA_BR.match(ln)
            mv = _RE_DOIS_NUMS_FIM.search(ln)
            if not (m and mv):
                continue
            valor = _num_br(mv.group(1))
            corpo = ln[m.end():mv.start()].strip()
            dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
            linhas.append({
                "data": pd.Timestamp(int(yyyy), int(mm), int(dd)),
                "historico": corpo,
                "documento": "",
                "valor": valor,
            })
    df = _df(linhas, conta)
    df.attrs["parser_incerto"] = True
    df.attrs["aviso"] = (
        "Banco não reconhecido: li este extrato pelo padrão comum (data + valor + "
        "saldo), mas NÃO tenho certeza do layout. Confira os valores antes de usar."
    )
    return df


def carregar_extrato_pdf_generico(
    arquivo: Any, conta: str = "—", ano_referencia: int | None = None
) -> pd.DataFrame:
    """Lê um extrato PDF não-Itaú, detectando o banco e tratando o layout."""
    paginas = _ler_paginas(arquivo)
    texto1 = paginas[0] if paginas else ""
    banco = detectar_banco(texto1)

    if banco == "sicredi":
        df = _parse_sicredi(paginas, conta)
    elif banco == "bradesco":
        df = _parse_bradesco(paginas, conta)
    elif banco == "caixa":
        df = _parse_caixa(paginas, conta)
    else:
        df = _parse_generico_incerto(paginas, conta)

    df.attrs.setdefault("banco_detectado", banco)
    return df
