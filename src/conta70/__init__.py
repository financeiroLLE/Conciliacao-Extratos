"""Conta 70 — controle provisório de créditos bancários não identificados.

Regra:
- Subset dos pendentes do banco: apenas CRÉDITOS (valor > 0) que NÃO casaram
  no match 1-pra-1, NÃO foram anulados por estorno, NÃO entraram em agrupamento TOP 1722
- Cada linha vem com status default "Não identificado"
- Persistência via planilha conta_70_historico.xlsx que o usuário mantém
- Quando o usuário marca como "Regularizado" e salva, o status persiste entre execuções
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import pandas as pd


STATUS_VALIDOS = [
    "Não identificado",
    "Pendente de NF",
    "Pendente de baixa",
    "Em análise",
    "Regularizado",
]


@dataclass
class ResultadoConta70:
    """Resultado do controle Conta 70."""
    detalhado: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def kpis(self) -> dict[str, Any]:
        if self.detalhado.empty:
            return {
                "total_a_lancar": 0.0,
                "qtd_total": 0,
                "qtd_nao_identificado": 0,
                "qtd_pendente_nf": 0,
                "qtd_pendente_baixa": 0,
                "qtd_em_analise": 0,
                "qtd_regularizado": 0,
                "qtd_contas": 0,
            }
        # Considera apenas linhas NÃO regularizadas para o "Total a lançar"
        a_lancar = self.detalhado[self.detalhado["status"] != "Regularizado"]
        return {
            "total_a_lancar": float(a_lancar["valor"].sum()),
            "qtd_total": int(len(self.detalhado)),
            "qtd_nao_identificado": int((self.detalhado["status"] == "Não identificado").sum()),
            "qtd_pendente_nf": int((self.detalhado["status"] == "Pendente de NF").sum()),
            "qtd_pendente_baixa": int((self.detalhado["status"] == "Pendente de baixa").sum()),
            "qtd_em_analise": int((self.detalhado["status"] == "Em análise").sum()),
            "qtd_regularizado": int((self.detalhado["status"] == "Regularizado").sum()),
            "qtd_contas": int(self.detalhado["conta"].nunique()) if "conta" in self.detalhado.columns else 0,
        }

    def por_banco(self) -> pd.DataFrame:
        if self.detalhado.empty:
            return pd.DataFrame()
        a_lancar = self.detalhado[self.detalhado["status"] != "Regularizado"]
        if a_lancar.empty:
            return pd.DataFrame()
        return (
            a_lancar.groupby("conta", as_index=False)
            .agg(qtd=("valor", "count"), total=("valor", "sum"))
            .rename(columns={"conta": "Conta", "qtd": "Quantidade", "total": "Total a Lançar"})
        )

    def por_data(self) -> pd.DataFrame:
        if self.detalhado.empty or "data" not in self.detalhado.columns:
            return pd.DataFrame()
        a_lancar = self.detalhado[self.detalhado["status"] != "Regularizado"].copy()
        if a_lancar.empty:
            return pd.DataFrame()
        a_lancar["data_str"] = pd.to_datetime(a_lancar["data"], errors="coerce").dt.strftime("%d/%m/%Y")
        return (
            a_lancar.groupby("data_str", as_index=False)
            .agg(qtd=("valor", "count"), total=("valor", "sum"))
            .rename(columns={"data_str": "Data", "qtd": "Quantidade", "total": "Total a Lançar"})
            .sort_values("Data")
        )

    def por_status(self) -> pd.DataFrame:
        if self.detalhado.empty:
            return pd.DataFrame()
        return (
            self.detalhado.groupby("status", as_index=False)
            .agg(qtd=("valor", "count"), total=("valor", "sum"))
            .rename(columns={"status": "Status", "qtd": "Quantidade", "total": "Valor"})
        )


def gerar_conta_70(
    pendentes_banco: pd.DataFrame,
    historico_anterior: pd.DataFrame | None = None,
    id_execucao: str = "",
    data_analise: datetime | None = None,
) -> ResultadoConta70:
    """Gera o controle Conta 70 a partir das pendências do banco.

    Args:
        pendentes_banco: linhas do banco que não casaram em nenhuma etapa do pipeline.
        historico_anterior: DataFrame de execuções anteriores (planilha que o usuário
            mantém). Quando uma linha atual coincide com uma do histórico, mantém o
            status do histórico (ex: "Regularizado").
        id_execucao: identificador da execução atual.
        data_analise: timestamp da análise.

    Returns:
        ResultadoConta70.
    """
    if data_analise is None:
        data_analise = datetime.now()

    # Filtra apenas créditos (valor > 0) — Conta 70 é controle de receitas não-identificadas
    if pendentes_banco.empty or "valor" not in pendentes_banco.columns:
        df_atual = pd.DataFrame()
    else:
        df = pendentes_banco.copy()
        df = df[df["valor"] > 0].copy()
        if df.empty:
            df_atual = pd.DataFrame()
        else:
            df_atual = pd.DataFrame({
                "data": pd.to_datetime(df["data"], errors="coerce"),
                "conta": df.get("conta", "").astype(str),
                "historico": df.get("historico", "").astype(str),
                "documento": df.get("documento", "").astype(str),
                "valor": pd.to_numeric(df["valor"], errors="coerce").fillna(0.0).round(2),
                "tipo_recebimento": _classificar_tipo_recebimento(df),
                "status": "Não identificado",
                "conta_contabil": "Conta 70",
                "observacao": "",
                "data_analise": data_analise,
                "id_execucao": id_execucao,
            })

    # Mescla com histórico anterior (mantém status de linhas já regularizadas)
    if historico_anterior is not None and not historico_anterior.empty and not df_atual.empty:
        df_atual = _mesclar_com_historico(df_atual, historico_anterior)

    # Se só tiver histórico (sem execução atual), retorna o histórico
    if df_atual.empty and historico_anterior is not None and not historico_anterior.empty:
        return ResultadoConta70(detalhado=historico_anterior.copy())

    return ResultadoConta70(detalhado=df_atual)


def _classificar_tipo_recebimento(df: pd.DataFrame) -> pd.Series:
    """Tenta classificar o tipo do recebimento pelo histórico."""
    def _ident(h: str) -> str:
        h = str(h).upper()
        if "PIX" in h:
            return "Pix"
        if "TED" in h or "DOC" in h:
            return "TED/DOC"
        if "BOLETO" in h:
            return "Boleto"
        if "CARTAO" in h or "CARTÃO" in h or "CIELO" in h or "STONE" in h or "REDE" in h or "GETNET" in h:
            return "Cartão"
        if "CREDITO" in h or "CRÉDITO" in h:
            return "Crédito"
        return "Outro"
    if "historico" in df.columns:
        return df["historico"].fillna("").apply(_ident)
    return pd.Series(["Outro"] * len(df))


def _mesclar_com_historico(atual: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """Mantém o status do histórico para linhas que coincidem com as atuais.

    Critério de match: data + conta + valor + historico (chave 4-tupla).
    """
    atual = atual.copy()
    if hist.empty:
        return atual

    # Normaliza histórico pra ter as mesmas colunas-chave
    hist_norm = hist.copy()
    if "data" in hist_norm.columns:
        hist_norm["data"] = pd.to_datetime(hist_norm["data"], errors="coerce")
    if "valor" in hist_norm.columns:
        hist_norm["valor"] = pd.to_numeric(hist_norm["valor"], errors="coerce").round(2)

    # Para cada linha atual, procura no histórico
    for idx, row in atual.iterrows():
        cond = (
            (hist_norm["data"] == row["data"])
            & (hist_norm["conta"].astype(str) == str(row["conta"]))
            & (hist_norm["valor"].round(2) == round(float(row["valor"]), 2))
            & (hist_norm["historico"].astype(str) == str(row["historico"]))
        )
        match = hist_norm[cond]
        if not match.empty:
            atual.at[idx, "status"] = match.iloc[0]["status"]
            if "observacao" in match.columns:
                atual.at[idx, "observacao"] = match.iloc[0].get("observacao", "") or ""
    return atual


def carregar_historico_conta_70(arquivo: Any) -> pd.DataFrame:
    """Lê a planilha de histórico mantida pelo usuário."""
    try:
        df = pd.read_excel(arquivo)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()

    # Normaliza nomes de colunas
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    obrig = {"data", "conta", "historico", "valor", "status"}
    if not obrig.issubset(df.columns):
        return pd.DataFrame()

    df["data"] = pd.to_datetime(df["data"], errors="coerce", dayfirst=True)
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce").round(2)
    df = df.dropna(subset=["data", "valor"]).reset_index(drop=True)
    return df
