"""Leitura do extrato mensal do Itaú em PDF — v5.30.

CONTEXTO:
- O XLS oficial do Itaú e o XLSX convertido do PDF já são lidos pelo
  `carregar_extrato_banco` (formato com colunas delimitadas).
- O PDF mensal do Itaú NÃO é delimitado: é texto posicionado em colunas
  (Data | Lançamento | Ag./Origem | Valor (R$) | Saldo (R$)).
- Este módulo lê esse PDF direto e devolve o MESMO schema canônico que o
  `carregar_extrato_banco` produz, pra que trocar o formato de entrada NÃO
  altere nenhum total exibido no app.

ESTRATÉGIA:
- Usa pdfplumber pra extrair palavras COM posição (x0/x1/top).
- Agrupa palavras por linha (top arredondado).
- Cada linha de dados começa com uma data dd/mm.
- Separa Valor de Saldo pela posição x (a coluna Saldo fica bem à direita da
  coluna Valor). O limite é derivado do cabeçalho de cada página (meio entre
  "Valor" e "Saldo"), com fallback fixo.
- Linhas que só têm número na coluna Saldo (as marcações diárias
  "S A L D O 1,00" e "SALDO ANTERIOR") são DESCARTADAS: são ruído, não
  movimentação. Toda métrica real (movimentação, aplicação, resgate,
  rendimento) é idêntica ao caminho XLSX — validado contra o mesmo extrato.

PARIDADE COM O CAMINHO XLSX:
- `documento` fica vazio (o caminho XLSX não mapeia "Ag./Origem" pra
  documento). Mantemos vazio aqui de propósito, pra não mudar o
  comportamento do matching ao trocar de formato.

LIMITAÇÃO CONHECIDA:
- O ano é inferido do cabeçalho "Data: dd/mm/yyyy" (ou do parâmetro
  ano_referencia). Extratos que cruzam a virada de ano (dez→jan) precisariam
  de tratamento adicional; os extratos da LLE são mensais e não cruzam.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

import pandas as pd


COLUNAS_ESPERADAS_BANCO = ["data", "historico", "documento", "valor", "conta"]

# dd/mm no início da linha (ex: 04/05)
_RE_DATA = re.compile(r"^\d{2}/\d{2}$")
# valor brasileiro: 1.234,56 / -6.140,92 / 0,07
_RE_VALOR = re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}$")
# ano no cabeçalho
_RE_ANO_CABECALHO = re.compile(r"Data:\s*\d{2}/\d{2}/(\d{4})")

# Fallback do limite x entre coluna Valor e Saldo, caso o cabeçalho não seja
# localizado numa página. Derivado do layout real do extrato Itaú Empresas.
_X_SPLIT_VALOR_SALDO_FALLBACK = 500.0
# Banda x onde aparece a coluna Ag./Origem (números 9014, 23, 3190...).
_AG_X_MIN, _AG_X_MAX = 260.0, 400.0


def _to_float_brl(s: str) -> float:
    """'-6.140,92' -> -6140.92"""
    return float(s.replace(".", "").replace(",", "."))


def _abrir_pdfplumber(arquivo: Any):
    """Abre o PDF com pdfplumber a partir de file-like (Streamlit) ou path.

    Import preguiçoso: só exige pdfplumber quando um PDF é realmente carregado,
    pra não quebrar o caminho XLS/XLSX se a dependência faltar.
    """
    try:
        import pdfplumber  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Leitura de extrato em PDF requer o pacote 'pdfplumber'. "
            "Adicione 'pdfplumber' ao requirements.txt."
        ) from e

    if hasattr(arquivo, "read"):
        try:
            arquivo.seek(0)
        except Exception:
            pass
        dados = arquivo.read()
        return pdfplumber.open(io.BytesIO(dados))
    return pdfplumber.open(arquivo)


def _descobrir_split_valor_saldo(words: list[dict]) -> float:
    """Acha o x que separa a coluna Valor da coluna Saldo no cabeçalho da página.

    Procura as palavras "Valor" e "Saldo"; usa o ponto médio entre elas.
    Retorna o fallback se não achar ambas.
    """
    x_valor = x_saldo = None
    for w in words:
        t = w["text"].strip().lower().rstrip(":")
        if t == "valor" and x_valor is None:
            x_valor = w["x1"]
        elif t == "saldo" and x_saldo is None:
            x_saldo = w["x0"]
    if x_valor is not None and x_saldo is not None and x_saldo > x_valor:
        return (x_valor + x_saldo) / 2.0
    return _X_SPLIT_VALOR_SALDO_FALLBACK


def carregar_extrato_pdf_itau(
    arquivo: Any,
    conta: str,
    ano_referencia: int | None = None,
) -> pd.DataFrame:
    """Lê o extrato mensal do Itaú em PDF e devolve o DataFrame canônico.

    Args:
        arquivo: file-like (Streamlit UploadedFile) ou path do PDF.
        conta: rótulo da conta (vai pra coluna 'conta').
        ano_referencia: ano pras datas dd/mm. Se None, infere do cabeçalho
            "Data: dd/mm/yyyy"; se não achar, usa o ano corrente.

    Returns:
        DataFrame com colunas: data, historico, documento, valor, conta, origem.
    """
    linhas: list[dict] = []

    with _abrir_pdfplumber(arquivo) as pdf:
        # Resolve o ano de referência uma vez.
        ano = ano_referencia
        if ano is None and pdf.pages:
            texto0 = pdf.pages[0].extract_text() or ""
            m = _RE_ANO_CABECALHO.search(texto0)
            ano = int(m.group(1)) if m else date.today().year

        for pagina in pdf.pages:
            words = pagina.extract_words()
            if not words:
                continue

            x_split = _descobrir_split_valor_saldo(words)

            # Agrupa palavras por linha usando o topo arredondado.
            por_linha: dict[int, list[dict]] = {}
            for w in words:
                por_linha.setdefault(round(w["top"]), []).append(w)

            for chave in sorted(por_linha):
                toks = sorted(por_linha[chave], key=lambda w: w["x0"])
                if not toks or not _RE_DATA.match(toks[0]["text"]):
                    continue

                data_str = toks[0]["text"]
                desc_toks: list[str] = []
                valor_str: str | None = None

                for w in toks[1:]:
                    t = w["text"]
                    if _RE_VALOR.match(t):
                        if w["x1"] <= x_split:
                            # coluna Valor — primeiro valor encontrado manda
                            if valor_str is None:
                                valor_str = t
                        # else: coluna Saldo — ignorado (ruído pra conciliação)
                    elif _AG_X_MIN < w["x0"] < _AG_X_MAX and re.fullmatch(r"\d{2,6}", t):
                        # Ag./Origem — não vai pra 'documento' (paridade com XLSX)
                        continue
                    else:
                        desc_toks.append(t)

                # Sem número na coluna Valor => linha de saldo diário / saldo
                # anterior (só Saldo). Descarta: é ruído, não movimentação.
                if valor_str is None:
                    continue

                try:
                    dia = int(data_str[0:2])
                    mes = int(data_str[3:5])
                    data = pd.Timestamp(year=ano, month=mes, day=dia)
                except ValueError:
                    continue

                linhas.append({
                    "data": data,
                    "historico": " ".join(desc_toks).strip(),
                    "documento": "",
                    "valor": _to_float_brl(valor_str),
                    "conta": conta,
                })

    if not linhas:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS_BANCO)

    df = pd.DataFrame(linhas)
    df = df.dropna(subset=["data"])
    df = df[df["valor"] != 0].reset_index(drop=True)
    df["historico"] = df["historico"].astype(str).str.strip()
    df["documento"] = df["documento"].astype(str).str.strip()
    df["origem"] = "banco"
    return df
