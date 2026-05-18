# 🏦 Conciliação Bancária — Grupo LLE (v2)

Sistema web para conciliar diariamente o **extrato bancário** com o **extrato do sistema Sankhya**, com dashboard executivo, detalhamento por banco, classificação por tipo de lançamento, separação entre receitas e despesas absolutas, identificação de aplicações/resgates e auditoria append-only.

**Stack:** Python + Pandas + Streamlit · **Hospedagem:** Streamlit Community Cloud (grátis) · **Identidade visual:** Manual da Marca Grupo LLE (Fev/2026)

---

## 🆕 Novidades v2 (sobre v1)

- **Total Extrato Bancário** exclui linhas de saldo, aplicação e resgate.
- **Receitas Absolutas** e **Despesas Absolutas** separadas (não compensadas).
- **Card "Falta Conciliar"** detalha receitas e despesas em letras menores.
- **Card "Falta Lançar"** usa a coluna **Conciliado=Não** do Sankhya quando disponível (fallback automático para regra antiga).
- **Possíveis Duplicidades** (3 de 4 campos batendo) — aba própria.
- **Aplicações e Resgates** em aba dedicada.
- **Saldo Final** com card destacado quando a conta está 100% conciliada.
- **Logo com fundo transparente** + borda azul institucional na sidebar.
- **Todos os botões legíveis sem hover**.
- Múltiplas contas do mesmo banco (Itaú PISA, KING, APOIO, INOV, LLE) — cada identificador é uma conta separada.

---

## ✨ Funcionalidades principais

### Dashboard executivo
- Total Bancário · Total Sankhya · Total Conciliado · % Conciliado
- Falta Conciliar (com Receitas/Despesas) · Falta Lançar · Divergência · Total Absoluto
- Receitas e Despesas absolutas (Banco e Sankhya)
- Possíveis Duplicidades · Aplicações/Resgates · Duplicidades estritas · Não Pertence

### Tela única de resultado
Após upload e "Executar conciliação", abre direto a tela completa com KPIs, painel de bancos clicáveis e detalhamento por tipo.

### Painel de bancos
Cada conta vira card clicável. Detalhamento mostra:
- KPIs específicos da conta · Card de Saldo Final (quando 100%) · Download por banco
- Abas: **Conciliadas · Pendentes · Falta Lançar (Sankhya) · Não Pertence · Conciliadas c/ Divergência · Possíveis Duplicidades · Aplicações e Resgates**

### Subabas por tipo
Boleto · Pix · Tarifa · TED/DOC · Débito Automático · Cartão · Pagamentos · Recebimentos · Outros

### Reprocessamento e auditoria
Cada execução salva snapshot em `data/outputs/execucoes/{id}/`. Índice append-only em `data/outputs/auditoria.jsonl`.

### Downloads
- Excel multi-aba · Excel por banco · Zip de CSVs · Download por recorte

---

## 🔬 Regras de negócio

### Total Extrato Bancário (v2)
Exclui movimentos que não são transações reais: `SALDO`, `APLICAÇÃO`, `RESGATE`, `INVESTIMENTO`, `CDB/RDB/LCI/LCA/TESOURO`, `POUPANÇA AUTOMÁTICA`, `CRÉDITO RENDIMENTO`.

### Match exato
- Valor: **exatamente igual** (sem tolerância de centavos).
- Conta: igual.
- Data: tolerância de ±N dias corridos (default 2 — cobre fim de semana e feriado curto).
- 1-pra-1.

### Falta Lançar — fonte automática
- Se Sankhya tem coluna `Conciliado` preenchida (Sim/Não), usa as linhas com `Não`.
- Senão usa pendentes pós-match. Card mostra a fonte usada.

### Duplicidades
- **Estritas**: 4 de 4 campos iguais (data, histórico, valor, documento).
- **Possíveis**: 3 de 4 — em aba própria, marcadas como "REVISAR MANUALMENTE".

### Receitas vs Despesas
- Receitas Absolutas = soma dos valores > 0 (movimentações reais).
- Despesas Absolutas = soma absoluta dos valores < 0, exibidas positivas.
- Sem compensação entre elas.

### Saldo Final
- Aparece SÓ quando a conta atinge 100% conciliada.
- Usa linhas SALDO INICIAL/FINAL do extrato; senão exibe movimentação líquida com aviso.

---

## 🚀 Como rodar localmente

```bash
git clone https://github.com/SEU_USUARIO/conciliacao-bancaria.git
cd conciliacao-bancaria
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Acesse `http://localhost:8501`.

### Dados sintéticos para testar
```bash
python tests/gerar_samples.py
```

### Testes
```bash
python tests/test_matching.py        # 26 testes
python tests/test_pipeline_smoke.py  # end-to-end
```

---

## 📁 Estrutura

```
conciliacao-bancaria/
├── app.py                          # App Streamlit
├── requirements.txt · README.md · DEPLOY.md · LICENSE · .gitignore
├── .streamlit/config.toml          # Tema Grupo LLE
├── assets/
│   ├── logo-grupo-lle-branco.png        # original (fundo preto)
│   └── logo-grupo-lle-transparente.png  # processada (fundo transparente)
├── src/
│   ├── parsers/                    # extrato banco · sistema ERP · pendências
│   ├── matching/                   # match exato · auditorias · fuzzy
│   ├── classificacao/              # tipo (Boleto/Pix/...) · movimento (mov/saldo/aplic/resgate)
│   ├── reports/                    # Excel multi-aba + CSV zip
│   ├── auditoria/                  # JSONL append-only + snapshots
│   └── pipeline.py                 # ResultadoConciliacao
├── tests/
└── data/{samples,uploads,outputs}
```

---

## 🔒 Privacidade
`.gitignore` ignora dados reais. Apenas samples sintéticos sobem. Arquivos no app ficam em memória.

## 📜 Licença
MIT.
