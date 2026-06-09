"""Auditoria de Taxas: cruza relatório da adquirente com o cadastro contratual."""
from __future__ import annotations
 
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import pandas as pd
 
from .cadastro_taxas import (
    _normalizar_modalidade,
    _parse_taxa,
    _normalizar_cabecalho,
    encontrar_taxa_vigente,
)
 
 
# Tolerância 0% — taxa precisa bater exatamente (com epsilon para erro de float)
EPSILON = 0.00001
 
 
@dataclass
class ResultadoAuditoriaTaxas:
    """Resultado da auditoria das taxas de cartão."""
    detalhado: pd.DataFrame  # todas as linhas auditadas com status
    divergentes: pd.DataFrame  # subconjunto com status != 'OK'
    kpis: dict[str, Any] = field(default_factory=dict)
 
    def divergentes_por_adquirente(self) -> pd.DataFrame:
        if self.divergentes.empty:
            return pd.DataFrame()
        return (
            self.divergentes.groupby("adquirente").agg(
                qtd=("status", "count"),
                impacto=("diferenca_rs", "sum"),
            ).reset_index()
        )
 
 
def carregar_relatorio_adquirente(arquivo: Any) -> pd.DataFrame:
    """Lê o relatório padronizado das adquirentes.
 
    Colunas esperadas (case-insensitive):
        data_venda, adquirente, modalidade, parcelas, valor_bruto,
        taxa_aplicada, valor_liquido (opcional), data_prevista_recebimento (opcional)
    """
    df_raw = pd.read_excel(arquivo, dtype=str)
    df_raw.columns = [_normalizar_cabecalho(c) for c in df_raw.columns]
 
    obrigatorias = {"data_venda", "adquirente", "modalidade", "parcelas", "valor_bruto", "taxa_aplicada"}
    faltando = obrigatorias - set(df_raw.columns)
    if faltando:
        raise ValueError(
            f"Relatório da adquirente: colunas obrigatórias faltando: {sorted(faltando)}. "
            f"Encontradas: {sorted(df_raw.columns)}"
        )
 
    out = pd.DataFrame()
    out["data_venda"] = pd.to_datetime(df_raw["data_venda"], errors="coerce", dayfirst=True)
    out["adquirente"] = df_raw["adquirente"].astype(str).str.strip()
    out["modalidade"] = df_raw["modalidade"].apply(_normalizar_modalidade)
    out["parcelas"] = pd.to_numeric(df_raw["parcelas"], errors="coerce").fillna(1).astype(int)
    out["valor_bruto"] = df_raw["valor_bruto"].apply(_parse_valor_brl)
    out["taxa_aplicada"] = df_raw["taxa_aplicada"].apply(_parse_taxa)
    out["valor_liquido"] = (
        df_raw["valor_liquido"].apply(_parse_valor_brl)
        if "valor_liquido" in df_raw.columns else pd.Series([None] * len(df_raw))
    )
    out["data_prevista_recebimento"] = (
        pd.to_datetime(df_raw["data_prevista_recebimento"], errors="coerce", dayfirst=True)
        if "data_prevista_recebimento" in df_raw.columns else pd.NaT
    )
    # v5.17: coluna 'bandeira' opcional — usada pelo lookup no cadastro
    out["bandeira"] = (
        df_raw["bandeira"].astype(str).str.strip()
        if "bandeira" in df_raw.columns else ""
    )
 
    out = out.dropna(subset=["data_venda", "adquirente", "modalidade"]).reset_index(drop=True)
    return out
 
 
def _parse_valor_brl(v: Any) -> float:
    """Aceita 'R$ 1.234,56', '1234.56', '1234,56', 1234.56."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if not s:
        return 0.0
    # Detecta formato BRL (vírgula decimal) vs ISO (ponto decimal)
    if "," in s and "." in s:
        # Provavelmente '1.234,56' — remove pontos, troca vírgula
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0
 
 
def auditar_taxas(
    relatorio: pd.DataFrame,
    cadastro: pd.DataFrame,
    historico: pd.DataFrame | None = None,
) -> ResultadoAuditoriaTaxas:
    """Audita o relatório das adquirentes contra o cadastro de taxas.
 
    Critério v4.0 (Jeito B): comparação em CENTAVOS no valor da taxa.
    - Esperado em R$: round(valor_bruto × taxa_contratada, 2)
    - Cobrado em R$: round(valor_bruto × taxa_aplicada, 2)
    - Divergente se: esperado_rs != cobrado_rs
 
    Esse critério evita falso positivo de arredondamento (a adquirente
    arredonda no centavo, fazendo a taxa efetiva oscilar em milésimos).
 
    Args:
        relatorio: DataFrame do relatório da adquirente do período atual.
        cadastro: DataFrame do cadastro de taxas (taxas.xlsx).
        historico: DataFrame com auditorias anteriores acumuladas (opcional).
            Quando fornecido, é concatenado ao relatório do período atual
            para gerar KPIs e tabelas acumuladas.
 
    Returns:
        ResultadoAuditoriaTaxas com detalhado, divergentes e KPIs.
    """
    if relatorio.empty and (historico is None or historico.empty):
        return ResultadoAuditoriaTaxas(
            detalhado=pd.DataFrame(),
            divergentes=pd.DataFrame(),
            kpis=_kpis_vazios(),
        )
 
    # Auditoria do relatório atual
    detalhe_atual = _auditar_dataframe(relatorio, cadastro) if not relatorio.empty else pd.DataFrame()
    if not detalhe_atual.empty:
        detalhe_atual["origem"] = "Atual"
 
    # Combina com histórico (já vem auditado, só adiciona)
    if historico is not None and not historico.empty:
        hist = historico.copy()
        if "origem" not in hist.columns:
            hist["origem"] = "Histórico"
        if detalhe_atual.empty:
            detalhe = hist
        else:
            detalhe = pd.concat([hist, detalhe_atual], ignore_index=True)
    else:
        detalhe = detalhe_atual
 
    divergentes = detalhe[detalhe["status"] == "Divergente"].copy() if not detalhe.empty else pd.DataFrame()
 
    kpis = _calcular_kpis(detalhe)
    return ResultadoAuditoriaTaxas(detalhado=detalhe, divergentes=divergentes, kpis=kpis)
 
 
def _auditar_dataframe(relatorio: pd.DataFrame, cadastro: pd.DataFrame) -> pd.DataFrame:
    """Audita um único DataFrame de relatório (sem histórico) usando critério Jeito B."""
    detalhe = relatorio.copy()
    detalhe["taxa_esperada"] = None
    detalhe["prazo_esperado"] = None
    detalhe["esperado_rs"] = None
    detalhe["cobrado_rs"] = None
    detalhe["diferenca_rs"] = None
    detalhe["diferenca_pp"] = None
    detalhe["status"] = ""
    detalhe["motivo"] = ""
 
    for idx, linha in detalhe.iterrows():
        # v5.17: passa bandeira no lookup se o relatório tiver (refina match)
        bandeira_linha = (
            str(linha.get("bandeira", "")).strip()
            if "bandeira" in detalhe.columns else ""
        )
        cfg = encontrar_taxa_vigente(
            cadastro,
            linha["adquirente"],
            linha["modalidade"],
            int(linha["parcelas"]),
            linha["data_venda"],
            bandeira=bandeira_linha or None,
        )
        bruto = float(linha["valor_bruto"])
        taxa_aplicada = float(linha["taxa_aplicada"])
        # Quanto a adquirente cobrou (em centavos, arredondado)
        cobrado_rs = round(bruto * taxa_aplicada, 2)
        detalhe.at[idx, "cobrado_rs"] = cobrado_rs
 
        if cfg is None:
            detalhe.at[idx, "status"] = "Sem contrato"
            bnd_str = f" / {bandeira_linha}" if bandeira_linha else ""
            detalhe.at[idx, "motivo"] = (
                f"Sem taxa cadastrada para {linha['adquirente']}{bnd_str} / "
                f"{linha['modalidade']} / {int(linha['parcelas'])}x na data {linha['data_venda'].date()}"
            )
            continue
 
        taxa_esperada = cfg["taxa_mdr"]
        esperado_rs = round(bruto * taxa_esperada, 2)
        detalhe.at[idx, "taxa_esperada"] = taxa_esperada
        detalhe.at[idx, "prazo_esperado"] = cfg["prazo_dias"]
        detalhe.at[idx, "esperado_rs"] = esperado_rs
        detalhe.at[idx, "diferenca_rs"] = round(cobrado_rs - esperado_rs, 2)
        detalhe.at[idx, "diferenca_pp"] = round((taxa_aplicada - taxa_esperada) * 100, 4)
 
        # CRITÉRIO JEITO B: compara em centavos no R$
        # v5.17: tolerância de 1 centavo (era 0.5) — adquirentes arredondam por
        # transação, então diferenças de 1 centavo são arredondamento, não cobrança a maior.
        if abs(cobrado_rs - esperado_rs) <= 0.01:
            detalhe.at[idx, "status"] = "OK"
            detalhe.at[idx, "motivo"] = (
                f"Taxa cobrada conforme contrato (R$ {cobrado_rs:.2f})"
            )
        else:
            diff = cobrado_rs - esperado_rs
            sinal = "ACIMA do contratado" if diff > 0 else "ABAIXO do contratado"
            detalhe.at[idx, "status"] = "Divergente"
            detalhe.at[idx, "motivo"] = (
                f"Cobrança {sinal} em R$ {abs(diff):.2f} "
                f"(esperado R$ {esperado_rs:.2f}, cobrado R$ {cobrado_rs:.2f})"
            )
 
    # Se valor_liquido estava vazio, calcula
    sem_liq = detalhe["valor_liquido"].isna() | (detalhe["valor_liquido"] == 0)
    detalhe.loc[sem_liq, "valor_liquido"] = (
        detalhe.loc[sem_liq, "valor_bruto"] * (1 - detalhe.loc[sem_liq, "taxa_aplicada"])
    )
 
    return detalhe
 
 
def _calcular_kpis(detalhe: pd.DataFrame) -> dict[str, Any]:
    if detalhe.empty:
        return _kpis_vazios()
 
    volume_bruto = float(detalhe["valor_bruto"].sum())
    liquido = float(detalhe["valor_liquido"].sum())
    taxas_pagas = volume_bruto - liquido
    taxa_media = (taxas_pagas / volume_bruto) if volume_bruto > 0 else 0.0
 
    qtd_div = int((detalhe["status"] == "Divergente").sum())
    qtd_sem_contrato = int((detalhe["status"] == "Sem contrato").sum())
    qtd_ok = int((detalhe["status"] == "OK").sum())
 
    div_df = detalhe[detalhe["status"] == "Divergente"]
    impacto_acumulado = float(div_df["diferenca_rs"].sum()) if not div_df.empty else 0.0
    impacto_voce_pagou_mais = float(
        div_df[div_df["diferenca_rs"] > 0]["diferenca_rs"].sum()
    ) if not div_df.empty else 0.0
 
    return {
        "volume_bruto": volume_bruto,
        "valor_liquido": liquido,
        "taxas_pagas": taxas_pagas,
        "taxa_media_efetiva": taxa_media,
        "qtd_divergencias": qtd_div,
        "qtd_sem_contrato": qtd_sem_contrato,
        "qtd_ok": qtd_ok,
        "qtd_total": len(detalhe),
        "impacto_acumulado": impacto_acumulado,
        "impacto_pagou_mais": impacto_voce_pagou_mais,
    }
 
 
def _kpis_vazios() -> dict[str, Any]:
    return {
        "volume_bruto": 0.0,
        "valor_liquido": 0.0,
        "taxas_pagas": 0.0,
        "taxa_media_efetiva": 0.0,
        "qtd_divergencias": 0,
        "qtd_sem_contrato": 0,
        "qtd_ok": 0,
        "qtd_total": 0,
        "impacto_acumulado": 0.0,
        "impacto_pagou_mais": 0.0,
    }
 
 
# ============================================================
# Histórico Acumulado (v4.0)
# ============================================================
 
def carregar_auditoria_anterior(arquivo: Any) -> pd.DataFrame:
    """Lê um Excel de auditoria anterior gerado pelo próprio sistema.
 
    Espera-se que o arquivo tenha as colunas geradas por _auditar_dataframe.
    Retorna DataFrame vazio se o arquivo não for válido (ignora silenciosamente).
    """
    try:
        df = pd.read_excel(arquivo)
    except Exception:
        return pd.DataFrame()
 
    # Normaliza cabeçalhos (caso o usuário tenha editado o arquivo)
    df.columns = [_normalizar_cabecalho(c) for c in df.columns]
 
    # Colunas mínimas para considerar válido
    obrig = {"data_venda", "adquirente", "modalidade", "parcelas", "valor_bruto", "taxa_aplicada", "status"}
    if not obrig.issubset(df.columns):
        return pd.DataFrame()
 
    # Converte tipos
    df["data_venda"] = pd.to_datetime(df["data_venda"], errors="coerce", dayfirst=True)
    df["parcelas"] = pd.to_numeric(df["parcelas"], errors="coerce").fillna(1).astype(int)
    for col in ("valor_bruto", "valor_liquido", "esperado_rs", "cobrado_rs", "diferenca_rs"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("taxa_aplicada", "taxa_esperada", "diferenca_pp"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
 
    return df.dropna(subset=["data_venda"]).reset_index(drop=True)
 
 
def consolidar_historico(arquivos: list[Any]) -> tuple[pd.DataFrame, list[str]]:
    """Consolida várias auditorias anteriores em um único DataFrame.
 
    Returns:
        (df_consolidado, avisos):
        - df_consolidado: linhas de todas as auditorias.
        - avisos: lista de mensagens (ex.: 'Arquivo X tem N duplicatas com Y').
    """
    if not arquivos:
        return pd.DataFrame(), []
 
    frames = []
    nomes = []
    for arq in arquivos:
        df = carregar_auditoria_anterior(arq)
        if df.empty:
            continue
        nome = getattr(arq, "name", "arquivo")
        df["_origem_arquivo"] = nome
        frames.append(df)
        nomes.append(nome)
 
    if not frames:
        return pd.DataFrame(), []
 
    consolidado = pd.concat(frames, ignore_index=True)
    avisos = _detectar_duplicatas(consolidado)
    return consolidado, avisos
 
 
def _detectar_duplicatas(df: pd.DataFrame) -> list[str]:
    """Identifica linhas duplicadas (mesma data+adquirente+modalidade+parcelas+valor_bruto+taxa_aplicada)."""
    if df.empty:
        return []
    chave_cols = ["data_venda", "adquirente", "modalidade", "parcelas", "valor_bruto", "taxa_aplicada"]
    chave_cols = [c for c in chave_cols if c in df.columns]
    if len(chave_cols) < 4:
        return []
 
    duplicadas = df[df.duplicated(subset=chave_cols, keep=False)]
    if duplicadas.empty:
        return []
 
    qtd = int(duplicadas.duplicated(subset=chave_cols, keep="first").sum())
    if qtd > 0:
        arquivos_envolvidos = []
        if "_origem_arquivo" in duplicadas.columns:
            arquivos_envolvidos = sorted(duplicadas["_origem_arquivo"].dropna().unique().tolist())
        msg = (
            f"⚠️ {qtd} lançamento(s) duplicado(s) detectado(s) entre os arquivos: "
            f"{', '.join(arquivos_envolvidos) if arquivos_envolvidos else 'múltiplos'}. "
            f"Critério: mesma data+adquirente+modalidade+parcelas+valor+taxa. "
            f"Revise antes de prosseguir — o sistema não removerá automaticamente."
        )
        return [msg]
    return []
 
