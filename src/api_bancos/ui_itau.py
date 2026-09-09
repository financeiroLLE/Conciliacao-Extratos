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


# ==============================================================================
# ARQUIVO EM MEMÓRIA — IMITA UploadedFile DO STREAMLIT
# ==============================================================================
class _ArquivoAPIItau:
    """Emula st.runtime.uploaded_file_manager.UploadedFile.

    Tem os atributos e métodos que o resto do app espera de um arquivo
    vindo do file_uploader: .name, .type, .size, .getvalue(), .read(),
    .seek(), .tell(). Assim entra transparente no pipeline existente.
    """

    _MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, nome: str, dados: bytes, mime: str = "") -> None:
        self.name = nome
        self.type = mime or self._MIME_XLSX
        self.size = len(dados)
        self._data = bytes(dados)
        self._pos = 0
        # marcador para o app identificar (se precisar) que veio da API
        self.origem_api = "itau"

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

    def close(self) -> None:  # compat com file-like protocol
        pass

    def __repr__(self) -> str:
        return f"<_ArquivoAPIItau name={self.name!r} size={self.size}>"


# ==============================================================================
# HELPERS DE ESTADO
# ==============================================================================
_CHAVE_ARQS = "itau_arquivos_api"
_CHAVE_NOME_SANKHYA = "itau_nome_sankhya_sugerido"


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
    # Se ficou sem nenhum arquivo, também limpa a sugestão de nome
    if not atuais:
        st.session_state.pop(_CHAVE_NOME_SANKHYA, None)


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
                reg = contas_disponiveis.get(x, {})
                num = reg.get("conta", "")
                nome_sk = reg.get("nome_sankhya", "")
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

    # FORA do form: processar (nao há mais download — vai direto pro uploader)
    if submitted:
        reg = contas_disponiveis.get(apelido_sel) or {}
        conta_numero = reg.get("conta", "")
        nome_sankhya = reg.get("nome_sankhya", "")
        if not conta_numero:
            st.error("Conta inválida — verifique o cadastro em [itau.contas] no Secrets.")
            return
        _puxar_e_injetar_no_uploader(
            apelido=apelido_sel,
            conta_numero=str(conta_numero),
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
    """
    with st.spinner(f"Puxando extrato Itaú · {apelido} · "
                    f"{data_inicio.strftime('%d/%m')} a {data_fim.strftime('%d/%m')}..."):
        try:
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

    aviso_nome = ""
    if not nome_sankhya:
        aviso_nome = (
            "  ⚠️ Sem `nome_sankhya` cadastrado para esta conta — "
            "o identificador vai precisar ser escolhido manualmente. "
            "Cadastre em Secrets → [itau.contas." + apelido + "]."
        )
    st.success(
        f"✓ Extrato {apelido} carregado ({arq.size:,} bytes)."
        + aviso_nome
    )
    # rerun para o uploader do app.py enxergar o novo arquivo já
    st.rerun()


def _render_lista_arquivos_api() -> None:
    """Mostra, logo abaixo do expansor, os arquivos que estão vindos da API
    (com botão para remover). Fica visível mesmo com o expansor colapsado,
    para que a Débora sempre veja o que está pronto para conciliar.
    """
    arqs = _arquivos_api_na_sessao()
    if not arqs:
        return

    nome_sk = st.session_state.get(_CHAVE_NOME_SANKHYA, "")
    rotulo_sk = f" · identificador: **{nome_sk}**" if nome_sk else ""
    st.markdown(
        f'<div style="margin:6px 0 2px;font-size:11.5px;color:#9fb3d6;">'
        f'📡 <b>Arquivos vindos da API Itaú</b>{rotulo_sk}'
        f'</div>',
        unsafe_allow_html=True,
    )
    for i, arq in enumerate(arqs):
        col_nome, col_x = st.columns([12, 1])
        with col_nome:
            st.markdown(
                f'<div style="background:#0b2560;border-radius:6px;'
                f'padding:6px 12px;margin-bottom:4px;color:#eaf0fb;'
                f'font-size:12px;display:flex;align-items:center;gap:8px;">'
                f'<span style="background:#EC7000;color:#fff;font-size:10px;'
                f'font-weight:700;padding:2px 8px;border-radius:4px;">ITAÚ · API</span>'
                f'<span>{arq.name}</span>'
                f'<span style="color:#9fb3d6;">· {arq.size:,} bytes</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col_x:
            if st.button("✖", key=f"rm_api_itau_{i}",
                         help="Remover este arquivo (para puxar de novo, use o expansor acima)"):
                _remover_arquivo_api(i)
                st.rerun()


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
    """Renderiza o bloco completo (chamado do app.py)."""
    if not _credenciais_configuradas():
        _render_bloco_nao_configurado()
        return

    # Container discreto
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
