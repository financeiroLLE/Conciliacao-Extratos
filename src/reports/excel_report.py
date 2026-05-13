"""
Geração do relatório final em Excel.

Estrutura do arquivo de saída (9 abas):

1. Resumo Executivo     — visão gerencial com totais e KPIs
2. Conciliados          — pares que casaram
3. Pendências Banco     — falta baixar no sistema
4. Pendências Sistema   — lançamento indevido / falta no banco
5. Divergência Valor    — mesma data/histórico, valores diferentes
6. Duplicidades         — registros repetidos
7. Banco Errado         — baixado em conta diferente
8. Sugestões Fuzzy      — para revisão manual
9. Pendências Consolidadas — INPUT do próximo dia (chave do fluxo)
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.utils.dataframe import dataframe_to_rows


HEADER_FILL = PatternFill("solid", start_color="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Arial", size=11)
TITLE_FONT = Font(bold=True, size=14, name="Arial")
ARIAL = Font(name="Arial", size=10)


def _formatar_cabecalho(ws, num_colunas: int, linha: int = 1):
    """Aplica formatação padrão de cabeçalho."""
    for col_idx in range(1, num_colunas + 1):
        c = ws.cell(row=linha, column=col_idx)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[linha].height = 30


def _escrever_df(ws, df: pd.DataFrame, comeco_linha: int = 1):
    """Escreve DataFrame na worksheet, com formatação."""
    if df.empty:
        ws.cell(row=comeco_linha, column=1, value="(nenhum registro encontrado)").font = ARIAL
        return

    rows = list(dataframe_to_rows(df, index=False, header=True))
    for r_idx, row in enumerate(rows, start=comeco_linha):
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = ARIAL
            if isinstance(val, (int, float)) and r_idx > comeco_linha:
                if "valor" in str(df.columns[c_idx - 1]).lower() or "diferen" in str(df.columns[c_idx - 1]).lower():
                    cell.number_format = 'R$ #,##0.00;[Red]-R$ #,##0.00'

    _formatar_cabecalho(ws, len(df.columns), linha=comeco_linha)

    # Ajuste de largura: simples, baseado no tamanho do header
    for c_idx, col_name in enumerate(df.columns, start=1):
        max_len = max(
            [len(str(col_name))]
            + [len(str(v)) for v in df.iloc[:, c_idx - 1].head(50).tolist() if pd.notna(v)]
        )
        ws.column_dimensions[get_column_letter(c_idx)].width = min(max(max_len + 2, 12), 50)

    ws.freeze_panes = ws.cell(row=comeco_linha + 1, column=1)


def _consolidar_pendencias(
    resultados: dict,
    pendencias_anteriores: pd.DataFrame,
    data_referencia: datetime,
) -> pd.DataFrame:
    """Monta a aba 'Pendências Consolidadas' — input do próximo dia.

    Combina:
    - Pendências detectadas hoje (banco e sistema)
    - Pendências anteriores que AINDA não foram resolvidas
    """
    blocos = []

    pb = resultados.get("pendentes_banco", pd.DataFrame())
    if not pb.empty:
        blocos.append(
            pd.DataFrame(
                {
                    "data": pb["data"],
                    "historico": pb["historico"],
                    "valor": pb["valor"],
                    "conta": pb["conta"],
                    "origem": "banco",
                    "tipo_pendencia": "Falta baixar no sistema",
                    "data_primeira_deteccao": data_referencia,
                    "dias_pendente": 0,
                }
            )
        )

    ps = resultados.get("pendentes_sistema", pd.DataFrame())
    if not ps.empty:
        blocos.append(
            pd.DataFrame(
                {
                    "data": ps["data"],
                    "historico": ps["historico"],
                    "valor": ps["valor"],
                    "conta": ps["conta"],
                    "origem": "sistema",
                    "tipo_pendencia": "Falta no banco / Lançamento indevido",
                    "data_primeira_deteccao": data_referencia,
                    "dias_pendente": 0,
                }
            )
        )

    # Pendências anteriores que ainda estão pendentes
    if not pendencias_anteriores.empty:
        ainda_pendentes = pendencias_anteriores.copy()
        ainda_pendentes["dias_pendente"] = (
            (data_referencia - ainda_pendentes["data_primeira_deteccao"]).dt.days
        )
        blocos.append(ainda_pendentes)

    if not blocos:
        return pd.DataFrame(
            columns=[
                "data",
                "historico",
                "valor",
                "conta",
                "origem",
                "tipo_pendencia",
                "data_primeira_deteccao",
                "dias_pendente",
            ]
        )

    return (
        pd.concat(blocos, ignore_index=True)
        .sort_values(["dias_pendente", "data"], ascending=[False, True])
        .reset_index(drop=True)
    )


def gerar_relatorio_excel(
    resultados: dict,
    contas_processadas: list[str],
    data_referencia: datetime,
    pendencias_anteriores: pd.DataFrame | None = None,
) -> bytes:
    """Gera o relatório Excel completo.

    Parameters
    ----------
    resultados : dict com chaves:
        conciliados, pendentes_banco, pendentes_sistema,
        divergencia_valor, duplicidades, banco_errado, sugestoes_fuzzy
    contas_processadas : lista de contas que foram conciliadas
    data_referencia : data da conciliação (data do extrato)
    pendencias_anteriores : DataFrame de pendências carregado do dia anterior

    Returns
    -------
    bytes do arquivo .xlsx
    """
    if pendencias_anteriores is None:
        pendencias_anteriores = pd.DataFrame()

    wb = Workbook()
    wb.remove(wb.active)

    # ========== Aba 1: Resumo Executivo ==========
    ws = wb.create_sheet("Resumo Executivo")
    ws["A1"] = "RELATÓRIO DE CONCILIAÇÃO BANCÁRIA"
    ws["A1"].font = TITLE_FONT
    ws.merge_cells("A1:D1")

    ws["A3"] = "Data de referência:"
    ws["B3"] = data_referencia.strftime("%d/%m/%Y")
    ws["A4"] = "Gerado em:"
    ws["B4"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ws["A5"] = "Contas processadas:"
    ws["B5"] = ", ".join(contas_processadas) if contas_processadas else "(todas)"
    for cell in ["A3", "A4", "A5", "B3", "B4", "B5"]:
        ws[cell].font = ARIAL
    for cell in ["A3", "A4", "A5"]:
        ws[cell].font = Font(name="Arial", size=10, bold=True)

    # Tabela de KPIs
    linha = 7
    ws.cell(row=linha, column=1, value="Indicador").font = HEADER_FONT
    ws.cell(row=linha, column=2, value="Quantidade").font = HEADER_FONT
    ws.cell(row=linha, column=3, value="Valor Total (R$)").font = HEADER_FONT
    for col in [1, 2, 3]:
        ws.cell(row=linha, column=col).fill = HEADER_FILL
        ws.cell(row=linha, column=col).alignment = Alignment(horizontal="center")

    kpis = [
        ("✅ Lançamentos conciliados", "conciliados", "valor"),
        ("❌ Pendências no banco (falta baixar)", "pendentes_banco", "valor"),
        ("❌ Pendências no sistema (indevidos)", "pendentes_sistema", "valor"),
        ("⚠️ Divergências de valor", "divergencia_valor", "valor_banco"),
        ("🔁 Duplicidades", "duplicidades", "valor"),
        ("🏦 Banco errado (suspeitos)", "banco_errado", "valor"),
        ("💡 Sugestões fuzzy", "sugestoes_fuzzy", "valor_banco"),
    ]

    for idx, (label, key, col_valor) in enumerate(kpis):
        linha = 8 + idx
        df = resultados.get(key, pd.DataFrame())
        qtd = len(df)
        total = df[col_valor].sum() if (not df.empty and col_valor in df.columns) else 0
        ws.cell(row=linha, column=1, value=label).font = ARIAL
        ws.cell(row=linha, column=2, value=qtd).font = ARIAL
        c_val = ws.cell(row=linha, column=3, value=float(total))
        c_val.font = ARIAL
        c_val.number_format = 'R$ #,##0.00;[Red]-R$ #,##0.00'

    ws.column_dimensions["A"].width = 45
    ws.column_dimensions["B"].width = 15
    ws.column_dimensions["C"].width = 22

    # ========== Demais abas (dados detalhados) ==========
    abas_dados = [
        ("Conciliados", "conciliados"),
        ("Pendências Banco", "pendentes_banco"),
        ("Pendências Sistema", "pendentes_sistema"),
        ("Divergência Valor", "divergencia_valor"),
        ("Duplicidades", "duplicidades"),
        ("Banco Errado", "banco_errado"),
        ("Sugestões Fuzzy", "sugestoes_fuzzy"),
    ]

    for nome_aba, chave in abas_dados:
        ws = wb.create_sheet(nome_aba)
        df = resultados.get(chave, pd.DataFrame())
        # Remove colunas internas (_row_id, etc.) só para exibição
        if not df.empty:
            df_show = df.drop(
                columns=[c for c in df.columns if c.startswith("_")],
                errors="ignore",
            )
            # Formata datas
            for c in df_show.columns:
                if pd.api.types.is_datetime64_any_dtype(df_show[c]):
                    df_show[c] = df_show[c].dt.strftime("%d/%m/%Y")
            _escrever_df(ws, df_show)
        else:
            _escrever_df(ws, df)

    # ========== Aba 9: Pendências Consolidadas (INPUT do dia seguinte) ==========
    ws = wb.create_sheet("Pendências Consolidadas")
    consolidado = _consolidar_pendencias(resultados, pendencias_anteriores, data_referencia)

    if not consolidado.empty:
        consolidado_show = consolidado.copy()
        consolidado_show.columns = [
            "Data",
            "Histórico",
            "Valor",
            "Conta",
            "Origem",
            "Tipo de Pendência",
            "Data 1ª Detecção",
            "Dias Pendente",
        ]
        for c in ["Data", "Data 1ª Detecção"]:
            if c in consolidado_show.columns:
                consolidado_show[c] = pd.to_datetime(consolidado_show[c]).dt.strftime("%d/%m/%Y")
        _escrever_df(ws, consolidado_show)
    else:
        _escrever_df(ws, consolidado)

    # Salva em memória
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def salvar_relatorio(
    resultados: dict,
    contas_processadas: list[str],
    data_referencia: datetime,
    caminho: str | Path,
    pendencias_anteriores: pd.DataFrame | None = None,
) -> Path:
    """Versão que salva em disco (útil para testes/CLI)."""
    bytes_xlsx = gerar_relatorio_excel(
        resultados, contas_processadas, data_referencia, pendencias_anteriores
    )
    caminho = Path(caminho)
    caminho.write_bytes(bytes_xlsx)
    return caminho
