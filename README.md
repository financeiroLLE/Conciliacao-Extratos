# 🏦 Conciliação Bancária — Grupo LLE

Sistema web para conciliar diariamente o **extrato bancário** com o **extrato do sistema Sankhya**, com dashboard executivo, detalhamento por banco, classificação por tipo de lançamento (Boleto/Pix/Tarifa/...) e auditoria append-only de execuções.

**Stack:** Python + Pandas + Streamlit · **Hospedagem:** Streamlit Community Cloud (grátis) · **Identidade visual:** Manual da Marca Grupo LLE (Fev/2026)

---

## ✨ Funcionalidades

### Dashboard executivo
7 cards principais calculados sobre o resultado real (sem mock):
- Total Extrato Bancário · Total Extrato Sankhya · Total Conciliado
- Falta Conciliar · Falta Lançar · Conciliado c/ Divergência
- Percentual Conciliado

### Tela única de resultado
Após o upload e o "Executar conciliação", o sistema **abre direto a tela de resultado** com todos os KPIs, painel de bancos clicáveis e detalhamento por tipo de lançamento — sem segundo passo lateral.

### Painel de bancos
Cada conta processada vira um card clicável. Ao clicar em "Ver detalhamento", abre tela específica daquele banco com:
- KPIs filtrados (Total Banco / Sankhya / Conciliado / % / Falta Conciliar / Falta Lançar / c/ Divergência / Total Lançamentos)
- Botão de download do relatório só daquela conta
- Abas internas: **Conciliadas** · **Pendentes** · **Não Pertence à Conta** · **Conciliadas com Divergência** (quando houver)

### Subabas por tipo de lançamento
Boleto · Pix · Tarifa · TED/DOC · Débito Automático · Cartão · Pagamentos · Recebimentos · Outros — com KPIs, tabela e downloads (Excel + CSV) para cada recorte.

### Reprocessamento e auditoria
- Cada execução salva snapshot completo em `data/outputs/execucoes/{id}/` (inputs, parâmetros, resultado).
- Índice append-only em `data/outputs/auditoria.jsonl` — **nunca é sobrescrito**.
- Reprocessar mantém o histórico anterior + cria nova versão.
- Página "Histórico" lista todas execuções com busca e download de snapshots.

### Downloads
- **Excel completo** (15 abas): Resumo Geral · Resumo por Banco · Conciliadas · Pendentes · Conciliadas com Divergência · Não Pertence à Conta · Boletos · Pix · Tarifas · Pagamentos · Recebimentos · Duplicidades · Sugestões Fuzzy · Pendências Consolidadas · Auditoria.
- **Excel por banco** (mesmas abas, filtradas).
- **Zip de CSVs** (uma tabela por arquivo).
- **Download por recorte** (botão Excel + CSV em cada aba de detalhamento).

---

## 🔬 Regras de negócio

### Match exato (conciliação automática)
- **Valor: exatamente igual** — sem tolerância de centavos.
- **Conta: igual**.
- **Data: tolerância de ±N dias corridos** (default 2, configurável na sidebar). Cobre compensação por fim de semana e feriados curtos.
- **1-pra-1**: cada lançamento do banco casa com no máximo um do sistema.

### Divergência de valor
Mesma data + histórico (normalizado: caixa alta + colapso de espaços) + conta, mas valores diferentes.

### Duplicidade (estrita)
Só é sinalizada quando **data + histórico + valor + documento** são **todos** iguais. 5 boletos legítimos de R$ 1.000 com documentos diferentes **não** são duplicidade.

### Não Pertence à Conta
Pendência em uma conta que tem candidato perfeito (mesmo valor + data próxima) em **outra conta**.

### Sugestões fuzzy
Aba complementar para revisão manual — **não entra na conciliação automática**.

---

## 🚀 Como rodar localmente

```bash
git clone https://github.com/SEU_USUARIO/conciliacao-bancaria.git
cd conciliacao-bancaria

python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

pip install -r requirements.txt
streamlit run app.py
```

Acesse `http://localhost:8501`.

### Gerar dados sintéticos para testar

```bash
python tests/gerar_samples.py
```

Cria 3 arquivos em `data/samples/` — use-os no app para validar o fluxo completo.

### Rodar testes

```bash
python tests/test_matching.py        # 16 testes unitários da lógica
python tests/test_pipeline_smoke.py  # end-to-end com geração de Excel
```

---

## ☁️ Deploy no Streamlit Community Cloud

Veja [DEPLOY.md](DEPLOY.md).

---

## 📁 Estrutura

```
conciliacao-bancaria/
├── app.py                          # App Streamlit (UI azul/amarela)
├── requirements.txt
├── README.md / DEPLOY.md / LICENSE
├── .gitignore
├── .streamlit/config.toml          # Tema Grupo LLE
├── assets/
│   └── logo-grupo-lle-branco.png   # Logo (texto branco, fundo escuro)
├── src/
│   ├── parsers/                    # Leitura dos extratos (banco + ERP + pendências)
│   ├── matching/                   # Match exato, fuzzy, auditorias
│   ├── classificacao/              # Boleto/Pix/Tarifa/... por regex
│   ├── reports/                    # Excel multi-aba + CSV zip
│   ├── auditoria/                  # JSONL append-only + snapshots
│   └── pipeline.py                 # Orquestrador (ResultadoConciliacao)
├── tests/
│   ├── test_matching.py
│   ├── test_pipeline_smoke.py
│   └── gerar_samples.py
└── data/
    ├── samples/                    # Dados sintéticos (ok no Git)
    ├── uploads/                    # IGNORADO (dados reais)
    └── outputs/                    # IGNORADO (relatórios + auditoria)
```

---

## 📋 Formato dos arquivos de entrada

### Extrato bancário (padronizado)

| Data       | Histórico               | Documento | Valor (R$) |
|------------|-------------------------|-----------|------------|
| 04/05/2026 | PIX RECEBIDO CLIENTE A  |           |   1500,00  |
| 04/05/2026 | TAR LIQ COB             | T1        |     -3,00  |

- Valor já vem com **sinal**: negativo = saída, positivo = entrada.
- Aceita 1 ou múltiplas abas (uma por dia).

### Relatório do sistema (ERP Sankhya)

Layout padrão: linha 1 título, linha 2 metadata, linha 3 cabeçalho, linha 4+ dados.

Colunas obrigatórias: `Dt. Lançamento`, `Histórico`, `Vlr. Lançamento`, `Receita/Despesa`.
Coluna de conta tem nome variável (passada por parâmetro ou detectada).
Valor vem positivo + sinal vem da coluna `Receita/Despesa`.

---

## 🔒 Privacidade

- `.gitignore` ignora `*.xls`, `*.xlsx`, `data/uploads/`, `data/outputs/`.
- Apenas `data/samples/` (sintéticos) sobe pro Git.
- Arquivos no app ficam em memória — não são persistidos no servidor.
- Snapshots de auditoria ficam **localmente** em `data/outputs/execucoes/`.

> Para acesso público a dados confidenciais no Streamlit Cloud, considere autenticação ou deploy privado.

---

## 📜 Licença

MIT.
