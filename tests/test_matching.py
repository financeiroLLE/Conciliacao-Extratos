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


def teste_total_movimentado_exclui_apenas_saldo():
    """Total Movimentado no Banco (v3): exclui APENAS saldo. Aplic/resg ENTRAM."""
    banco = _df_banco([
        (_dt("04/05/2026"), "SALDO INICIAL", "", 5000.00, "C1"),
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 1000.00, "C1"),
        (_dt("04/05/2026"), "APLICAÇÃO AUTOMÁTICA", "", -2000.00, "C1"),
        (_dt("04/05/2026"), "RESGATE FUNDO", "", 500.00, "C1"),
        (_dt("04/05/2026"), "BOLETO", "B1", -300.00, "C1"),
        (_dt("04/05/2026"), "SALDO FINAL", "", 4200.00, "C1"),
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    kpis = res.kpis_globais()
    # v3: PIX 1000 + APLIC 2000 + RESGATE 500 + BOLETO 300 = 3800 (só saldo fora)
    assert kpis["total_movimentado_banco"] == 3800.00, \
        f"esperado 3800, veio {kpis['total_movimentado_banco']}"
    # Alias antigo deve continuar funcionando
    assert kpis["total_extrato_bancario"] == 3800.00
    # Receitas (v3): PIX 1000 + RESGATE 500 = 1500.
    # Despesas: APLIC 2000 + BOLETO 300 = 2300.
    assert kpis["receitas_banco"] == 1500.00
    assert kpis["despesas_banco"] == 2300.00
    print("✓ teste_total_movimentado_exclui_apenas_saldo")


def teste_aplicacoes_resgates_ainda_disponiveis_em_aba_propria():
    """Mesmo entrando no total, aplic/resg continuam no DataFrame aplicacoes_resgates."""
    banco = _df_banco([
        (_dt("04/05/2026"), "APLICAÇÃO AUTOMÁTICA", "A1", -2000.00, "C1"),
        (_dt("04/05/2026"), "RESGATE FUNDO", "R1", 500.00, "C1"),
        (_dt("04/05/2026"), "PIX", "", -100.00, "C1"),
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert len(res.aplicacoes_resgates) == 2, \
        f"esperado 2 aplic/resg na aba, veio {len(res.aplicacoes_resgates)}"
    tipos = set(res.aplicacoes_resgates["tipo_aplicacao"])
    assert "Aplicação" in tipos and "Resgate" in tipos
    print("✓ teste_aplicacoes_resgates_ainda_disponiveis_em_aba_propria")


def teste_excesso_no_sankhya():
    """Quando Sankhya tem mais lançamentos que banco, sinaliza o EXCEDENTE (pós-match)."""
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
    ])
    sistema = _df_banco([
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),  # 4º — vai sobrar
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # 3 conciliam, 1 sobra como pendente do Sankhya → 1 excedente
    assert len(res.conciliados) == 3
    assert len(res.excesso_sankhya) == 1, \
        f"esperado 1 excedente, veio {len(res.excesso_sankhya)}"
    print("✓ teste_excesso_no_sankhya")


def teste_excesso_sankhya_vazio_quando_banco_maior():
    """Banco com mais lançamentos do que Sankhya → NÃO há excedente do Sankhya."""
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX", "", 100.00, "C1"),
        (_dt("04/05/2026"), "PIX", "", 100.00, "C1"),
    ])
    sistema = _df_banco([
        (_dt("04/05/2026"), "PIX", "", 100.00, "C1"),
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert res.excesso_sankhya.empty, "banco maior não gera excesso do Sankhya"
    print("✓ teste_excesso_sankhya_vazio_quando_banco_maior")


def teste_receitas_despesas_absolutos_nao_compensam():
    """Receitas e despesas absolutas não se anulam mutuamente."""
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX RECEBIDO A", "", 10000.00, "C1"),
        (_dt("04/05/2026"), "PIX ENVIADO B", "", -7000.00, "C1"),
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    kpis = res.kpis_globais()
    assert kpis["receitas_banco"] == 10000.0
    assert kpis["despesas_banco"] == 7000.0  # POSITIVO
    assert kpis["total_extrato_bancario"] == 17000.0  # soma absoluta
    print("✓ teste_receitas_despesas_absolutos_nao_compensam")


def teste_possiveis_duplicidades_3_de_4():
    """Mesmo valor+data+histórico mas documentos diferentes = possível duplicidade."""
    banco = _df_banco([
        (_dt("04/05/2026"), "BOLETO ASTRA", "DOC-A", -1000.00, "C1"),
        (_dt("04/05/2026"), "BOLETO ASTRA", "DOC-B", -1000.00, "C1"),
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert not res.possiveis_duplicidades.empty, \
        "deveria detectar possível duplicidade (3 de 4)"
    assert res.duplicidades.empty, \
        "NÃO deveria detectar duplicidade estrita (docs diferentes)"
    print("✓ teste_possiveis_duplicidades_3_de_4")


def teste_falta_lancar_via_conciliado_nao():
    """Quando Sankhya tem coluna Conciliado preenchida, usa ela pra Falta Lançar."""
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX", "", -500.00, "C1"),
    ])
    # Sistema com 2 lançamentos: 1 conciliado=Sim, 1 conciliado=Não
    sistema = pd.DataFrame([
        {"data": _dt("04/05/2026"), "historico": "PIX", "documento": "",
         "valor": -500.00, "conta": "C1", "conciliado": "Sim",
         "agencia": "", "num_conta": "", "banco_nome": "",
         "tipo_movimento": "", "usuario": "", "num_unico_bancario": "",
         "origem": "sistema"},
        {"data": _dt("04/05/2026"), "historico": "OUTRO LANÇAMENTO", "documento": "",
         "valor": -200.00, "conta": "C1", "conciliado": "Não",
         "agencia": "", "num_conta": "", "banco_nome": "",
         "tipo_movimento": "", "usuario": "", "num_unico_bancario": "",
         "origem": "sistema"},
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert res.usa_conciliado_sankhya, "deveria detectar coluna Conciliado preenchida"
    kpis = res.kpis_globais()
    assert kpis["fonte_falta_lancar"] == "sankhya_conciliado_nao"
    assert kpis["falta_lancar"] == 200.0  # só o "Não"
    print("✓ teste_falta_lancar_via_conciliado_nao")


def teste_falta_lancar_fallback_quando_coluna_vazia():
    """Quando coluna Conciliado está vazia, usa regra antiga (pendentes pós-match)."""
    banco = _df_banco([(_dt("04/05/2026"), "PIX", "", -500.00, "C1")])
    sistema = _df_banco([
        (_dt("04/05/2026"), "PIX", "", -500.00, "C1"),
        (_dt("04/05/2026"), "OUTRO", "", -200.00, "C1"),
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert not res.usa_conciliado_sankhya, \
        "sem coluna Conciliado preenchida, não deveria usar"
    kpis = res.kpis_globais()
    assert kpis["fonte_falta_lancar"] == "pendentes_pos_match"
    # PIX casa, OUTRO de 200 fica pendente do sistema → Falta Lançar = 200
    assert kpis["falta_lancar"] == 200.0
    print("✓ teste_falta_lancar_fallback_quando_coluna_vazia")


def teste_falta_conciliar_separa_receita_despesa():
    """Card Falta Conciliar mostra receitas e despesas separadas."""
    banco = _df_banco([
        (_dt("04/05/2026"), "PIX RECEBIDO", "", 1500.00, "C1"),  # não casa
        (_dt("04/05/2026"), "BOLETO", "B1", -800.00, "C1"),       # não casa
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    kpis = res.kpis_globais()
    assert kpis["falta_conciliar_receitas"] == 1500.0
    assert kpis["falta_conciliar_despesas"] == 800.0
    assert kpis["falta_conciliar"] == 2300.0
    print("✓ teste_falta_conciliar_separa_receita_despesa")


def teste_saldo_final_quando_100():
    """Conta 100% conciliada com linhas de saldo → calcula saldo final."""
    banco = _df_banco([
        (_dt("01/05/2026"), "SALDO INICIAL", "", 10000.00, "C1"),
        (_dt("04/05/2026"), "PIX", "", -500.00, "C1"),
        (_dt("05/05/2026"), "SALDO FINAL", "", 9500.00, "C1"),
    ])
    sistema = _df_banco([(_dt("04/05/2026"), "PIX", "", -500.00, "C1")])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    info = res.saldo_final_da_conta("C1")
    assert info is not None, "deveria retornar info de saldo (100% conciliado)"
    assert info["saldo_inicial"] == 10000.00
    assert info["saldo_final"] == 9500.00
    assert info["tem_saldo_no_extrato"] is True
    print("✓ teste_saldo_final_quando_100")


def teste_saldo_final_so_se_100():
    """Quando não está 100%, saldo_final_da_conta retorna None."""
    banco = _df_banco([
        (_dt("01/05/2026"), "SALDO INICIAL", "", 10000.00, "C1"),
        (_dt("04/05/2026"), "PIX A", "", -500.00, "C1"),
        (_dt("04/05/2026"), "PIX B", "", -100.00, "C1"),
        (_dt("05/05/2026"), "SALDO FINAL", "", 9400.00, "C1"),
    ])
    sistema = _df_banco([(_dt("04/05/2026"), "PIX A", "", -500.00, "C1")])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    info = res.saldo_final_da_conta("C1")
    assert info is None, "não deveria ter saldo final (não está 100%)"
    print("✓ teste_saldo_final_so_se_100")


def teste_classificacao_movimento():
    from src.classificacao import classificar_movimentacao
    assert classificar_movimentacao("SALDO INICIAL") == "saldo"
    assert classificar_movimentacao("APLICAÇÃO AUTOMÁTICA") == "aplicacao"
    assert classificar_movimentacao("RESGATE FUNDO XYZ") == "resgate"
    assert classificar_movimentacao("PIX RECEBIDO") == "movimentacao"
    assert classificar_movimentacao("BOLETO ALUGUEL") == "movimentacao"
    assert classificar_movimentacao("COMPRA CDB") == "aplicacao"
    print("✓ teste_classificacao_movimento")


def teste_saldo_com_letras_separadas_por_espaco():
    """'S A L D O' deve ser reconhecido como saldo (caso real Itaú)."""
    from src.classificacao import classificar_movimentacao
    assert classificar_movimentacao("S A L D O") == "saldo"
    assert classificar_movimentacao("SDO APLIC AUT MAIS AP") == "saldo"
    print("✓ teste_saldo_com_letras_separadas_por_espaco")


def teste_rendimento_pago_e_movimentacao_nao_aplicacao():
    """'REND PAGO APLIC AUT' deve ser MOVIMENTAÇÃO (receita real), não aplicação."""
    from src.classificacao import classificar_movimentacao
    assert classificar_movimentacao("REND PAGO APLIC AUT APR") == "movimentacao"
    assert classificar_movimentacao("CRÉDITO RENDIMENTO") == "movimentacao"
    print("✓ teste_rendimento_pago_e_movimentacao_nao_aplicacao")


def teste_res_aplic_e_resgate():
    """'RES APLIC AUT' deve ser resgate, não aplicação."""
    from src.classificacao import classificar_movimentacao
    assert classificar_movimentacao("RES APLIC AUT MAIS AP") == "resgate"
    assert classificar_movimentacao("RESG. AUT MAIS") == "resgate"
    print("✓ teste_res_aplic_e_resgate")


def teste_baixa_api_e_boleto():
    """'BAIXA API' no Sankhya deve ser classificado como Boleto."""
    from src.classificacao import classificar_tipo
    assert classificar_tipo("BAIXA API FORNECEDOR XYZ") == "Boleto"
    assert classificar_tipo("BAIXA API") == "Boleto"
    print("✓ teste_baixa_api_e_boleto")


def teste_possiveis_duplic_ignora_documento_vazio():
    """Não dispara possíveis duplicidades quando documento é vazio (caso real Itaú SISPAG)."""
    banco = _df_banco([
        (_dt("14/05/2026"), "SISPAG FORNECEDORES", "", -2240.00, "C1"),
        (_dt("14/05/2026"), "SISPAG FORNECEDORES", "", -700.00, "C1"),
        (_dt("14/05/2026"), "SISPAG FORNECEDORES", "", -2700.00, "C1"),
    ])
    sistema = pd.DataFrame(columns=banco.columns)
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert res.possiveis_duplicidades.empty, \
        "documento vazio NÃO deveria disparar possíveis duplicidades"
    print("✓ teste_possiveis_duplic_ignora_documento_vazio")


def teste_excesso_sankhya_pos_match():
    """Excesso só sinaliza linhas pendentes do Sankhya (não as já conciliadas)."""
    banco = _df_banco([
        (_dt("14/05/2026"), "PIX", "", -1000.00, "C1"),
    ])
    sistema = _df_banco([
        (_dt("14/05/2026"), "FORNECEDOR XYZ", "", -1000.00, "C1"),  # casa
        (_dt("14/05/2026"), "FORNECEDOR ABC", "", -1000.00, "C1"),  # excedente
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # 1 deve casar, 1 fica como excesso
    assert len(res.conciliados) == 1, f"esperava 1 conciliado, veio {len(res.conciliados)}"
    assert len(res.excesso_sankhya) == 1, f"esperava 1 excesso, veio {len(res.excesso_sankhya)}"
    print("✓ teste_excesso_sankhya_pos_match")


def teste_divergencia_consolidada_aceita_receita():
    """v3.4: 'Divergência (Sankhya × Banco)' aceita receita (valor > 0).

    Cenário do print do usuário: lançamento de R$ 5.000 no Sankhya como receita,
    sem par no banco. Deve aparecer como Receita (não como Despesa)."""
    banco = _df_banco([
        (_dt("14/05/2026"), "PIX", "", -200.00, "C1"),
    ])
    sistema = _df_banco([
        (_dt("14/05/2026"), "PIX", "", -200.00, "C1"),  # casa
        (_dt("14/05/2026"), "RECEITA EXTRA", "", 5000.00, "C1"),  # receita extra
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    k = res.kpis_globais()
    assert k["divergencia_sankhya_banco"] == 5000.00, \
        f"esperado 5000, veio {k['divergencia_sankhya_banco']}"
    assert k["divergencia_sankhya_banco_receitas"] == 5000.00, "receita errada"
    assert k["divergencia_sankhya_banco_despesas"] == 0.0, "não deveria ter despesa"
    # Tem que aparecer no detalhamento
    div_df = res.divergencias_sankhya_banco()
    assert len(div_df) == 1
    assert div_df.iloc[0]["valor"] == 5000.00
    print("✓ teste_divergencia_consolidada_aceita_receita")


def teste_concat_multiplos_extratos_data_object():
    """v3.6: Pipeline não pode quebrar com 'merge on object and datetime64'
    quando vários extratos são concatenados e o tipo de 'data' fica object."""
    # Banco com data como STRING (object) — simula concat onde uma das partes perdeu o dtype
    banco = pd.DataFrame([
        {"data": "2026-05-14", "historico": "PIX", "documento": "", "valor": -100.0, "conta": "C1", "origem": "banco"},
        {"data": "2026-05-14", "historico": "TED", "documento": "", "valor": -200.0, "conta": "C2", "origem": "banco"},
    ])
    banco["data"] = banco["data"].astype("object")  # força object dtype

    sistema = pd.DataFrame([
        {"data": pd.Timestamp("2026-05-14"), "historico": "FORN A", "documento": "", "valor": -100.0, "conta": "C1", "origem": "sistema"},
        {"data": pd.Timestamp("2026-05-14"), "historico": "FORN B", "documento": "", "valor": -200.0, "conta": "C2", "origem": "sistema"},
        {"data": pd.Timestamp("2026-05-14"), "historico": "EXTRA",  "documento": "", "valor": 5000.0, "conta": "C1", "origem": "sistema"},  # excedente
    ])

    # Não deve quebrar
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert res is not None
    print("✓ teste_concat_multiplos_extratos_data_object")


def teste_divergencia_nao_conta_linha_ja_casada():
    """v3.11: Se o Sankhya marca uma linha como 'Conciliado=Não' MAS ela já casou
    no nosso match automático, NÃO deve aparecer em Divergência. Bug do print Sicredi:
    22 linhas conciliadas estavam aparecendo também em divergência."""
    banco = _df_banco([
        (_dt("14/05/2026"), "PIX RECEBIDO", "", 100.00, "C1"),
        (_dt("14/05/2026"), "PIX RECEBIDO", "", 200.00, "C1"),
    ])
    sistema = _df_banco([
        (_dt("14/05/2026"), "CLIENTE A", "", 100.00, "C1"),  # casa com banco
        (_dt("14/05/2026"), "CLIENTE B", "", 200.00, "C1"),  # casa com banco
    ])
    # Marca AMBAS como Conciliado=Não no Sankhya (cenário do bug)
    sistema["conciliado"] = "Não"

    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # Ambas casaram no match automático
    assert len(res.conciliados) == 2, f"esperava 2 conciliados, veio {len(res.conciliados)}"
    # Mas nenhuma deve aparecer como divergência (a falha era que entravam em 'Sem par no banco')
    div = res.divergencias_sankhya_banco()
    assert div.empty, (
        f"esperava 0 divergências (linhas já conciliadas no match), veio {len(div)}\n"
        f"{div.to_string() if not div.empty else ''}"
    )
    k = res.kpis_globais()
    assert k["qtd_divergencia_sankhya_banco"] == 0, \
        f"esperava qtd=0, veio {k['qtd_divergencia_sankhya_banco']}"
    print("✓ teste_divergencia_nao_conta_linha_ja_casada")


def teste_estorno_total_anula_par():
    """v5.0: par recebimento + estorno com saldo zero é anulado totalmente.
    Nenhum dos 2 entra em Pendentes/Falta Conciliar/Conta 70."""
    banco = _df_banco([
        (_dt("10/05/2026"), "RECEBIMENTO CARTAO STONE CLIENTE X", "", 1000.00, "C1"),
        (_dt("11/05/2026"), "ESTORNO RECEBIMENTO CARTAO STONE CLIENTE X", "", -1000.00, "C1"),
        (_dt("12/05/2026"), "TED RECEBIDA FORNECEDOR Y", "", 500.00, "C1"),  # entra normalmente
    ])
    sistema = _df_banco([])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)

    # 1 par anulado
    assert len(res.estornos_anulados) == 1, f"esperava 1 par, veio {len(res.estornos_anulados)}"
    par = res.estornos_anulados.iloc[0]
    assert par["status"] == "Anulado por Estorno"
    assert par["saldo_liquido"] == 0.0
    # Nem o original nem o estorno aparecem em pendentes
    pend = res.pendentes_banco
    assert len(pend) == 1, f"esperava 1 pendente, veio {len(pend)}: {pend}"
    assert pend.iloc[0]["valor"] == 500.00
    print("✓ teste_estorno_total_anula_par")


def teste_estorno_parcial_mantem_diferenca():
    """v5.0: par com valores diferentes (estorno parcial) mantém saldo na análise."""
    banco = _df_banco([
        (_dt("10/05/2026"), "PAGAMENTO FORNECEDOR Z", "", -1000.00, "C1"),
        (_dt("11/05/2026"), "ESTORNO PARCIAL PAGAMENTO Z", "", 300.00, "C1"),
    ])
    sistema = _df_banco([])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)

    # Sem anulado total (porque saldo != 0)
    assert res.estornos_anulados.empty
    # 1 estorno parcial detectado
    assert len(res.estornos_parciais) == 1
    par = res.estornos_parciais.iloc[0]
    assert par["saldo_liquido"] == -700.00
    # A diferença de -R$ 700 deve ter voltado pro fluxo como linha sintética
    pend = res.pendentes_banco
    # Tem que ter 1 linha com valor -700 e histórico marcado
    assert len(pend) == 1, f"esperava 1 pendente, veio {len(pend)}"
    assert pend.iloc[0]["valor"] == -700.00
    assert "[ESTORNO PARCIAL]" in pend.iloc[0]["historico"]
    print("✓ teste_estorno_parcial_mantem_diferenca")


def teste_estorno_palavra_chave_chargeback():
    """v5.0: chargeback é reconhecido como termo de estorno."""
    banco = _df_banco([
        (_dt("10/05/2026"), "RECEBIMENTO CARTAO STONE", "", 500.00, "C1"),
        (_dt("15/05/2026"), "CHARGEBACK STONE", "", -500.00, "C1"),
    ])
    sistema = _df_banco([])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert len(res.estornos_anulados) == 1
    par = res.estornos_anulados.iloc[0]
    assert par["motivo"].lower() == "chargeback"
    print("✓ teste_estorno_palavra_chave_chargeback")


def teste_estorno_fora_da_janela_nao_anula():
    """v5.0: par fora da janela de 7 dias não é considerado estorno."""
    banco = _df_banco([
        (_dt("01/05/2026"), "RECEBIMENTO CARTAO", "", 500.00, "C1"),
        (_dt("20/05/2026"), "ESTORNO CARTAO", "", -500.00, "C1"),  # 19 dias depois
    ])
    sistema = _df_banco([])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert res.estornos_anulados.empty
    # Ambos entram em pendentes
    assert len(res.pendentes_banco) == 2
    print("✓ teste_estorno_fora_da_janela_nao_anula")


def teste_estorno_sem_palavra_chave_nao_anula():
    """v5.0: par com valores opostos mas SEM palavra-chave de estorno no histórico
    não é tratado como estorno (poderia ser coisa diferente)."""
    banco = _df_banco([
        (_dt("10/05/2026"), "RECEBIMENTO CLIENTE A", "", 500.00, "C1"),
        (_dt("11/05/2026"), "PAGAMENTO FORNECEDOR B", "", -500.00, "C1"),  # mesmo valor mas sem palavra-chave
    ])
    sistema = _df_banco([])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert res.estornos_anulados.empty
    assert len(res.pendentes_banco) == 2
    print("✓ teste_estorno_sem_palavra_chave_nao_anula")


def teste_top1722_agrupamento_basico():
    """v5.2: 4 linhas Sankhya TOP 1722 somam exatamente o crédito do banco.
    Lógica nova: soma total por conta."""
    banco = _df_banco([
        (_dt("10/05/2026"), "CREDITO CARTAO STONE", "", 5000.00, "ITAU"),
    ])
    sistema = pd.DataFrame([
        {"data": _dt("10/05/2026"), "historico": "CLIENTE A", "documento": "NF001",
         "valor": 1200.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "CLIENTE B", "documento": "NF002",
         "valor": 800.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "CLIENTE C", "documento": "NF003",
         "valor": 2000.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "CLIENTE D", "documento": "NF004",
         "valor": 1000.00, "conta": "ITAU", "top_baixa": "1722"},
    ])

    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)

    # 1 grupo conciliado (1 conta = ITAU)
    assert len(res.top1722_grupos) == 1, f"esperava 1 grupo, veio {len(res.top1722_grupos)}"
    grupo = res.top1722_grupos.iloc[0]
    assert grupo["conta"] == "ITAU"
    assert grupo["qtd_creditos_banco"] == 1
    assert grupo["valor_banco_total"] == 5000.00
    assert grupo["qtd_linhas_sankhya"] == 4
    assert grupo["valor_sankhya_total"] == 5000.00
    assert grupo["diferenca"] == 0.0
    # Banco e Sankhya saíram de pendentes
    assert len(res.pendentes_banco) == 0
    assert len(res.pendentes_sistema) == 0
    print("✓ teste_top1722_agrupamento_basico")


def teste_top1722_sem_top_nao_agrupa():
    """v5.0: linhas sem TOP 1722 não devem entrar em agrupamento."""
    banco = _df_banco([
        (_dt("10/05/2026"), "CREDITO CARTAO", "", 1000.00, "ITAU"),
    ])
    sistema = pd.DataFrame([
        {"data": _dt("10/05/2026"), "historico": "X", "documento": "",
         "valor": 600.00, "conta": "ITAU", "top_baixa": "1500"},  # TOP diferente
        {"data": _dt("10/05/2026"), "historico": "Y", "documento": "",
         "valor": 400.00, "conta": "ITAU", "top_baixa": ""},  # sem TOP
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # Nenhum grupo deve formar (600+400=1000 mas TOPs não são 1722)
    assert res.top1722_grupos.empty
    print("✓ teste_top1722_sem_top_nao_agrupa")


def teste_top1722_com_diferenca_taxa():
    """v5.2: diferença pequena (< 3.5%) é tratada como taxa de cartão e AGRUPA.
    As linhas saem de Pendentes/Divergência."""
    banco = _df_banco([
        (_dt("10/05/2026"), "CREDITO CARTAO", "", 4850.00, "ITAU"),  # banco recebeu líquido (3% taxa)
    ])
    sistema = pd.DataFrame([
        {"data": _dt("10/05/2026"), "historico": "A", "documento": "",
         "valor": 2000.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "B", "documento": "",
         "valor": 3000.00, "conta": "ITAU", "top_baixa": "1722"},
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # Diferença R$ 150 sobre R$ 5000 = 3% → dentro da tolerância → agrupa COM DIFERENÇA
    assert res.top1722_grupos.empty  # não foi agrupamento "limpo"
    assert len(res.top1722_diferencas) == 1
    diff = res.top1722_diferencas.iloc[0]
    assert diff["valor_banco_total"] == 4850.00
    assert diff["valor_sankhya_total"] == 5000.00
    assert diff["diferenca"] == -150.00
    assert "Diferença" in diff["status"]
    # Linhas saíram de Pendentes mesmo com diferença
    assert len(res.pendentes_banco) == 0
    assert len(res.pendentes_sistema) == 0
    print("✓ teste_top1722_com_diferenca_taxa")


def teste_top1722_diferenca_grande_nao_agrupa():
    """v5.2: diferença > 3.5% NÃO agrupa, linhas continuam em Pendentes."""
    banco = _df_banco([
        # Banco R$ 1234 (valor que não casa direto com nenhuma linha individual do Sankhya)
        (_dt("10/05/2026"), "CREDITO CARTAO", "", 1234.00, "ITAU"),
    ])
    sistema = pd.DataFrame([
        # Sankhya soma R$ 5000 — diferença R$ 3766 (75%) → MUITO grande
        {"data": _dt("10/05/2026"), "historico": "A", "documento": "",
         "valor": 2000.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "B", "documento": "",
         "valor": 3000.00, "conta": "ITAU", "top_baixa": "1722"},
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # Diferença 75% → NÃO agrupa
    assert res.top1722_grupos.empty
    assert len(res.top1722_diferencas) == 1
    assert "NÃO agrupado" in res.top1722_diferencas.iloc[0]["status"]
    # Linhas continuam em Pendentes (Sankhya não foi consumido)
    assert len(res.pendentes_sistema) == 2
    print("✓ teste_top1722_diferenca_grande_nao_agrupa")


def teste_top1722_datas_diferentes_mesma_conta():
    """v5.2: vendas em datas diferentes da mesma conta entram no mesmo agrupamento.
    Agora não tem janela de data — agrupa POR CONTA."""
    banco = _df_banco([
        (_dt("10/05/2026"), "CREDITO CARTAO", "", 3000.00, "ITAU"),
    ])
    sistema = pd.DataFrame([
        # Vendas em datas diferentes — não importa pra lógica de soma por conta
        {"data": _dt("08/05/2026"), "historico": "A", "documento": "",
         "valor": 1500.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("09/05/2026"), "historico": "B", "documento": "",
         "valor": 1500.00, "conta": "ITAU", "top_baixa": "1722"},
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    assert len(res.top1722_grupos) == 1
    assert res.top1722_grupos.iloc[0]["qtd_linhas_sankhya"] == 2
    print("✓ teste_top1722_datas_diferentes_mesma_conta")


def teste_top1722_2_creditos_banco_mesma_conta():
    """v5.2: 2 créditos banco da mesma conta + 3 linhas Sankhya = 1 grupo (soma total)."""
    banco = _df_banco([
        (_dt("10/05/2026"), "CREDITO CARTAO GETNET", "", 1000.00, "ITAU"),
        (_dt("11/05/2026"), "CREDITO CARTAO GETNET", "", 2000.00, "ITAU"),
    ])
    sistema = pd.DataFrame([
        {"data": _dt("10/05/2026"), "historico": "A", "documento": "",
         "valor": 1000.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "B", "documento": "",
         "valor": 800.00, "conta": "ITAU", "top_baixa": "1722"},
        {"data": _dt("10/05/2026"), "historico": "C", "documento": "",
         "valor": 1200.00, "conta": "ITAU", "top_baixa": "1722"},
    ])
    res = executar_pipeline(banco, sistema, rodar_fuzzy=False)
    # Pode ter 1 match exato 1-pra-1 (R$ 1000) + grupo do resto (R$ 2000 = 800+1200)
    # OU pode agrupar tudo (banco 3000 = sankhya 3000)
    # O importante: nada fica em pendentes
    assert len(res.pendentes_banco) == 0, f"sobrou banco: {res.pendentes_banco}"
    assert len(res.pendentes_sistema) == 0, f"sobrou sankhya: {res.pendentes_sistema}"
    # Valor total casado = R$ 3000 (match + agrupamento)
    valor_conciliado_total = (
        res.conciliados["banco_valor"].sum()
        if not res.conciliados.empty and "banco_valor" in res.conciliados.columns else 0
    )
    valor_grupo = (
        res.top1722_grupos["valor_banco_total"].sum()
        if not res.top1722_grupos.empty else 0
    )
    assert abs(valor_conciliado_total + valor_grupo - 3000.00) < 0.01, (
        f"esperava R$ 3000 total, veio R$ {valor_conciliado_total + valor_grupo}"
    )
    print("✓ teste_top1722_2_creditos_banco_mesma_conta")


def teste_extrato_com_metadados_antes_do_cabecalho():
    """v3.7: Extrato bancário com linhas de metadados (Nome, Agência, Data emissão...)
    ANTES do cabeçalho real. O parser deve detectar dinamicamente a linha do header."""
    import openpyxl
    from io import BytesIO
    from src.parsers import carregar_extrato_banco

    # Simula extrato Itaú: várias linhas de metadados antes do cabeçalho
    wb = openpyxl.Workbook()
    ws = wb.active
    # Linhas de metadados (10 linhas antes do cabeçalho real)
    ws.append(["", "", "", "", "", "", ""])
    ws.append(["", "Nome:", "", "", "L.L.E. FERRAGENS LTDA.", "Agência/Conta:", "0023/ 78861-5"])
    ws.append(["", "", "", "", "", "", ""])
    ws.append(["", "Data:", "", "", "15/05/2026", "Horário:", "08:05:39h"])
    ws.append(["", "", "", "", "", "", ""])
    ws.append(["", "Extrato de Conta Corrente", "", "", "", "", ""])
    ws.append(["", "", "", "", "", "", ""])
    # AGORA o cabeçalho real:
    ws.append(["", "Data", "", "", "Lançamento", "Valor (R$)", "Saldo (R$)"])
    # Dados:
    ws.append(["", "14/05", "", "", "PIX RECEBIDO CLIENTE A", -1000.00, ""])
    ws.append(["", "14/05", "", "", "TED ENVIADA FORNECEDOR", -500.00, ""])
    ws.append(["", "14/05", "", "", "S A L D O", None, "5000"])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = "extrato_itau_metadados.xlsx"

    df = carregar_extrato_banco(buf, conta="itau", ano_referencia=2026)
    assert len(df) == 2, f"esperava 2 linhas, veio {len(df)}"
    assert df["valor"].abs().sum() == 1500.00, f"soma errada: {df['valor'].abs().sum()}"
    print("✓ teste_extrato_com_metadados_antes_do_cabecalho")


def teste_conta70_basico():
    """v5.0: créditos banco sem par viram linhas Conta 70 com status 'Não identificado'."""
    from src.conta70 import gerar_conta_70
    pend_banco = _df_banco([
        (_dt("10/05/2026"), "PIX RECEBIDO CLIENTE X", "", 500.00, "ITAU"),
        (_dt("10/05/2026"), "TED FORNECEDOR Y", "", -300.00, "ITAU"),  # despesa não vai
        (_dt("11/05/2026"), "CREDITO NF DESCONHECIDA", "", 1000.00, "ITAU"),
    ])
    res = gerar_conta_70(pend_banco)
    assert len(res.detalhado) == 2, f"esperava 2 (só créditos), veio {len(res.detalhado)}"
    assert all(res.detalhado["status"] == "Não identificado")
    assert all(res.detalhado["conta_contabil"] == "Conta 70")
    assert res.kpis["total_a_lancar"] == 1500.00
    assert res.kpis["qtd_total"] == 2
    print("✓ teste_conta70_basico")


def teste_conta70_historico_mantem_regularizado():
    """v5.0: linhas marcadas como Regularizado no histórico mantêm o status."""
    from src.conta70 import gerar_conta_70
    pend_banco = _df_banco([
        (_dt("10/05/2026"), "PIX CLIENTE X", "", 500.00, "ITAU"),
        (_dt("11/05/2026"), "PIX CLIENTE Y", "", 800.00, "ITAU"),
    ])
    historico = pd.DataFrame([
        {"data": _dt("10/05/2026"), "conta": "ITAU", "historico": "PIX CLIENTE X",
         "valor": 500.00, "status": "Regularizado", "observacao": "NF 123"},
    ])
    res = gerar_conta_70(pend_banco, historico_anterior=historico)
    # 1 linha veio do histórico (Regularizada)
    reg = res.detalhado[res.detalhado["status"] == "Regularizado"]
    assert len(reg) == 1
    assert reg.iloc[0]["observacao"] == "NF 123"
    # Outra continua "Não identificado"
    nao_ident = res.detalhado[res.detalhado["status"] == "Não identificado"]
    assert len(nao_ident) == 1
    # Total a lançar = só a NÃO regularizada (800)
    assert res.kpis["total_a_lancar"] == 800.00
    print("✓ teste_conta70_historico_mantem_regularizado")


def teste_conta70_classificacao_tipo():
    """v5.0: classifica tipo do recebimento pelo histórico (Pix, Cartão, TED, etc)."""
    from src.conta70 import gerar_conta_70
    pend_banco = _df_banco([
        (_dt("10/05/2026"), "PIX RECEBIDO CLIENTE X", "", 500.00, "ITAU"),
        (_dt("10/05/2026"), "TED RECEBIDA", "", 1000.00, "ITAU"),
        (_dt("10/05/2026"), "BOLETO PAGO", "", 800.00, "ITAU"),
        (_dt("10/05/2026"), "CREDITO CARTAO STONE", "", 2000.00, "ITAU"),
    ])
    res = gerar_conta_70(pend_banco)
    tipos = res.detalhado["tipo_recebimento"].tolist()
    assert "Pix" in tipos
    assert "TED/DOC" in tipos
    assert "Boleto" in tipos
    assert "Cartão" in tipos
    print("✓ teste_conta70_classificacao_tipo")


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
