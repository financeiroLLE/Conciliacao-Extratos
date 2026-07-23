"""Conta 70 — casamento e numeração (envio à contabilidade).

Objetivo: dado o extrato do Sankhya da Conta 70 (tudo que caiu na conta) e a
Capa acumulada (a planilha que vai pra contabilidade, já numerada onde
identificado e EM BRANCO onde não), o motor:

  1. Reconhece o que JÁ está numerado na Capa (identificado) e carrega o número.
  2. Nos SEM número, forma os casamentos entrada↔baixa **pela identidade**
     (CNPJ / CPF / nome / dados da transação no histórico) e propõe o próximo
     número sequencial, continuando do maior número já usado.
  3. O que não fecha com segurança vira **"A conferir"** — NUNCA chuta.

Regras de ouro (da Débora):
  - A regra de casamento é a DESCRIÇÃO/identidade. Valor e data são só
    conferência, nunca decidem sozinhos.
  - Zero falso positivo: na dúvida, "A conferir".
  - O arquivo da contabilidade é somente leitura — o motor nunca o altera.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


def _fmt_numero_txt(v: Any) -> str:
    """Numeração da Capa como TEXTO. Aceita alfanumérico (ex.: '686a').
    '' = sem número (em aberto). '839.0' -> '839'."""
    if pd.isna(v):
        return ""
    sv = str(v).strip()
    if sv.lower() in ("", "nan", "none"):
        return ""
    m = re.match(r"^(\d+)\.0$", sv)
    return m.group(1) if m else sv

# ---------------------------------------------------------------------------
# Identidade (a chave de casamento)
# ---------------------------------------------------------------------------
_PREFIXOS = ["DEP NAO IDENT", "DEP NÃO IDENT", "DEP N IDENT", "DEP IDENT"]
_RUIDO = ["PIX RECEBIDO", "OUTRA INST", "DIF TIT", "SISPAG", "TED", "DOC "]


def extrair_identidade(historico: Any) -> str:
    """Chave estável de identidade a partir do histórico.

    Prioridade: CNPJ (14 díg.) > CPF (11 díg.) > nome limpo. Datas, valores e
    ruído (PIX RECEBIDO, etc.) são removidos porque a baixa costuma trazer coisa
    a mais que a entrada não tem.
    """
    u = str(historico or "").upper()
    m = re.search(r"(?<!\d)(\d{14})(?!\d)", u)  # CNPJ
    if m:
        return "CNPJ:" + m.group(1)
    m = re.search(r"(?<!\d)(\d{11})(?!\d)", u)  # CPF
    if m:
        return "CPF:" + m.group(1)
    x = u
    for p in _PREFIXOS:
        x = x.replace(p, " ")
    x = re.sub(r"\d{2}/\d{2}/\d{4}", " ", x)          # datas
    x = re.sub(r"R?\$?\s*\d[\d\.]*,\d{2}", " ", x)     # valores
    for r in _RUIDO:
        x = x.replace(r, " ")
    x = re.sub(r"[^A-ZÀ-Ú ]", " ", x)                  # tira números soltos/pontuação
    x = re.sub(r"\s+", " ", x).strip()
    return ("NOME:" + x[:40]) if len(x) >= 4 else "SEM-ID"


def _lado(receita_despesa: Any) -> str:
    return "entrada" if "DESPESA" in str(receita_despesa).upper() else "baixa"


# v5.71: nova regra de casamento Sankhya × Capa por chave (data + |valor| + R/D +
# histórico normalizado). Não usa mais Núm. Documento (numeração interna do
# Sankhya, não confiável — a Débora sempre destacou isso). Além disso, aplica
# um corte histórico no balde vermelho: movimentos anteriores a essa data que
# não estão em nenhuma linha da Capa são resíduo histórico (a Capa anterior a
# fev/2024 estava incompleta) e ficam fora da esteira.
DATA_CORTE_ESTEIRA = pd.Timestamp("2024-02-01")


def _norm_hist_esteira(h: Any) -> str:
    """Histórico normalizado para usar como parte da chave de casamento
    (data + |valor| + R/D + hist) entre Conciliação Bancária e Capa 70.

    v5.71 revisado — trata as variações reais que aparecem entre o export da
    ConcB e a linha correspondente na Capa:
      • aspas simples, duplas e escapadas com "\\": todas viram espaço
      • carriage return (\\r), line feed (\\n), tab (\\t) e a variante
        Excel "_x000D_" (que é como o Excel escreve o \\r ao exportar):
        todos viram espaço. Sem isso, uma linha com "\\r20/06/2024" na ConcB
        não bate com "_x000D_20/06/2024" na Capa mesmo sendo idênticas.
      • espaços consecutivos: colapsados em um único
      • duplicação de sufixo no final ("X - Y - Y" → "X - Y"): removida em
        até 3 iterações, cobrindo casos como o real
        `... - DEXCO S.A" - DEXCO S.A`
      • uppercase + strip para comparação estável
    """
    if h is None:
        return ""
    s = str(h).upper()
    # Excel escreve \r como _x000D_ ao exportar — trata como espaço
    s = s.replace('_X000D_', ' ')
    # aspas (simples, duplas), barras invertidas E controles (\r \n \t) viram espaço
    s = re.sub(r'["\'\\\r\n\t]+', ' ', s)
    # colapsa espaços
    s = re.sub(r'\s+', ' ', s).strip()
    # remove duplicações de sufixo (até 3 níveis, pra estabilizar)
    for _ in range(3):
        m = re.match(r'^(.*?)(\s*-\s*[^-]+?)\s*\2\s*$', s)
        if not m:
            break
        s = m.group(1) + m.group(2)
    return s


def _chave_esteira(row) -> tuple:
    """Chave (data_date, |valor| em centavos, R/D, hist_norm) para casamento.
    Usa valor absoluto em centavos como inteiro para evitar erro de float.
    """
    dt = pd.to_datetime(row.get("data"), errors="coerce")
    dt = dt.date() if pd.notna(dt) else None
    try:
        v = int(round(abs(float(row.get("valor", 0))) * 100))
    except Exception:
        v = 0
    rd = str(row.get("receita_despesa", "")).strip()
    hn = _norm_hist_esteira(row.get("historico", ""))
    return (dt, v, rd, hn)


# ---------------------------------------------------------------------------
# Leitura de arquivos (somente leitura)
# ---------------------------------------------------------------------------
def _to_data(v: Any) -> pd.Timestamp:
    """Converte data que pode vir como texto OU número de série do Excel."""
    if isinstance(v, (int, float)) and not pd.isna(v):
        try:
            return pd.Timestamp("1899-12-30") + pd.to_timedelta(float(v), unit="D")
        except Exception:
            return pd.NaT
    return pd.to_datetime(v, errors="coerce", dayfirst=True)


def _ler_planilha(arquivo: Any, header: int = 0) -> pd.DataFrame:
    nome = str(getattr(arquivo, "name", "") or "").lower()
    if nome.endswith(".csv"):
        import io as _io

        raw = arquivo.read() if hasattr(arquivo, "read") else open(arquivo, "rb").read()
        for sep in (";", ","):
            try:
                cand = pd.read_csv(_io.BytesIO(raw), sep=sep, dtype=str, engine="python", header=header)
                if cand.shape[1] > 1:
                    return cand
            except Exception:
                continue
        return pd.read_csv(_io.BytesIO(raw), dtype=str, engine="python", header=header)
    return pd.read_excel(arquivo, header=header)


def _detectar_header(arquivo: Any) -> int:
    """O export do Sankhya vem com 2 linhas de título antes do cabeçalho real;
    a Capa já tem o cabeçalho na 1ª linha. Detecta onde está 'Tipo de Movimento'.
    """
    try:
        bruto = _ler_planilha(arquivo, header=None)
    except Exception:
        return 0
    for i in range(min(5, len(bruto))):
        linha = " ".join(str(x) for x in bruto.iloc[i].tolist()).lower()
        if "tipo de movimento" in linha and "histórico" in linha:
            return i
    return 0


def carregar_movimento(arquivo: Any) -> pd.DataFrame:
    """Lê um arquivo de Conta 70 (Sankhya ou Capa) para o formato padrão.

    Colunas de saída: tipo_movimento, num_documento, valor, receita_despesa,
    data, historico, num_unico, numero (a numeração da Capa, se houver),
    identidade, lado. Nunca escreve no arquivo — só lê.
    """
    hdr = _detectar_header(arquivo)
    if hasattr(arquivo, "seek"):
        try:
            arquivo.seek(0)
        except Exception:
            pass
    df = _ler_planilha(arquivo, header=hdr)
    df.columns = [str(c).strip() for c in df.columns]

    def col(*nomes):
        for n in nomes:
            for c in df.columns:
                if c.lower() == n.lower():
                    return c
        return None

    c_tipo = col("Tipo de Movimento")
    c_doc = col("Núm. Documento", "Num. Documento", "Numero Documento")
    c_val = col("Vlr. Lançamento", "Valor", "Vlr Lancamento")
    c_rd = col("Receita/Despesa", "Receita/D")
    c_dt = col("Dt. Lançamento", "Data")
    c_hist = col("Histórico", "Historico")
    c_uni = col("Núm. Único Bancário", "Num. Unico Bancario")

    # A numeração da Capa é uma coluna EXTRA depois do Histórico (cabeçalho vazio,
    # "x" ou "unnamed"). O export do Sankhya também tem colunas depois do Histórico
    # (Dt. Conciliação, Núm. Único Bancário, etc.) — essas NÃO são numeração.
    _sankhya_pos = {
        "dt. conciliação", "dt. conciliacao", "núm. único bancário",
        "num. unico bancario", "pré-data", "pre-data", "usuário", "usuario",
        "dt. alteração", "dt. alteracao", "vlr. troco", "vlr. cheque", "conciliado",
    }
    c_num = None
    if c_hist is not None:
        idx_hist = list(df.columns).index(c_hist)
        depois = list(df.columns)[idx_hist + 1:]
        for c in depois:
            hl = c.strip().lower()
            if hl in _sankhya_pos:
                continue
            serie = pd.to_numeric(df[c], errors="coerce")
            eh_rotulo_numeracao = hl in ("x", "nan", "") or hl.startswith("unnamed")
            if serie.notna().sum() > 0 and eh_rotulo_numeracao:
                c_num = c
                break

    out = pd.DataFrame()
    out["tipo_movimento"] = df[c_tipo].astype(str) if c_tipo else ""
    out["num_documento"] = df[c_doc].astype(str) if c_doc else ""
    out["valor"] = pd.to_numeric(df[c_val], errors="coerce") if c_val else 0.0
    out["receita_despesa"] = df[c_rd].astype(str) if c_rd else ""
    out["data"] = df[c_dt].map(_to_data) if c_dt else pd.NaT
    out["historico"] = df[c_hist].astype(str) if c_hist else ""
    out["num_unico"] = df[c_uni].astype(str) if c_uni else ""
    out["numero"] = pd.to_numeric(df[c_num], errors="coerce") if c_num else pd.NA
    # v5.13: numeração como texto (aceita alfanumérico, ex.: "686a") — não perde
    # linhas já numeradas com letra. '' = em aberto.
    out["numero_txt"] = df[c_num].map(_fmt_numero_txt) if c_num else ""

    out = out.dropna(subset=["valor"]).reset_index(drop=True)
    out["identidade"] = out["historico"].map(extrair_identidade)
    out["lado"] = out["receita_despesa"].map(_lado)
    return out


# ---------------------------------------------------------------------------
# Motor de casamento / numeração
# ---------------------------------------------------------------------------
@dataclass
class ResultadoCasamento:
    detalhado: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def kpis(self) -> dict[str, Any]:
        d = self.detalhado
        if d.empty:
            return {"ja_numerado": 0, "numerado_agora": 0, "a_conferir": 0, "grupos_novos": 0}
        return {
            "ja_numerado": int((d["situacao"] == "Já numerado").sum()),
            "numerado_agora": int((d["situacao"] == "Numerado agora").sum()),
            "a_conferir": int((d["situacao"] == "A conferir").sum()),
            "grupos_novos": int(
                d.loc[d["situacao"] == "Numerado agora", "numero_proposto"].nunique()
            ),
        }


@dataclass
class ResultadoAtrelamento:
    detalhado: pd.DataFrame = field(default_factory=pd.DataFrame)
    proximo_numero: int = 0

    @property
    def kpis(self) -> dict[str, Any]:
        d = self.detalhado
        if d.empty:
            return {k: 0 for k in ("ja_identificado", "herdado", "numerado_agora", "aguardando_baixa", "a_conferir", "total")}
        s = d["situacao"]
        return {
            "ja_identificado": int((s == "Já identificado").sum()),
            "herdado": int((s == "Herdado da baixa").sum()),
            "numerado_agora": int((s == "Numerado agora").sum()),
            "aguardando_baixa": int((s == "Aguardando baixa").sum()),
            "a_conferir": int((s == "A conferir").sum()),
            "total": int(len(d)),
        }


def _cdoc(v: Any) -> str:
    s = re.sub(r"\.0$", "", str(v).strip())
    return s if s.lower() not in ("", "nan", "none") else ""


def atrelar(sankhya: pd.DataFrame, capa: pd.DataFrame, ultimo_numero: int | None = None, tol: float = 0.01) -> ResultadoAtrelamento:
    """Atrela o movimento do Sankhya à numeração que já existe na Capa e propõe
    número pros casamentos novos. Nunca chuta.

      A) Baixa atrela pelo Núm. Documento da Capa  -> "Já identificado".
      B) Entrada herda o número da sua baixa (mesma identidade + valor fecha)
         -> "Herdado da baixa".
      C) Entrada + baixa ambos sem número que fecham -> "Numerado agora" (próximo nº).
      D) Entrada parada sem baixa -> "Aguardando baixa".
      E) Resto duvidoso -> "A conferir".
    """
    sk = sankhya.copy().reset_index(drop=True)
    sk = sk.dropna(subset=["valor"])
    sk = sk[sk["valor"].abs() > tol].reset_index(drop=True)
    sk["doc"] = sk["num_documento"].map(_cdoc)

    # v5.13: reconhece numeração ALFANUMÉRICA (ex.: "686a") como já numerada,
    # para não re-numerar uma linha que já tem número na Capa.
    if "numero_txt" in capa.columns:
        _numtxt = capa["numero_txt"].astype(str).str.strip().replace({"nan": "", "None": ""})
        capa_ok = capa[_numtxt.str.len() > 0].copy()
        capa_ok["doc"] = capa_ok["num_documento"].map(_cdoc)
        capa_ok["_num_lbl"] = capa_ok["numero_txt"].map(_fmt_numero_txt)
    else:
        capa_ok = capa[capa["numero"].notna()].copy()
        capa_ok["doc"] = capa_ok["num_documento"].map(_cdoc)
        capa_ok["_num_lbl"] = capa_ok["numero"].map(lambda n: int(n))
    doc2num: dict[str, Any] = {}
    for d, n in zip(capa_ok["doc"], capa_ok["_num_lbl"]):
        if d and d not in doc2num:
            doc2num[d] = n

    sk["numero_final"] = pd.NA
    sk["situacao"] = ""
    sk["motivo"] = ""

    # A) v5.71 (revisto pós-produção, 2ª iteração): casa cada linha do Sankhya
    # contra a Capa por chave curta (data + |valor| + R/D) + PREFIX MATCH no
    # histórico normalizado. Regra descoberta olhando dado real:
    #   • A Capa acrescenta o NOME DO PARCEIRO no fim do histórico da ConcB.
    #     Exemplo real:
    #        ConcB: "DEP IDENT- 46647633000197 - SANTANDER - 07/05/2024" -
    #        Capa : "DEP IDENT- 46647633000197 - SANTANDER - 07/05/2024" - CONSORCIO RIO IMAGEM II BAIXADA
    #   • Meu match exato antigo não pegava isso (histórico "diferente"),
    #     então dezenas de receitas já numeradas caíam na esteira falsamente.
    #   • Prefix match é SEGURO: se um começa com o outro, é a mesma linha
    #     (não é fuzzy arbitrário). Alinhado com "zero falso positivo".
    #
    # Ordem: NUMERADAS primeiro (marca "Já identificado"). SEM número NÃO
    # decide aqui — deixa pro Bloco C parear entrada↔baixa e numerar.
    from collections import Counter as _Counter, defaultdict as _defaultdict

    def _chave_curta(row):
        """Chave curta (data + |valor| + R/D) — sem histórico."""
        dt = pd.to_datetime(row.get("data"), errors="coerce")
        dt = dt.date() if pd.notna(dt) else None
        try:
            v = int(round(abs(float(row.get("valor", 0))) * 100))
        except Exception:
            v = 0
        rd = str(row.get("receita_despesa", "")).strip()
        return (dt, v, rd)

    def _bate_hist(h_sk: str, h_ca: str) -> bool:
        """True se históricos normalizados são iguais OU um é prefixo do outro."""
        if not h_sk or not h_ca:
            return False
        if h_sk == h_ca:
            return True
        # Prefix (aceita "quase igual" com sufixo diferente, como nome do parceiro)
        m = min(len(h_sk), len(h_ca))
        if m >= 20:  # exige pelo menos 20 chars em comum para ser conservador
            if h_ca.startswith(h_sk) or h_sk.startswith(h_ca):
                return True
        return False

    # Índice das linhas NUMERADAS da Capa por chave curta
    # valor: lista de tuples (hist_norm, num, idx_original_capa)
    slots_numerados: dict = _defaultdict(list)
    if not capa_ok.empty:
        for i_capa, r_capa in capa_ok.iterrows():
            k = _chave_curta(r_capa)
            h_norm = _norm_hist_esteira(r_capa.get("historico", ""))
            slots_numerados[k].append([h_norm, r_capa["_num_lbl"], i_capa])

    # Índice das linhas SEM número da Capa (só como INFO para o motivo)
    if "numero_txt" in capa.columns:
        _numtxt_all = capa["numero_txt"].astype(str).str.strip().replace({"nan": "", "None": ""})
        capa_sem = capa[_numtxt_all.str.len() == 0].copy()
    else:
        capa_sem = capa[capa["numero"].isna()].copy()
    slots_sem_num_info: _Counter = _Counter()
    if not capa_sem.empty:
        for _, r_capa in capa_sem.iterrows():
            slots_sem_num_info[_chave_curta(r_capa)] += 1

    # Casa cada linha do Sankhya
    for idx in sk.index:
        k = _chave_curta(sk.loc[idx])
        h_sk = _norm_hist_esteira(sk.at[idx, "historico"])
        candidatos = slots_numerados.get(k, [])
        pos_match = None
        # 1ª passada: match EXATO
        for pos, (h_ca, _n, _i) in enumerate(candidatos):
            if h_ca == h_sk:
                pos_match = pos
                break
        # 2ª passada: PREFIX (só se não achou exato)
        if pos_match is None:
            for pos, (h_ca, _n, _i) in enumerate(candidatos):
                if _bate_hist(h_sk, h_ca):
                    pos_match = pos
                    break

        if pos_match is not None:
            _hist, num, _i_capa = candidatos.pop(pos_match)
            sk.at[idx, "numero_final"] = num
            sk.at[idx, "situacao"] = "Já identificado"
            sk.at[idx, "motivo"] = (
                "Bate com linha numerada da Capa (data+valor+R/D+histórico)"
            )
        elif slots_sem_num_info.get(k, 0) > 0:
            # Bate por chave curta com sem-número da Capa — marca info mas
            # NÃO decide situação, para o Bloco C tentar parear e numerar.
            slots_sem_num_info[k] -= 1
            sk.at[idx, "_capa_sem_num"] = True

    # B) entrada herda o número da baixa (mesma identidade + valor fecha)
    atr = sk[sk["numero_final"].notna()]
    for idx in sk[(sk["numero_final"].isna()) & (sk["lado"] == "entrada")].index:
        ent = sk.loc[idx]
        cand = atr[atr["identidade"] == ent["identidade"]]
        if cand.empty:
            continue
        somas = cand.groupby("numero_final")["valor"].apply(lambda s: s.abs().sum())
        casa = somas[(somas - abs(ent["valor"])).abs() <= tol]
        if len(casa) == 1:
            sk.at[idx, "numero_final"] = casa.index[0]
            sk.at[idx, "situacao"] = "Herdado da baixa"
            sk.at[idx, "motivo"] = "Entrada pegou o número da baixa (identidade + valor fecha)"
        elif len(casa) > 1:
            sk.at[idx, "situacao"] = "A conferir"
            sk.at[idx, "motivo"] = "Mais de um grupo possível pra mesma identidade"

    # C) casamento totalmente novo (entrada + baixa sem número que fecham) dentro do Sankhya
    if ultimo_numero is None:
        _m = pd.to_numeric(capa["numero"], errors="coerce").max()
        ultimo_numero = int(_m) if pd.notna(_m) else 0
    prox = int(ultimo_numero) + 1
    sem = sk[(sk["numero_final"].isna()) & (sk["situacao"] == "")]
    for idv, g in sem.groupby("identidade"):
        if idv == "SEM-ID":
            continue
        ent = g[g["lado"] == "entrada"]
        bx = g[g["lado"] == "baixa"]
        if ent.empty or bx.empty:
            continue
        # emparelha CADA entrada com uma baixa DO MESMO VALOR (mesma operação).
        # Um número por PAR — nunca junta valores diferentes só por serem do mesmo CNPJ.
        bx_disp = list(bx.index)
        for ei in ent.index:
            ev = abs(float(sk.at[ei, "valor"]))
            match = None
            for bi in bx_disp:
                if abs(abs(float(sk.at[bi, "valor"])) - ev) <= tol:
                    match = bi
                    break
            if match is not None:
                sk.loc[[ei, match], "numero_final"] = prox
                sk.loc[[ei, match], "situacao"] = "Numerado agora"
                sk.loc[[ei, match], "motivo"] = "Casamento novo (entrada + baixa de mesmo valor)"
                prox += 1
                bx_disp.remove(match)

    # D/E) resto — linhas do Sankhya que não foram identificadas (bloco A),
    # não herdaram (bloco B) e não pariam (bloco C).
    #
    # v5.71: aplica corte histórico. Linhas anteriores a DATA_CORTE_ESTEIRA
    # (01/02/2024) que NÃO estão em nenhuma linha da Capa são resíduo da Capa
    # velha (incompleta antes desse marco) — não vão pra esteira. Ficam
    # marcadas como "Órfão histórico" para auditoria; o app.py filtra por
    # {"Aguardando baixa", "A conferir"} antes da esteira, então naturalmente
    # não aparecem.
    for idx in sk[sk["situacao"] == ""].index:
        _dt = pd.to_datetime(sk.at[idx, "data"], errors="coerce")
        _antigo = pd.notna(_dt) and _dt < DATA_CORTE_ESTEIRA
        _na_capa_sem_num = bool(sk.at[idx, "_capa_sem_num"]) if "_capa_sem_num" in sk.columns else False

        if _antigo and not _na_capa_sem_num:
            sk.at[idx, "situacao"] = "Órfão histórico"
            sk.at[idx, "motivo"] = (
                f"Anterior a {DATA_CORTE_ESTEIRA.strftime('%d/%m/%Y')} e ausente da Capa — fora do escopo"
            )
        elif sk.at[idx, "lado"] == "entrada":
            sk.at[idx, "situacao"] = "Aguardando baixa"
            if _na_capa_sem_num:
                sk.at[idx, "motivo"] = "Está na Capa sem número — falta a baixa correspondente pra numerar"
            else:
                sk.at[idx, "motivo"] = "Não está na Capa (nova entrada — falta numerar)"
        else:
            sk.at[idx, "situacao"] = "A conferir"
            if _na_capa_sem_num:
                sk.at[idx, "motivo"] = "Está na Capa sem número — falta a entrada correspondente pra numerar"
            else:
                sk.at[idx, "motivo"] = "Não está na Capa (baixa sem par identificado)"

    # Limpa coluna auxiliar antes de retornar
    if "_capa_sem_num" in sk.columns:
        sk = sk.drop(columns=["_capa_sem_num"])

    return ResultadoAtrelamento(detalhado=sk, proximo_numero=prox)


def casar_e_numerar(mov: pd.DataFrame, ultimo_numero: int = 0, tol: float = 0.01) -> ResultadoCasamento:
    """Forma casamentos entrada↔baixa nas linhas SEM número e propõe numeração.

    Confiança (numera automaticamente) SÓ quando, para uma mesma identidade:
      - existe exatamente 1 entrada (ou várias que somam) e 1+ baixas, e
      - a soma das baixas fecha com a soma das entradas (tolerância `tol`).
    Isso usa o valor apenas como CONFIRMAÇÃO do grupo formado pela identidade.
    Qualquer outra situação (identidade com vários pares possíveis, sem par,
    ou que não fecha) vira "A conferir" — nunca chuta.
    """
    d = mov.copy()
    d["situacao"] = ""
    d["numero_proposto"] = pd.NA
    d["motivo"] = ""

    tem_num = d["numero"].notna()
    d.loc[tem_num, "situacao"] = "Já numerado"
    d.loc[tem_num, "numero_proposto"] = d.loc[tem_num, "numero"]

    prox = int(ultimo_numero) + 1
    sem = d[~tem_num]
    for idv, g in sem.groupby("identidade"):
        idxs = g.index
        if idv in ("SEM-ID",):
            d.loc[idxs, "situacao"] = "A conferir"
            d.loc[idxs, "motivo"] = "Sem identidade clara no histórico"
            continue
        ent = g[g["lado"] == "entrada"]
        bx = g[g["lado"] == "baixa"]
        soma_ent = float(ent["valor"].abs().sum())
        soma_bx = float(bx["valor"].abs().sum())
        fecha = abs(soma_ent - soma_bx) <= tol
        # Confiante: tem os dois lados e o valor confirma o fechamento do grupo.
        if len(ent) >= 1 and len(bx) >= 1 and fecha:
            d.loc[idxs, "situacao"] = "Numerado agora"
            d.loc[idxs, "numero_proposto"] = prox
            d.loc[idxs, "motivo"] = "Casou por identidade e o valor fechou"
            prox += 1
        else:
            d.loc[idxs, "situacao"] = "A conferir"
            if len(ent) == 0:
                d.loc[idxs, "motivo"] = "Baixa sem entrada correspondente na base"
            elif len(bx) == 0:
                d.loc[idxs, "motivo"] = "Entrada ainda sem baixa (parada na conta)"
            else:
                d.loc[idxs, "motivo"] = "Vários lançamentos na mesma identidade que não fecham"
    return ResultadoCasamento(detalhado=d)


# ---------------------------------------------------------------------------
# Diagnóstico da esteira (camada atual: só Sankhya + Capa)
# ---------------------------------------------------------------------------
def _tipo_hist(h):
    u = str(h).upper()
    if "CARTORIO" in u or "CARTÓRIO" in u or "NITEROI" in u:
        return "Cartório"
    if "SISPAG" in u:
        return "SISPAG"
    if "TED" in u:
        return "TED"
    if "PIX" in u:
        return "PIX"
    return "Outro"


def _banco_hist(h):
    u = str(h).upper()
    for b in ["SANTANDER", "BRADESCO", "SICREDI", "CAIXA", "ITAU", "ITAÚ"]:
        if b in u:
            return b.title().replace("Itau", "Itaú")
    return "—"


def diagnosticar(pend: pd.DataFrame, hoje=None) -> pd.DataFrame:
    """Recebe os pendentes (situacao Aguardando baixa / A conferir) e devolve,
    para cada linha: dias parados, banco, tipo, status, diagnóstico, ação e
    prioridade. Camada atual — usa só o que já temos (Sankhya + Capa)."""
    d = pend.copy()
    hoje = pd.Timestamp(hoje) if hoje is not None else pd.Timestamp.today().normalize()
    if d.empty:
        # esteira vazia: devolve as colunas esperadas (vazias), sem apply/concat
        # (que num DataFrame vazio duplicaria colunas e quebraria os filtros)
        for _c in ["dias", "banco", "tipo", "status_esteira", "diagnostico", "acao", "prioridade"]:
            if _c not in d.columns:
                d[_c] = pd.Series(dtype="object")
        return d
    dts = pd.to_datetime(d["data"], errors="coerce")
    d["dias"] = (hoje - dts).dt.days
    d["banco"] = d["historico"].map(_banco_hist)
    d["tipo"] = d["historico"].map(_tipo_hist)

    def _diag(r):
        u = str(r["historico"]).upper()
        dias = r["dias"]
        idt = str(r["identidade"])
        motivo = str(r.get("motivo", ""))
        sit = str(r.get("situacao", ""))

        # v5.71 (revisto): usa o motivo real do atrelar para gerar um
        # diagnóstico específico, em vez do texto genérico "Vários candidatos"
        # que era aplicado sem distinção a toda linha com situacao "A conferir".
        if "Mais de um grupo possível" in motivo:
            return ("Vários candidatos", "Vários candidatos — escolher", "Escolher o título certo", "Média")
        if "Está na Capa sem número — falta a baixa" in motivo:
            return ("Aguardando baixa no Sankhya", "Já está na Capa sem número — falta a baixa correspondente aparecer", "Ver se a baixa foi lançada", "Alta")
        if "Está na Capa sem número — falta a entrada" in motivo:
            return ("Aguardando entrada no Sankhya", "Já está na Capa sem número — falta a entrada correspondente aparecer", "Ver se a entrada foi lançada", "Alta")
        if "Não está na Capa (nova entrada" in motivo:
            return ("Nova entrada — sem par", "Entrada não está na Capa e sem baixa correspondente", "Verificar se falta lançar no Sankhya", "Média")
        if "Não está na Capa (baixa sem par" in motivo:
            return ("Baixa sem par no Sankhya", "Baixa sem par identificado — não está na Capa", "Verificar comprovante/nota", "Média")

        # Fallbacks antigos (mantidos por compatibilidade com outras origens)
        if sit == "A conferir":
            return ("Precisa de conferência", "Vários candidatos — escolher", "Escolher o título certo", "Média")
        if "CARTORIO" in u or "CARTÓRIO" in u or "NITEROI" in u or "SISPAG" in u:
            return ("Pode ser cartório", "Pode ser cartório", "Verificar cartório", "Alta")
        if idt.startswith("SEM-ID"):
            return ("Sem CNPJ/CPF no histórico", "Sem CNPJ/CPF no histórico", "Pedir comprovante ao banco", "Média")
        if pd.notna(dias) and dias > 15:
            return ("Parado há mais de 15 dias", "Parado há mais de 15 dias", "Parado há muito tempo — revisar", "Alta")
        if pd.notna(dias) and dias > 7:
            return ("Parado há mais de 7 dias", "Parado há mais de 7 dias", "Revisar", "Alta")
        return ("Recebido, falta identificar", "Recebido, falta identificar", "Procurar a nota/título", "Baixa")

    diag = d.apply(lambda r: pd.Series(_diag(r), index=["status_esteira", "diagnostico", "acao", "prioridade"]), axis=1)
    return pd.concat([d, diag], axis=1)


# ---------------------------------------------------------------------------
# Faturamento (notas emitidas não baixadas) e sugestão por CNPJ
# ---------------------------------------------------------------------------
def carregar_faturamento(arquivo) -> pd.DataFrame:
    """Lê a planilha de notas emitidas (faturamento). Detecta o cabeçalho,
    extrai CNPJ/CPF, nota, nome e valor. Somente leitura."""
    hdr = 0
    try:
        bruto = _ler_planilha(arquivo, header=None)
        for i in range(min(6, len(bruto))):
            linha = " ".join(str(x) for x in bruto.iloc[i].tolist()).lower()
            if "nro nota" in linha or "nome parceiro" in linha or "cnpj" in linha:
                hdr = i
                break
    except Exception:
        hdr = 0
    if hasattr(arquivo, "seek"):
        try:
            arquivo.seek(0)
        except Exception:
            pass
    df = _ler_planilha(arquivo, header=hdr)
    df.columns = [str(c).strip() for c in df.columns]

    def col(*nomes):
        for n in nomes:
            for c in df.columns:
                if c.lower() == n.lower():
                    return c
        return None

    c_cnpj = col("CNPJ / CPF", "CNPJ/CPF", "CNPJ", "CPF/CNPJ")
    c_nota = col("Nro Nota", "Nº Nota", "Numero Nota", "Nro. Nota")
    c_nome = col("Nome Parceiro (Parceiro)", "Nome Parceiro", "Parceiro")
    c_val = col("Valor Líquido", "Vlr do Desdobramento", "Vlr Desdobramento", "Valor")
    c_cod = col("Parceiro", "Código Parceiro", "Cod Parceiro")

    def _limpar_doc(v):
        s = re.sub(r"\.0+$", "", str(v).strip())   # remove ".0" de número lido como float
        return re.sub(r"\D", "", s)

    out = pd.DataFrame()
    out["cnpj"] = df[c_cnpj].map(_limpar_doc) if c_cnpj else ""
    out["nota"] = df[c_nota].astype(str).str.replace(r"\.0$", "", regex=True) if c_nota else ""
    out["nome"] = df[c_nome].astype(str) if c_nome else ""
    out["valor"] = pd.to_numeric(df[c_val], errors="coerce") if c_val else pd.NA
    out["cod_parceiro"] = df[c_cod].astype(str).str.replace(r"\.0$", "", regex=True) if c_cod else ""
    if c_nota:
        out = out[df[c_nota].notna()].reset_index(drop=True)
    out["cnpj"] = out["cnpj"].map(lambda d: d if d not in ("", "0", "nan") else "")
    return out


def sugerir_atrelamentos_cnpj(entradas_abertas: pd.DataFrame, faturamento: pd.DataFrame, tol: float = 0.01) -> pd.DataFrame:
    """Cruza as entradas abertas (com CNPJ/CPF no histórico) contra o faturamento
    pelo CNPJ. Valor é conferência (mostra se fecha), não regra. Nunca chuta."""
    e = entradas_abertas.copy()
    e["cnpj"] = e["identidade"].map(lambda i: re.sub(r"\D", "", str(i).split(":")[-1]) if ":" in str(i) else "")
    fat = faturamento[faturamento["cnpj"] != ""]
    linhas = []
    for _, r in e[e["cnpj"] != ""].iterrows():
        cand = fat[fat["cnpj"] == r["cnpj"]]
        if cand.empty:
            continue
        alvo = abs(r["valor"])
        fecha = cand[(pd.to_numeric(cand["valor"], errors="coerce") - alvo).abs() <= tol]
        nota = fecha.iloc[0] if not fecha.empty else cand.iloc[0]
        linhas.append({
            "idx": r.name,
            "cnpj": r["cnpj"], "nome": nota.get("nome", ""), "nota": nota.get("nota", ""),
            "receita_despesa": r.get("receita_despesa", ""),
            "valor_recebido": alvo, "valor_nota": pd.to_numeric(nota.get("valor"), errors="coerce"),
            "valor_fecha": (not fecha.empty), "historico": r["historico"],
            "n_candidatos": len(cand),
        })
    return pd.DataFrame(linhas)


def gerar_capa_acumulada(capa_arquivo, detalhado, ultimo_numero: int, confirmados=None, acoes=None):
    """Devolve a Capa COMPLETA (todas as linhas e colunas originais, com o sinal
    original — despesa negativa) e preenche a numeração SÓ nas linhas que o app
    identificou este período, quando há match único. Nunca sobrescreve número
    existente e nunca chuta (match ambíguo fica em branco).

    `acoes` = {numero: texto} escreve, na coluna I ("O que fazer no Sankhya"),
    a instrução de baixa para cada linha numerada.

    Retorna (df_capa_completa, n_preenchidos, n_novos_total).
    """
    confirmados = confirmados or {}
    acoes = acoes or {}
    hdr = _detectar_header(capa_arquivo)
    if hasattr(capa_arquivo, "seek"):
        try:
            capa_arquivo.seek(0)
        except Exception:
            pass
    raw = _ler_planilha(capa_arquivo, header=hdr)
    raw.columns = [str(c).strip() for c in raw.columns]
    cols_orig = list(raw.columns)

    def col(*nomes):
        for n in nomes:
            for c in raw.columns:
                if c.lower() == n.lower():
                    return c
        return None

    c_doc = col("Núm. Documento", "Num. Documento")
    c_val = col("Vlr. Lançamento", "Valor", "Vlr Lancamento")
    c_dt = col("Dt. Lançamento", "Data")
    c_hist = col("Histórico", "Historico")
    c_tipo = col("Tipo de Movimento", "Tipo Movimento", "Tipo")
    c_conc = col("Conciliado")
    c_rd = col("Receita/Despesa", "Receita / Despesa", "Receita Despesa")

    _sankhya_pos = {
        "dt. conciliação", "dt. conciliacao", "núm. único bancário",
        "num. unico bancario", "pré-data", "pre-data", "usuário", "usuario",
        "dt. alteração", "dt. alteracao", "vlr. troco", "vlr. cheque", "conciliado",
    }
    c_num = None
    if c_hist is not None:
        depois = cols_orig[cols_orig.index(c_hist) + 1:]
        for c in depois:
            hl = c.strip().lower()
            if hl in _sankhya_pos:
                continue
            if pd.to_numeric(raw[c], errors="coerce").notna().sum() > 0 and (
                hl in ("x", "nan", "") or hl.startswith("unnamed")
            ):
                c_num = c
                break
    if c_num is None:
        c_num = "Número"
        raw[c_num] = pd.NA
        cols_orig = cols_orig + [c_num]

    # coluna I — instrução de baixa (o que fazer no Sankhya)
    c_acao = "O que fazer no Sankhya"
    if c_acao not in raw.columns:
        raw[c_acao] = ""
        cols_orig = cols_orig + [c_acao]

    raw["_v"] = pd.to_numeric(raw[c_val], errors="coerce").abs().round(2) if c_val else 0.0
    raw["_d"] = raw[c_dt].map(_to_data) if c_dt else pd.NaT
    raw["_cur"] = pd.to_numeric(raw[c_num], errors="coerce")

    d = detalhado
    novos = d[pd.to_numeric(d["numero_final"], errors="coerce") > ultimo_numero]
    preenchidos = 0
    acrescentados = 0
    novas_linhas = []
    _rd_col = raw[c_rd].astype(str).str.upper() if c_rd else None
    for _, r in novos.iterrows():
        num = r["numero_final"]
        doc = str(r.get("num_documento", "")).strip()
        v = round(abs(float(r["valor"])), 2)
        dt = r.get("data")
        rd = str(r.get("receita_despesa", "")).upper()
        eh_desp = "DESPESA" in rd
        # só o mesmo lado (não mistura receita com despesa de mesmo valor)
        if _rd_col is not None:
            side = _rd_col.str.contains("DESPESA" if eh_desp else "RECEITA", na=False)
        else:
            side = pd.Series(True, index=raw.index)
        if doc and doc.lower() not in ("", "nan"):
            existe = raw[side & (raw[c_doc].astype(str) == doc) & (raw["_v"] == v)]
        else:
            existe = raw[side & (raw["_v"] == v) & (raw["_d"] == dt)]
        cand = existe[existe["_cur"].isna()]  # candidatos ainda sem número
        if len(cand) == 1:
            i0 = cand.index[0]
            raw.loc[i0, c_num] = num
            raw.loc[i0, "_cur"] = num
            try:
                raw.loc[i0, c_acao] = str(acoes.get(int(num), ""))
            except Exception:
                pass
            preenchidos += 1
        elif len(existe) == 0:
            # o lado não existe na Capa -> acrescenta (com o mesmo número)
            nova = {c: pd.NA for c in cols_orig}
            if c_tipo:
                nova[c_tipo] = r.get("tipo_movimento", "")
            if c_doc:
                nova[c_doc] = r.get("num_documento", "")
            if c_val:
                nova[c_val] = -v if eh_desp else v
            if c_conc:
                nova[c_conc] = "Sim"
            if c_rd:
                nova[c_rd] = r.get("receita_despesa", "")
            if c_dt:
                nova[c_dt] = r.get("data")
            if c_hist:
                nova[c_hist] = r.get("historico", "")
            nova[c_num] = num
            try:
                nova[c_acao] = str(acoes.get(int(num), ""))
            except Exception:
                nova[c_acao] = ""
            novas_linhas.append(nova)
            acrescentados += 1
        # len(existe) > 0 mas nenhum candidato livre => já está na capa (numerado/ambíguo): não mexe

    if novas_linhas:
        raw = pd.concat([raw, pd.DataFrame(novas_linhas)], ignore_index=True)

    # v5.25 — Ponto 6 (Débora): status de baixa em TODOS os numerados que ainda
    # estão SEM instrução, com base nos lados do número:
    #   receita + despesa -> "Baixado no Sankhya"
    #   só receita        -> "Pendente de numerar despesa"
    #   só despesa        -> vazio
    # As instruções desta rodada (ex.: "Baixar NF X") NÃO são sobrescritas.
    if c_rd is not None:
        _num_all = pd.to_numeric(raw[c_num], errors="coerce")
        _rd_all = raw[c_rd].astype(str).str.upper()
        _tem_rec, _tem_desp = {}, {}
        for _nn, _rr in zip(_num_all, _rd_all):
            if pd.isna(_nn):
                continue
            _k = int(_nn)
            if "RECEITA" in _rr:
                _tem_rec[_k] = True
            if "DESPESA" in _rr:
                _tem_desp[_k] = True

        def _status6(nn):
            if pd.isna(nn):
                return None
            _k = int(nn)
            rec, desp = _tem_rec.get(_k, False), _tem_desp.get(_k, False)
            if rec and desp:
                return "Baixado no Sankhya"
            if rec and not desp:
                return "Pendente de numerar despesa"
            return ""  # só despesa -> vazio

        _ac_ser = raw[c_acao]
        if isinstance(_ac_ser, pd.DataFrame):
            _ac_ser = _ac_ser.iloc[:, 0]
        _ac_list = [("" if pd.isna(x) else str(x)).strip() for x in _ac_ser.tolist()]
        _num_list = _num_all.tolist()
        _new_ac = []
        for _pos in range(len(_ac_list)):
            _cur = _ac_list[_pos]
            # mantém só as instruções ACIONÁVEIS desta rodada; todo o resto
            # (vazio, "Baixa já lançada", status antigo) é recalculado pelos lados.
            if _cur.startswith("Baixar NF") or _cur.startswith("Atrelado manualmente"):
                _new_ac.append(_cur)
            else:
                _st6 = _status6(_num_list[_pos])
                _new_ac.append(_st6 if _st6 is not None else "")
        raw[c_acao] = _new_ac

    raw = raw.drop(columns=["_v", "_d", "_cur"], errors="ignore")
    return raw[cols_orig], preenchidos + acrescentados, len(novos)
