"""
src/paginas/login_supabase.py — v2 (Magic Link com redirect)

Tela de login por Magic Link (Supabase).

Fluxo:
1. Usuario digita email -> botao "Enviar link"
2. Backend envia link por email
3. Usuario clica no link no email
4. Supabase redireciona pra esta pagina com tokens no fragment (#)
5. JavaScript captura fragment e converte em query params
6. Codigo Python detecta query params e cria sessao
7. Mostra tela de sucesso
"""

import streamlit as st
import streamlit.components.v1 as components

from src.auth_supabase import (
    OTP_SENT_KEY,
    current_user,
    is_admin,
    is_logged_in,
    send_magic_link,
    set_session_from_tokens,
    sign_out,
)


# ============================================================
# JavaScript pra capturar fragment (#access_token=...) e converter
# em query params (?access_token=...) que o Streamlit consegue ler
# ============================================================
_JS_CAPTURE_FRAGMENT = """
<script>
(function() {
  try {
    const hash = window.parent.location.hash;
    if (hash && hash.length > 1 && hash.includes('access_token=')) {
      const params = new URLSearchParams(hash.substring(1));
      const accessToken = params.get('access_token');
      const refreshToken = params.get('refresh_token');
      if (accessToken && refreshToken) {
        const currentUrl = new URL(window.parent.location.href);
        currentUrl.hash = '';
        currentUrl.searchParams.set('page', 'login_supabase');
        currentUrl.searchParams.set('access_token', accessToken);
        currentUrl.searchParams.set('refresh_token', refreshToken);
        window.parent.location.replace(currentUrl.toString());
      }
    }
  } catch (e) {
    console.error('Erro ao capturar fragment:', e);
  }
})();
</script>
"""


def _tentar_autenticar_via_url() -> bool:
    """Se tem access_token na URL, tenta criar sessao.
    Retorna True se autenticou agora."""
    qp = st.query_params
    access_token = qp.get("access_token")
    refresh_token = qp.get("refresh_token")

    if not access_token or not refresh_token:
        return False

    if is_logged_in():
        # Ja logado, so limpa tokens da URL por seguranca
        try:
            del st.query_params["access_token"]
            del st.query_params["refresh_token"]
        except Exception:
            pass
        return False

    r = set_session_from_tokens(access_token, refresh_token)

    # Limpar tokens da URL apos usar (nao deixar exposto)
    try:
        del st.query_params["access_token"]
        del st.query_params["refresh_token"]
    except Exception:
        pass

    if r["ok"]:
        st.rerun()
    else:
        st.error(f"Falha ao autenticar via link: {r['erro']}")
    return r["ok"]


def _render_ja_logado():
    user = current_user()
    st.success("Login Supabase ativo")
    st.write("**Nome:**", user.get("nome_completo", "-"))
    st.write("**Email:**", user.get("email", "-"))
    st.write("**Perfil:**", user.get("perfil", "-"))
    st.write("**Ativo:**", user.get("ativo", False))
    st.write("**Admin:**", is_admin())

    if user.get("_erro_perfil"):
        st.warning(f"Perfil nao encontrado: {user['_erro_perfil']}")

    st.divider()
    if st.button("Sair (logout Supabase)", type="secondary"):
        sign_out()
        st.rerun()


def _render_form_login():
    email_enviado = st.session_state.get(OTP_SENT_KEY, "")

    with st.container(border=True):
        st.subheader("Passo 1 — Digite seu email")

        email = st.text_input(
            "Seu email",
            value=email_enviado,
            placeholder="financeiro@grupolle.com.br",
            key="login_supabase_email_input",
        )

        if st.button("Enviar link de acesso", type="primary", use_container_width=True):
            with st.spinner("Enviando..."):
                r = send_magic_link(email)
            if r["ok"]:
                st.success(f"Link enviado para {email}.")
                st.rerun()
            else:
                st.error(f"Falha ao enviar: {r['erro']}")

    if email_enviado:
        with st.container(border=True):
            st.subheader("Passo 2 — Verifique seu email")
            st.info(
                f"Enviamos um link de acesso para **{email_enviado}**. "
                f"Abra seu email e clique no botao **'Sign in'** do email "
                f"que voce recebeu do Supabase. Voce sera redirecionado "
                f"automaticamente para o app ja autenticado."
            )
            st.caption("O link expira em 1 hora e so pode ser usado uma vez.")

            if st.button("Reenviar link", use_container_width=False):
                with st.spinner("Reenviando..."):
                    r = send_magic_link(email_enviado)
                if r["ok"]:
                    st.success("Novo link enviado.")
                else:
                    st.error(r["erro"])


def render():
    """Renderiza a pagina de login Supabase."""

    # PRIMEIRA COISA: injeta o JS que captura o fragment.
    # Se estiver no retorno do link (com #access_token=...), ele redireciona.
    components.html(_JS_CAPTURE_FRAGMENT, height=0)

    # Tenta autenticar via URL se veio com tokens
    _tentar_autenticar_via_url()

    st.title("Login Supabase (teste)")
    st.caption("Parte 1.3.B da Fase 1 — MVP-A. Login por Magic Link.")

    st.divider()

    if is_logged_in():
        _render_ja_logado()
    else:
        _render_form_login()

    st.divider()

    with st.expander("Diagnostico tecnico", expanded=False):
        st.write("**is_logged_in():**", is_logged_in())
        st.write("**is_admin():**", is_admin())
        st.write("**OTP enviado para:**", st.session_state.get(OTP_SENT_KEY, "(nenhum)"))
        st.write("**Query params:**", dict(st.query_params))
        st.write("**Session state keys:**", [k for k in st.session_state.keys() if "supabase" in k.lower()])


if __name__ == "__main__":
    render()
