"""Leitura do extrato bancário padronizado.

Formato esperado: planilha com colunas Data, Histórico, Documento (opcional)
e Valor (R$) — uma ou múltiplas abas (cada aba pode ser um dia).
O valor já vem com sinal: negativo para saída, positivo para entrada.
"""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd


COLUNAS_ESPERADAS_BANCO = ["data", "historico", "documento", "valor", "conta"]


def _normalizar_nome_coluna(nome: str) -> str:
    """Tira acentos, caixa, espaços e parênteses para comparar cabeçalhos."""
    if not isinstance(nome, str):
        return ""
    s = nome.strip().lower()
    s = (
        s.replace("á", "a").replace("ã", "a").replace("â", "a").replace("à", "a")
         .replace("é", "e").replace("ê", "e")
         .replace("í", "i")
         .replace("ó", "o").replace("ô", "o").replace("õ", "o")
         .replace("ú", "u").replace("ü", "u")
         .replace("ç", "c")
    )
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[()/$.\-]", "", s)
    return s


def _mapear_colunas(df: pd.DataFrame) -> dict[str, str]:
    """Mapeia colunas do arquivo para nomes canônicos."""
    canonicos = {
        "data": ["data", "datalancamento", "dtlancamento"],
        "historico": ["historico", "descricao", "memo", "lancamento", "movimentacao"],
        "documento": ["documento", "doc", "numdoc", "numerodoc", "dcto"],
        # "valorr" cobre 'Valor (R$)' depois da normalização que remove parênteses
        "valor": ["valor", "valorr", "valorrs", "vlrlancamento", "vlr"],
        # extratos com Crédito/Débito em colunas separadas (ex.: Bradesco .xls)
        "credito": ["credito", "creditor", "creditors", "credit"],
        "debito": ["debito", "debitor", "debitors", "debit"],
        "saldo": ["saldo", "saldor", "saldors"],
    }
    encontrados: dict[str, str] = {}
    for col_real in df.columns:
        norm = _normalizar_nome_coluna(str(col_real))
        for canonico, aliases in canonicos.items():
            if norm in aliases and canonico not in encontrados:
                encontrados[canonico] = col_real
                break
    return encontrados


def _detectar_linha_cabecalho(df: pd.DataFrame, max_linhas: int = 20) -> int | None:
    """v3.7: Procura nas primeiras `max_linhas` qual contém o cabeçalho real.

    Critério: linha onde pelo menos 2 células batem com nomes canônicos
    (data + valor, ou data + lançamento/histórico).
    """
    canonicos_aceitos = {
        "data", "datalancamento", "dtlancamento",
        "historico", "descricao", "memo", "lancamento", "movimentacao",
        "documento", "doc", "numdoc", "numerodoc", "dcto",
        "valor", "valorr", "valorrs", "vlrlancamento", "vlr",
        "credito", "creditor", "creditors", "credit",
        "debito", "debitor", "debitors", "debit",
        "saldo", "saldor", "saldors",
    }
    n = min(len(df), max_linhas)
    for i in range(n):
        linha = df.iloc[i]
        batidas = 0
        for celula in linha:
            norm = _normalizar_nome_coluna(str(celula))
            if norm in canonicos_aceitos:
                batidas += 1
                if batidas >= 2:
                    return i
    return None


def _parse_data_robusto(serie: pd.Series, ano_referencia: int | None = None) -> pd.Series:
    """Parser de data que respeita formato brasileiro (DD/MM/YYYY) E formato ISO.

    Datas brasileiras: 04/05/2026 → 4 de maio.
    Datas ISO: 2026-05-04 ou 2026-05-04 00:00:00 → 4 de maio.
    Datas SEM ano: 04/05 → completa com `ano_referencia` (ou ano corrente).
    Datas serial Excel: 46162 (número) → converte usando origem 1899-12-30.
    Datetimes nativos passam direto.
    """
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce")

    # v5.28: trata datas serial do Excel (números 30000-80000 = anos 1982-2119)
    if pd.api.types.is_numeric_dtype(serie):
        try:
            return pd.to_datetime(serie, origin="1899-12-30", unit="D", errors="coerce")
        except Exception:
            pass

    str_serie = serie.astype(str).str.strip()

    # v5.28: detecta serial Excel em forma de string ("46162", "46150" etc)
    parece_serial = str_serie.str.match(r"^\d{4,5}(\.\d+)?$", na=False)
    if parece_serial.any() and not str_serie.str.contains("/", na=False).any():
        # se TUDO parece serial e nada tem barra, trata como serial
        try:
            nums = pd.to_numeric(str_serie, errors="coerce")
            return pd.to_datetime(nums, origin="1899-12-30", unit="D", errors="coerce")
        except Exception:
            pass

    # Detecta padrão DD/MM (sem ano) — extrai-se das datas SEM ano e adiciona o ano de referência
    padrao_sem_ano = r"^\d{1,2}/\d{1,2}\s*$"
    parece_sem_ano = str_serie.str.match(padrao_sem_ano, na=False)
    if parece_sem_ano.any():
        if ano_referencia is None:
            from datetime import date
            ano_referencia = date.today().year
        str_serie = str_serie.where(
            ~parece_sem_ano,
            str_serie + f"/{ano_referencia}",
        )

    # BUGFIX: não decidir o formato da coluna INTEIRA com parece_iso.all() — bastava
    # UMA célula vazia/'nan' para o `.all()` virar False e jogar TODAS as datas no
    # ramo dayfirst, que trocava mês/dia das ISO ('2026-05-08' virava ago/2026) e
    # descartava dia >= 13 ('2026-05-18' → mês 18 → NaT, linha perdida no dropna).
    # Agora cada linha é parseada conforme o SEU próprio formato.
    resultado = pd.Series(pd.NaT, index=str_serie.index, dtype="datetime64[ns]")
    mask_iso = str_serie.str.match(r"^\d{4}-\d{2}-\d{2}", na=False)
    if mask_iso.any():
        # ISO (YYYY-MM-DD...): ordem ano-mês-dia é inequívoca, dayfirst não se aplica.
        # format="ISO8601" parseia com e sem hora ('2026-05-29' e '2026-05-29 00:00:00')
        # sem o pandas tentar inferir UM único formato pro conjunto (o que viraria NaT
        # nas linhas sem hora quando misturadas com linhas com hora).
        try:
            iso_vals = pd.to_datetime(str_serie[mask_iso], format="ISO8601", errors="coerce")
        except (ValueError, TypeError):
            iso_vals = pd.to_datetime(str_serie[mask_iso], errors="coerce")
        resultado.loc[mask_iso] = iso_vals
    mask_br = ~mask_iso
    if mask_br.any():
        # Brasileiro DD/MM/YYYY (inclui datas que receberam o ano de referência acima)
        resultado.loc[mask_br] = pd.to_datetime(
            str_serie[mask_br], dayfirst=True, errors="coerce"
        )
    return resultado


def _parse_valor_brl(v: Any) -> float:
    """Converte string '-1.000,00' ou '1000.00' para float."""
    if pd.isna(v):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return 0.0
    # Remove R$
    s = s.replace("R$", "").replace(" ", "").strip()
    # Formato brasileiro: 1.234,56 → 1234.56
    if "," in s and "." in s:
        # ambos: ponto é milhar, vírgula é decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _eh_pdf(arquivo: Any) -> bool:
    """True se o arquivo é um PDF (por extensão .pdf ou bytes mágicos '%PDF')."""
    nome = getattr(arquivo, "name", None) or (arquivo if isinstance(arquivo, str) else "")
    if str(nome).lower().endswith(".pdf"):
        return True
    if hasattr(arquivo, "read"):
        try:
            pos = arquivo.tell()
        except Exception:
            pos = None
        try:
            arquivo.seek(0)
            cabecalho = arquivo.read(5)
            if isinstance(cabecalho, str):
                cabecalho = cabecalho.encode("latin-1", "ignore")
        except Exception:
            cabecalho = b""
        finally:
            try:
                arquivo.seek(pos if pos is not None else 0)
            except Exception:
                pass
        return cabecalho.startswith(b"%PDF")
    return False


def carregar_extrato_banco(
    arquivo: Any,
    conta: str,
    ano_referencia: int | None = None,
) -> pd.DataFrame:
    """Lê o(s) extrato(s) bancário(s) padronizado(s) e retorna DataFrame canônico.

    Aceita arquivo .xlsx/.xls com 1 ou mais abas. Cada aba é tratada como um pedaço
    do extrato (datas diferentes geralmente).

    Retorna DataFrame com colunas: data, historico, documento, valor, conta.

    v5.30: detecta PDF (por extensão .pdf ou pelos bytes mágicos "%PDF").
    v5.31: detecta o BANCO pelo cabeçalho — Itaú vai pro parser dedicado;
    Sicredi/Bradesco/Caixa (e desconhecidos) vão pro leitor genérico.
    XLS/XLSX seguem o caminho normal.
    """
    if _eh_pdf(arquivo):
        from .extrato_pdf_generico import (
            detectar_banco,
            carregar_extrato_pdf_generico,
            _texto_pagina1,
        )
        banco = detectar_banco(_texto_pagina1(arquivo))  # detecção rápida (pypdf, 1ª pág)
        try:
            arquivo.seek(0)
        except Exception:
            pass
        if banco == "itau":
            from .extrato_pdf_itau import carregar_extrato_pdf_itau
            return carregar_extrato_pdf_itau(
                arquivo, conta=conta, ano_referencia=ano_referencia
            )
        return carregar_extrato_pdf_generico(
            arquivo, conta=conta, ano_referencia=ano_referencia
        )

    # Aceita tanto file_uploader do streamlit quanto path
    if hasattr(arquivo, "read"):
        # UploadedFile do Streamlit
        nome = getattr(arquivo, "name", "")
        try:
            arquivo.seek(0)
        except Exception:
            pass
        # v5.54: engine pela ASSINATURA do conteúdo, não pela extensão —
        # bancos/ERPs às vezes exportam xlsx renomeado de .xls (e vice-versa).
        _cab = arquivo.read(4)
        try:
            arquivo.seek(0)
        except Exception:
            pass
        if _cab[:4] == b"PK\x03\x04":
            engine = "openpyxl"
        elif _cab[:4] == b"\xd0\xcf\x11\xe0":
            engine = "xlrd"
        else:
            engine = "xlrd" if nome.lower().endswith(".xls") else "openpyxl"
        sheets = pd.read_excel(arquivo, sheet_name=None, engine=engine, dtype=str)
    else:
        try:
            with open(arquivo, "rb") as _fh:
                _cab = _fh.read(4)
        except Exception:
            _cab = b""
        if _cab[:4] == b"PK\x03\x04":
            engine = "openpyxl"
        elif _cab[:4] == b"\xd0\xcf\x11\xe0":
            engine = "xlrd"
        else:
            engine = "xlrd" if str(arquivo).lower().endswith(".xls") else "openpyxl"
        sheets = pd.read_excel(arquivo, sheet_name=None, engine=engine, dtype=str)

    frames: list[pd.DataFrame] = []
    for _, df_aba in sheets.items():
        if df_aba.empty:
            continue
        df_aba = df_aba.dropna(how="all").reset_index(drop=True)
        if df_aba.empty:
            continue

        # Remove colunas totalmente vazias (alguns extratos têm colunas-fantasma)
        df_aba = df_aba.dropna(axis=1, how="all")
        if df_aba.empty or len(df_aba.columns) == 0:
            continue

        # v3.7: alguns extratos (ex: Itaú PDF→XLS) têm várias linhas de metadados
        # antes do cabeçalho real. Vamos procurar dinamicamente a linha que contém
        # o cabeçalho (presença de 'Data' + 'Valor' ou 'Lançamento'/'Histórico').
        mapa = _mapear_colunas(df_aba)

        def _tem_valor(m):
            return ("valor" in m) or ("credito" in m) or ("debito" in m)

        if "data" not in mapa or not _tem_valor(mapa):
            # Procura nas primeiras 20 linhas qual delas é o cabeçalho real
            header_linha = _detectar_linha_cabecalho(df_aba, max_linhas=20)
            if header_linha is not None:
                df_aba.columns = [str(c) for c in df_aba.iloc[header_linha].tolist()]
                df_aba = df_aba.iloc[header_linha + 1:].reset_index(drop=True)
                df_aba = df_aba.dropna(axis=1, how="all")
                mapa = _mapear_colunas(df_aba)

        if "data" not in mapa or not _tem_valor(mapa):
            # aba não parece ser extrato — pula
            continue

        out = pd.DataFrame()
        out["data"] = _parse_data_robusto(df_aba[mapa["data"]], ano_referencia=ano_referencia)
        out["historico"] = df_aba[mapa["historico"]].fillna("") if "historico" in mapa else ""
        out["documento"] = (
            df_aba[mapa["documento"]].fillna("") if "documento" in mapa else ""
        )
        # valor: coluna única OU Crédito(+) − Débito(−).
        # Crédito e Débito podem vir com ou sem sinal; usamos o módulo de cada um
        # (crédito soma, débito subtrai) para não depender de como o banco assina.
        if "valor" in mapa:
            out["valor"] = df_aba[mapa["valor"]].apply(_parse_valor_brl)
        else:
            cred = df_aba[mapa["credito"]].apply(_parse_valor_brl).abs() if "credito" in mapa else 0.0
            deb = df_aba[mapa["debito"]].apply(_parse_valor_brl).abs() if "debito" in mapa else 0.0
            cred = cred.fillna(0.0) if hasattr(cred, "fillna") else cred
            deb = deb.fillna(0.0) if hasattr(deb, "fillna") else deb
            out["valor"] = cred - deb
        out["conta"] = conta
        # v5.47: guarda o SALDO CRU da linha (quando a coluna existe) só para o
        # dedup abaixo. Duas transações reais idênticas têm saldos correntes
        # DIFERENTES; o recap do Bradesco repete a linha com o MESMO saldo.
        if "saldo" in mapa:
            _sraw = df_aba[mapa["saldo"]]
            _stem = _sraw.notna() & (_sraw.astype(str).str.strip() != "")
            out["_saldo_dedup"] = [
                _parse_valor_brl(x) if t else pd.NA
                for x, t in zip(_sraw.tolist(), _stem.tolist())
            ]
        else:
            out["_saldo_dedup"] = pd.NA

        # descarta linhas que NÃO são transação: totalizadores ("Total") e
        # cabeçalhos repetidos no meio do extrato ("Data"/"Lançamento").
        _h = out["historico"].astype(str).str.strip().str.upper()
        _lixo = _h.isin(["TOTAL", "TOTAIS", "LANÇAMENTO", "LANCAMENTO", "DATA", "SALDO ANTERIOR", "SALDO FINAL", "HISTÓRICO", "HISTORICO"])
        out = out[~_lixo].reset_index(drop=True)

        # alguns extratos (ex.: Bradesco) trazem um recap "Últimos Lançamentos"
        # que REPETE linhas do corpo principal. v5.55: dedup SÓ COM PROVA —
        # remove apenas linha cuja (data, histórico, valor, SALDO PREENCHIDO)
        # repete: o recap repete a linha com o MESMO saldo corrente. Linha SEM
        # saldo NUNCA é removida: no Itaú diário as transações não têm saldo e
        # 11 tarifas TAR C/C SISPAG de R$ 0,32 no mesmo dia são 11 cobranças
        # REAIS — o dedup antigo colapsava em 1 e o extrato "perdia" R$ 6,08
        # (caso real ITAU KING, 19 tarifas engolidas). Célula vazia agora vira
        # NA (não 0,0), então não forma chave repetida.
        _tem_saldo_linha = out["_saldo_dedup"].notna()
        _dup_provada = out.duplicated(
            subset=["data", "historico", "valor", "_saldo_dedup"], keep="first"
        ) & _tem_saldo_linha
        out = out[~_dup_provada].reset_index(drop=True)
        out = out.drop(columns=["_saldo_dedup"], errors="ignore")

        # remove linhas sem data ou valor zero/sem valor — v5.47: ANTES de emitir
        # as linhas de saldo, senão um SALDO FINAL de R$ 0,00 legítimo (conta
        # zerada) era apagado pelo filtro de valor.
        out = out.dropna(subset=["data"])
        out = out[out["valor"] != 0].reset_index(drop=True)

        # saldo do extrato (coluna "Saldo (R$)"): emite saldo inicial e final,
        # para o fechamento (saldo inicial + receitas − despesas = saldo final).
        # v5.47 — três correções, validadas com extrato Sicredi real:
        #   1. A linha "Saldo Anterior" costuma vir SEM DATA (é o saldo antes da
        #      1ª transação). Antes era descartada e o "inicial" virava o saldo
        #      DEPOIS da 1ª transação (errado). Agora ela é aceita sem data.
        #   2. O saldo FINAL agora vem da última linha COM TRANSAÇÃO REAL
        #      (célula de valor preenchida). Antes pegava rodapés de
        #      "lançamentos futuros/agendados" (ex.: CESTA EMPRESARIAL com data
        #      além do período e saldo vazio → virava 0,00).
        #   3. Sem linha "Saldo Anterior", o inicial é DERIVADO com aritmética
        #      exata: saldo da 1ª transação − valor da 1ª transação.
        if "saldo" in mapa:
            _saldo_raw = df_aba[mapa["saldo"]]
            _tem_saldo_cel = _saldo_raw.notna() & (_saldo_raw.astype(str).str.strip() != "")
            _saldo_col = _saldo_raw.apply(_parse_valor_brl)
            _hist_raw = (df_aba[mapa["historico"]].fillna("").astype(str) if "historico" in mapa else pd.Series([""] * len(df_aba)))
            _dt = _parse_data_robusto(df_aba[mapa["data"]], ano_referencia=ano_referencia)
            if "valor" in mapa:
                _vtx_raw = df_aba[mapa["valor"]]
                _tem_vtx = _vtx_raw.notna() & (_vtx_raw.astype(str).str.strip() != "")
                _vtx = _vtx_raw.apply(_parse_valor_brl)
            else:
                _tem_vtx = pd.Series([False] * len(df_aba))
                _vtx = pd.Series([0.0] * len(df_aba))
            _val = pd.DataFrame({
                "data": _dt.values,
                "saldo": _saldo_col.values,
                "hist": _hist_raw.str.upper().values,
                "vtx": _vtx.values,
                "tem_vtx": _tem_vtx.values,
            })
            _val = _val[_tem_saldo_cel.values]
            _val = _val[~_val["hist"].str.strip().isin(["TOTAL", "TOTAIS"])]
            if not _val.empty:
                # 1) linha "SALDO ANTERIOR" — aceita SEM data
                _ant = _val[_val["hist"].str.contains("SALDO ANTERIOR", na=False)]
                # 2) saldo final — última linha COM transação real (data + valor)
                _pool_fim = _val.dropna(subset=["data"])
                _pool_fim = _pool_fim[_pool_fim["tem_vtx"]]
                # v5.54: TRAVA DE CONSISTÊNCIA — quando o extrato tem saldo
                # corrido (saldo nas linhas de transação), só emite saldos se o
                # encadeamento confere: saldo[i] ≈ saldo[i-1] + valor[i] em ≥90%
                # dos pares. O Santander diário vem em ordem inversa com saldo
                # espúrio na 1ª linha — sem a trava, o app exibiria inicial/final
                # errados. Extratos estilo Itaú (saldo só em linhas "S A L D O")
                # não têm corrido para validar e seguem o caminho de fallback.
                if not _pool_fim.empty and len(_pool_fim) >= 3:
                    _ok_fwd = _tot_par = 0
                    _sv = _pool_fim[["saldo", "vtx"]].to_numpy()
                    for _i in range(1, len(_sv)):
                        _tot_par += 1
                        if abs((_sv[_i - 1][0] + _sv[_i][1]) - _sv[_i][0]) < 0.011:
                            _ok_fwd += 1
                    if _tot_par >= 2 and (_ok_fwd / _tot_par) < 0.9:
                        _pool_fim = _pool_fim.iloc[0:0]  # descarta: corrido não confere
                if _pool_fim.empty:
                    _pool_fim = _val.dropna(subset=["data"])
                    _pool_fim = _pool_fim[~_pool_fim["tem_vtx"]]  # só marcadores tipo "S A L D O"
                if not _pool_fim.empty:
                    _pool_fim = _pool_fim.sort_values("data")
                    _lin_fim = _pool_fim.iloc[-1]
                    _data_min = _pool_fim["data"].min()
                    if not _ant.empty:
                        _lin_ini_saldo = float(_ant.iloc[0]["saldo"])
                        _data_ini = _ant.iloc[0]["data"] if pd.notna(_ant.iloc[0]["data"]) else _data_min
                    else:
                        # 3) deriva o inicial: saldo da 1ª transação − valor dela
                        _prim = _pool_fim.iloc[0]
                        _lin_ini_saldo = round(float(_prim["saldo"]) - float(_prim["vtx"]), 2)
                        _data_ini = _data_min
                    _saldos = pd.DataFrame([
                        {"data": _data_ini, "historico": "SALDO ANTERIOR", "documento": "", "valor": _lin_ini_saldo, "conta": conta},
                        {"data": _lin_fim["data"], "historico": "SALDO FINAL", "documento": "", "valor": float(_lin_fim["saldo"]), "conta": conta},
                    ])
                    out = pd.concat([out, _saldos], ignore_index=True)

        frames.append(out)

    if not frames:
        return pd.DataFrame(columns=COLUNAS_ESPERADAS_BANCO)

    resultado = pd.concat(frames, ignore_index=True)
    resultado["historico"] = resultado["historico"].astype(str).str.strip()
    resultado["documento"] = resultado["documento"].astype(str).str.strip()
    resultado["origem"] = "banco"
    return resultado
