"""Gera arquivos sintéticos consistentes em data/samples/ para testes manuais."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


SAMPLES = Path("data/samples")


def gerar_extrato_banco_simples():
    rows = [
        (datetime(2026, 5, 4), "SALDO INICIAL", "", 8500.00),
        (datetime(2026, 5, 4), "PIX RECEBIDO CLIENTE A", "", 1500.00),
        (datetime(2026, 5, 4), "PIX ENVIADO FORNECEDOR X", "", -800.00),
        (datetime(2026, 5, 4), "BOLETO PAGAMENTO LUZ", "BOL-123", -350.00),
        (datetime(2026, 5, 4), "TAR LIQ COB", "T1", -3.00),
        (datetime(2026, 5, 4), "TAR LIQ COB", "T2", -3.00),
        (datetime(2026, 5, 4), "TED RECEBIDA", "", 5000.00),
        (datetime(2026, 5, 4), "APLICAÇÃO AUTOMÁTICA", "APL-1", -3000.00),
        (datetime(2026, 5, 5), "RESGATE FUNDO INVEST", "RG-1", 1000.00),
        (datetime(2026, 5, 5), "DARF FEDERAL", "DARF1", -1200.00),
        # Esse fica como pendência (não está no sistema)
        (datetime(2026, 5, 5), "PIX TAXA EXTRA", "", -45.00),
        (datetime(2026, 5, 5), "SALDO FINAL", "", 10599.00),
    ]
    df = pd.DataFrame(rows, columns=["Data", "Histórico", "Documento", "Valor (R$)"])
    return df


def gerar_extrato_banco_outra_conta():
    rows = [
        (datetime(2026, 5, 4), "BOLETO ALUGUEL", "B-99", -2500.00),
        (datetime(2026, 5, 4), "RECEBIMENTO CLIENTE B", "", 3200.00),
    ]
    df = pd.DataFrame(rows, columns=["Data", "Histórico", "Documento", "Valor (R$)"])
    return df


def gerar_relatorio_sistema():
    # Layout do ERP: linha 1 título, linha 2 metadado, linha 3 cabeçalho, linha 4+ dados
    cabecalho = ["Dt. Lançamento", "Histórico", "Núm. Documento", "Vlr. Lançamento",
                  "Receita/Despesa", "Conta Bancária", "Conciliado"]
    dados = [
        # Bradesco-CC-12345 — devem casar com extrato simples
        ("04/05/2026", "PIX RECEBIDO CLIENTE A", "", 1500.00, "Receita", "Bradesco-CC-12345", "Não"),
        ("04/05/2026", "PIX ENVIADO FORNECEDOR X", "", 800.00, "Despesa", "Bradesco-CC-12345", "Não"),
        ("04/05/2026", "BOLETO PAGAMENTO LUZ", "BOL-123", 350.00, "Despesa", "Bradesco-CC-12345", "Não"),
        ("04/05/2026", "TAR LIQ COB", "T1", 3.00, "Despesa", "Bradesco-CC-12345", "Não"),
        ("04/05/2026", "TAR LIQ COB", "T2", 3.00, "Despesa", "Bradesco-CC-12345", "Não"),
        ("04/05/2026", "TED RECEBIDA", "", 5000.00, "Receita", "Bradesco-CC-12345", "Não"),
        ("05/05/2026", "DARF FEDERAL", "DARF1", 1200.00, "Despesa", "Bradesco-CC-12345", "Não"),
        # Esse vai virar "falta lançar" (não está no banco)
        ("05/05/2026", "TRANSFERENCIA INDEVIDA", "", 999.00, "Despesa", "Bradesco-CC-12345", "Não"),
        # Itau-CC-67890
        ("04/05/2026", "BOLETO ALUGUEL", "B-99", 2500.00, "Despesa", "Itau-CC-67890", "Não"),
        ("04/05/2026", "RECEBIMENTO CLIENTE B", "", 3200.00, "Receita", "Itau-CC-67890", "Não"),
    ]
    df_dados = pd.DataFrame(dados, columns=cabecalho)

    # Compõe o arquivo final com as 2 linhas iniciais de metadata
    SAMPLES.mkdir(parents=True, exist_ok=True)
    path = SAMPLES / "relatorio_sistema_exemplo.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        # Folha vazia primeiro
        ws_temp = pd.DataFrame([["Conciliação Bancária"]])
        ws_temp.to_excel(writer, sheet_name="Relatorio", index=False, header=False, startrow=0)
        # Linha de metadado
        meta = pd.DataFrame([["Emissão: 05/05/2026 · Total: 10 registros · Usuário: TESTE"]])
        meta.to_excel(writer, sheet_name="Relatorio", index=False, header=False, startrow=1)
        # Cabeçalho e dados
        df_dados.to_excel(writer, sheet_name="Relatorio", index=False, startrow=2)
    return path


def gerar_extrato_xlsx(df: pd.DataFrame, nome: str) -> Path:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    path = SAMPLES / nome
    df.to_excel(path, index=False, engine="openpyxl")
    return path


def main():
    extrato1 = gerar_extrato_banco_simples()
    extrato2 = gerar_extrato_banco_outra_conta()
    p1 = gerar_extrato_xlsx(extrato1, "Bradesco-CC-12345.xlsx")
    p2 = gerar_extrato_xlsx(extrato2, "Itau-CC-67890.xlsx")
    p3 = gerar_relatorio_sistema()
    print(f"Gerados:\n  - {p1}\n  - {p2}\n  - {p3}")


if __name__ == "__main__":
    main()
