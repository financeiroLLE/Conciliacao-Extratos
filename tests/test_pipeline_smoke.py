"""Teste de fumaça do pipeline com os arquivos reais do usuário."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parsers import carregar_extrato_banco, carregar_relatorio_sistema
from src.pipeline import executar_pipeline
from src.reports import salvar_relatorio


def main():
    print("=" * 70)
    print("TESTE DE FUMAÇA — Pipeline com arquivos reais")
    print("=" * 70)

    # 1. Carrega extrato bancário
    print("\n[1/4] Carregando extrato bancário...")
    banco = carregar_extrato_banco(
        "/mnt/user-data/uploads/05_Maio_COPIA.xlsx",
        conta="CC-12345",  # nome fictício da conta
    )
    print(f"    Linhas: {len(banco)}")
    print(f"    Datas: {banco['data'].min().date()} a {banco['data'].max().date()}")
    print(f"    Valor total: R$ {banco['valor'].sum():,.2f}")
    print(f"    Amostra:")
    print(banco.head(3).to_string())

    # 2. Carrega sistema
    # Usa a versão convertida (xlsx) porque é mais robusta
    print("\n[2/4] Carregando relatório do sistema...")
    sistema = carregar_relatorio_sistema("/home/claude/Conciliacao_BancariaTESTE.xlsx")
    # Como o arquivo de teste não tem coluna de conta, atribuímos manualmente
    sistema["conta"] = "CC-12345"
    print(f"    Linhas: {len(sistema)}")
    print(f"    Datas: {sistema['data'].min().date()} a {sistema['data'].max().date()}")
    print(f"    Valor total: R$ {sistema['valor'].sum():,.2f}")
    print(f"    Amostra:")
    print(sistema.head(3).to_string())

    # 3. Roda pipeline
    print("\n[3/4] Executando pipeline...")
    resultado = executar_pipeline(banco, sistema, rodar_fuzzy=True)
    kpis = resultado.kpis()
    print(f"    ✅ Conciliados: {kpis['total_conciliados']}")
    print(f"    ❌ Pendências banco: {kpis['total_pendentes_banco']}")
    print(f"    ❌ Pendências sistema: {kpis['total_pendentes_sistema']}")
    print(f"    ⚠️  Divergências: {kpis['total_divergencias']}")
    print(f"    🔁 Duplicidades: {kpis['total_duplicidades']}")
    print(f"    🏦 Banco errado: {kpis['total_banco_errado']}")
    print(f"    💡 Sugestões fuzzy: {kpis['total_sugestoes']}")

    # 4. Gera Excel
    print("\n[4/4] Gerando Excel...")
    caminho = salvar_relatorio(
        resultado.as_dict(),
        contas_processadas=resultado.contas_processadas,
        data_referencia=resultado.data_referencia,
        caminho="/home/claude/relatorio_teste.xlsx",
    )
    print(f"    Salvo em: {caminho}")
    print(f"    Tamanho: {caminho.stat().st_size / 1024:.1f} KB")

    print("\n✅ Pipeline executado com sucesso!")


if __name__ == "__main__":
    main()
