# 🏦 Conciliação Bancária Automatizada

Sistema web para conciliar diariamente o **extrato bancário** com o **relatório do ERP** (sistema), identificando pendências, divergências, duplicidades e lançamentos baixados na conta errada.

**Stack:** Python + Pandas + Streamlit · **Hospedagem:** Streamlit Community Cloud (grátis)

---

## ✨ O que o sistema faz

Dado um extrato bancário padronizado e o relatório de Conciliação Bancária do ERP, o sistema produz um relatório Excel com 9 abas:

| Aba | Conteúdo |
|---|---|
| 1. Resumo Executivo | KPIs e visão geral |
| 2. Conciliados | Pares que bateram exatamente (Data + Valor + Conta) |
| 3. Pendências Banco | Está no extrato, falta baixar no sistema |
| 4. Pendências Sistema | Está no sistema, não aparece no banco (lançamento indevido) |
| 5. Divergência Valor | Mesma data/histórico, valores diferentes |
| 6. Duplicidades | Mesmo lançamento registrado mais de uma vez |
| 7. Banco Errado | Lançado na conta errada (suspeitos) |
| 8. Sugestões Fuzzy | Possíveis matches para revisão manual (não automático) |
| 9. **Pendências Consolidadas** ⭐ | **INPUT do próximo dia** — sobe de volta amanhã |

### Como funciona o controle diário sem banco de dados

O sistema **não usa banco de dados**. Em vez disso, o próprio relatório Excel funciona como estado persistente:

```
Dia 12: rodou conciliação → baixou conciliacao_20260512.xlsx
Dia 13: sobe extrato do dia 13 + relatório do sistema
        + sobe conciliacao_20260512.xlsx no campo "Pendências anteriores"
        → o app reconcilia automaticamente pendências antigas
        → mostra "essa pendência está há 1 dia em aberto"
        → gera conciliacao_20260513.xlsx atualizado
```

A coluna **Dias Pendente** na aba "Pendências Consolidadas" mostra há quantos dias cada pendência está aberta — quanto maior, mais urgente.

---

## 🚀 Como rodar localmente

```bash
# 1. Clone o repositório
git clone https://github.com/SEU_USUARIO/conciliacao-bancaria.git
cd conciliacao-bancaria

# 2. Crie um ambiente virtual (opcional, mas recomendado)
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Rode o app
streamlit run app.py
```

Acesse: http://localhost:8501

---

## ☁️ Deploy no Streamlit Community Cloud (grátis)

1. Faça push do repositório no GitHub (público)
2. Acesse https://share.streamlit.io
3. Faça login com sua conta do GitHub
4. Clique em **New app** → selecione o repositório
5. Branch: `main` · Main file: `app.py`
6. Clique em **Deploy**

Em ~2 minutos seu app fica online em uma URL pública (`https://seuapp.streamlit.app`).

> ⚠️ **Atenção:** o Streamlit Cloud é público. Se 4+ pessoas vão usar e os dados são confidenciais, considere:
> - Adicionar autenticação básica (`streamlit-authenticator`)
> - OU usar deploy privado (Streamlit for Teams, Railway, Render, servidor próprio)

---

## 📁 Estrutura do projeto

```
conciliacao-bancaria/
├── app.py                         # App Streamlit
├── requirements.txt               # Dependências Python
├── README.md                      # Este arquivo
├── .gitignore                     # Protege dados confidenciais
├── .streamlit/
│   └── config.toml                # Tema e config do Streamlit
├── src/
│   ├── parsers/                   # Leitura dos arquivos de entrada
│   │   ├── extrato_banco.py
│   │   ├── sistema_erp.py
│   │   └── pendencias_anteriores.py
│   ├── matching/                  # Lógica de conciliação
│   │   ├── exact_match.py         # Data + Valor + Conta
│   │   ├── fuzzy_match.py         # Sugestões para revisão
│   │   └── auditorias.py          # Duplicidades, divergências, banco errado
│   ├── reports/
│   │   └── excel_report.py        # Geração do .xlsx multi-aba
│   └── pipeline.py                # Orquestrador
├── tests/
│   ├── test_matching.py           # Testes unitários
│   ├── test_pipeline_smoke.py     # Teste end-to-end
│   └── gerar_samples.py           # Gera dados sintéticos de exemplo
└── data/
    ├── samples/                   # Exemplos FICTÍCIOS (ok no Git)
    ├── uploads/                   # IGNORADO pelo Git (dados reais)
    └── outputs/                   # IGNORADO pelo Git (relatórios)
```

---

## 📋 Formato dos arquivos de entrada

### Extrato bancário (padronizado manualmente)

| Data | Histórico | Documento | Valor (R$) |
|---|---|---|---|
| 04/05/2026 | PIX ENVIADO LLE | — | -1000,00 |
| 04/05/2026 | TAR LIQ COB COM REG COMPE | 193956 | -3,00 |

- Pode ter **múltiplas abas** (uma por dia) ou uma só
- **Valor já vem com sinal**: negativo para saída, positivo para entrada
- A coluna `Documento` é opcional

### Relatório do sistema (ERP)

Layout padrão do ERP usado:
- Linha 1: Título "Conciliação Bancária"
- Linha 2: Emissão / Total de registros / Usuário
- Linha 3: Cabeçalho das colunas
- Linha 4+: Dados

Colunas obrigatórias: `Dt. Lançamento`, `Histórico`, `Vlr. Lançamento`, `Receita/Despesa`

Colunas opcionais aproveitadas: `Núm. Único Bancário`, `Núm. Documento`, `Conciliado`, `Tipo de Movimento`, `Usuário`, **coluna de conta bancária** (qualquer nome — o app tenta detectar).

> No sistema, o valor vem positivo + coluna `Receita/Despesa`. O app aplica o sinal automaticamente.

---

## 🔬 Como funciona a conciliação

**Chave de match:** `(Data, Valor, Conta)` — exato, com match 1-pra-1.

Exemplo: 3 tarifas de R$ 3,00 no banco × 2 tarifas de R$ 3,00 no sistema → 2 casam, 1 fica como pendência.

**Fuzzy matching** (similaridade de histórico) **NÃO entra na conciliação automática**. Aparece apenas em uma aba separada de "Sugestões" para revisão humana.

---

## 🧪 Rodar testes

```bash
# Testes unitários
python tests/test_matching.py

# Teste end-to-end com arquivos reais (precisa de arquivos em data/uploads/)
python tests/test_pipeline_smoke.py
```

---

## 🔒 Privacidade dos dados

Este repositório é público, mas **nenhum dado real é commitado**:

- O `.gitignore` ignora `*.xls`, `*.xlsx`, e as pastas `data/uploads/` e `data/outputs/`
- Apenas `data/samples/` (dados sintéticos fictícios) sobe pro Git
- Arquivos enviados pelo usuário no Streamlit ficam em memória — não são persistidos

---

## 📜 Licença

MIT — fique à vontade para usar, modificar e contribuir.

---

## 🤝 Contribuindo

Sugestões e PRs são bem-vindos. Para reportar bugs ou pedir features, abra uma [Issue](https://github.com/SEU_USUARIO/conciliacao-bancaria/issues).
