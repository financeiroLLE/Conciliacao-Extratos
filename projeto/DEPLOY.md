# 🚀 Guia de deploy passo a passo

Este guia te leva do zero ao app online em ~15 minutos.

---

## Pré-requisitos

- [ ] Conta no GitHub (grátis)
- [ ] Git instalado no seu computador ([baixar](https://git-scm.com/downloads))
- [ ] Python 3.10+ instalado ([baixar](https://www.python.org/downloads/))

---

## Parte 1 — Criar o repositório no GitHub

1. Acesse https://github.com/new
2. Preencha:
   - **Repository name:** `conciliacao-bancaria`
   - **Description:** "Sistema de conciliação bancária automatizada"
   - **Visibility:** Public
   - **NÃO marque** "Add a README" (já temos um)
3. Clique em **Create repository**
4. Copie a URL que aparece (ex: `https://github.com/SEU_USUARIO/conciliacao-bancaria.git`)

---

## Parte 2 — Subir o código

No terminal, dentro da pasta do projeto:

```bash
# Inicializa o git
git init
git add .
git commit -m "feat: versão inicial do sistema de conciliação"

# Conecta com o GitHub (substitua SEU_USUARIO)
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/conciliacao-bancaria.git
git push -u origin main
```

Quando pedir login, use seu usuário do GitHub. Se der erro de autenticação, use um **Personal Access Token** em vez de senha:
- GitHub → Settings → Developer settings → Personal access tokens → Generate new token
- Marque o escopo "repo" e gere
- Use o token gerado como senha

---

## Parte 3 — Testar localmente antes do deploy

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar o app
streamlit run app.py
```

Abra http://localhost:8501 e:
1. Vá na aba "Upload"
2. Use os arquivos em `data/samples/` para testar:
   - Extrato bancário: `data/samples/extrato_banco_exemplo.xlsx`
   - Identificador da conta: `BCO-EXEMPLO-001`
   - Relatório do sistema: `data/samples/relatorio_sistema_exemplo.xlsx`
   - Nome da coluna conta: `Conta Bancária`
3. Clique em "Executar conciliação"
4. Veja os resultados e baixe o relatório

Se funcionou, está pronto pro deploy.

---

## Parte 4 — Deploy no Streamlit Community Cloud

1. Acesse https://share.streamlit.io
2. Clique em **Sign in with GitHub** e autorize
3. Clique em **New app** (botão azul no canto superior direito)
4. Preencha:
   - **Repository:** `SEU_USUARIO/conciliacao-bancaria`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL (opcional):** escolha um subdomínio, ex: `conciliacao-empresa`
5. Clique em **Deploy!**

Aguarde 2-5 minutos. Quando aparecer a tela do app, está no ar! 🎉

A URL será algo como: `https://conciliacao-empresa.streamlit.app`

---

## Parte 5 — Compartilhar com a equipe

- Envie a URL para as 4+ pessoas que vão usar
- Não precisa de login (conforme decisão de projeto)
- Cada usuário pode acessar de qualquer dispositivo (computador, celular, tablet)

> ⚠️ **Importante sobre privacidade:**
> - A URL é pública. Quem tem o link, acessa.
> - Os arquivos enviados ficam **em memória apenas durante a sessão**, não são salvos no servidor.
> - Mas o **tráfego passa pelo Streamlit Cloud**. Se a empresa exige que dados financeiros nunca saiam de servidores internos, considere hospedar em um servidor próprio.

---

## Parte 6 — Atualizar o app

Sempre que você quiser melhorar algo:

```bash
# Edite os arquivos localmente, depois:
git add .
git commit -m "feat: nome da melhoria"
git push
```

O Streamlit Cloud detecta automaticamente o push e reimplanta em ~1 minuto. **Não precisa fazer nada manual.**

---

## ❓ Problemas comuns

**"ModuleNotFoundError: No module named 'streamlit'"**
→ Você não está no ambiente virtual ou esqueceu `pip install -r requirements.txt`

**App quebra no Streamlit Cloud mas funciona local**
→ Verifique se todas as bibliotecas usadas estão no `requirements.txt` com versões compatíveis

**"Permission denied" ao fazer push**
→ Use Personal Access Token em vez de senha (ver Parte 2)

**Upload muito grande**
→ O limite padrão é 200 MB (configurado no `.streamlit/config.toml`). Se precisar mais, ajuste `maxUploadSize`.
