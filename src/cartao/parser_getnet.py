"""Parser do extrato CRU da GETNET (XLSX) — v5.16.

A GETNET exporta um arquivo com 3 abas: 'Resumo', 'Sintético por Grupo',
'Detalhado'. A aba 'Detalhado' tem cada venda individual com:
- BANDEIRA / MODALIDADE (ex: 'Mastercard Crédito', 'Visa Débito')
- LANÇAMENTO (ex: 'Venda Crédito A Vista', 'Venda Parcelado Loja')
- VALOR DA PARCELA, DESCONTOS, VALOR LIQUIDO DA PARCELA
- DATA DA VENDA, PARCELAS, NSU, autorização

Este parser converte automaticamente o XLSX cru pra o formato padrão
esperado por `auditar_taxas` (data_venda, adquirente, modalidade,
parcelas, valor_bruto, taxa_aplicada, valor_liquido).

Sem este parser, o usuário precisaria converter manualmente no Excel.
"""
from __future__ import annotations

from typing import Any
import pandas as pd


# ============================================================
# Detecção
# ============================================================

def eh_extrato_getnet_cru(arquivo: Any) -> bool:
    """Detecta se o arquivo é o extrato CRU da GETNET (3 abas características)."""
    try:
        xl = pd.ExcelFile(arquivo)
        sheets_lower = [s.lower() for s in xl.sheet_names]
        # GETNET tem essas 3 abas características
        return (
            "detalhado" in sheets_lower
            and any("sint" in s for s in sheets_lower)
            and "resumo" in sheets_lower
        )
    except Exception:
        return False


# ============================================================
# Mapeamento bandeira/modalidade
# ============================================================

# A coluna "BANDEIRA / MODALIDADE" combina bandeira+tipo (ex: "Mastercard Crédito").
# A coluna "LANÇAMENTO" diz se é à vista, parcelado ou débito.
# Mapeamento pra modalidade canônica (que o cadastro espera).

def _classificar_modalidade(bandeira_modalidade: str, lancamento: str) -> str:
    """Retorna a modalidade canônica baseada em BANDEIRA/MODALIDADE + LANÇAMENTO.

    Exemplos:
    - 'Mastercard Crédito' + 'Venda Crédito A Vista'  → 'Crédito à vista'
    - 'Mastercard Crédito' + 'Venda Parcelado Loja'   → 'Crédito parcelado'
    - 'Visa Débito'        + 'Venda Débito A Vista'   → 'Débito'
    - 'Elo Crédito'        + 'Venda Parcelado E-Comm' → 'Crédito parcelado'
    """
    bm = str(bandeira_modalidade or "").lower()
    lc = str(lancamento or "").lower()

    # Débito sempre é Débito (à vista por definição)
    if "débito" in bm or "debito" in bm:
        return "Débito"

    # Crédito: olha o lançamento pra distinguir à vista vs parcelado
    if "parcelado" in lc:
        return "Crédito parcelado"
    if "à vista" in lc or "a vista" in lc:
        return "Crédito à vista"

    # Fallback: se tem "Crédito" na bandeira mas o lançamento não diz
    if "crédito" in bm or "credito" in bm:
        return "Crédito à vista"  # default conservador

    return ""  # desconhecido — vai virar "Sem contrato" na auditoria


def _extrair_bandeira(bandeira_modalidade: str) -> str:
    """Extrai só a bandeira de 'Mastercard Crédito' → 'Mastercard'."""
    bm = str(bandeira_modalidade or "").strip()
    # Remove o sufixo de tipo
    for sufixo in (" Crédito", " Débito", " Credito", " Debito"):
        if bm.endswith(sufixo):
            return bm[: -len(sufixo)].strip()
    # Se não tem sufixo reconhecido, retorna inteiro
    return bm


def _extrair_parcelas(parcelas_str: Any) -> int:
    """'1 de 3' → 3 ; '1 de 1' → 1 ; '' → 1."""
    if parcelas_str is None or pd.isna(parcelas_str):
        return 1
    s = str(parcelas_str).strip().lower()
    if not s or s == "-":
        return 1
    # Formato "X de Y" → pega Y
    if " de " in s:
        try:
            return int(s.split(" de ")[-1].strip())
        except (ValueError, IndexError):
            return 1
    # Tenta interpretar como número direto
    try:
        return int(float(s))
    except ValueError:
        return 1


# ============================================================
# Carregamento
# ============================================================

def carregar_extrato_getnet_cru(arquivo: Any) -> pd.DataFrame:
    """Lê o XLSX cru da GETNET e retorna DataFrame no formato esperado por `auditar_taxas`.

    Colunas de saída:
        data_venda, adquirente, modalidade, parcelas,
        valor_bruto, taxa_aplicada, valor_liquido,
        data_prevista_recebimento,
        bandeira, nsu, autorizacao, hora_venda  (extras GETNET)

    Returns:
        DataFrame com vendas (filtradas pelo TIPO DE LANÇAMENTO = 'Vendas').

    Raises:
        ValueError: se o arquivo não tem estrutura GETNET reconhecível.
    """
    try:
        xl = pd.ExcelFile(arquivo)
    except Exception as e:
        raise ValueError(f"Não foi possível abrir o arquivo: {e}")

    # Acha a aba 'Detalhado' (pode ter variação de capitalização)
    sheet_detalhado = None
    for s in xl.sheet_names:
        if s.strip().lower() == "detalhado":
            sheet_detalhado = s
            break

    if sheet_detalhado is None:
        raise ValueError(
            "Aba 'Detalhado' não encontrada. Este arquivo não parece ser o "
            "extrato cru da GETNET. Verifique se baixou o relatório correto "
            "(Recebíveis Completos > Detalhado)."
        )

    # O cabeçalho real está na linha 8 do Excel (índice 7 quando read_excel com header=N)
    # mas isso pode variar — vamos detectar dinamicamente buscando a linha que tem
    # 'BANDEIRA / MODALIDADE' como célula.
    bruto = pd.read_excel(arquivo, sheet_name=sheet_detalhado, header=None)

    linha_header = None
    for i in range(min(20, len(bruto))):
        row_str = " | ".join(str(v) for v in bruto.iloc[i].values if pd.notna(v))
        if "BANDEIRA" in row_str.upper() and "MODALIDADE" in row_str.upper():
            linha_header = i
            break

    if linha_header is None:
        raise ValueError(
            "Cabeçalho esperado ('BANDEIRA / MODALIDADE') não encontrado na aba Detalhado. "
            "O formato pode ter mudado — verifique manualmente."
        )

    # Recarrega com o header certo
    df = pd.read_excel(arquivo, sheet_name=sheet_detalhado, header=linha_header)

    # Conferir colunas mínimas
    cols_necessarias = {
        "TIPO DE LANÇAMENTO", "BANDEIRA / MODALIDADE", "LANÇAMENTO",
        "VALOR DA PARCELA", "DESCONTOS", "VALOR LIQUIDO DA PARCELA",
        "DATA DA VENDA", "PARCELAS",
    }
    faltando = cols_necessarias - set(df.columns)
    if faltando:
        raise ValueError(
            f"Colunas esperadas faltando no extrato GETNET: {sorted(faltando)}. "
            f"Colunas encontradas: {sorted(df.columns)}"
        )

    # Filtra só linhas de venda (descarta Saldo Anterior, Pagamento Realizado, totais)
    df = df[df["TIPO DE LANÇAMENTO"].astype(str).str.strip() == "Vendas"].copy()

    if df.empty:
        raise ValueError(
            "Nenhuma venda encontrada na aba Detalhado. "
            "O arquivo pode estar vazio ou só com pagamentos/saldos."
        )

    # === Construir DataFrame padronizado ===
    out = pd.DataFrame()

    # Data da venda
    out["data_venda"] = pd.to_datetime(df["DATA DA VENDA"], errors="coerce", dayfirst=True)

    # Adquirente sempre "Getnet" (este parser é específico)
    out["adquirente"] = "Getnet"

    # Modalidade: combina BANDEIRA/MODALIDADE + LANÇAMENTO
    out["modalidade"] = df.apply(
        lambda r: _classificar_modalidade(r["BANDEIRA / MODALIDADE"], r["LANÇAMENTO"]),
        axis=1,
    )

    # Parcelas: extrai de "1 de 3" → 3
    out["parcelas"] = df["PARCELAS"].apply(_extrair_parcelas)

    # Valor bruto: VALOR DA PARCELA (o valor cheio antes do desconto)
    out["valor_bruto"] = pd.to_numeric(df["VALOR DA PARCELA"], errors="coerce")

    # Valor líquido: VALOR LIQUIDO DA PARCELA
    out["valor_liquido"] = pd.to_numeric(df["VALOR LIQUIDO DA PARCELA"], errors="coerce")

    # Taxa aplicada: desconto / valor_bruto (ABSOLUTO, sempre positivo)
    descontos = pd.to_numeric(df["DESCONTOS"], errors="coerce").fillna(0.0).abs()
    # Evita divisão por zero
    out["taxa_aplicada"] = (descontos / out["valor_bruto"]).where(
        out["valor_bruto"] > 0, 0.0
    ).round(6)

    # Data prevista de recebimento (vencimento)
    if "DATA DE VENCIMENTO" in df.columns:
        out["data_prevista_recebimento"] = pd.to_datetime(
            df["DATA DE VENCIMENTO"], errors="coerce", dayfirst=True
        )
    else:
        out["data_prevista_recebimento"] = pd.NaT

    # === Extras GETNET (não usados pela auditoria, mas úteis pra detalhamento) ===
    out["bandeira"] = df["BANDEIRA / MODALIDADE"].apply(_extrair_bandeira)
    if "NÚMERO COMPROVANTE DE VENDA (NSU)" in df.columns:
        out["nsu"] = df["NÚMERO COMPROVANTE DE VENDA (NSU)"].astype(str).str.strip()
    if "AUTORIZAÇÃO" in df.columns:
        out["autorizacao"] = df["AUTORIZAÇÃO"].astype(str).str.strip()
    if "HORA DA VENDA" in df.columns:
        out["hora_venda"] = df["HORA DA VENDA"].astype(str).str.strip()
    if "TERMINAL LÓGICO" in df.columns:
        out["terminal"] = df["TERMINAL LÓGICO"].astype(str).str.strip()

    # Limpa linhas inválidas (sem data ou sem valor)
    out = out.dropna(subset=["data_venda", "valor_bruto"]).reset_index(drop=True)

    return out


# ============================================================
# Resumo do que foi lido (para mostrar ao usuário)
# ============================================================

def resumir_extrato_getnet(df: pd.DataFrame) -> dict:
    """Calcula um resumo do extrato GETNET pra mostrar ao usuário antes de auditar."""
    if df.empty:
        return {
            "qtd": 0,
            "bruto_total": 0.0,
            "liquido_total": 0.0,
            "taxa_total_paga": 0.0,
            "taxa_media": 0.0,
            "por_modalidade": pd.DataFrame(),
            "data_min": None,
            "data_max": None,
        }

    bruto = float(df["valor_bruto"].sum())
    liquido = float(df["valor_liquido"].sum())
    taxa_paga = bruto - liquido
    taxa_media = (taxa_paga / bruto) if bruto > 0 else 0.0

    # Detalhamento por bandeira + modalidade
    por_mod = (
        df.groupby(["bandeira", "modalidade"], dropna=False)
        .agg(
            qtd=("valor_bruto", "count"),
            bruto=("valor_bruto", "sum"),
            liquido=("valor_liquido", "sum"),
        )
        .reset_index()
    )
    por_mod["taxa_real"] = (
        (por_mod["bruto"] - por_mod["liquido"]) / por_mod["bruto"]
    ).round(6)
    por_mod = por_mod.sort_values(["bandeira", "modalidade"]).reset_index(drop=True)

    return {
        "qtd": len(df),
        "bruto_total": bruto,
        "liquido_total": liquido,
        "taxa_total_paga": taxa_paga,
        "taxa_media": taxa_media,
        "por_modalidade": por_mod,
        "data_min": df["data_venda"].min(),
        "data_max": df["data_venda"].max(),
    }
