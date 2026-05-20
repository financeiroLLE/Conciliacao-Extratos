"""Gera planilhas de exemplo para o módulo CARTÃO.

- taxas_exemplo.xlsx: cadastro de taxas contratadas (Stone, Cielo, Rede, Getnet)
- relatorio_adquirente_exemplo.xlsx: relatório de vendas (com divergências propositais)
"""
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta

SAMPLES_DIR = Path(__file__).parent.parent / "data" / "samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)


def gerar_taxas_exemplo():
    """Gera taxas_exemplo.xlsx com 4 adquirentes."""
    linhas = []

    # Stone
    linhas.append(["Stone", "Débito", 1, "1,39%", "0%", 1, "01/01/2026", ""])
    linhas.append(["Stone", "Crédito à vista", 1, "2,49%", "1,99%", 30, "01/01/2026", ""])
    for n in range(2, 13):
        taxa = "2,89%" if n == 2 else "3,19%"
        linhas.append(["Stone", "Crédito parcelado", n, taxa, "1,99%", 30, "01/01/2026", ""])
    linhas.append(["Stone", "Pix QR Code", 1, "0,49%", "0%", 1, "01/01/2026", ""])

    # Cielo
    linhas.append(["Cielo", "Débito", 1, "1,29%", "0%", 1, "01/01/2026", ""])
    linhas.append(["Cielo", "Crédito à vista", 1, "2,39%", "1,89%", 30, "01/01/2026", ""])
    for n in range(2, 13):
        linhas.append(["Cielo", "Crédito parcelado", n, "3,09%", "1,89%", 30, "01/01/2026", ""])
    linhas.append(["Cielo", "Pix QR Code", 1, "0,39%", "0%", 1, "01/01/2026", ""])

    # Rede
    linhas.append(["Rede", "Débito", 1, "1,49%", "0%", 1, "01/01/2026", ""])
    linhas.append(["Rede", "Crédito à vista", 1, "2,59%", "2,09%", 30, "01/01/2026", ""])
    for n in range(2, 13):
        linhas.append(["Rede", "Crédito parcelado", n, "3,29%", "2,09%", 30, "01/01/2026", ""])

    # Getnet
    linhas.append(["Getnet", "Débito", 1, "1,35%", "0%", 1, "01/01/2026", ""])
    linhas.append(["Getnet", "Crédito à vista", 1, "2,45%", "1,95%", 30, "01/01/2026", ""])
    for n in range(2, 13):
        linhas.append(["Getnet", "Crédito parcelado", n, "3,15%", "1,95%", 30, "01/01/2026", ""])

    df = pd.DataFrame(linhas, columns=[
        "adquirente", "modalidade", "parcelas", "taxa_mdr",
        "taxa_antecipacao", "prazo_dias", "vigencia_inicio", "vigencia_fim",
    ])

    saida = SAMPLES_DIR / "taxas_exemplo.xlsx"
    df.to_excel(saida, index=False)
    print(f"OK: {saida} ({len(df)} linhas)")


def gerar_relatorio_adquirente_exemplo():
    """Gera relatorio_adquirente_exemplo.xlsx com algumas divergências propositais."""
    linhas = []
    data_base = datetime(2026, 5, 14)

    # Stone — algumas OK, 1 divergente
    linhas.append([data_base, "Stone", "Débito", 1, "100,00", "1,39%", "98,61", data_base + timedelta(days=1)])
    linhas.append([data_base, "Stone", "Débito", 1, "250,00", "1,39%", "246,52", data_base + timedelta(days=1)])
    linhas.append([data_base, "Stone", "Crédito à vista", 1, "500,00", "2,49%", "487,55", data_base + timedelta(days=30)])
    # Divergente: Stone aplicou 2,99% no parcelado 3x mas o contrato é 3,19%
    linhas.append([data_base, "Stone", "Crédito parcelado", 3, "1200,00", "2,99%", "1164,12", data_base + timedelta(days=30)])
    # Divergente: Stone aplicou 1,69% no débito (acima dos 1,39%)
    linhas.append([data_base, "Stone", "Débito", 1, "350,00", "1,69%", "344,09", data_base + timedelta(days=1)])
    linhas.append([data_base, "Stone", "Pix QR Code", 1, "200,00", "0,49%", "199,02", data_base + timedelta(days=1)])

    # Cielo — OK
    linhas.append([data_base, "Cielo", "Débito", 1, "150,00", "1,29%", "148,07", data_base + timedelta(days=1)])
    linhas.append([data_base, "Cielo", "Crédito à vista", 1, "800,00", "2,39%", "780,88", data_base + timedelta(days=30)])
    linhas.append([data_base, "Cielo", "Crédito parcelado", 6, "1800,00", "3,09%", "1744,38", data_base + timedelta(days=30)])

    # Rede — 1 OK, 1 divergente
    linhas.append([data_base, "Rede", "Crédito à vista", 1, "600,00", "2,59%", "584,46", data_base + timedelta(days=30)])
    # Divergente: Rede aplicou 3,55% no parcelado 4x mas contrato é 3,29%
    linhas.append([data_base, "Rede", "Crédito parcelado", 4, "900,00", "3,55%", "868,05", data_base + timedelta(days=30)])

    # Getnet — sem contrato cadastrado pra Pix (vai aparecer como "Sem contrato")
    linhas.append([data_base, "Getnet", "Pix QR Code", 1, "300,00", "0,39%", "298,83", data_base + timedelta(days=1)])

    df = pd.DataFrame(linhas, columns=[
        "data_venda", "adquirente", "modalidade", "parcelas",
        "valor_bruto", "taxa_aplicada", "valor_liquido", "data_prevista_recebimento",
    ])
    saida = SAMPLES_DIR / "relatorio_adquirente_exemplo.xlsx"
    df.to_excel(saida, index=False)
    print(f"OK: {saida} ({len(df)} linhas)")


if __name__ == "__main__":
    gerar_taxas_exemplo()
    gerar_relatorio_adquirente_exemplo()
