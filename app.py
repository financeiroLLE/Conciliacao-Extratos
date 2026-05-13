"""
App Streamlit — Sistema de Conciliação Bancária Automatizada.

Fluxo:
1. Usuário escolhe modo: 1 conta por vez ou várias de uma vez
2. Sobe extrato(s) bancário(s) + relatório do sistema + (opcional) pendências anteriores
3. App roda pipeline e mostra dashboard
4. Usuário baixa o relatório Excel
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pandas as pd
import streamlit as st

from src.parsers import (
    carregar_extrato_banco,
    carregar_pendencias_anteriores,
    carregar_relatorio_sistema,
)
from src.pipeline import executar_pipeline
from src.reports import gerar_relatorio_excel


# ============================================================
# Configuração da página
# ============================================================
st.set_page_config(
    page_title="Conciliação Bancária",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# Estilo CSS leve
# ============================================================
st.markdown(
    """
    <style>
    .stMetric { background-color: #f5f7fa; padding: 10px; border-radius: 8px; }
    .block-container { padding-top: 2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# Sidebar — configuração da execução
# ============================================================
with st.sidebar:
    st.header("⚙️ Configuração")

    modo = st.radio(
        "Modo de execução",
        ["1 conta por vez", "Várias contas de uma vez"],
        help=(
            "**1 conta**: sobe um extrato + relatório filtrado dessa conta.\n\n"
            "**Várias contas**: sobe um único relatório do sistema com todas as "
            "contas e um extrato por conta."
        ),
    )

    data_ref = st.date_input(
        "Data de referência (D-1)",
        value=date.today(),
        format="DD/MM/YYYY",
        help="Data do extrato que está sendo conciliado.",
    )

    st.divider()
    rodar_fuzzy = st.checkbox(
        "Gerar sugestões fuzzy",
        value=True,
        help=(
            "Para cada pendência, busca lançamentos com histórico parecido "
            "na outra ponta. Apenas para revisão manual — não concilia."
        ),
    )

    st.divider()
    with st.expander("ℹ️ Sobre"):
        st.markdown(
            """
            **Conciliação Bancária v0.1**

            Chave de match: **Data + Valor exato**

            Auditorias geradas:
            - Divergência de valor
            - Duplicidades
            - Sistema sem contrapartida (lançamento indevido)
            - Banco sem contrapartida (falta baixar)
            - Banco baixado em conta errada

            [Repositório no GitHub](https://github.com/SEU_USUARIO/conciliacao-bancaria)
            """
        )


# ============================================================
# Header principal
# ============================================================
st.title("🏦 Conciliação Bancária")
st.caption(
    "Bate o extrato do banco com o relatório do sistema, identifica pendências "
    "e gera o relatório Excel."
)


# ============================================================
# Tabs: Upload | Resultados | Download
# ============================================================
tab_upload, tab_resultados, tab_download = st.tabs(
    ["📤 1. Upload de arquivos", "📊 2. Resultados", "💾 3. Download do relatório"]
)


# ============================================================
# TAB 1 — Upload
# ============================================================
with tab_upload:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Extrato(s) bancário(s)")
        st.caption(
            "Formato esperado (padronizado): **Data, Histórico, Valor (R$)**. "
            "Pode ter múltiplas abas (uma por dia)."
        )

        if modo == "1 conta por vez":
            arquivo_banco = st.file_uploader(
                "Arraste o extrato do banco",
                type=["xlsx", "xls"],
                key="banco_single",
            )
            nome_conta = st.text_input(
                "Identificador da conta",
                placeholder="ex: Bradesco-CC-12345",
                key="conta_single",
            )
            arquivos_banco = (
                [(nome_conta, arquivo_banco)]
                if arquivo_banco and nome_conta
                else []
            )
        else:
            st.info(
                "📌 Suba um extrato por conta. Use o nome do arquivo para "
                "identificar a conta (ex: `Bradesco-12345.xlsx`)."
            )
            arquivos_multi = st.file_uploader(
                "Arraste os extratos (um por conta)",
                type=["xlsx", "xls"],
                accept_multiple_files=True,
                key="banco_multi",
            )
            arquivos_banco = [
                (f.name.rsplit(".", 1)[0], f) for f in (arquivos_multi or [])
            ]

    with col2:
        st.subheader("Relatório do sistema")
        st.caption(
            "Relatório de Conciliação Bancária exportado do ERP "
            "(formato com cabeçalhos nas linhas 1-3)."
        )
        arquivo_sistema = st.file_uploader(
            "Arraste o relatório do sistema",
            type=["xlsx", "xls"],
            key="sistema",
        )

        coluna_conta_sistema = st.text_input(
            "Nome da coluna 'Conta' no sistema",
            value="",
            placeholder="(deixe vazio para auto-detectar)",
            help=(
                "Qual coluna do relatório identifica a conta bancária. "
                "Se vazio, tenta achar automaticamente."
            ),
        )

    st.divider()
    st.subheader("Pendências de dias anteriores (opcional)")
    st.caption(
        "Sobe aqui o relatório Excel gerado em dias anteriores — a aba "
        "'Pendências Consolidadas' é lida automaticamente."
    )
    arquivo_pendencias = st.file_uploader(
        "Relatório anterior (opcional)",
        type=["xlsx"],
        key="pendencias",
    )

    st.divider()
    pode_executar = bool(arquivos_banco and arquivo_sistema)
    if not pode_executar:
        st.warning(
            "⏳ Aguardando upload do extrato bancário **e** do relatório do sistema."
        )

    if st.button(
        "▶️ Executar conciliação",
        type="primary",
        disabled=not pode_executar,
        use_container_width=True,
    ):
        with st.spinner("Processando..."):
            try:
                # Carrega extratos
                dfs_banco = []
                for nome_conta, arq in arquivos_banco:
                    df = carregar_extrato_banco(arq, conta=nome_conta)
                    dfs_banco.append(df)
                banco = pd.concat(dfs_banco, ignore_index=True)

                # Carrega sistema
                sistema = carregar_relatorio_sistema(
                    arquivo_sistema,
                    coluna_conta=coluna_conta_sistema or None,
                )

                # Se modo single e sistema não tinha coluna de conta detectada
                if modo == "1 conta por vez" and (sistema["conta"] == "—").all():
                    sistema["conta"] = arquivos_banco[0][0]
                    st.info(
                        f"ℹ️ Relatório do sistema não tinha coluna de conta — "
                        f"atribuído a '{arquivos_banco[0][0]}' automaticamente."
                    )

                # Pendências anteriores
                pendencias = carregar_pendencias_anteriores(arquivo_pendencias)

                # Executa pipeline
                resultado = executar_pipeline(
                    banco,
                    sistema,
                    data_referencia=datetime.combine(data_ref, datetime.min.time()),
                    rodar_fuzzy=rodar_fuzzy,
                )

                # Guarda no session_state pra outras tabs
                st.session_state["resultado"] = resultado
                st.session_state["pendencias_anteriores"] = pendencias
                st.session_state["banco_total"] = len(banco)
                st.session_state["sistema_total"] = len(sistema)

                st.success(
                    "✅ Conciliação concluída! Veja os resultados na aba 'Resultados'."
                )
            except Exception as e:
                st.error(f"❌ Erro durante o processamento:\n\n```\n{e}\n```")
                import traceback
                with st.expander("Stack trace completo"):
                    st.code(traceback.format_exc())


# ============================================================
# TAB 2 — Resultados
# ============================================================
with tab_resultados:
    if "resultado" not in st.session_state:
        st.info("👈 Execute uma conciliação na aba 'Upload' para ver os resultados.")
    else:
        resultado = st.session_state["resultado"]
        kpis = resultado.kpis()

        st.subheader("📊 Resumo da conciliação")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Linhas banco", st.session_state.get("banco_total", "—"))
        c2.metric("Linhas sistema", st.session_state.get("sistema_total", "—"))
        c3.metric("✅ Conciliados", kpis["total_conciliados"])
        c4.metric(
            "Taxa de conciliação",
            f"{100 * kpis['total_conciliados'] / max(st.session_state.get('banco_total', 1), 1):.1f}%",
        )

        st.divider()

        # Linha de alertas
        st.subheader("🚨 Pendências e alertas")
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "❌ Falta baixar (banco)",
            kpis["total_pendentes_banco"],
            delta=f"R$ {kpis['valor_pendente_banco']:,.2f}",
            delta_color="off",
        )
        c2.metric(
            "❌ Lançamento indevido (sistema)",
            kpis["total_pendentes_sistema"],
            delta=f"R$ {kpis['valor_pendente_sistema']:,.2f}",
            delta_color="off",
        )
        c3.metric("🏦 Banco errado (suspeitos)", kpis["total_banco_errado"])

        c1, c2, c3 = st.columns(3)
        c1.metric("⚠️ Divergência de valor", kpis["total_divergencias"])
        c2.metric("🔁 Duplicidades", kpis["total_duplicidades"])
        c3.metric("💡 Sugestões fuzzy", kpis["total_sugestoes"])

        st.divider()

        # Tabela navegável por categoria
        st.subheader("🔎 Detalhamento")
        categoria = st.selectbox(
            "Escolha a categoria para visualizar",
            [
                "Conciliados",
                "Pendências Banco (falta baixar)",
                "Pendências Sistema (indevidos)",
                "Divergência de valor",
                "Duplicidades",
                "Banco errado",
                "Sugestões fuzzy",
            ],
        )
        mapping = {
            "Conciliados": resultado.conciliados,
            "Pendências Banco (falta baixar)": resultado.pendentes_banco,
            "Pendências Sistema (indevidos)": resultado.pendentes_sistema,
            "Divergência de valor": resultado.divergencia_valor,
            "Duplicidades": resultado.duplicidades,
            "Banco errado": resultado.banco_errado,
            "Sugestões fuzzy": resultado.sugestoes_fuzzy,
        }
        df_show = mapping[categoria]
        if df_show.empty:
            st.success(f"🎉 Nenhum registro em '{categoria}'.")
        else:
            # Remove colunas internas
            df_show = df_show.drop(
                columns=[c for c in df_show.columns if c.startswith("_")],
                errors="ignore",
            )
            st.dataframe(df_show, use_container_width=True, height=500)


# ============================================================
# TAB 3 — Download
# ============================================================
with tab_download:
    if "resultado" not in st.session_state:
        st.info("👈 Execute uma conciliação para gerar o relatório.")
    else:
        resultado = st.session_state["resultado"]
        pendencias = st.session_state.get(
            "pendencias_anteriores", pd.DataFrame()
        )

        st.subheader("💾 Baixar relatório Excel")
        st.markdown(
            """
            O relatório contém 9 abas:

            1. **Resumo Executivo** — visão gerencial com KPIs
            2. **Conciliados** — pares que casaram
            3. **Pendências Banco** — falta baixar no sistema
            4. **Pendências Sistema** — lançamento indevido
            5. **Divergência Valor** — valores diferentes
            6. **Duplicidades** — registros repetidos
            7. **Banco Errado** — suspeitos de baixa em conta errada
            8. **Sugestões Fuzzy** — para revisão manual
            9. **Pendências Consolidadas** ⭐ — **INPUT do próximo dia**

            > 💡 Guarde esse arquivo e suba-o de volta amanhã na aba de upload, no
            > campo "Pendências de dias anteriores". Assim você acompanha por quantos
            > dias cada pendência está em aberto.
            """
        )

        with st.spinner("Gerando Excel..."):
            xlsx_bytes = gerar_relatorio_excel(
                resultado.as_dict(),
                contas_processadas=resultado.contas_processadas,
                data_referencia=resultado.data_referencia,
                pendencias_anteriores=pendencias,
            )

        nome_arquivo = (
            f"conciliacao_{resultado.data_referencia.strftime('%Y%m%d')}.xlsx"
        )
        st.download_button(
            "⬇️ Baixar relatório",
            data=xlsx_bytes,
            file_name=nome_arquivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
        st.caption(f"Arquivo: `{nome_arquivo}` — {len(xlsx_bytes) / 1024:.1f} KB")
