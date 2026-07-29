"""
src/paginas/conciliacao_vendas.py

Pagina esqueleto do modulo Concilia\u00e7\u00e3o de Vendas.
Sera implementada nas Fases 3-8 do MVP-A.
"""

import streamlit as st


_CSS = """
<style>
  .cv-empty {
    background: #FFF6C8;
    border: 2px dashed #FFCC00;
    border-radius: 14px;
    padding: 48px 32px;
    text-align: center;
    margin: 2rem 0;
  }
  .cv-empty h2 {
    color: #0A1730;
    font-size: 20px;
    font-weight: 500;
    margin: 0 0 12px 0;
    letter-spacing: 0.5px;
  }
  .cv-empty p {
    color: #5F5E5A;
    font-size: 13px;
    margin: 6px 0;
    line-height: 1.6;
  }
  .cv-empty .icon {
    font-size: 48px;
    color: #FFCC00;
    margin-bottom: 12px;
    display: block;
  }
  .cv-roadmap {
    background: #FFFFFF;
    border: 0.5px solid #E5E5E5;
    border-radius: 12px;
    padding: 20px 24px;
    margin-top: 1.5rem;
  }
  .cv-roadmap h3 {
    color: #0A1730;
    font-size: 14px;
    font-weight: 500;
    margin: 0 0 12px 0;
    letter-spacing: 0.5px;
  }
  .cv-roadmap ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .cv-roadmap li {
    padding: 6px 0;
    font-size: 12px;
    color: #5F5E5A;
    border-bottom: 0.5px solid #F0F0F0;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .cv-roadmap li:last-child { border-bottom: none; }
  .cv-roadmap .status {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 500;
    margin-left: auto;
  }
  .cv-roadmap .status.done { background: #EAF3DE; color: #27500A; }
  .cv-roadmap .status.wip { background: #FAEEDA; color: #633806; }
  .cv-roadmap .status.next { background: #F1EFE8; color: #5F5E5A; }
</style>
"""


def render_conciliacao_vendas():
    """Renderiza a pagina esqueleto do modulo Conciliacao de Vendas."""
    st.markdown(_CSS, unsafe_allow_html=True)

    st.markdown(
        """
        <div class="cv-empty">
            <div style="font-size:48px;color:#FFCC00;">\U0001F6D2</div>
            <h2>M\u00f3dulo em constru\u00e7\u00e3o</h2>
            <p>A concilia\u00e7\u00e3o de vendas de cart\u00e3o est\u00e1 sendo constru\u00edda.</p>
            <p>Este m\u00f3dulo vai cruzar as vendas registradas no Sankhya com as
            capturas das adquirentes (Cielo, Getnet) para conciliar automaticamente
            e apontar diverg\u00eancias.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="cv-roadmap">
          <h3>Roteiro de constru\u00e7\u00e3o</h3>
          <ul>
            <li>Infraestrutura Supabase + autentica\u00e7\u00e3o<span class="status done">conclu\u00eddo</span></li>
            <li>Reorganiza\u00e7\u00e3o do menu + m\u00f3dulo esqueleto<span class="status wip">em andamento</span></li>
            <li>Tela de configura\u00e7\u00f5es (empresas, adquirentes, estabelecimentos)<span class="status next">pr\u00f3ximo</span></li>
            <li>Leitores de arquivo (Financeiro Sankhya, Cielo 03D, Getnet)<span class="status next">pr\u00f3ximo</span></li>
            <li>Motor de concilia\u00e7\u00e3o (4 grupos)<span class="status next">pr\u00f3ximo</span></li>
            <li>Ferramentas manuais + auditoria de taxa<span class="status next">pr\u00f3ximo</span></li>
            <li>Dashboard + exporta\u00e7\u00e3o Excel<span class="status next">pr\u00f3ximo</span></li>
            <li>Valida\u00e7\u00e3o final + produ\u00e7\u00e3o<span class="status next">pr\u00f3ximo</span></li>
          </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )
