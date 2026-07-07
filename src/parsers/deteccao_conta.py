"""Detecção automática da conta a partir do CONTEÚDO do extrato.

Resolve o problema de ter que renomear o arquivo: o extrato de cada banco traz
banco + agência + conta no cabeçalho. Este módulo lê esse cabeçalho e devolve a
identidade da conta, independente do nome do arquivo.

Formatos vistos em extratos reais LLE:
  - Bradesco : "Bradesco Net Empresa" ... "Agência: 3370  Conta: 151490-3"
  - Sicredi  : "Cooperativa: 4501" / "Conta: 47001-5" / "Associado: LLE FERRAGENS"
  - Santander: "AGENCIA 3455 CONTA 130033115" (termos CONTAMAX/CORBAN)
  - Caixa    : "GERENCIADOR CAIXA" ... "Conta: 4263 | 1292 | 000577224045-1"
  - Itaú     : tratado de forma genérica (procura agência/conta); cai na lista
               de escolha quando não houver certeza.

Regra de ouro: quando não achar com segurança, NÃO chuta — devolve o que
conseguiu e marca `confianca="baixa"` para a tela oferecer a lista de escolha.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ContaDetectada:
    banco: str = ""
    agencia: str = ""
    conta: str = ""
    conta_digitos: str = ""   # só dígitos, para casar com o Sankhya
    empresa: str = ""
    confianca: str = "baixa"  # "alta" quando achou banco + conta

    @property
    def identificador(self) -> str:
        partes = [p for p in (self.banco, self.agencia, self.conta) if p]
        return "-".join(partes) if partes else ""


def _texto_cabecalho(arquivo) -> str:
    """Extrai o texto das primeiras linhas/página do extrato (xls/xlsx/csv/pdf)."""
    nome = str(getattr(arquivo, "name", "") or "").lower()
    if hasattr(arquivo, "seek"):
        try:
            arquivo.seek(0)
        except Exception:
            pass
    if nome.endswith(".pdf"):
        # tenta pdfplumber (layout) e cai pra pypdf
        try:
            import pdfplumber
            with pdfplumber.open(arquivo) as pdf:
                return (pdf.pages[0].extract_text() or "")[:2500]
        except Exception:
            pass
        try:
            from pypdf import PdfReader
            if hasattr(arquivo, "seek"):
                arquivo.seek(0)
            return (PdfReader(arquivo).pages[0].extract_text() or "")[:2500]
        except Exception:
            return ""
    # planilhas
    try:
        import pandas as pd
        if nome.endswith(".csv"):
            df = pd.read_csv(arquivo, header=None, nrows=15, dtype=str, sep=None, engine="python")
        else:
            df = pd.read_excel(arquivo, header=None, nrows=15, dtype=str)
        linhas = []
        for _, row in df.iterrows():
            linhas.append(" ".join(str(x) for x in row.tolist() if str(x) != "nan"))
        return "\n".join(linhas)[:2500]
    except Exception:
        return ""


def _empresa(txt: str) -> str:
    m = re.search(r"(?:cliente|associado)\s*[:|]?\s*([A-Za-zÀ-Ú][A-Za-zÀ-Ú .&]{3,60})", txt, re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def detectar_conta_extrato(arquivo) -> ContaDetectada:
    """Lê o cabeçalho do extrato e devolve a conta detectada."""
    txt = _texto_cabecalho(arquivo)
    if not txt:
        return ContaDetectada()
    u = txt.upper()

    # --- banco (Santander antes de Caixa: "CAIXA" pode aparecer em texto Santander) ---
    if "BRADESCO" in u:
        banco = "Bradesco"
    elif "SICREDI" in u or "COOPERATIVA" in u or "ASSOCIADO" in u:
        banco = "Sicredi"
    elif "SANTANDER" in u or "CONTAMAX" in u or "CORBAN" in u:
        banco = "Santander"
    elif "GERENCIADOR" in u or "CAIXA" in u:
        banco = "Caixa"
    elif "ITAU" in u or "ITAÚ" in u:
        banco = "Itaú"
    else:
        banco = ""

    ag = conta = ""

    if banco == "Bradesco":
        m = re.search(r"AG[ÊE]NCIA\s*[:\-]?\s*(\d+)\s*CONTA\s*[:\-]?\s*([\d.\-]+)", u)
        if m:
            ag, conta = m.group(1), m.group(2)
    elif banco == "Sicredi":
        ma = re.search(r"COOPERATIVA\s*[:|\-]?\s*(\d+)", u)
        mc = re.search(r"CONTA\s*[:|\-]?\s*([\d.\-]+)", u)
        ag = ma.group(1) if ma else ""
        conta = mc.group(1) if mc else ""
    elif banco == "Santander":
        m = re.search(r"AG[ÊE]NCIA\s*[:\-]?\s*(\d+)\s*CONTA\s*[:\-]?\s*([\d.\-]+)", u)
        if m:
            ag, conta = m.group(1), m.group(2)
    elif banco == "Caixa":
        # "Conta: 4263 | 1292 | 000577224045-1"  (agência | operação | conta)
        m = re.search(r"CONTA\s*[:\-]?\s*(\d+)\s*\|\s*(\d+)\s*\|\s*([\d.\-]+)", u)
        if m:
            ag, conta = m.group(1), m.group(3)
    else:
        # Itaú / desconhecido: tentativa genérica
        ma = re.search(r"AG[ÊE]NCIA\s*[:\-]?\s*(\d+)", u)
        mc = re.search(r"CONTA\s*[:\-]?\s*([\d.\-]{4,})", u)
        ag = ma.group(1) if ma else ""
        conta = mc.group(1) if mc else ""

    det = ContaDetectada(
        banco=banco, agencia=ag.strip(), conta=conta.strip(),
        conta_digitos=re.sub(r"\D", "", conta), empresa=_empresa(txt),
    )
    det.confianca = "alta" if (banco and det.conta_digitos) else "baixa"
    return det
