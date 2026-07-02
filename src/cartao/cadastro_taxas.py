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


def _upper_sem_acento(s: Any) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()


# Bandeiras combinadas primeiro (senão "MAS/ELO" cairia em "ELO"). Cada uma
# vira DUAS bandeiras canônicas (o contrato combinado vale pras duas marcas).
_TT_BANDEIRAS_COMBINADAS = [
    ("VIS/MAS", ["Visa", "Mastercard"]),
    ("MAS/ELO", ["Mastercard", "Elo"]),
]
_BANDEIRAS_CANONICAS = ("Mastercard", "Visa", "Hipercard", "Amex", "Elo")


def canonizar_bandeira(s: Any) -> str:
    """Nome canônico da bandeira, tolerante às duas fontes.

    O Sankhya escreve curto ('Master', 'Hiper', 'Amex') e o extrato do GetNet
    escreve completo ('Mastercard', 'Hipercard', 'American Express'). Mapeando
    por palavra-chave, os dois lados falam o MESMO nome — senão o casamento por
    bandeira falha e tudo cai em "sem contrato". Bandeira desconhecida é mantida
    como veio (fica "sem contrato" honesto, nunca um match falso).
    """
    u = _upper_sem_acento(s)
    if not u:
        return ""
    if "MASTER" in u or u == "MC":
        return "Mastercard"
    if "VISA" in u or u == "VIS":
        return "Visa"
    if "HIPER" in u:
        return "Hipercard"
    if "AMEX" in u or "AMERICAN" in u:
        return "Amex"
    if "ELO" in u:
        return "Elo"
    return str(s).strip()


def _tt_adquirente(u: str) -> str:
    if "GETNET" in u or "GET NET" in u:
        return "Getnet"
    import re
    if re.search(r"(?<![A-Z0-9])PS(?![A-Z0-9])", u):
        return "PagSeguro"
    return ""


def _tt_bandeiras(u: str) -> list[str]:
    """Bandeira(s) canônica(s) da linha do Tipo de Título.
    Combinadas ('VIS/MAS') viram duas ('Visa', 'Mastercard')."""
    for k, lista in _TT_BANDEIRAS_COMBINADAS:
        if k in u:
            return list(lista)
    b = canonizar_bandeira(u)
    return [b] if b in _BANDEIRAS_CANONICAS else [""]


def _tt_parcelas(u: str, qtd: Any) -> list[int]:
    import re
    if "DEBITO" in u:
        return [1]
    # 1) coluna "Qtd. parcelas" preenchida vence tudo
    if qtd is not None and str(qtd).strip().lower() not in ("", "nan", "none"):
        try:
            return [int(float(str(qtd).replace(",", ".")))]
        except Exception:
            pass
    # 2) faixa "2 A 6" / "7 A 12"
    m = re.search(r"(\d+)\s*A\s*(\d+)", u)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= b <= 24:
            return list(range(a, b + 1))
    # 3) "7X" / "1X"
    m = re.search(r"(\d+)\s*X", u)
    if m:
        return [int(m.group(1))]
    # 4) crédito à vista sem número
    if "A VISTA" in u:
        return [1]
    return []


def _converter_tipo_de_titulo(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Converte o export nativo do Sankhya 'Tipo de Título'
    (Descrição / Qtd. parcelas / % Taxa Administradora / Subtipo)
    na LISTA padrão (adquirente, bandeira, modalidade, parcelas, taxa_mdr).

    Regras (seguem o dado, não o palpite):
      - adquirente: 'GETNET' → Getnet, token 'PS' → PagSeguro; senão descarta.
      - modalidade: 'DEBITO' → Débito; parcelas==1 → Crédito à vista; >1 → parcelado.
      - parcelas: coluna Qtd; senão faixa '2 A 6' expandida; senão 'NX'; senão 1.
      - bandeira: Hiper/Amex/Elo/Visa/Master (+ combinadas Visa/Master, Master/Elo).
    Linhas que não dão pra mapear com segurança são descartadas (nunca chutadas).
    """
    col_taxa = next(c for c in df_raw.columns if "taxa_administradora" in c)
    col_qtd = next(
        (c for c in df_raw.columns if "parcelas" in c and "qtd" in c), None
    )
    linhas = []
    for _, r in df_raw.iterrows():
        desc = str(r.get("descricao", "") or "").strip()
        if not desc:
            continue
        u = _upper_sem_acento(desc)
        adq = _tt_adquirente(u)
        parc = _tt_parcelas(u, r.get(col_qtd) if col_qtd else None)
        if "DEBITO" in u:
            mod = "Débito"
        elif parc and max(parc) == 1:
            mod = "Crédito à vista"
        elif parc:
            mod = "Crédito parcelado"
        else:
            mod = ""
        if not adq or not mod or not parc:
            continue
        # "% Taxa Administradora" é SEMPRE percentual: 3.24 = 3,24% e 0.78 = 0,78%.
        # Guardamos com "%" pra o parser dividir por 100 sempre — senão valores <= 1
        # (ex.: débito 0,78%) seriam lidos como fração (0,78 = 78%).
        taxa_raw = r.get(col_taxa)
        taxa_txt = "" if taxa_raw is None else str(taxa_raw).strip().replace(",", ".")
        if not taxa_txt or taxa_txt.lower() in ("nan", "none"):
            continue  # sem taxa não dá pra auditar — descarta em vez de chutar 0%
        taxa_mdr = f"{taxa_txt}%"
        bandeiras = _tt_bandeiras(u)
        for band in bandeiras:
            for p in parc:
                linhas.append(
                    {
                        "adquirente": adq,
                        "bandeira": band,
                        "modalidade": mod,
                        "parcelas": p,
                        "taxa_mdr": taxa_mdr,
                    }
                )
    return pd.DataFrame(
        linhas,
        columns=["adquirente", "bandeira", "modalidade", "parcelas", "taxa_mdr"],
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
    _nome = str(getattr(arquivo, "name", "") or "").lower()
    if _nome.endswith(".csv"):
        import io as _io

        _raw = arquivo.read() if hasattr(arquivo, "read") else open(arquivo, "rb").read()
        df_raw = None
        for _sep in (";", ","):
            try:
                _cand = pd.read_csv(_io.BytesIO(_raw), sep=_sep, dtype=str, engine="python")
                if _cand.shape[1] > 1:
                    df_raw = _cand
                    break
            except Exception:
                continue
        if df_raw is None:
            df_raw = pd.read_csv(_io.BytesIO(_raw), dtype=str, engine="python")
    else:
        df_raw = pd.read_excel(arquivo, dtype=str)
    df_raw.columns = [_normalizar_cabecalho(c) for c in df_raw.columns]

    # Formato nativo do Sankhya "Tipo de Título" (Descrição / Qtd. parcelas /
    # % Taxa Administradora / Subtipo): converte pra LISTA padrão antes de validar.
    if "descricao" in df_raw.columns and any(
        "taxa_administradora" in c for c in df_raw.columns
    ):
        df_raw = _converter_tipo_de_titulo(df_raw)

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
    # v5.17: coluna 'bandeira' opcional (Visa, Mastercard, Elo, etc).
    # Quando presente, refina o match: taxas variam por bandeira mesmo com mesma
    # modalidade/parcelas. Quando ausente (cadastro antigo), funciona como antes.
    out["bandeira"] = (
        df_raw["bandeira"].astype(str).map(canonizar_bandeira)
        if "bandeira" in df_raw.columns else ""
    )
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
    bandeira: str | None = None,
) -> dict | None:
    """Procura a taxa vigente para a venda específica.

    v5.17: Aceita parâmetro `bandeira` opcional. Quando o cadastro tem coluna
    'bandeira' E o caller passa bandeira, refina o match. Caso contrário, faz
    match só por adquirente/modalidade/parcelas (comportamento original).

    Retorna dict com {taxa_mdr, taxa_antecipacao, prazo_dias, vigencia_inicio,
    vigencia_fim, bandeira} ou None se não encontrar contrato vigente.
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

    # v5.17: refina por bandeira quando disponível
    cadastro_tem_bandeira = (
        "bandeira" in cadastro.columns
        and (cadastro["bandeira"].astype(str).str.strip() != "").any()
    )
    if bandeira and cadastro_tem_bandeira:
        bnd_norm = canonizar_bandeira(bandeira).lower()
        cand_bnd = cand[
            cand["bandeira"].astype(str).map(lambda b: canonizar_bandeira(b).lower())
            == bnd_norm
        ]
        if not cand_bnd.empty:
            cand = cand_bnd
        # Se não bateu por bandeira mas tem linhas SEM bandeira (cadastro genérico),
        # usa elas como fallback. Evita "Sem contrato" quando o cadastro é misto.
        else:
            cand_sem_bandeira = cand[
                cand["bandeira"].astype(str).str.strip() == ""
            ]
            if not cand_sem_bandeira.empty:
                cand = cand_sem_bandeira
            else:
                # Não tem nem específico nem genérico → sem contrato
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
        "bandeira": str(linha.get("bandeira", "")) if "bandeira" in linha.index else "",
    }
