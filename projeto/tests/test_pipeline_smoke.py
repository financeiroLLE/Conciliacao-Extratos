"""Teste end-to-end: gera samples, roda pipeline, gera Excel multi-aba."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers import carregar_extrato_banco, carregar_relatorio_sistema
from src.pipeline import executar_pipeline
from src.reports import gerar_relatorio_excel, gerar_csvs_zip


def main():
    # Garante que samples existem
    from tests.gerar_samples import main as gerar
    gerar()

    SAMPLES = Path("data/samples")

    print("\n=== Lendo extratos ===")
    banco_a = carregar_extrato_banco(
        SAMPLES / "Bradesco-CC-12345.xlsx", conta="Bradesco-CC-12345"
    )
    banco_b = carregar_extrato_banco(
        SAMPLES / "Itau-CC-67890.xlsx", conta="Itau-CC-67890"
    )
    import pandas as pd
    banco = pd.concat([banco_a, banco_b], ignore_index=True)
    print(f"Banco: {len(banco)} linhas em {banco['conta'].nunique()} contas")

    sistema = carregar_relatorio_sistema(SAMPLES / "relatorio_sistema_exemplo.xlsx")
    print(f"Sistema: {len(sistema)} linhas em {sistema['conta'].nunique()} contas")

    print("\n=== Rodando pipeline ===")
    resultado = executar_pipeline(
        banco, sistema, data_referencia=datetime(2026, 5, 5)
    )

    kpis = resultado.kpis_globais()
    print(f"\nKPIs globais:")
    for k, v in kpis.items():
        if isinstance(v, float):
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")

    print(f"\nKPIs por banco:")
    for conta, k in resultado.kpis_por_banco().items():
        print(f"\n  [{conta}]")
        print(f"    conciliados: {k['qtd_conciliados']} / pendentes_b: {k['qtd_pendentes_banco']} / pendentes_s: {k['qtd_pendentes_sistema']}")
        print(f"    % conciliado: {k['percentual_conciliado']:.1f}%")

    print("\n=== Gerando relatório Excel ===")
    xlsx_bytes = gerar_relatorio_excel(resultado)
    out = Path("data/outputs/teste_smoke.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(xlsx_bytes)
    print(f"Excel: {out} ({len(xlsx_bytes) / 1024:.1f} KB)")

    print("\n=== Gerando CSVs zip ===")
    zip_bytes = gerar_csvs_zip(resultado)
    out_zip = Path("data/outputs/teste_smoke_csvs.zip")
    out_zip.write_bytes(zip_bytes)
    print(f"Zip CSV: {out_zip} ({len(zip_bytes) / 1024:.1f} KB)")

    print("\n✓ Smoke test concluído")


if __name__ == "__main__":
    main()
