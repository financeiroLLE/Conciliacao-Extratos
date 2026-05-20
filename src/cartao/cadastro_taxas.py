"""Cadastro de Taxas: parser do taxas.xlsx e busca de vigência."""
from __future__ import annotations

from typing import Any
import pandas as pd


# Modalidades aceitas (caixa exata como aparece na UI)
MODALIDADES_VALIDAS = ["Débito", "Crédito à vista", "Crédito parcelado", "Pix QR Code"]


def _normalizar_modalidade(s: str) -> str:
    """Normaliza variações comuns ('debito', 'CREDITO A VISTA', etc) → caixa canônica."""
    if not isinstance(s, str):
        return ""
    chave = s.strip().lower().replace("á", "a").replace("é", "e").replace("í", "i")
    chave = chave.replace("ó", "o").replace("ú", "u").replace("â", "a").replace("ê", "e")
    chave = chave.replace("ô", "o").replace("ç", "c")
    mapa = {
        "debito": "Débito",
        "credito": "Crédito à vista",
        "credito a vista": "Crédito à vista",
        "credito à vista": "Crédito à vista",
        "credito vista": "Crédito à vista",
        "credito parcelado": "Crédito parcelado",
        "parcelado": "Crédito parcelado",
        "pix": "Pix QR Code",
        "pix qr": "Pix QR Code",
        "pix qr code": "Pix QR Code",
        "pix maquininha": "Pix QR Code",
    }
    return mapa.get(chave, s.strip())


def _parse_taxa(v: Any) -> float:
    """Aceita '1,39%', '1.39%', '0.0139', '1.39'. Retorna fração (0.0139).

    Regra:
    - Se a string contém '%', SEMPRE divide por 100 (ex: '0,49%' → 0.0049).
    - Se é número puro > 1, assume percentual (ex: 1.39 → 0.0139).
    - Se é número puro ≤ 1, assume fração (ex: 0.0139 → 0.0139).
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v) / 100.0 if abs(v) > 1 else float(v)
    s_original = str(v).strip()
    if not s_original:
        return 0.0
    tem_pct = "%" in s_original
    s = s_original.replace("%", "").replace(",", ".").strip()
    if not s:
        return 0.0
    try:
        n = float(s)
        if tem_pct:
            return n / 100.0  # SEMPRE divide quando tem %
        return n / 100.0 if abs(n) > 1 else n
    except ValueError:
        return 0.0


def _normalizar_cabecalho(col: str) -> str:
    return (
        str(col).strip().lower()
        .replace(" ", "_").replace("-", "_")
        .replace("ç", "c").replace("ã", "a").replace("á", "a")
        .replace("é", "e").replace("ê", "e").replace("í", "i")
        .replace("ó", "o").replace("ô", "o").replace("ú", "u")
    )


def carregar_cadastro_taxas(arquivo: Any) -> pd.DataFrame:
    """Lê o arquivo taxas.xlsx e retorna DataFrame normalizado.

    Colunas esperadas (case-insensitive, com normalização):
        adquirente, modalidade, parcelas, taxa_mdr, taxa_antecipacao,
        prazo_dias, vigencia_inicio, vigencia_fim

    Retorna DataFrame com:
        adquirente (str), modalidade (str canônica), parcelas (int),
        taxa_mdr (float 0..1), taxa_antecipacao (float 0..1),
        prazo_dias (int), vigencia_inicio (Timestamp), vigencia_fim (Timestamp ou NaT)
    """
    df_raw = pd.read_excel(arquivo, dtype=str)
    df_raw.columns = [_normalizar_cabecalho(c) for c in df_raw.columns]

    obrigatorias = {"adquirente", "modalidade", "parcelas", "taxa_mdr"}
    faltando = obrigatorias - set(df_raw.columns)
    if faltando:
        raise ValueError(
            f"Cadastro de taxas: colunas obrigatórias faltando: {sorted(faltando)}. "
            f"Encontradas: {sorted(df_raw.columns)}"
        )

    out = pd.DataFrame()
    out["adquirente"] = df_raw["adquirente"].astype(str).str.strip()
    out["modalidade"] = df_raw["modalidade"].apply(_normalizar_modalidade)
    out["parcelas"] = pd.to_numeric(df_raw["parcelas"], errors="coerce").fillna(1).astype(int)
    out["taxa_mdr"] = df_raw["taxa_mdr"].apply(_parse_taxa)
    out["taxa_antecipacao"] = (
        df_raw["taxa_antecipacao"].apply(_parse_taxa)
        if "taxa_antecipacao" in df_raw.columns else 0.0
    )
    out["prazo_dias"] = (
        pd.to_numeric(df_raw["prazo_dias"], errors="coerce").fillna(0).astype(int)
        if "prazo_dias" in df_raw.columns else 0
    )
    out["vigencia_inicio"] = (
        pd.to_datetime(df_raw["vigencia_inicio"], errors="coerce", dayfirst=True)
        if "vigencia_inicio" in df_raw.columns else pd.NaT
    )
    out["vigencia_fim"] = (
        pd.to_datetime(df_raw["vigencia_fim"], errors="coerce", dayfirst=True)
        if "vigencia_fim" in df_raw.columns else pd.NaT
    )

    # Remove linhas inválidas (sem adquirente ou sem modalidade)
    out = out[
        (out["adquirente"].str.len() > 0)
        & (out["modalidade"].str.len() > 0)
    ].reset_index(drop=True)
    return out


def encontrar_taxa_vigente(
    cadastro: pd.DataFrame,
    adquirente: str,
    modalidade: str,
    parcelas: int,
    data_venda: pd.Timestamp,
) -> dict | None:
    """Procura a taxa vigente para a venda específica.

    Retorna dict com {taxa_mdr, taxa_antecipacao, prazo_dias, vigencia_inicio, vigencia_fim}
    ou None se não encontrar contrato vigente.
    """
    if cadastro.empty:
        return None

    adq_norm = str(adquirente).strip().lower()
    mod_norm = _normalizar_modalidade(str(modalidade))

    cand = cadastro[
        (cadastro["adquirente"].str.lower() == adq_norm)
        & (cadastro["modalidade"] == mod_norm)
        & (cadastro["parcelas"] == int(parcelas))
    ]
    if cand.empty:
        return None

    # Filtra por vigência
    data_v = pd.to_datetime(data_venda, errors="coerce")
    if pd.isna(data_v):
        # Sem data, retorna a primeira linha encontrada
        linha = cand.iloc[0]
        return _linha_para_dict(linha)

    # Vigência: inicio <= data_venda AND (fim vazio OR fim >= data_venda)
    vigente = cand[
        (cand["vigencia_inicio"].isna() | (cand["vigencia_inicio"] <= data_v))
        & (cand["vigencia_fim"].isna() | (cand["vigencia_fim"] >= data_v))
    ]
    if vigente.empty:
        return None
    # Se mais de uma, pega a com vigencia_inicio mais recente
    vigente = vigente.sort_values("vigencia_inicio", ascending=False, na_position="last")
    linha = vigente.iloc[0]
    return _linha_para_dict(linha)


def _linha_para_dict(linha: pd.Series) -> dict:
    return {
        "taxa_mdr": float(linha["taxa_mdr"]),
        "taxa_antecipacao": float(linha.get("taxa_antecipacao", 0.0)),
        "prazo_dias": int(linha.get("prazo_dias", 0) or 0),
        "vigencia_inicio": linha.get("vigencia_inicio"),
        "vigencia_fim": linha.get("vigencia_fim"),
    }
