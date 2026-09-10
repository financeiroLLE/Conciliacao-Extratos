"""
src/api_bancos/ui_itau.py — componente Streamlit para puxar extrato Itaú

Adiciona um bloco visual acima do file_uploader do módulo bancário.
Se credenciais não estiverem configuradas, mostra explicação clara.
Se configuradas, mostra botões "Testar conexão" e "Puxar extrato".

FLUXO NOVO (sem download intermediário):
  1. Débora escolhe conta + período e clica em "Puxar extrato".
  2. A API responde e o arquivo é injetado em
     st.session_state["itau_arquivos_api"] como um objeto UploadedFile-like.
  3. O app.py mescla essa lista com os arquivos do file_uploader nativo,
     tratando os dois iguais no pipeline de conciliação.
  4. O nome do Sankhya correspondente (ex.: "ITAU PISA") é guardado em
     st.session_state["itau_nome_sankhya_sugerido"] para autopreencher o
     identificador da conta.

LAYOUT v5.81:
  - Depois de puxar, o expansor colapsa sozinho (para não poluir a tela).
  - Um selo verde "✓ N arquivo(s) puxado(s)" aparece acima do expansor,
    para você saber que rolou sem precisar reabrir.
  - O card do arquivo da API mostra o nome_sankhya embutido (ex.: "ITAU PISA")
    para conferência antes de rodar a conciliação.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List

import streamlit as st

from src.api_bancos import itau as api_itau


# ==============================================================================
# CORES
# ==============================================================================
AMARELO = "#FFCC00"
AZUL_NAVY = "#0A1730"
VERDE = "#2E7D4F"
VERMELHO = "#A32D2D"
ITAU_LARANJA = "#EC7000"


# ==============================================================================
# ARQUIVO EM MEMÓRIA — IMITA UploadedFile DO STREAMLIT
# ==============================================================================
class _ArquivoAPIItau:
    """Emula st.runtime.uploaded_file_manager.UploadedFile.

    Implementa a interface file-like completa que pandas/openpyxl esperam:
    .name, .type, .size, .mode, .closed, .getvalue(), .read(), .seek(),
    .tell(), .seekable(), .readable(), .writable(), .flush(), .close().
    Assim entra transparente no pipeline existente (v5.82: adicionados
    seekable/readable/writable/flush/mode que faltavam — sem eles, o
    openpyxl quebrava com "object has no attribute 'seekable'").
    """

    _MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, nome: str, dados: bytes, mime: str = "") -> None:
        self.name = nome
        self.type = mime or self._MIME_XLSX
        self.size = len(dados)
        self.mode = "rb"                # openpyxl/pandas consultam isso
        self._data = bytes(dados)
        self._pos = 0
        self._closed = False
        # marcador para o app identificar que veio da API (pula detecção
        # de banco por cabeçalho, que não faz sentido para arquivo gerado
        # a partir de JSON da API)
        self.origem_api = "itau"

    # --- leitura ---
    def getvalue(self) -> bytes:
        return self._data

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            data = self._data[self._pos:]
            self._pos = len(self._data)
        else:
            data = self._data[self._pos:self._pos + n]
            self._pos += len(data)
        return data

    def readable(self) -> bool:
        return True

    # --- posicionamento ---
    def seek(self, pos: int, whence: int = 0) -> int:
        if whence == 0:
            self._pos = max(0, int(pos))
        elif whence == 1:
            self._pos = max(0, self._pos + int(pos))
        elif whence == 2:
            self._pos = max(0, len(self._data) + int(pos))
        return self._pos

    def tell(self) -> int:
        return self._pos

    def seekable(self) -> bool:
        return True

    # --- escrita (não suportada, mas o protocolo pede o método) ---
    def writable(self) -> bool:
        return False

    def flush(self) -> None:
        pass

    # --- lifecycle ---
    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __repr__(self) -> str:
        return f"<_ArquivoAPIItau name={self.name!r} size={self.size}>"


def eh_arquivo_api_itau(arquivo) -> bool:
    """Helper para o app.py distinguir arquivos da API dos arrastados manualmente."""
    return isinstance(arquivo, _ArquivoAPIItau) or getattr(arquivo, "origem_api", "") == "itau"


# ==============================================================================
# HELPERS DE ESTADO
# ==============================================================================
_CHAVE_ARQS = "itau_arquivos_api"
_CHAVE_NOME_SANKHYA = "itau_nome_sankhya_sugerido"
_CHAVE_METRICAS = "itau_metricas_ultimo_puxar"  # v5.83: qtd lançamentos + soma


def _arquivos_api_na_sessao() -> List[_ArquivoAPIItau]:
    lst = st.session_state.get(_CHAVE_ARQS)
    if not isinstance(lst, list):
        return []
    # segurança: só retornar instâncias corretas (protege contra outras origens)
    return [x for x in lst if isinstance(x, _ArquivoAPIItau)]


def _adicionar_arquivo_api(arq: _ArquivoAPIItau, nome_sankhya: str = "") -> None:
    """Adiciona arquivo à lista, deduplicando pelo (name + size)."""
    atuais = _arquivos_api_na_sessao()
    chave_novo = (arq.name, arq.size)
    ja_existe = any((x.name, x.size) == chave_novo for x in atuais)
    if not ja_existe:
        atuais.append(arq)
    st.session_state[_CHAVE_ARQS] = atuais
    if nome_sankhya:
        st.session_state[_CHAVE_NOME_SANKHYA] = nome_sankhya


def _remover_arquivo_api(indice: int) -> None:
    atuais = _arquivos_api_na_sessao()
    if 0 <= indice < len(atuais):
        atuais.pop(indice)
    st.session_state[_CHAVE_ARQS] = atuais
    # Se ficou sem nenhum arquivo, também limpa a sugestão de nome e métricas
    if not atuais:
        st.session_state.pop(_CHAVE_NOME_SANKHYA, None)
        st.session_state.pop(_CHAVE_METRICAS, None)
        # v5.86: e limpa também os widgets do identificador (senão fica travado)
        for _k in ("conta_single", "conta_single_sel", "conta_single_novo"):
            st.session_state.pop(_k, None)


def _credenciais_configuradas() -> bool:
    """Retorna True se st.secrets['itau'] tem os 4 campos mínimos."""
    try:
        if "itau" not in st.secrets:
            return False
        s = st.secrets["itau"]
        return bool(
            s.get("client_id") and s.get("client_secret")
            and s.get("certificado_crt") and s.get("chave_privada_key")
        )
    except Exception:
        return False


# ==============================================================================
# BLOCOS VISUAIS
# ==============================================================================
def _render_bloco_nao_configurado() -> None:
    """Bloco explicativo se credenciais faltarem."""
    st.markdown(
        f'<div style="background:#F5F5F5;border-left:3px solid #999;'
        f'padding:10px 14px;border-radius:4px;margin-bottom:10px;font-size:12px;">'
        f'<b style="color:{AZUL_NAVY};">🔌 API Itaú não configurada</b><br>'
        f'<span style="color:#666;">Adicione as credenciais em '
        f'<b>Settings → Secrets → [itau]</b> para puxar extratos automaticamente.</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_selo_puxado(qtd: int) -> None:
    """Selo verde acima do expansor confirmando que puxou (para
    o usuário saber sem precisar reabrir o expansor colapsado)."""
    if qtd <= 0:
        return
    plural = "s" if qtd > 1 else ""
    st.markdown(
        f'<div style="display:inline-block;background:{VERDE};color:#fff;'
        f'padding:3px 10px;border-radius:4px;font-size:10.5px;font-weight:700;'
        f'letter-spacing:.03em;margin:0 0 6px;">'
        f'✓ {qtd} EXTRATO{plural.upper()} PUXADO{plural.upper()} DA API'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_dialogo_puxar(contas_disponiveis: dict) -> None:
    """Formulário compacto para puxar extrato."""
    apelidos = list(contas_disponiveis.keys())
    if not apelidos:
        st.warning("Nenhuma conta configurada em [itau.contas]")
        return

    with st.form(key="frm_puxar_itau", clear_on_submit=False):
        col_data1, col_data2, col_conta = st.columns([1, 1, 2])

        with col_data1:
            hoje = date.today()
            data_inicio = st.date_input(
                "De",
                value=hoje - timedelta(days=7),
                key="itau_data_ini",
                format="DD/MM/YYYY",
            )
        with col_data2:
            data_fim = st.date_input(
                "Até",
                value=hoje,
                key="itau_data_fim",
                format="DD/MM/YYYY",
            )
        with col_conta:
            def _fmt_opcao(x: str) -> str:
                reg = contas_disponiveis.get(x, {}) or {}
                num = ""
                nome_sk = ""
                try:
                    num = str(reg.get("conta", "") or "")
                    nome_sk = str(reg.get("nome_sankhya", "") or "")
                except Exception:
                    num = str(reg)
                extra = f" · {nome_sk}" if nome_sk else ""
                return f"{x} ({num}){extra}"

            apelido_sel = st.selectbox(
                "Conta",
                options=apelidos,
                key="itau_conta_sel",
                format_func=_fmt_opcao,
            )

        submitted = st.form_submit_button(
            "🔄  Puxar extrato",
            type="primary",
            use_container_width=True,
        )

    # FORA do form: processar (não há mais download — vai direto pro uploader)
    if submitted:
        reg = contas_disponiveis.get(apelido_sel) or {}
        try:
            conta_numero = str(reg.get("conta", "") or "")
            nome_sankhya = str(reg.get("nome_sankhya", "") or "")
        except Exception:
            conta_numero = str(reg)
            nome_sankhya = ""
        if not conta_numero:
            st.error("Conta inválida — verifique o cadastro em [itau.contas] no Secrets.")
            return
        _puxar_e_injetar_no_uploader(
            apelido=apelido_sel,
            conta_numero=conta_numero,
            nome_sankhya=nome_sankhya,
            data_inicio=data_inicio,
            data_fim=data_fim,
        )


def _puxar_e_injetar_no_uploader(
    apelido: str,
    conta_numero: str,
    nome_sankhya: str,
    data_inicio: date,
    data_fim: date,
) -> None:
    """Chama a API e injeta o arquivo resultante direto no uploader do app.

    Sem download intermediário, sem re-arrastar. O arquivo passa a existir
    em st.session_state["itau_arquivos_api"] como um _ArquivoAPIItau, e o
    app.py mescla essa lista com o file_uploader nativo.

    v5.83: guarda o DataFrame resultante em session_state para o card
    mostrar quantos lançamentos foram carregados e a soma R$ — assim
    a Débora enxerga na hora se veio vazio.
    """
    with st.spinner(f"Puxando extrato Itaú · {apelido} · "
                    f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m')}..."):
        try:
            # v5.83: puxa DF primeiro (para saber qtd e soma), depois monta XLSX
            df = api_itau.puxar_extrato_df(
                conta_formatada=conta_numero,
                data_inicio=data_inicio,
                data_fim=data_fim,
            )
            bytes_xlsx, nome_arquivo = api_itau.puxar_extrato_xlsx(
                conta_formatada=conta_numero,
                data_inicio=data_inicio,
                data_fim=data_fim,
                conta_apelido=apelido,
            )
        except Exception as e:
            st.error(f"❌ Falha ao puxar extrato Itaú: {e}")
            return

    arq = _ArquivoAPIItau(nome=nome_arquivo, dados=bytes_xlsx)
    _adicionar_arquivo_api(arq, nome_sankhya=nome_sankhya)

    # v5.83: guarda métricas para o card mostrar
    # v5.85: além da soma bruta, guarda volume movimentado (|valor|) e
    # totais de crédito/débito. Créditos e débitos de conta corrente se
    # cancelam, então a soma bruta tende a zero e NÃO indica bug —
    # o volume é a métrica correta para comparar com o Sankhya.
    try:
        qtd = int(len(df))
        if qtd > 0 and "valor" in df.columns:
            valores = df["valor"].astype(float)
            soma = float(valores.sum())
            volume = float(valores.abs().sum())
            total_credito = float(valores[valores > 0].sum())
            total_debito = float(-valores[valores < 0].sum())  # positivo (magnitude)
        else:
            soma = volume = total_credito = total_debito = 0.0
    except Exception:
        qtd = 0
        soma = volume = total_credito = total_debito = 0.0
    st.session_state[_CHAVE_METRICAS] = {
        "qtd": qtd,
        "soma": soma,
        "volume": volume,
        "total_credito": total_credito,
        "total_debito": total_debito,
        "apelido": apelido,
        "periodo": f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
    }

    if not nome_sankhya:
        st.warning(
            f"⚠️ Sem `nome_sankhya` cadastrado para a conta '{apelido}' — "
            "o identificador vai precisar ser escolhido manualmente. "
            f"Cadastre em Secrets → [itau.contas.{apelido}]."
        )

    # v5.86: reset dos widgets do identificador de conta no app.py.
    # O Streamlit prioriza st.session_state[key] sobre o value= do widget,
    # então se o campo já foi renderizado vazio antes, ele continua vazio
    # mesmo com nome_sankhya novo. Removendo as chaves, o value= volta a valer.
    for _k in ("conta_single", "conta_single_sel", "conta_single_novo"):
        st.session_state.pop(_k, None)

    # rerun para o app.py enxergar o novo arquivo e para o expansor colapsar
    st.rerun()


def _render_lista_arquivos_api() -> None:
    """Mostra, logo abaixo do expansor, os arquivos vindos da API — cada
    um em um card compacto com o nome_sankhya embutido (para o usuário
    conferir antes de conciliar). Botão X integrado visualmente ao card.

    v5.82: o botão X passa a ficar DENTRO do card visualmente, colado à
    direita, sem gap, formando um único bloco (via CSS scoped por classe).
    """
    arqs = _arquivos_api_na_sessao()
    if not arqs:
        return

    nome_sk = st.session_state.get(_CHAVE_NOME_SANKHYA, "")

    # CSS uma única vez por render — estiliza o botão X para casar com o card
    st.markdown(
        """
        <style>
        div[data-testid="stHorizontalBlock"]:has(> div .arqcard-itau) {
            gap: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(> div .arqcard-itau) button[kind="secondary"] {
            background: #0b2560 !important;
            border: 1px solid #1e3b7a !important;
            border-left: none !important;
            border-radius: 0 8px 8px 0 !important;
            color: #9fb3d6 !important;
            height: 62px !important;
            font-size: 15px !important;
            font-weight: 700 !important;
            margin: 4px 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(> div .arqcard-itau) button[kind="secondary"]:hover {
            color: #ff6b6b !important;
            border-color: #ff6b6b !important;
        }
        .arqcard-itau {
            background: linear-gradient(90deg, rgba(236,112,0,.10), transparent 45%);
            border: 1px solid #1e3b7a;
            border-left: 3px solid #EC7000;
            border-right: none;
            border-radius: 8px 0 0 8px;
            padding: 12px 14px;
            margin: 4px 0;
            display: flex;
            align-items: center;
            gap: 12px;
            min-height: 62px;
            box-sizing: border-box;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    metricas = st.session_state.get(_CHAVE_METRICAS) or {}
    qtd_lancamentos = int(metricas.get("qtd", -1))  # -1 = desconhecido (sessão antiga)
    volume_valor = float(metricas.get("volume", 0.0))
    total_credito = float(metricas.get("total_credito", 0.0))
    total_debito = float(metricas.get("total_debito", 0.0))

    def _fmt_brl(v: float) -> str:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    for i, arq in enumerate(arqs):
        col_card, col_x = st.columns([25, 1])
        with col_card:
            # v5.85: mostra volume movimentado (|créditos| + |débitos|),
            # que é a métrica que o Sankhya usa como referência.
            if qtd_lancamentos < 0:
                info_qtd = f'{arq.size:,} bytes'
            elif qtd_lancamentos == 0:
                info_qtd = (
                    f'<span style="color:#F6BF13;font-weight:700;">'
                    f'⚠ 0 lançamentos</span> · {arq.size:,} bytes'
                )
            else:
                info_qtd = (
                    f'<span style="color:#0F8C3B;font-weight:700;">'
                    f'{qtd_lancamentos} lançamentos · '
                    f'movimentação {_fmt_brl(volume_valor)}</span>'
                )

            # v5.85: quando tem qtd > 0, mostra também créditos e débitos
            # separados (uma linha extra) — útil pra bater os totais.
            info_cred_deb = ""
            if qtd_lancamentos > 0:
                info_cred_deb = (
                    f'<div style="color:#9fb3d6;font-size:10.5px;margin-top:2px;">'
                    f'<span style="color:#0F8C3B;">+ {_fmt_brl(total_credito)} crédito</span> · '
                    f'<span style="color:#C0392B;">- {_fmt_brl(total_debito)} débito</span>'
                    f'</div>'
                )

            if nome_sk:
                linha2 = (
                    f'<div style="color:#9fb3d6;font-size:11px;margin-top:2px;">'
                    f'conta · '
                    f'<b style="color:#eaf0fb;">{nome_sk}</b> · '
                    f'{info_qtd}</div>'
                    f'{info_cred_deb}'
                )
            else:
                linha2 = (
                    f'<div style="color:#9fb3d6;font-size:11px;margin-top:2px;">'
                    f'{info_qtd} · '
                    f'<span style="color:#FAC318;">sem nome_sankhya cadastrado</span></div>'
                    f'{info_cred_deb}'
                )

            st.markdown(
                f'<div class="arqcard-itau">'
                f'<span style="background:{ITAU_LARANJA};color:#fff;font-size:10px;'
                f'font-weight:700;padding:3px 9px;border-radius:4px;'
                f'letter-spacing:.03em;white-space:nowrap;">ITAÚ · API</span>'
                f'<div style="flex:1;overflow:hidden;">'
                f'<div style="color:#eaf0fb;font-size:12px;font-weight:600;'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">'
                f'{arq.name}</div>'
                f'{linha2}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        with col_x:
            if st.button("✖", key=f"rm_api_itau_{i}",
                         help="Remover este arquivo (para puxar de novo, abra o expansor acima)"):
                _remover_arquivo_api(i)
                st.rerun()

    # v5.85: só detecta problema real quando NENHUM lançamento vem,
    # OU quando volume movimentado é zero (aí sim é bug). Soma bruta ~ 0
    # com volume > 0 é COMPORTAMENTO NORMAL (créditos ≈ débitos) —
    # não deve gerar alerta.
    parece_problema = arqs and (
        qtd_lancamentos == 0
        or (qtd_lancamentos > 0 and volume_valor < 0.01)
    )
    if arqs:
        arq0 = arqs[0]
        if parece_problema:
            st.warning(
                "⚠️ **Extrato sem movimentação lida da API.** Zero "
                "lançamentos ou volume zero — algo está errado. "
                "Use os botões abaixo para diagnosticar."
            )
        # v5.85: botões de conferência ficam disponíveis SEMPRE (útil
        # pra auditoria), mas discretos e sem alerta quando está tudo ok.
        col_dl, col_dbg = st.columns([1, 1])
        with col_dl:
            st.download_button(
                "⬇  Baixar cópia do XLSX (para conferir)",
                data=arq0.getvalue(),
                file_name=arq0.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dbg_baixar_{arq0.name}",
                use_container_width=True,
            )
        with col_dbg:
            # v5.85: expander só abre por padrão quando tem problema REAL
            with st.expander(
                "🔧  Debug técnico — JSON bruto da API",
                expanded=bool(parece_problema),
            ):
                dbg = api_itau.obter_ultimo_debug()
                st.write(f"**Conta consultada:** `{dbg.get('conta','?')}`")
                st.write(f"**Período:** {dbg.get('periodo','?')}")
                st.write(f"**URL base:** `{dbg.get('url_base','?')}`")
                st.write(f"**HTTP status por página:** {dbg.get('http_status') or []}")
                if dbg.get("erro"):
                    st.write(f"**Erro:** {dbg['erro']}")
                st.write(f"**Nº de páginas retornadas:** {len(dbg.get('payloads') or [])}")
                st.write("---")
                st.write("**Payload bruto da 1ª página (primeiro `event` completo):**")
                payloads = dbg.get("payloads") or []
                if payloads:
                    payload0 = payloads[0]
                    # tenta extrair só um event para ficar legível
                    primeiro_event = None
                    try:
                        data_bloco = payload0.get("data")
                        if isinstance(data_bloco, dict):
                            data_bloco = [data_bloco]
                        if data_bloco:
                            events = (data_bloco[0] or {}).get("events") or []
                            if events:
                                primeiro_event = events[0]
                    except Exception:
                        pass

                    if primeiro_event is not None:
                        st.caption("Um único lançamento (chaves = nomes dos campos que a API usa):")
                        st.json(primeiro_event)
                        st.caption("Estrutura completa da 1ª página (colapsável):")
                        with st.expander("Ver payload inteiro"):
                            st.json(payload0)
                    else:
                        st.caption(
                            "Não encontrei events[] no formato esperado. "
                            "Payload inteiro abaixo (procure a chave onde ficam os lançamentos):"
                        )
                        st.json(payload0)
                else:
                    st.warning("Nenhum payload retornado pela API.")


def _render_botao_testar() -> None:
    """Botão que só testa se as credenciais estão OK (sem puxar dados)."""
    if st.button("🧪  Testar conexão Itaú",
                 key="itau_testar",
                 use_container_width=True,
                 help="Verifica se client_id, secret e certificado estão corretos"):
        with st.spinner("Testando conexão com Itaú..."):
            resultado = api_itau.testar_conexao()

        if resultado["ok"]:
            st.success(f"✓ {resultado['mensagem']}")
        else:
            st.error(f"❌ {resultado['mensagem']}")


def render() -> None:
    """Renderiza o bloco completo (chamado do app.py).

    Sem arquivos vindos da API → expansor colapsado (usuário abre e puxa).
    Com arquivos → expansor colapsado + selo verde acima + card do arquivo abaixo.
    """
    if not _credenciais_configuradas():
        _render_bloco_nao_configurado()
        return

    arqs_atuais = _arquivos_api_na_sessao()

    # Selo acima do expansor (só quando já tem arquivo puxado)
    _render_selo_puxado(len(arqs_atuais))

    # Container principal — colapsado por padrão para não poluir
    with st.expander("🏦  Puxar extrato Itaú direto da API (opcional)",
                     expanded=False):
        contas = api_itau.listar_contas()

        col_a, col_b = st.columns([1, 3])
        with col_a:
            _render_botao_testar()

        if not contas:
            st.warning(
                "Nenhuma conta cadastrada. Adicione no Secrets no formato novo:\n"
                "```\n"
                "[itau.contas.principal]\n"
                "conta = \"002300788615\"\n"
                "nome_sankhya = \"ITAU PISA\"\n"
                "```"
            )
            return

        _render_dialogo_puxar(contas)

    # FORA do expansor — sempre visível quando tem arquivos carregados
    _render_lista_arquivos_api()


# ==============================================================================
# API CHAMADA DO app.py
# ==============================================================================
def _render_botao_puxar_itau() -> None:
    """Wrapper para o app.py chamar (evita renomeação lá)."""
    render()


def arquivos_api_atuais() -> List[_ArquivoAPIItau]:
    """Exposto para o app.py mesclar com o file_uploader nativo."""
    return _arquivos_api_na_sessao()


def nome_sankhya_sugerido() -> str:
    """Exposto para o app.py autopreencher o identificador da conta."""
    return str(st.session_state.get(_CHAVE_NOME_SANKHYA, "")).strip()
