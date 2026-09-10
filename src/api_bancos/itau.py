"""
src/api_bancos/itau.py — Cliente da API de Extrato Itaú BBA

Fluxo (baseado no PDF oficial Itaú BBA):
  1. Obter access_token via OAuth2 (client_credentials) com mTLS
  2. Chamar endpoint de extrato com Bearer token + mTLS
  3. Converter JSON de resposta em DataFrame pandas com colunas
     compatíveis com o formato interno do app

Credenciais são lidas de st.secrets["itau"]:
  - client_id
  - client_secret
  - certificado_crt (PEM completo, com BEGIN/END CERTIFICATE)
  - chave_privada_key (PEM completo, com BEGIN/END PRIVATE KEY)
  - contas.{apelido}.conta         (formato XXXX00YYYYYZ = agência + 00 + conta + DAC)
  - contas.{apelido}.nome_sankhya  (texto exato da coluna "Descrição" do relatório
                                     Sankhya — ex.: "ITAU PISA")

Ambiente:
  Produção  · sts.itau.com.br + account-statement.api.itau.com
  Homologação · sts.rdhi.com.br + account-statement.api.hom.itau.com

Requisitos: requests>=2.32
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests


# ==============================================================================
# CONFIG DE AMBIENTE
# ==============================================================================
URLS_PROD = {
    "token": "https://sts.itau.com.br/api/oauth/token",
    "extrato_base": "https://account-statement.api.itau.com/account-statement/v1/statements",
}
URLS_HOMOL = {
    "token": "https://sts.rdhi.com.br/api/oauth/token",
    "extrato_base": "https://account-statement.api.hom.itau.com/account-statement/v1/statements",
}


# ==============================================================================
# DTO E CACHE DE TOKEN
# ==============================================================================
@dataclass
class TokenCache:
    access_token: str
    expira_em: datetime


# Cache de token em memória (por processo). Como o token dura 5 min,
# vale reusar dentro da mesma sessão do Streamlit.
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: Dict[str, TokenCache] = {}

# v5.83: buffer para DEBUG. Guarda o último payload bruto de cada página
# retornada pela API, para o ui_itau.py mostrar quando o parser vier vazio.
# Serve para descobrirmos o FORMATO REAL do JSON que o Itaú entrega
# (que pode diferir da documentação). Reseta a cada nova chamada.
_ULTIMO_DEBUG: Dict[str, Any] = {
    "payloads": [],           # lista de dicts (um por página) — bruto da API
    "http_status": [],        # status HTTP de cada página
    "conta": "",
    "periodo": "",
    "url_base": "",
    "erro": "",
}


# ==============================================================================
# HELPERS
# ==============================================================================
def _limpar_pem(texto: str) -> str:
    """Normaliza um PEM: remove espaços em branco no início/fim de cada linha."""
    if not texto:
        return ""
    linhas = [ln.rstrip() for ln in texto.splitlines()]
    # remove linhas vazias no início/fim mas preserva quebras internas
    while linhas and not linhas[0].strip():
        linhas.pop(0)
    while linhas and not linhas[-1].strip():
        linhas.pop()
    return "\n".join(linhas) + "\n"


def _criar_arquivos_temporarios(cert_pem: str, key_pem: str) -> Tuple[str, str]:
    """Escreve certificado e chave em arquivos temporários protegidos.

    A biblioteca requests exige paths de arquivo para o parâmetro `cert` do mTLS.
    Retorna (path_crt, path_key). Chamador deve remover depois de usar.
    """
    cert_pem = _limpar_pem(cert_pem)
    key_pem = _limpar_pem(key_pem)

    fd_crt, path_crt = tempfile.mkstemp(suffix=".crt", prefix="itau_")
    fd_key, path_key = tempfile.mkstemp(suffix=".key", prefix="itau_")

    try:
        os.write(fd_crt, cert_pem.encode("utf-8"))
        os.write(fd_key, key_pem.encode("utf-8"))
    finally:
        os.close(fd_crt)
        os.close(fd_key)

    # Restringir permissões (Unix; no-op no Windows Streamlit Cloud usa Linux)
    try:
        os.chmod(path_crt, 0o600)
        os.chmod(path_key, 0o600)
    except Exception:
        pass

    return path_crt, path_key


def _remover_arquivos(*paths: str) -> None:
    for p in paths:
        try:
            os.remove(p)
        except Exception:
            pass


# ==============================================================================
# CONFIG A PARTIR DE st.secrets
# ==============================================================================
def _normalizar_conta_registro(valor: Any) -> Dict[str, str]:
    """Normaliza o valor de [itau.contas.<apelido>] em dict {conta, nome_sankhya}.

    Aceita dois formatos por compatibilidade:
      (novo)   [itau.contas.principal]
               conta = "002300788615"
               nome_sankhya = "ITAU PISA"

      (antigo) [itau.contas]
               principal = "002300788615"
               → nome_sankhya = "" (autopreenchimento não vai rodar)

    IMPORTANTE: uma sub-tabela TOML lida via st.secrets NÃO é instance de dict
    puro — vem como AttrDict do Streamlit. Por isso checamos pela interface
    (hasattr get) em vez de isinstance(dict), senão o formato novo cai no
    ramo antigo e a str(AttrDict) polui o dropdown com o dict inteiro.
    """
    if hasattr(valor, "get") and not isinstance(valor, (str, bytes)):
        try:
            return {
                "conta": str(valor.get("conta", "") or "").strip(),
                "nome_sankhya": str(valor.get("nome_sankhya", "") or "").strip(),
            }
        except Exception:
            pass
    # Formato antigo: valor simples (só o número da conta)
    return {"conta": str(valor).strip(), "nome_sankhya": ""}


def _obter_config() -> Dict[str, Any]:
    """Lê credenciais de st.secrets['itau'].

    Retorna dict com: client_id, client_secret, cert_pem, key_pem,
                      ambiente ('prod'|'homol'), contas (dict aninhado).

    Formato de `contas`:
        {
          "principal": {"conta": "002300788615", "nome_sankhya": "ITAU PISA"},
          "king":      {"conta": "0034...",      "nome_sankhya": "ITAU KING"},
          ...
        }

    Lança RuntimeError se algo faltar.
    """
    import streamlit as st

    if "itau" not in st.secrets:
        raise RuntimeError(
            "Credenciais do Itaú não configuradas. "
            "Vá em Streamlit Cloud → Settings → Secrets e adicione a seção [itau]."
        )

    sec = st.secrets["itau"]
    faltando = [k for k in ("client_id", "client_secret", "certificado_crt", "chave_privada_key")
                if k not in sec]
    if faltando:
        raise RuntimeError(
            "Faltam campos no [itau] de Secrets: " + ", ".join(faltando)
        )

    ambiente = str(sec.get("ambiente", "prod")).lower()
    if ambiente not in ("prod", "homol"):
        raise RuntimeError(f"Ambiente Itaú inválido: {ambiente}. Use 'prod' ou 'homol'.")

    contas: Dict[str, Dict[str, str]] = {}
    if "contas" in sec:
        try:
            bruto = dict(sec["contas"])
        except Exception:
            bruto = {}
        for apelido, valor in bruto.items():
            registro = _normalizar_conta_registro(valor)
            if registro["conta"]:
                contas[str(apelido)] = registro

    return {
        "client_id": str(sec["client_id"]).strip(),
        "client_secret": str(sec["client_secret"]).strip(),
        "cert_pem": str(sec["certificado_crt"]),
        "key_pem": str(sec["chave_privada_key"]),
        "ambiente": ambiente,
        "contas": contas,
    }


# ==============================================================================
# OBTENÇÃO DO ACCESS TOKEN
# ==============================================================================
def _obter_access_token(config: Dict[str, Any]) -> str:
    """Faz OAuth2 client_credentials com mTLS. Retorna access_token.

    Usa cache em memória de ~4 minutos (token dura 5 min).
    """
    cache_key = f"{config['ambiente']}:{config['client_id']}"
    agora = datetime.utcnow()

    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached.expira_em > agora:
            return cached.access_token

    urls = URLS_PROD if config["ambiente"] == "prod" else URLS_HOMOL
    url_token = urls["token"]

    path_crt, path_key = _criar_arquivos_temporarios(config["cert_pem"], config["key_pem"])
    try:
        payload = {
            "grant_type": "client_credentials",
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        resp = requests.post(
            url_token,
            data=payload,
            headers=headers,
            cert=(path_crt, path_key),
            timeout=30,
        )
    finally:
        _remover_arquivos(path_crt, path_key)

    if resp.status_code != 200:
        # Erro amigável — evita expor detalhes técnicos demais
        detalhe = ""
        try:
            j = resp.json()
            detalhe = j.get("error_description") or j.get("error") or ""
        except Exception:
            detalhe = resp.text[:200]
        raise RuntimeError(
            f"Falha ao obter token do Itaú (HTTP {resp.status_code}). "
            f"Verifique client_id, client_secret e o certificado. Detalhe: {detalhe}"
        )

    dados = resp.json()
    token = dados.get("access_token")
    if not token:
        raise RuntimeError("Itaú respondeu sem access_token. Contate suporte técnico Itaú.")

    expires_in = int(dados.get("expires_in", 300))  # padrão 5 min
    # Guarda com 30s de margem
    expira_em = datetime.utcnow() + timedelta(seconds=max(30, expires_in - 30))

    with _TOKEN_LOCK:
        _TOKEN_CACHE[cache_key] = TokenCache(access_token=token, expira_em=expira_em)

    return token


# ==============================================================================
# CHAMADA DA API DE EXTRATO
# ==============================================================================
def _chamar_extrato(
    config: Dict[str, Any],
    conta_formatada: str,
    data_inicio: date,
    data_fim: date,
    page: int = 1,
    page_size: int = 1000,
) -> Dict[str, Any]:
    """Chama endpoint de extrato uma vez. Retorna o JSON de resposta."""
    urls = URLS_PROD if config["ambiente"] == "prod" else URLS_HOMOL
    url = f"{urls['extrato_base']}/{conta_formatada}"

    token = _obter_access_token(config)

    path_crt, path_key = _criar_arquivos_temporarios(config["cert_pem"], config["key_pem"])
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-itau-correlationID": str(uuid.uuid4()),
        }
        params = {
            "type": "current_account",
            "start_date": data_inicio.strftime("%Y-%m-%d"),
            "end_date": data_fim.strftime("%Y-%m-%d"),
            "page_size": page_size,
            "page": page,
        }
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            cert=(path_crt, path_key),
            timeout=60,
        )
    finally:
        _remover_arquivos(path_crt, path_key)

    if resp.status_code == 401:
        # Token expirou entre obter e usar; limpa cache e lança para camada acima retry
        with _TOKEN_LOCK:
            _TOKEN_CACHE.clear()
        raise RuntimeError("Token expirou durante a chamada. Tente novamente.")

    if resp.status_code == 404:
        raise RuntimeError(
            f"Conta {conta_formatada} não encontrada no Itaú, ou sem movimentação no período. "
            "Confirme o formato: 4 dígitos agência + 00 + 5 dígitos conta + 1 DAC."
        )

    if resp.status_code != 200:
        detalhe = ""
        try:
            j = resp.json()
            detalhe = j.get("message") or j.get("error_description") or ""
        except Exception:
            detalhe = resp.text[:200]
        _ULTIMO_DEBUG["http_status"].append(resp.status_code)
        _ULTIMO_DEBUG["erro"] = f"HTTP {resp.status_code} · {detalhe}"
        raise RuntimeError(
            f"Falha ao consultar extrato (HTTP {resp.status_code}). Detalhe: {detalhe}"
        )

    payload = resp.json()
    # v5.83: guarda payload bruto para debug (ui_itau.py mostra se veio vazio)
    _ULTIMO_DEBUG["payloads"].append(payload)
    _ULTIMO_DEBUG["http_status"].append(resp.status_code)
    return payload


# ==============================================================================
# CONVERSÃO JSON → DataFrame INTERNO
# ==============================================================================
def _extrair_lancamentos(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrai lista plana de lançamentos do JSON retornado pelo Itaú.

    O formato do PDF mostra:
    { "data": [ { "events": [ { "id", "type", "operation", "date": {...},
                                "literal": {...}, "value", ... } ] } ] }

    Retorna lista de dicts com campos: data, valor, historico, documento, tipo.
    """
    lancamentos: List[Dict[str, Any]] = []
    data_bloco = payload.get("data")
    if not data_bloco:
        return lancamentos

    # Pode vir como lista ou objeto único
    if isinstance(data_bloco, dict):
        data_bloco = [data_bloco]

    for grupo in data_bloco:
        events = grupo.get("events") or []
        for ev in events:
            # Data — pode estar em ev["date"]["event"] ou ev["date"]["accounting"]
            dt_dict = ev.get("date") or {}
            dt_str = dt_dict.get("accounting") or dt_dict.get("event") or ""
            try:
                # accounting geralmente é "YYYY-MM-DD"; event pode ter timestamp
                dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00")).date()
            except Exception:
                try:
                    dt = datetime.strptime(str(dt_str)[:10], "%Y-%m-%d").date()
                except Exception:
                    dt = None

            # Valor + operação (C=crédito, D=débito)
            valor_raw = ev.get("value")
            try:
                valor = float(valor_raw) if valor_raw is not None else 0.0
            except (TypeError, ValueError):
                valor = 0.0
            operacao = str(ev.get("operation", "")).upper()
            if operacao == "D" and valor > 0:
                valor = -valor

            # Histórico — literal.complete tem descrição longa; shortened é curto
            lit = ev.get("literal") or {}
            historico = lit.get("complete") or lit.get("shortened") or ""
            # tip é dica adicional (o que aquele código significa)
            tip = lit.get("tip") or ""

            # Documento — id (identificador único do lançamento) ou reference
            documento = ev.get("id") or ev.get("reference") or ""

            # Estorno?
            estorno = bool(ev.get("reversal"))

            lancamentos.append({
                "data": dt,
                "valor": valor,
                "historico": str(historico).strip(),
                "documento": str(documento).strip(),
                "tipo_operacao": operacao,  # C ou D
                "estorno": estorno,
                "tip": tip,
            })

    return lancamentos


def _paginar_e_baixar_extrato(
    config: Dict[str, Any],
    conta_formatada: str,
    data_inicio: date,
    data_fim: date,
    page_size: int = 1000,
    max_paginas: int = 50,
) -> List[Dict[str, Any]]:
    """Chama a API do Itaú paginando até acabarem os lançamentos."""
    # v5.83: reseta o buffer de debug a cada nova consulta
    _ULTIMO_DEBUG["payloads"] = []
    _ULTIMO_DEBUG["http_status"] = []
    _ULTIMO_DEBUG["conta"] = conta_formatada
    _ULTIMO_DEBUG["periodo"] = f"{data_inicio} a {data_fim}"
    _ULTIMO_DEBUG["url_base"] = (
        URLS_PROD["extrato_base"] if config["ambiente"] == "prod"
        else URLS_HOMOL["extrato_base"]
    )
    _ULTIMO_DEBUG["erro"] = ""

    todos: List[Dict[str, Any]] = []
    page = 1
    while page <= max_paginas:
        payload = _chamar_extrato(
            config, conta_formatada, data_inicio, data_fim,
            page=page, page_size=page_size,
        )
        parciais = _extrair_lancamentos(payload)
        if not parciais:
            break
        todos.extend(parciais)

        # Verificar se tem próxima página. O Itaú pode expor via pagination ou
        # via retorno menor que page_size. Estratégia conservadora:
        if len(parciais) < page_size:
            break

        # Se o payload trouxer um indicador de "has_next" ou similar, respeitar
        pag = payload.get("pagination") or {}
        if isinstance(pag, dict):
            total_paginas = pag.get("total_pages") or pag.get("pages")
            if total_paginas and page >= int(total_paginas):
                break

        page += 1
        # pequena pausa educada
        time.sleep(0.2)

    return todos


# ==============================================================================
# API PÚBLICA
# ==============================================================================
def testar_conexao() -> Dict[str, Any]:
    """Faz uma chamada de token pra validar credenciais + certificado.

    Retorna dict com {ok: bool, mensagem: str, ambiente: str}.
    """
    try:
        config = _obter_config()
        _obter_access_token(config)
        return {
            "ok": True,
            "mensagem": f"Conexão OK com ambiente {config['ambiente']}.",
            "ambiente": config["ambiente"],
        }
    except Exception as e:
        return {"ok": False, "mensagem": str(e), "ambiente": ""}


def listar_contas() -> Dict[str, Dict[str, str]]:
    """Retorna dict {apelido: {conta, nome_sankhya}} configurado no Secrets."""
    try:
        return _obter_config()["contas"]
    except Exception:
        return {}


def obter_nome_sankhya(apelido: str) -> str:
    """Retorna o nome_sankhya cadastrado para o apelido, ou string vazia se não achar."""
    contas = listar_contas()
    reg = contas.get(str(apelido))
    if not reg:
        return ""
    return str(reg.get("nome_sankhya", "")).strip()


def obter_ultimo_debug() -> Dict[str, Any]:
    """v5.83: retorna cópia do último snapshot de debug da API.

    Contém: payloads brutos (por página), status HTTP, conta consultada,
    período, url_base e eventual erro. Usado pelo ui_itau.py quando o
    parser vem vazio, para mostrar o formato REAL do JSON do Itaú.
    """
    return {
        "payloads": list(_ULTIMO_DEBUG.get("payloads") or []),
        "http_status": list(_ULTIMO_DEBUG.get("http_status") or []),
        "conta": str(_ULTIMO_DEBUG.get("conta", "")),
        "periodo": str(_ULTIMO_DEBUG.get("periodo", "")),
        "url_base": str(_ULTIMO_DEBUG.get("url_base", "")),
        "erro": str(_ULTIMO_DEBUG.get("erro", "")),
    }


def puxar_extrato_df(
    conta_formatada: str,
    data_inicio: date,
    data_fim: date,
) -> pd.DataFrame:
    """Puxa extrato e devolve DataFrame padrão do app.

    Colunas:
      - data (date)
      - valor (float, negativo=débito)
      - historico (str)
      - documento (str)
      - tipo_operacao (str: C/D)
      - estorno (bool)

    A conta deve estar no formato XXXX00YYYYYZ (13 dígitos).
    """
    # Validação básica do formato
    conta_limpa = re.sub(r"\D", "", str(conta_formatada))
    # PDF Itaú BBA fala em 13 dígitos (XXXX00YYYYYZ), mas contas de mais de
    # 5 dígitos existem. Aceita 12-14 e deixa a API responder se estiver errado.
    if not (12 <= len(conta_limpa) <= 14):
        raise RuntimeError(
            f"Conta '{conta_formatada}' inválida. Formato esperado: "
            "13 dígitos aproximados (agência + 00 + conta + DAC). "
            f"Você passou {len(conta_limpa)} dígitos."
        )

    if data_fim < data_inicio:
        raise RuntimeError("data_fim não pode ser anterior a data_inicio.")

    # Itaú aceita até 92 dias por consulta (verificar em prod)
    delta_dias = (data_fim - data_inicio).days
    if delta_dias > 92:
        raise RuntimeError(
            f"Período de {delta_dias} dias excede o máximo de 92 dias por consulta. "
            "Divida em consultas menores."
        )

    config = _obter_config()
    lancamentos = _paginar_e_baixar_extrato(
        config, conta_limpa, data_inicio, data_fim,
    )

    if not lancamentos:
        return pd.DataFrame(columns=[
            "data", "valor", "historico", "documento", "tipo_operacao", "estorno",
        ])

    df = pd.DataFrame(lancamentos)
    # Ordenar por data
    if "data" in df.columns:
        df = df.sort_values("data", na_position="last", kind="stable").reset_index(drop=True)
    return df


def puxar_extrato_xlsx(
    conta_formatada: str,
    data_inicio: date,
    data_fim: date,
    conta_apelido: Optional[str] = None,
) -> Tuple[bytes, str]:
    """Puxa extrato e devolve (bytes_xlsx, nome_sugerido).

    Formato XLSX próximo do que os parsers atuais do app leem:
    colunas Data, Histórico, Documento, Valor.

    Útil pra alimentar o `file_uploader` do app como se fosse arquivo local.
    """
    import io
    from openpyxl import Workbook

    df = puxar_extrato_df(conta_formatada, data_inicio, data_fim)

    wb = Workbook()
    ws = wb.active
    ws.title = "Extrato Itau"

    # Cabeçalho no formato "clássico" que os parsers atuais reconhecem
    ws.append(["Data", "Histórico", "Documento", "Valor"])
    for _, r in df.iterrows():
        dt = r.get("data")
        valor = r.get("valor") or 0
        historico = r.get("historico") or ""
        documento = r.get("documento") or ""
        ws.append([
            dt.strftime("%d/%m/%Y") if dt else "",
            historico,
            documento,
            float(valor),
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    apelido_txt = f"_{conta_apelido}" if conta_apelido else ""
    nome = (
        f"extrato_itau{apelido_txt}_"
        f"{data_inicio.strftime('%Y%m%d')}_"
        f"{data_fim.strftime('%Y%m%d')}.xlsx"
    )
    return buf.read(), nome
