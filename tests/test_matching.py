"""Testes unitários com dados sintéticos para validar a lógica de conciliação."""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.matching import (
    conciliar_exato,
    detectar_banco_errado,
    detectar_divergencia_valor,
    detectar_duplicidades,
)


def _df_banco(rows):
    df = pd.DataFrame(rows, columns=["data", "historico", "valor", "conta"])
    df["data"] = pd.to_datetime(df["data"])
    df["origem"] = "banco"
    df["_row_id"] = [f"BCO-{i:03d}" for i in range(len(df))]
    df["documento"] = ""
    return df


def _df_sistema(rows):
    df = pd.DataFrame(rows, columns=["data", "historico", "valor", "conta"])
    df["data"] = pd.to_datetime(df["data"])
    df["origem"] = "sistema"
    df["_row_id"] = [f"SIS-{i:03d}" for i in range(len(df))]
    df["num_unico_bancario"] = ""
    df["num_documento"] = ""
    df["conciliado"] = "Sim"
    df["tipo_movimento"] = ""
    df["usuario"] = ""
    return df


def test_match_perfeito():
    """3 lançamentos iguais nos dois lados → 3 matches, 0 pendências."""
    banco = _df_banco([
        ("2026-05-04", "PIX LLE", -1000.00, "C1"),
        ("2026-05-04", "TAR COB", -3.00, "C1"),
        ("2026-05-05", "PIX OUT", -500.50, "C1"),
    ])
    sistema = _df_sistema([
        ("2026-05-04", "Pagamento LLE", -1000.00, "C1"),
        ("2026-05-04", "Tarifa cobrança", -3.00, "C1"),
        ("2026-05-05", "Pagamento OUT", -500.50, "C1"),
    ])
    r = conciliar_exato(banco, sistema)
    assert len(r["conciliados"]) == 3, f"Esperado 3, veio {len(r['conciliados'])}"
    assert len(r["pendentes_banco"]) == 0
    assert len(r["pendentes_sistema"]) == 0
    print("✅ test_match_perfeito")


def test_pendencia_banco():
    """Banco tem 1 lançamento que não está no sistema."""
    banco = _df_banco([
        ("2026-05-04", "PIX A", -100.00, "C1"),
        ("2026-05-04", "PIX B", -200.00, "C1"),  # não tem no sistema
    ])
    sistema = _df_sistema([
        ("2026-05-04", "Pgto A", -100.00, "C1"),
    ])
    r = conciliar_exato(banco, sistema)
    assert len(r["conciliados"]) == 1
    assert len(r["pendentes_banco"]) == 1
    assert r["pendentes_banco"].iloc[0]["valor"] == -200.00
    print("✅ test_pendencia_banco")


def test_pendencia_sistema():
    """Sistema tem lançamento que não foi pro banco (lançamento indevido)."""
    banco = _df_banco([
        ("2026-05-04", "PIX A", -100.00, "C1"),
    ])
    sistema = _df_sistema([
        ("2026-05-04", "Pgto A", -100.00, "C1"),
        ("2026-05-04", "Pgto INDEVIDO", -999.00, "C1"),  # não tem no banco
    ])
    r = conciliar_exato(banco, sistema)
    assert len(r["conciliados"]) == 1
    assert len(r["pendentes_sistema"]) == 1
    assert r["pendentes_sistema"].iloc[0]["valor"] == -999.00
    print("✅ test_pendencia_sistema")


def test_duplicidades_multiplas_no_mesmo_dia():
    """3 lançamentos iguais no banco × 2 iguais no sistema → 2 casam, 1 fica."""
    banco = _df_banco([
        ("2026-05-04", "TAR", -3.00, "C1"),
        ("2026-05-04", "TAR", -3.00, "C1"),
        ("2026-05-04", "TAR", -3.00, "C1"),
    ])
    sistema = _df_sistema([
        ("2026-05-04", "TAR", -3.00, "C1"),
        ("2026-05-04", "TAR", -3.00, "C1"),
    ])
    r = conciliar_exato(banco, sistema)
    assert len(r["conciliados"]) == 2
    assert len(r["pendentes_banco"]) == 1
    print("✅ test_duplicidades_multiplas_no_mesmo_dia")


def test_banco_errado():
    """Lançamento no banco da C1 mas baixado no sistema da C2."""
    banco = _df_banco([
        ("2026-05-04", "PIX RECEBIDO", 5000.00, "C1"),
    ])
    sistema = _df_sistema([
        ("2026-05-04", "Receb cliente", 5000.00, "C2"),  # conta errada
    ])
    # Primeiro vê que não conciliam (contas diferentes)
    r = conciliar_exato(banco, sistema)
    assert len(r["conciliados"]) == 0

    # Depois detecta banco errado
    suspeitos = detectar_banco_errado(r["pendentes_banco"], r["pendentes_sistema"])
    assert len(suspeitos) == 1
    assert suspeitos.iloc[0]["conta_correta_banco"] == "C1"
    assert suspeitos.iloc[0]["conta_baixada_sistema"] == "C2"
    print("✅ test_banco_errado")


def test_duplicidades_dentro_do_banco():
    """Mesmo lançamento aparecendo 2x no extrato → duplicidade."""
    banco = _df_banco([
        ("2026-05-04", "PIX LLE", -1000.00, "C1"),
        ("2026-05-04", "PIX LLE", -1000.00, "C1"),  # duplicata
        ("2026-05-04", "PIX OUTRO", -50.00, "C1"),
    ])
    dups = detectar_duplicidades(banco, lado="banco")
    assert len(dups) == 2, f"Esperado 2 duplicatas, veio {len(dups)}"
    print("✅ test_duplicidades_dentro_do_banco")


def test_divergencia_valor():
    """Mesma data + histórico parecido, valores diferentes."""
    banco = _df_banco([
        ("2026-05-04", "PAGAMENTO TITULO ABC", -1000.00, "C1"),
    ])
    sistema = _df_sistema([
        ("2026-05-04", "PAGAMENTO TITULO ABC", -1050.00, "C1"),  # diferença de R$50
    ])
    divs = detectar_divergencia_valor(banco, sistema)
    assert len(divs) == 1
    assert divs.iloc[0]["diferenca"] == 50.00
    print("✅ test_divergencia_valor")


def test_data_formato_brasileiro():
    """REGRESSÃO: garantir que datas DD/MM/AAAA não são interpretadas
    como MM/DD/AAAA. Este bug existiu nas primeiras versões e teria
    quebrado conciliação em produção."""
    import tempfile
    from openpyxl import Workbook

    # Cria sample mínimo do sistema com data brasileira
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "Conciliação Bancária"
        ws["A2"] = "Emissão"
        ws.cell(row=3, column=1, value="Dt. Lançamento")
        ws.cell(row=3, column=2, value="Histórico")
        ws.cell(row=3, column=3, value="Vlr. Lançamento")
        ws.cell(row=3, column=4, value="Receita/Despesa")
        ws.cell(row=4, column=1, value="04/05/2026")  # 4 de MAIO
        ws.cell(row=4, column=2, value="TESTE")
        ws.cell(row=4, column=3, value=100.00)
        ws.cell(row=4, column=4, value="Despesa")
        wb.save(f.name)

        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.parsers import carregar_relatorio_sistema

        df = carregar_relatorio_sistema(f.name)
        # Deve ser 4 de MAIO (mês=5), não 5 de abril (mês=4)
        assert df.iloc[0]["data"].month == 5, (
            f"BUG REGRESSO: data interpretada como mês {df.iloc[0]['data'].month}, esperado 5"
        )
        assert df.iloc[0]["data"].day == 4
    print("✅ test_data_formato_brasileiro")



if __name__ == "__main__":
    test_match_perfeito()
    test_pendencia_banco()
    test_pendencia_sistema()
    test_duplicidades_multiplas_no_mesmo_dia()
    test_banco_errado()
    test_duplicidades_dentro_do_banco()
    test_divergencia_valor()
    test_data_formato_brasileiro()
    print("\n🎉 Todos os testes passaram!")
