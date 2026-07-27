"""Gerador de hash de senha — v6.0

Uso local (roda no seu computador, NÃO no app). Gera o hash bcrypt de
uma senha que você digita, pra colar no Streamlit Secrets sem que a
senha em texto puro apareça em lugar nenhum.

Como rodar:
    1. Instale a biblioteca (uma vez só):
       pip install streamlit-authenticator

    2. Rode este script:
       python gerar_hash_senha.py

    3. Digite a senha desejada quando pedir (não aparece na tela)
    4. Copie o hash que ele imprime e cole no arquivo de Secrets
       do Streamlit Cloud (Settings → Secrets), no campo `password`
       do bloco da usuária.

A senha em si NUNCA precisa sair do seu computador — só o hash vai
pro app. Se alguém interceptar o hash, não consegue descobrir a senha
(bcrypt é uma via de mão única).
"""

import getpass

try:
    from streamlit_authenticator.utilities.hasher import Hasher
except ImportError:
    print(
        "\n⚠️  Biblioteca streamlit-authenticator não instalada.\n"
        "    Rode: pip install streamlit-authenticator\n"
    )
    raise SystemExit(1)


def main() -> None:
    print("\n=== Gerador de hash de senha — Conciliação LLE ===\n")

    senha = getpass.getpass("Digite a senha desejada (não aparece na tela): ")
    if not senha:
        print("\n❌ Senha vazia. Cancelado.\n")
        return
    if len(senha) < 8:
        print("\n⚠️  Recomendo senha com pelo menos 8 caracteres.\n")

    confirmacao = getpass.getpass("Confirme a senha: ")
    if senha != confirmacao:
        print("\n❌ As senhas não batem. Cancelado.\n")
        return

    # A API do streamlit-authenticator 0.4+ é: Hasher.hash("texto")
    try:
        hash_gerado = Hasher.hash(senha)
    except AttributeError:
        # fallback pra versões antigas (0.3.x): Hasher([senha]).generate()
        hash_gerado = Hasher([senha]).generate()[0]

    print("\n✅ Hash gerado com sucesso.\n")
    print("Cole este bloco no Streamlit Cloud → Settings → Secrets:")
    print()
    print('-' * 68)
    print()
    print("[auth.credentials.usernames.<seu_username>]")
    print('name = "Nome Completo Aqui"')
    print('email = "email@grupolle.com.br"')
    print(f'password = "{hash_gerado}"')
    print("failed_login_attempts = 0")
    print("logged_in = false")
    print()
    print('-' * 68)
    print()
    print("Substitua <seu_username> pelo nome do usuário (ex.: debora).")
    print("Substitua Nome/email pelos dados reais.")
    print("A senha em texto puro NÃO precisa ser enviada — só o hash acima.")
    print()


if __name__ == "__main__":
    main()
