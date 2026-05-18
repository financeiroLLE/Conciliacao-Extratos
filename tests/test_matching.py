"""Testes das regras de conciliação.

Roda com: python -m pytest tests/ -v
Ou: python tests/test_matching.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Permite rodar standalone
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.matching.exact_match import match_exato
from src.matching.auditorias import (
    detectar_divergencia_valor,
    detectar_duplicidades,
    detectar_nao_pertence,
)
from src.classificacao import classificar_tipo, adicionar_classificacao
from src.pipeline import executar_pipeline


# ===========================================================================
# Helpers
# ===========================================================================

def _df_banco(linhas):
    return pd.DataFrame(linhas, columns=[
        "data", "historico", "documento", "valor", "conta"
    ])


def _dt(s):
    return datetime.strptime(s, "%d/%m/%Y")


# ===========================================================================
# Testes
# ===========================================================================

def teste_match_exato_basico():
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX ENVIADO LLE", "", -1000.00, "Bradesco"),
        (_dt("04/05/2026"), "TAR LIQ COB COM REG", "193956", -3.00, "Bradesco"),
    ])
    sistema = _df_banco([
        (_dt("04/05/2026"), "PIX LLE", "X1", -1000.00, "Bradesco"),
        (_dt("04/05/2026"), "TARIFA COBRANCA", "193956", -3.00, "Bradesco"),
    ])
    conciliados, pb, ps = match_exato(banco, sistema)
    assert len(conciliados) == 2, f"esperado 2 conciliados, veio {len(conciliados)}"
    assert pb.empty and ps.empty
    print("✓ teste_match_exato_basico")


def teste_match_sem_tolerancia_de_valor():
    """Valor exato — diferença de 1 centavo NÃO casa."""
    banco = _df_banco([(_dt("04/05/2026"), "PIX", "", -1000.00, "C1")])
    sistema = _df_banco([(_dt("04/05/2026"), "PIX", "", -1000.01, "C1")])
    conciliados, pb, ps = match_exato(banco, sistema)
    assert conciliados.empty, "valor c/ 1 centavo de diferença não pode casar"
    assert len(pb) == 1 and len(ps) == 1
    print("✓ teste_match_sem_tolerancia_de_valor")


def teste_match_com_tolerancia_de_data():
    """Sexta no banco, segunda no sistema → casa com tolerância 2 dias (default)."""
    banco = _df_banco([(_dt("01/05/2026"), "PIX", "", -500.00, "C1")])  # sexta
    sistema = _df_banco([(_dt("04/05/2026"), "PIX", "", -500.00, "C1")])  # segunda
    conciliados, pb, ps = match_exato(banco, sistema, tolerancia_dias=3)
    assert len(conciliados) == 1, f"esperado 1 conciliado, veio {len(conciliados)}"
    assert conciliados.iloc[0]["dias_diferenca"] == 3
    print("✓ teste_match_com_tolerancia_de_data")


def teste_match_fora_da_tolerancia_de_data():
    banco = _df_banco([(_dt("01/05/2026"), "PIX", "", -500.00, "C1")])
    sistema = _df_banco([(_dt("10/05/2026"), "PIX", "", -500.00, "C1")])
    conciliados, pb, ps = match_exato(banco, sistema, tolerancia_dias=2)
    assert conciliados.empty
    assert len(pb) == 1 and len(ps) == 1
    print("✓ teste_match_fora_da_tolerancia_de_data")


def teste_match_1_para_1():
    """3 lançamentos R$ 3 no banco × 2 no sistema → 2 casam, 1 fica pendente."""
    banco = _df_banco([
        (_dt("04/05/2026"), "TAR", f"D{i}", -3.00, "C1") for i in range(3)
    ])
    sistema = _df_banco([
        (_dt("04/05/2026"), "TAR", f"S{i}", -3.00, "C1") for i in range(2)
    ])
    conciliados, pb, ps = match_exato(banco, sistema)
    assert len(conciliados) == 2
    assert len(pb) == 1
    assert ps.empty
    print("✓ teste_match_1_para_1")


def teste_match_so_casa_se_conta_igual():
    banco = _df_banco([(_dt("04/05/2026"), "PIX", "", -100.00, "C1")])
    sistema = _df_banco([(_dt("04/05/2026"), "PIX", "", -100.00, "C2")])
    conciliados, pb, ps = match_exato(banco, sistema)
    assert conciliados.empty
    assert len(pb) == 1 and len(ps) == 1
    print("✓ teste_match_so_casa_se_conta_igual")


def teste_data_formato_brasileiro():
    """Regressão: 04/05/2026 deve ser 4 de maio, não 5 de abril."""
    from src.parsers.extrato_banco import _parse_valor_brl
    # Cria DataFrame com data string e testa que pd.to_datetime com dayfirst=True funciona
    dt = pd.to_datetime("04/05/2026", dayfirst=True)
    assert dt.day == 4
    assert dt.month == 5
    assert dt.year == 2026
    print("✓ teste_data_formato_brasileiro")


def teste_divergencia_valor_so_quando_historico_exato():
    """Histórico precisa ser idêntico após normalização (sem prefixo de 15 chars)."""
    pb = _df_banco([(_dt("04/05/2026"), "TAR LIQ COB COM REG COMPE", "1", -3.00, "C1")])
    ps = _df_banco([(_dt("04/05/2026"), "TAR LIQ COB CORBAN GAR", "2", -5.00, "C1")])
    div = detectar_divergencia_valor(pb, ps)
    assert div.empty, "históricos parecidos mas diferentes NÃO podem virar divergência"
    print("✓ teste_divergencia_valor_so_quando_historico_exato")


def teste_divergencia_valor_dispara_quando_historico_igual():
    pb = _df_banco([(_dt("04/05/2026"), "TARIFA   COB", "1", -3.00, "C1")])
    ps = _df_banco([(_dt("04/05/2026"), "tarifa cob", "2", -3.50, "C1")])
    div = detectar_divergencia_valor(pb, ps)
    assert len(div) == 1, f"esperado 1, veio {len(div)}"
    assert abs(div.iloc[0]["diferenca"] - 0.50) < 0.001
    print("✓ teste_divergencia_valor_dispara_quando_historico_igual")


def teste_duplicidade_estrita_so_com_4_campos_iguais():
    """5x faturas ASTRA legítimas com docs DIFERENTES → não é duplicidade."""
    banco = _df_banco([
        (_dt("04/05/2026"), "FATURA ASTRA", f"DOC{i}", -1000.00, "C1") for i in range(5)
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    dup = detectar_duplicidades(banco, sistema)
    assert dup.empty, "valores iguais com docs diferentes NÃO são duplicidade"
    print("✓ teste_duplicidade_estrita_so_com_4_campos_iguais")


def teste_duplicidade_quando_tudo_repete():
    """Mesmo data + histórico + valor + documento → duplicidade."""
    banco = _df_banco([
        (_dt("04/05/2026"), "BOLETO X", "DOC1", -1000.00, "C1"),
        (_dt("04/05/2026"), "BOLETO X", "DOC1", -1000.00, "C1"),  # repete
        (_dt("04/05/2026"), "BOLETO X", "DOC1", -1000.00, "C1"),  # repete
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    dup = detectar_duplicidades(banco, sistema)
    assert len(dup) == 1, f"esperado 1 grupo duplicado, veio {len(dup)}"
    assert dup.iloc[0]["ocorrencias"] == 3
    print("✓ teste_duplicidade_quando_tudo_repete")


def teste_nao_pertence_a_conta():
    """Pendência R$ 500 em C1 do banco × pendência R$ 500 em C2 do sistema → suspeito."""
    pb = _df_banco([(_dt("04/05/2026"), "PIX", "", -500.00, "C1")])
    ps = _df_banco([(_dt("04/05/2026"), "PIX", "", -500.00, "C2")])
    nao_pert = detectar_nao_pertence(pb, ps)
    assert len(nao_pert) == 2, "deve detectar dos dois lados"
    assert set(nao_pert["origem"]) == {"banco", "sistema"}
    print("✓ teste_nao_pertence_a_conta")


def teste_classificacao_tipos():
    assert classificar_tipo("PIX RECEBIDO") == "Pix"
    # "TAR LIQ COB" tem TAR (Tarifa) e COB (Boleto). Tarifa vence (ordem).
    assert classificar_tipo("TAR LIQ COB COM") == "Tarifa"
    assert classificar_tipo("BOLETO PAGAMENTO LUZ") == "Boleto"
    assert classificar_tipo("DARF FEDERAL") == "Imposto"
    assert classificar_tipo("TED ENVIADA") == "TED/DOC"
    assert classificar_tipo("XYZ COMPRA AVULSA") == "Outros"
    print("✓ teste_classificacao_tipos")


def teste_pipeline_integrado():
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX LLE", "", -1000.00, "Bradesco"),
        (_dt("04/05/2026"), "TARIFA", "T1", -3.00, "Bradesco"),
        (_dt("04/05/2026"), "BOLETO X", "B1", -500.00, "Bradesco"),
    ])
    sistema = _df_banco([
        (_dt("04/05/2026"), "PIX LLE", "", -1000.00, "Bradesco"),
        (_dt("04/05/2026"), "TARIFA", "T1", -3.00, "Bradesco"),
        # 500 não está no sistema → pendente do banco
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert len(res.conciliados) == 2
    assert len(res.pendentes_banco) == 1
    assert res.pendentes_sistema.empty
    kpis = res.kpis_globais()
    assert kpis["qtd_conciliados"] == 2
    assert kpis["total_extrato_bancario"] == 1503.00
    assert kpis["total_conciliado"] == 1003.00
    # %: 1003/1503 ≈ 66.7%
    assert 66.0 < kpis["percentual_conciliado"] < 67.5
    print("✓ teste_pipeline_integrado")


def teste_kpis_por_banco():
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX", "", -100.00, "ContaA"),
        (_dt("04/05/2026"), "PIX", "", -200.00, "ContaB"),
    ])
    sistema = _df_banco([
        (_dt("04/05/2026"), "PIX", "", -100.00, "ContaA"),
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    kpis_pb = res.kpis_por_banco()
    assert set(kpis_pb.keys()) == {"ContaA", "ContaB"}
    assert kpis_pb["ContaA"]["qtd_conciliados"] == 1
    assert kpis_pb["ContaB"]["qtd_conciliados"] == 0
    assert kpis_pb["ContaB"]["qtd_pendentes_banco"] == 1
    print("✓ teste_kpis_por_banco")


def teste_adicionar_classificacao_em_df_vazio():
    df = pd.DataFrame(columns=["data", "historico", "valor"])
    out = adicionar_classificacao(df)
    assert "tipo" in out.columns and "natureza" in out.columns
    assert out.empty
    print("✓ teste_adicionar_classificacao_em_df_vazio")


def main():
    testes = [v for k, v in globals().items() if k.startswith("teste_")]
    falhas = []
    for t in testes:
        try:
            t()
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            falhas.append(t.__name__)
        except Exception as e:
            print(f"✗ {t.__name__}: {type(e).__name__}: {e}")
            falhas.append(t.__name__)
    print()
    print(f"{len(testes) - len(falhas)}/{len(testes)} passaram")
    return 0 if not falhas else 1


if __name__ == "__main__":
    sys.exit(main())
