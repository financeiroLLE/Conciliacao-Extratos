"""
App Streamlit — Sistema de Conciliação Bancária (Grupo LLE).

Identidade visual: Manual da Marca Grupo LLE (Fev/2026).
Estrutura: sidebar escura + páginas Dashboard / Conciliação / Histórico.
"""

from __future__ import annotations

import base64
from datetime import date, datetime
from pathlib import Path

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
# Identidade visual — Grupo LLE
# ============================================================
CORES = {
    "azul_escuro": "#041747",   # institucional escuro — sidebar e header
    "azul": "#0071FE",          # primário
    "amarelo": "#FAC318",       # destaque
    "verde": "#0F8C3B",         # sucesso
    "branco": "#FFFFFF",
    "card_escuro": "#0A1F4D",   # cards na área principal sobre fundo claro? não, mantemos cards claros
    "card_escuro_2": "#102447", # variação do card
    "cinza_claro": "#F4F6FA",
    "cinza_borda": "#E1E5EB",
    "coral": "#F08977",         # destaque (linha selecionada na referência)
    "texto_muted": "#8C97B0",   # texto secundário sobre fundo escuro
}

ASSETS = Path(__file__).parent / "assets"


@st.cache_data
def _logo_uri(versao: str = "preto") -> str:
    """Retorna o logo como data URI. versao: 'preto' (texto preto) ou 'branco' (texto branco)."""
    nome = "logo-grupo-lle-branco.svg" if versao == "branco" else "logo-grupo-lle.svg"
    path = ASSETS / nome
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


# ============================================================
# Configuração da página
# ============================================================
st.set_page_config(
    page_title="Conciliação Bancária · Grupo LLE",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Sessão — controle de página atual e histórico de conciliações
# ============================================================
if "pagina" not in st.session_state:
    st.session_state.pagina = "Conciliação"
if "historico" not in st.session_state:
    # Lista de dicts com os resultados das conciliações feitas na sessão
    st.session_state.historico = []


def ir_para(pagina: str):
    """Callback dos botões da sidebar."""
    st.session_state.pagina = pagina


# ============================================================
# CSS global — identidade Grupo LLE com sidebar escura
# ============================================================
logo_preto = _logo_uri("preto")
logo_branco = _logo_uri("branco")

st.html(
    f"""
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"], .stMarkdown, .stText, button, input, select, textarea {{
    font-family: 'Montserrat', sans-serif !important;
}}
h1, h2, h3, h4, h5, h6 {{
    font-family: 'Montserrat', sans-serif !important;
    color: {CORES["azul_escuro"]};
    font-weight: 700;
}}

[data-testid="stSidebar"] {{
    background-color: {CORES["azul_escuro"]} !important;
    border-right: none;
}}
[data-testid="stSidebar"] * {{ color: {CORES["branco"]} !important; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.12) !important; }}

.lle-sidebar-logo {{
    text-align: center;
    padding: 16px 0 8px 0;
}}
.lle-sidebar-logo img {{
    height: 72px;
    width: auto;
}}
.lle-sidebar-tagline {{
    text-align: center;
    color: {CORES["amarelo"]} !important;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.5px;
    margin: 4px 0 24px 0;
}}

[data-testid="stSidebar"] .stButton > button {{
    background-color: rgba(255,255,255,0.06);
    color: {CORES["branco"]} !important;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 10px;
    padding: 12px 16px;
    font-weight: 600;
    font-size: 14px;
    text-align: left;
    width: 100%;
    transition: all 0.2s ease;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background-color: rgba(255,255,255,0.12);
    border-color: rgba(255,255,255,0.20);
    transform: translateX(2px);
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background-color: {CORES["azul"]} !important;
    border-color: {CORES["azul"]} !important;
}}

.lle-header-escuro {{
    background-color: {CORES["azul_escuro"]};
    border-radius: 16px;
    padding: 24px 32px;
    margin-bottom: 28px;
    display: flex;
    align-items: center;
    gap: 24px;
}}
.lle-header-escuro img {{
    height: 56px;
    width: auto;
}}
.lle-header-escuro .lle-title {{
    font-size: 26px;
    font-weight: 800;
    color: {CORES["branco"]};
    line-height: 1.1;
    margin: 0;
    letter-spacing: -0.5px;
}}
.lle-header-escuro .lle-subtitle {{
    font-size: 13px;
    color: {CORES["amarelo"]};
    margin-top: 4px;
    font-weight: 600;
}}

.stMetric {{
    background-color: {CORES["cinza_claro"]};
    padding: 14px 18px;
    border-radius: 10px;
    border-left: 4px solid {CORES["azul"]};
}}
[data-testid="stMetricLabel"] {{
    font-weight: 600 !important;
    color: {CORES["azul_escuro"]} !important;
}}

.stButton > button[kind="primary"] {{
    background-color: {CORES["azul"]};
    color: white;
    font-weight: 600;
    border: none;
}}
.stButton > button[kind="primary"]:hover {{
    background-color: {CORES["azul_escuro"]};
}}

.stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; color: {CORES["azul_escuro"]}; }}
.stTabs [aria-selected="true"] {{ color: {CORES["azul"]} !important; }}

.block-container {{ padding-top: 1.5rem; max-width: 1400px; }}

.lle-card {{
    background-color: {CORES["cinza_claro"]};
    border-radius: 10px;
    padding: 14px 20px;
    margin-bottom: 8px;
    border: 1px solid {CORES["cinza_borda"]};
    transition: all 0.15s ease;
}}
.lle-card:hover {{
    border-color: {CORES["azul"]};
    transform: translateX(2px);
}}
.lle-card.destaque {{
    border-color: {CORES["coral"]};
    border-width: 2px;
}}

.lle-footer {{
    margin-top: 48px;
    padding: 16px 24px;
    text-align: center;
    font-size: 12px;
    color: #8A93A6;
    border-top: 1px solid {CORES["cinza_borda"]};
}}
.lle-footer strong {{ color: {CORES["azul_escuro"]}; }}
.lle-footer a {{ color: {CORES["azul"]}; text-decoration: none; }}
</style>
"""
)


# ============================================================
# Sidebar — navegação
# ============================================================
with st.sidebar:
    # Logo branco institucional (versão para fundo escuro, conforme manual)
    if logo_branco:
        st.html(
            f"""
            <div class="lle-sidebar-logo">
                <img src="{logo_branco}" alt="Grupo LLE" />
            </div>
            <div class="lle-sidebar-tagline">CONCILIAÇÃO BANCÁRIA</div>
            """
        )

    paginas = [
        ("📊 Dashboard", "Dashboard"),
        ("🔄 Conciliação", "Conciliação"),
        ("📂 Histórico da sessão", "Histórico"),
    ]
    for label, key in paginas:
        is_atual = st.session_state.pagina == key
        st.button(
            label,
            key=f"nav_{key}",
            on_click=ir_para,
            args=(key,),
            type="primary" if is_atual else "secondary",
            use_container_width=True,
        )

    st.html("<hr style='margin: 20px 0; border-color: rgba(255,255,255,0.12);'>")

    with st.expander("⚙️ Configurações"):
        rodar_fuzzy = st.checkbox(
            "Gerar sugestões fuzzy",
            value=True,
            help=(
                "Para cada pendência, busca lançamentos com histórico parecido "
                "na outra ponta. Apenas para revisão manual — não concilia."
            ),
        )

    with st.expander("ℹ️ Sobre"):
        st.markdown(
            """
            **Conciliação Bancária v1.0**

            Chave de match: **Data + Valor + Conta**

            Auditorias geradas:
            - Divergência de valor
            - Duplicidades (qtd diferente)
            - Pendências (banco/sistema)
            - Banco baixado em conta errada
            """
        )


# ============================================================
# Header da página (aparece em todas)
# ============================================================
PAGE_INFO = {
    "Dashboard": ("Dashboard", "Visão geral da sessão"),
    "Conciliação": ("Conciliação", "Upload, análise e download"),
    "Histórico": ("Histórico", "Conciliações desta sessão"),
}
titulo, subtitulo = PAGE_INFO[st.session_state.pagina]

st.html(
    f"""
    <div class="lle-header-escuro">
        <img src="{logo_branco}" alt="Grupo LLE" />
        <div>
            <div class="lle-title">{titulo}</div>
            <div class="lle-subtitle">{subtitulo}</div>
        </div>
    </div>
    """
)


# ============================================================
# Helpers de página
# ============================================================
def _formatar_brl(v: float) -> str:
    sinal = "-" if v < 0 else ""
    return f"{sinal}R$ {abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
# Página: Dashboard
# ============================================================
def pagina_dashboard():
    hist = st.session_state.historico

    if not hist:
        st.info(
            "👋 Bem-vindo! Você ainda não rodou nenhuma conciliação nesta sessão. "
            "Vá para a página **Conciliação** para começar."
        )
        if st.button("➡️ Ir para Conciliação", type="primary"):
            ir_para("Conciliação")
            st.rerun()
        return

    # KPIs agregados de todas as conciliações da sessão
    total_conc = sum(r["kpis"]["total_conciliados"] for r in hist)
    total_pend_b = sum(r["kpis"]["total_pendentes_banco"] for r in hist)
    total_pend_s = sum(r["kpis"]["total_pendentes_sistema"] for r in hist)
    total_dup = sum(r["kpis"]["total_duplicidades"] for r in hist)

    st.subheader("📊 Resumo da sessão")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conciliações rodadas", len(hist))
    c2.metric("✅ Total conciliado", total_conc)
    c3.metric("❌ Pendências banco", total_pend_b)
    c4.metric("❌ Pendências sistema", total_pend_s)

    c1, c2 = st.columns(2)
    c1.metric("🔁 Duplicidades detectadas", total_dup)
    c2.metric("📅 Última conciliação", hist[-1]["data_referencia"].strftime("%d/%m/%Y"))

    st.divider()
    st.subheader("📋 Últimas conciliações")
    for i, r in enumerate(reversed(hist[-5:])):
        idx_real = len(hist) - 1 - i
        contas_str = ", ".join(r["contas"][:3]) + (
            f" +{len(r['contas']) - 3}" if len(r["contas"]) > 3 else ""
        )
        st.html(
            f"""
            <div class="lle-card">
                <strong>{r["data_referencia"].strftime("%d/%m/%Y")}</strong> ·
                {contas_str} ·
                ✅ {r["kpis"]["total_conciliados"]} conciliados ·
                ❌ {r["kpis"]["total_pendentes_banco"] + r["kpis"]["total_pendentes_sistema"]} pendências
            </div>
            """
        )


# ============================================================
# Página: Conciliação
# ============================================================
def pagina_conciliacao():
    tab_upload, tab_resultados, tab_download = st.tabs(
        ["📤 1. Upload", "📊 2. Resultados", "💾 3. Download"]
    )

    # ---------- TAB 1: Upload ----------
    with tab_upload:
        modo = st.radio(
            "Modo de execução",
            ["1 conta por vez", "Várias contas de uma vez"],
            horizontal=True,
            help=(
                "**1 conta**: sobe um extrato + relatório filtrado dessa conta.\n\n"
                "**Várias contas**: sobe um único relatório com todas as contas e "
                "um extrato por conta."
            ),
        )
        data_ref = st.date_input(
            "Data de referência (D-1)",
            value=date.today(),
            format="DD/MM/YYYY",
        )

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Extrato(s) bancário(s)")
            st.caption(
                "Formato esperado (padronizado): **Data, Histórico, Valor (R$)**."
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
                    help=(
                        "**Rótulo que VOCÊ escolhe** para identificar essa conta "
                        "(ex: `Bradesco-CC-12345`, `Itau-Matriz`). Não precisa "
                        "existir em nenhum arquivo. Mínimo 3 caracteres."
                    ),
                )
                arquivos_banco = (
                    [(nome_conta, arquivo_banco)]
                    if arquivo_banco and nome_conta
                    else []
                )
            else:
                st.info(
                    "📌 Use o nome do arquivo para identificar a conta "
                    "(ex: `Bradesco-12345.xlsx`)."
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
                "Relatório de Conciliação Bancária exportado do ERP."
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
                    "**Nome EXATO da coluna do ERP** que diz a qual conta cada "
                    "lançamento pertence (ex: `Conta Bancária`). Se vazio, tenta "
                    "detectar sozinho."
                ),
            )

        st.divider()
        st.subheader("Pendências de dias anteriores (opcional)")
        st.caption(
            "Sobe aqui o relatório Excel gerado em dias anteriores — a aba "
            "'Pendências Consolidadas' é lida automaticamente."
        )
        arquivo_pendencias = st.file_uploader(
            "Relatório anterior",
            type=["xlsx"],
            key="pendencias",
        )

        st.divider()

        # Validação dos nomes de conta
        NOMES_PROIBIDOS = {"data", "valor", "histórico", "historico", "conta", "—", ""}
        contas_invalidas = [
            nome for nome, _ in arquivos_banco
            if nome.lower().strip() in NOMES_PROIBIDOS or len(nome.strip()) < 3
        ]
        pode_executar = (
            bool(arquivos_banco)
            and bool(arquivo_sistema)
            and not contas_invalidas
        )

        if not arquivos_banco or not arquivo_sistema:
            st.warning(
                "⏳ Aguardando upload do extrato bancário **e** do relatório do sistema."
            )
        elif contas_invalidas:
            st.error(
                f"❌ Identificador de conta inválido: `{contas_invalidas}`. "
                f"Mínimo 3 caracteres, evite palavras genéricas como 'data', 'conta'."
            )

        if st.button(
            "▶️ Executar conciliação",
            type="primary",
            disabled=not pode_executar,
            use_container_width=True,
        ):
            with st.spinner("Processando..."):
                try:
                    dfs_banco = []
                    for nome_conta, arq in arquivos_banco:
                        df = carregar_extrato_banco(arq, conta=nome_conta)
                        dfs_banco.append(df)
                    banco = pd.concat(dfs_banco, ignore_index=True)

                    sistema = carregar_relatorio_sistema(
                        arquivo_sistema,
                        coluna_conta=coluna_conta_sistema or None,
                    )

                    if modo == "1 conta por vez" and (sistema["conta"] == "—").all():
                        sistema["conta"] = arquivos_banco[0][0]
                        st.info(
                            f"ℹ️ Relatório do sistema não tinha coluna de conta — "
                            f"atribuído a '{arquivos_banco[0][0]}'."
                        )

                    pendencias = carregar_pendencias_anteriores(arquivo_pendencias)

                    resultado = executar_pipeline(
                        banco,
                        sistema,
                        data_referencia=datetime.combine(data_ref, datetime.min.time()),
                        rodar_fuzzy=rodar_fuzzy,
                    )

                    st.session_state["resultado"] = resultado
                    st.session_state["pendencias_anteriores"] = pendencias
                    st.session_state["banco_total"] = len(banco)
                    st.session_state["sistema_total"] = len(sistema)

                    # Registra no histórico da sessão
                    st.session_state.historico.append({
                        "data_referencia": resultado.data_referencia,
                        "contas": resultado.contas_processadas,
                        "kpis": resultado.kpis(),
                        "timestamp": datetime.now(),
                    })

                    st.success(
                        "✅ Conciliação concluída! Veja os resultados na aba 'Resultados'."
                    )
                except Exception as e:
                    st.error(f"❌ Erro durante o processamento:\n\n```\n{e}\n```")
                    import traceback
                    with st.expander("Stack trace completo"):
                        st.code(traceback.format_exc())

    # ---------- TAB 2: Resultados ----------
    with tab_resultados:
        if "resultado" not in st.session_state:
            st.info("👈 Execute uma conciliação na aba 'Upload' para ver os resultados.")
        else:
            resultado = st.session_state["resultado"]
            kpis = resultado.kpis()

            st.subheader("📊 Resumo")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Linhas banco", st.session_state.get("banco_total", "—"))
            c2.metric("Linhas sistema", st.session_state.get("sistema_total", "—"))
            c3.metric("✅ Conciliados", kpis["total_conciliados"])
            taxa = 100 * kpis["total_conciliados"] / max(
                st.session_state.get("banco_total", 1), 1
            )
            c4.metric("Taxa de conciliação", f"{taxa:.1f}%")

            st.divider()
            st.subheader("🚨 Pendências e alertas")
            c1, c2, c3 = st.columns(3)
            c1.metric(
                "❌ Falta baixar (banco)",
                kpis["total_pendentes_banco"],
                delta=_formatar_brl(kpis["valor_pendente_banco"]),
                delta_color="off",
            )
            c2.metric(
                "❌ Lançamento indevido",
                kpis["total_pendentes_sistema"],
                delta=_formatar_brl(kpis["valor_pendente_sistema"]),
                delta_color="off",
            )
            c3.metric("🏦 Banco errado", kpis["total_banco_errado"])

            c1, c2, c3 = st.columns(3)
            c1.metric("⚠️ Divergência de valor", kpis["total_divergencias"])
            c2.metric("🔁 Duplicidades", kpis["total_duplicidades"])
            c3.metric("💡 Sugestões fuzzy", kpis["total_sugestoes"])

            st.divider()
            st.subheader("🔎 Detalhamento")
            categoria = st.selectbox(
                "Categoria",
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
                df_show = df_show.drop(
                    columns=[c for c in df_show.columns if c.startswith("_")],
                    errors="ignore",
                )
                st.dataframe(df_show, use_container_width=True, height=500)

    # ---------- TAB 3: Download ----------
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
                O relatório contém 9 abas. A aba **Pendências Consolidadas** serve
                como **input do próximo dia** — suba-a de volta amanhã no campo
                "Pendências de dias anteriores" para acompanhar há quantos dias
                cada pendência está em aberto.
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


# ============================================================
# Página: Histórico (cards estilo referência)
# ============================================================
def pagina_historico():
    if not st.session_state.historico:
        st.info(
            "📂 Nenhuma conciliação foi rodada nesta sessão ainda. "
            "As conciliações desta sessão aparecerão aqui."
        )
        return

    st.caption(
        f"💡 O histórico é mantido apenas durante a sessão atual. "
        f"Total: {len(st.session_state.historico)} conciliação(ões)."
    )

    # Busca + filtro (estilo referência)
    col1, col2 = st.columns([3, 1])
    busca = col1.text_input(
        "",
        placeholder="🔍 Buscar conta ou data (dd/mm)...",
        label_visibility="collapsed",
        key="busca_hist",
    )

    items = list(reversed(st.session_state.historico))
    if busca:
        b = busca.lower().strip()
        items = [
            it for it in items
            if b in " ".join(it["contas"]).lower()
            or b in it["data_referencia"].strftime("%d/%m/%Y").lower()
        ]

    if not items:
        st.warning("Nenhum resultado para a busca.")
        return

    for idx, item in enumerate(items):
        kpis = item["kpis"]
        contas_str = ", ".join(item["contas"][:2]) + (
            f" +{len(item['contas']) - 2}" if len(item["contas"]) > 2 else ""
        )
        # Destaque para o mais recente
        classe = "lle-card destaque" if idx == 0 else "lle-card"

        # Status emoji baseado em quantidade de pendências
        pend_total = kpis["total_pendentes_banco"] + kpis["total_pendentes_sistema"]
        if pend_total == 0:
            status_icone = "🟢"
            status_txt = "Limpa"
        elif pend_total < 20:
            status_icone = "🟡"
            status_txt = f"{pend_total} pendências"
        else:
            status_icone = "🔴"
            status_txt = f"{pend_total} pendências"

        st.html(
            f"""
            <div class="{classe}">
                <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                    <span style="font-size:18px;">{status_icone}</span>
                    <strong style="color:{CORES["azul_escuro"]}; font-size:14px;">
                        {item["data_referencia"].strftime("%d/%m/%Y")}
                    </strong>
                    <span style="color:#6B7280;">—</span>
                    <span style="color:{CORES["azul_escuro"]}; font-weight:600;">
                        {contas_str}
                    </span>
                    <span style="color:#6B7280;">—</span>
                    <span style="color:{CORES["verde"]}; font-weight:600;">
                        ✅ {kpis["total_conciliados"]} conciliados
                    </span>
                    <span style="color:#6B7280;">—</span>
                    <span style="color:{CORES["azul"]}; font-weight:600;">
                        {status_txt}
                    </span>
                    <span style="color:#9CA3AF; margin-left:auto; font-size:12px;">
                        {item["timestamp"].strftime("%H:%M")}
                    </span>
                </div>
            </div>
            """
        )


# ============================================================
# Roteamento
# ============================================================
if st.session_state.pagina == "Dashboard":
    pagina_dashboard()
elif st.session_state.pagina == "Conciliação":
    pagina_conciliacao()
elif st.session_state.pagina == "Histórico":
    pagina_historico()


# ============================================================
# Footer institucional
# ============================================================
st.html(
    """
    <div class="lle-footer">
        <strong>Grupo LLE</strong> · Conciliação Bancária ·
        Aplicação interna seguindo o Manual da Marca (Fev/2026).<br>
        Dúvidas sobre identidade visual:
        <a href="mailto:marketing@grupolle.com.br">marketing@grupolle.com.br</a>
    </div>
    """
)
