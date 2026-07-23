"""Orquestrador da conciliação — versão 3.

Mudanças sobre v2:
- "Total Movimentado no Banco" (renomeado de "Total Extrato Bancário") agora INCLUI
  aplicações e resgates. Só EXCLUI linhas de SALDO.
- Auditoria nova: detecta excesso de lançamentos no Sankhya em relação ao banco.
- Cards "Receitas Absolutas" e "Despesas Absolutas" foram removidos do dashboard.
- Cards de "Aplicações" e "Resgates" foram unificados em um único card "Investimentos".

v5.71 — CORREÇÃO ESTRUTURAL de colisão inocente:
- Regras de agrupamento (TOP 1722, TOP 1702, Folha, Salários N→M, Depósitos
  Abertos) agora rodam ANTES do match_exato — sobre banco_mov / sistema_mov
  diretamente. Antes disso, o match_exato 1-pra-1 podia "roubar" uma linha
  componente de um grupo por coincidência de data+valor com uma despesa avulsa
  do Sankhya (ex.: 141 SISPAG SALARIOS + 1 avulso PEDRO HENRIQUE com mesmo
  valor de um SISPAG → grupo perdia um componente → soma não fechava → 141
  SISPAG viravam divergência falsa). Reservando as linhas do agrupamento
  primeiro, o match_exato só vê o que sobrou e não há colisão.
- Tarifas Repetidas continua depois do match_exato (rede de segurança).
- Estornos, AUT MAIS, Tarifas Adquirente ficam onde estavam.
- Nenhuma regra individual foi tocada — só a ORDEM de execução no pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from .matching import (
    detectar_divergencia_valor,
    detectar_duplicidades,
    detectar_possiveis_duplicidades,
    detectar_nao_pertence,
    detectar_excesso_sankhya,
    detectar_excesso_sankhya_pos_match,
    match_exato,
    sugerir_matches_fuzzy,
)
from .classificacao import (
    adicionar_classificacao,
    adicionar_categoria_movimento,
)


@dataclass
class ResultadoConciliacao:
    """Container com todos os DataFrames e metadados da conciliação."""

    conciliados: pd.DataFrame
    pendentes_banco: pd.DataFrame
    pendentes_sistema: pd.DataFrame
    divergencias: pd.DataFrame
    duplicidades: pd.DataFrame
    possiveis_duplicidades: pd.DataFrame
    excesso_sankhya: pd.DataFrame  # v3: lançamentos a mais no Sankhya
    nao_pertence: pd.DataFrame
    sugestoes_fuzzy: pd.DataFrame
    aplicacoes_resgates: pd.DataFrame
    falta_lancar_sankhya: pd.DataFrame  # quando Sankhya tem Conciliado=Não preenchido
    # v5.0: estornos detectados no banco
    estornos_anulados: pd.DataFrame = field(default_factory=pd.DataFrame)
    estornos_parciais: pd.DataFrame = field(default_factory=pd.DataFrame)
    # v5.0: TOP 1722 (agrupamento cartão de crédito)
    top1722_grupos: pd.DataFrame = field(default_factory=pd.DataFrame)
    top1722_linhas: pd.DataFrame = field(default_factory=pd.DataFrame)
    top1722_linhas_banco: pd.DataFrame = field(default_factory=pd.DataFrame)
    top1722_diferencas: pd.DataFrame = field(default_factory=pd.DataFrame)
    # v5.35: TOP 1702 (agrupamento boleto) — irmão do 1722
    top1702_grupos: pd.DataFrame = field(default_factory=pd.DataFrame)
    top1702_linhas: pd.DataFrame = field(default_factory=pd.DataFrame)
    top1702_linhas_banco: pd.DataFrame = field(default_factory=pd.DataFrame)
    top1702_diferencas: pd.DataFrame = field(default_factory=pd.DataFrame)

    banco_completo: pd.DataFrame = field(default_factory=pd.DataFrame)
    sistema_completo: pd.DataFrame = field(default_factory=pd.DataFrame)

    data_referencia: datetime = None
    contas_processadas: list[str] = field(default_factory=list)
    tolerancia_dias: int = 2
    usa_conciliado_sankhya: bool = False

    def kpis_globais(self) -> dict[str, Any]:
        # v5.1: getattr defensivo — objetos em session_state de versões antigas
        # podem não ter os campos novos (estornos_*, top1722_*).
        return _calcular_kpis(
            self.conciliados,
            self.pendentes_banco,
            self.pendentes_sistema,
            self.divergencias,
            self.banco_completo,
            self.sistema_completo,
            self.falta_lancar_sankhya,
            self.usa_conciliado_sankhya,
            self.excesso_sankhya,
            getattr(self, "estornos_anulados", pd.DataFrame()),
            getattr(self, "estornos_parciais", pd.DataFrame()),
            getattr(self, "top1722_grupos", pd.DataFrame()),
            pd.concat(
                [getattr(self, "top1702_grupos", pd.DataFrame()),
                 getattr(self, "top1702_diferencas", pd.DataFrame())],
                ignore_index=True,
            ),
            pd.concat(
                [getattr(self, "top1722_linhas", pd.DataFrame()),
                 getattr(self, "top1702_linhas", pd.DataFrame())],
                ignore_index=True,
            ),
        )

    def kpis_por_banco(self) -> dict[str, dict[str, Any]]:
        return {conta: self.kpis_da_conta(conta) for conta in self.contas_processadas}

    def kpis_da_conta(self, conta: str) -> dict[str, Any]:
        # v5.1: getattr defensivo + filtro seguro pra campos opcionais
        def _filtra(attr_name: str) -> pd.DataFrame:
            df = getattr(self, attr_name, None)
            if df is None or df.empty or "conta" not in df.columns:
                return pd.DataFrame()
            return df[df["conta"] == conta]

        return _calcular_kpis(
            _filtrar_conciliados(self.conciliados, conta),
            _filtrar_conta(self.pendentes_banco, conta),
            _filtrar_conta(self.pendentes_sistema, conta),
            _filtrar_divergencias(self.divergencias, conta),
            _filtrar_conta(self.banco_completo, conta),
            _filtrar_conta(self.sistema_completo, conta),
            _filtrar_conta(self.falta_lancar_sankhya, conta) if self.usa_conciliado_sankhya else pd.DataFrame(),
            self.usa_conciliado_sankhya,
            _filtrar_conta(self.excesso_sankhya, conta),
            _filtra("estornos_anulados"),
            _filtra("estornos_parciais"),
            _filtra("top1722_grupos"),
            pd.concat(
                [_filtra("top1702_grupos"), _filtra("top1702_diferencas")],
                ignore_index=True,
            ),
            pd.concat(
                [_filtra("top1722_linhas"), _filtra("top1702_linhas")],
                ignore_index=True,
            ),
        )

    def divergencias_sankhya_banco(self, conta: str | None = None) -> pd.DataFrame:
        """v3.4: Visão consolidada de divergências entre Sankhya e Banco.

        Une 3 origens:
        - 'Sem par no banco': lançamentos do Sankhya com Conciliado=Não ou pendentes pós-match
        - 'Excesso no Sankhya': Sankhya tem N>M lançamentos com mesma data+valor+conta
        - 'Valor diferente': mesma chave (data+hist+conta), valor diferente

        Deduplica por (data, valor, hist, conta) — uma linha pode aparecer em vários grupos.
        """
        frames = []

        # 1) Sem par no banco — Fase 1 (v6.0): a fonte é SEMPRE o resultado do nosso
        # match (pendências do Sankhya pós-conciliação), NUNCA a flag 'Conciliado=Não'
        # do ERP. Quem decide a conciliação é o app, comparando banco × Sankhya; a
        # marcação do Sankhya é dado de entrada, não veredito. Isso remove a antiga
        # fonte circular (uma linha podia ser 'Conciliada' e 'Divergência' ao mesmo
        # tempo só porque o ERP a marcava como Conciliado=Não).
        df = _eh_movimentado(self.pendentes_sistema)
        if not df.empty:
            d = df[["data", "valor", "historico", "conta"]].copy()
            d["documento"] = df.get("documento", "")
            d["origem_divergencia"] = "Sem par no banco"
            d["origem"] = "Sankhya"
            frames.append(d)

        # 2) Excesso no Sankhya
        if not self.excesso_sankhya.empty:
            d = self.excesso_sankhya[["data", "valor", "historico", "conta"]].copy()
            d["documento"] = self.excesso_sankhya.get("documento", "")
            d["origem_divergencia"] = "Excesso no Sankhya"
            d["origem"] = "Sankhya"
            frames.append(d)

        # 3) Valor diferente
        if not self.divergencias.empty and "valor_sistema" in self.divergencias.columns:
            d = self.divergencias[["data", "valor_sistema", "historico_sistema"]].copy()
            d.columns = ["data", "valor", "historico"]
            d["conta"] = self.divergencias.get("conta", "")
            d["documento"] = self.divergencias.get("documento_sistema", "")
            d["origem_divergencia"] = "Valor diferente"
            d["origem"] = "Banco × Sankhya"
            frames.append(d)

        if not frames:
            return pd.DataFrame(columns=[
                "data", "valor", "historico", "documento", "conta", "origem_divergencia", "origem"
            ])
        out = pd.concat(frames, ignore_index=True)
        out = out.drop_duplicates(subset=["data", "valor", "historico", "conta"])
        out = out.reset_index(drop=True)

        if conta is not None:
            out = out[out["conta"] == conta].copy()
        return out

    def conciliados_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conciliados(self.conciliados, conta)

    def divergencias_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_divergencias(self.divergencias, conta)

    def nao_pertence_da_conta(self, conta: str) -> pd.DataFrame:
        if self.nao_pertence.empty:
            return self.nao_pertence
        return self.nao_pertence[self.nao_pertence["conta_atual"] == conta].copy()

    def aplicacoes_resgates_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conta(self.aplicacoes_resgates, conta)

    def possiveis_duplicidades_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conta(self.possiveis_duplicidades, conta)

    def excesso_sankhya_da_conta(self, conta: str) -> pd.DataFrame:
        return _filtrar_conta(self.excesso_sankhya, conta)

    def falta_lancar_da_conta(self, conta: str) -> pd.DataFrame:
        if self.usa_conciliado_sankhya:
            return _filtrar_conta(self.falta_lancar_sankhya, conta)
        return _filtrar_conta(self.pendentes_sistema, conta)

    def saldo_final_da_conta(self, conta: str, exigir_conciliado: bool = True) -> dict[str, Any] | None:
        """Retorna info de saldo final da conta.

        Por padrão só devolve quando a conta está 100% conciliada (card verde
        do detalhamento). v5.47: com `exigir_conciliado=False`, devolve sempre
        que o extrato tiver saldo — usado pelo Dashboard para mostrar o
        FECHAMENTO DO EXTRATO (saldo inicial + movimentos = saldo final), que é
        um teste de leitura do extrato e não depende da conciliação.
        """
        kpis = self.kpis_da_conta(conta)
        if exigir_conciliado and kpis["percentual_conciliado"] < 99.99:
            return None

        banco = _filtrar_conta(self.banco_completo, conta)
        if banco.empty or "categoria_mov" not in banco.columns:
            return None

        saldos = banco[banco["categoria_mov"] == "saldo"].copy()
        saldo_inicial = saldo_final = None
        if not saldos.empty:
            saldos_ord = saldos.sort_values("data")
            try:
                saldo_inicial = float(saldos_ord.iloc[0]["valor"])
                saldo_final = float(saldos_ord.iloc[-1]["valor"])
            except Exception:
                pass

        # v3: movimentação líquida considera TUDO que é movimentado (movimentacao+aplic+resgate)
        movimentado = banco[banco["categoria_mov"] != "saldo"]
        mov_liquida = float(movimentado["valor"].sum()) if not movimentado.empty else 0.0

        return {
            "conta": conta,
            "saldo_inicial": saldo_inicial,
            "saldo_final": saldo_final,
            "movimentacao_liquida": mov_liquida,
            "periodo_de": banco["data"].min() if not banco.empty else None,
            "periodo_ate": banco["data"].max() if not banco.empty else None,
            "tem_saldo_no_extrato": saldo_final is not None,
        }


# ===========================================================================
# Helpers
# ===========================================================================

def _filtrar_conta(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty or "conta" not in df.columns:
        return df
    return df[df["conta"] == conta].copy()


def _filtrar_conciliados(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty:
        return df
    if "banco_conta" in df.columns:
        return df[df["banco_conta"] == conta].copy()
    return df


def _filtrar_divergencias(df: pd.DataFrame, conta: str) -> pd.DataFrame:
    if df.empty:
        return df
    if "conta" in df.columns:
        return df[df["conta"] == conta].copy()
    return df


def _soma_abs(df: pd.DataFrame, col: str = "valor") -> float:
    if df.empty or col not in df.columns:
        return 0.0
    return float(df[col].abs().sum())


def _eh_movimentado(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra linhas que contam como movimentação financeira (v3).

    REGRA v3: inclui movimentação normal + aplicações + resgates + investimentos.
    SÓ exclui linhas de SALDO (saldo inicial/final/bloqueado/aplic auto etc).
    """
    if df.empty or "categoria_mov" not in df.columns:
        return df
    return df[df["categoria_mov"] != "saldo"]


def _remover_por_indices(df: pd.DataFrame, indices: set[int]) -> pd.DataFrame:
    """v5.71: helper para remover linhas por índice após reset_index e retornar
    o DataFrame já resetado. Usado pelas regras de agrupamento pré-match_exato.
    """
    if not indices:
        return df
    df = df.reset_index(drop=True)
    idx_validos = [i for i in indices if i < len(df)]
    if not idx_validos:
        return df
    return df.drop(index=idx_validos).reset_index(drop=True)


def _calcular_kpis(
    conciliados: pd.DataFrame,
    pendentes_banco: pd.DataFrame,
    pendentes_sistema: pd.DataFrame,
    divergencias: pd.DataFrame,
    banco_completo: pd.DataFrame,
    sistema_completo: pd.DataFrame,
    falta_lancar_sankhya: pd.DataFrame,
    usa_conciliado_sankhya: bool,
    excesso_sankhya: pd.DataFrame | None = None,
    estornos_anulados: pd.DataFrame | None = None,
    estornos_parciais: pd.DataFrame | None = None,
    top1722_grupos: pd.DataFrame | None = None,
    top1702_grupos: pd.DataFrame | None = None,
    linhas_casadas_grupos_sis: pd.DataFrame | None = None,
) -> dict[str, Any]:
    banco_mov = _eh_movimentado(banco_completo)
    sistema_mov = _eh_movimentado(sistema_completo)

    # v5.26: total movimentado NÃO deve incluir aplicação/resgate/rendimento AUT MAIS.
    # Aplicações AUT MAIS não são despesa real (dinheiro fica na empresa, só aplicado).
    # Resgates AUT MAIS não são receita real (mesmo dinheiro retorna pra conta).
    # Esses lançamentos têm seu próprio card "Investimentos" pra contabilizar.
    if "categoria_mov" in banco_mov.columns:
        banco_mov_real = banco_mov[
            ~banco_mov["categoria_mov"].isin(["aplicacao", "resgate", "rendimento"])
        ]
    else:
        banco_mov_real = banco_mov

    if "categoria_mov" in sistema_mov.columns:
        sistema_mov_real = sistema_mov[
            ~sistema_mov["categoria_mov"].isin(["aplicacao", "resgate", "rendimento"])
        ]
    else:
        sistema_mov_real = sistema_mov

    total_banco = _soma_abs(banco_mov_real)
    total_sistema = _soma_abs(sistema_mov_real)

    # Receitas e Despesas absolutas (também sem investimentos)
    if not banco_mov_real.empty:
        receitas_banco = float(banco_mov_real[banco_mov_real["valor"] > 0]["valor"].sum())
        despesas_banco = float(banco_mov_real[banco_mov_real["valor"] < 0]["valor"].abs().sum())
    else:
        receitas_banco = despesas_banco = 0.0

    if not sistema_mov_real.empty:
        receitas_sistema = float(sistema_mov_real[sistema_mov_real["valor"] > 0]["valor"].sum())
        despesas_sistema = float(sistema_mov_real[sistema_mov_real["valor"] < 0]["valor"].abs().sum())
    else:
        receitas_sistema = despesas_sistema = 0.0

    # Conciliados
    if conciliados.empty:
        total_conciliado = 0.0
        receitas_conciliadas = despesas_conciliadas = 0.0
        total_conciliado_mov = 0.0
        total_conciliado_invest = 0.0
    else:
        c = conciliados
        total_conciliado = float(c["banco_valor"].abs().sum())
        receitas_conciliadas = float(c[c["banco_valor"] > 0]["banco_valor"].sum())
        despesas_conciliadas = float(c[c["banco_valor"] < 0]["banco_valor"].abs().sum())
        # v5.49: separa os pares de MOVIMENTAÇÃO dos pares de investimento
        # (aplicação/resgate/rendimento). O % conciliado usava total_conciliado
        # (com investimentos) sobre total_banco (SEM investimentos) — base
        # mista que estourava acima de 100% (ex.: 165,5%) em conta com muita
        # aplicação automática e pouca movimentação.
        try:
            from src.classificacao.movimento import classificar_movimentacao as _cls_mov
            _cat_par = c["banco_historico"].fillna("").astype(str).apply(_cls_mov)
            _mask_mov_par = (_cat_par == "movimentacao").values
            total_conciliado_mov = float(c.loc[_mask_mov_par, "banco_valor"].abs().sum())
        except Exception:
            total_conciliado_mov = total_conciliado
        total_conciliado_invest = round(total_conciliado - total_conciliado_mov, 2)

    # Falta Conciliar (pendentes do banco, só movimentação)
    pb_mov = _eh_movimentado(pendentes_banco)
    falta_conciliar = _soma_abs(pb_mov)
    if not pb_mov.empty:
        falta_conciliar_receitas = float(pb_mov[pb_mov["valor"] > 0]["valor"].sum())
        falta_conciliar_despesas = float(pb_mov[pb_mov["valor"] < 0]["valor"].abs().sum())
    else:
        falta_conciliar_receitas = falta_conciliar_despesas = 0.0

    # v3.4: DIVERGÊNCIA (Sankhya × Banco) — consolida 3 origens:
    #   1. Sankhya com Conciliado=Não OU pendentes pós-match (Sankhya sem par no banco)
    #   2. Excesso no Sankhya (mesma data+valor+conta, Sankhya tem mais que o banco)
    #   3. Divergência de valor (mesma chave, valor diferente)
    # As 3 podem se sobrepor, então deduplicamos pelo conjunto (data, valor, hist, conta).

    # v3.11 BUGFIX: linhas do Sankhya com 'Conciliado=Não' que JÁ casaram no nosso
    # match não devem entrar em 'Sem par no banco'. Caso comum: lançamentos
    # contabilmente "não conciliados" no ERP mas que batem 1-pra-1 com o banco.
    chaves_casadas_sis = set()
    if not conciliados.empty:
        for _, row in conciliados.iterrows():
            d_v = row.get("sistema_data")
            v_v = row.get("sistema_valor")
            c_v = row.get("sistema_conta")
            h_v = row.get("sistema_historico", "")
            if d_v is not None and v_v is not None:
                chaves_casadas_sis.add(
                    (str(d_v), round(float(v_v), 2), str(c_v), str(h_v))
                )

    # v5.59: linhas do Sankhya casadas por AGRUPAMENTO (cartão 1722 / boleto
    # 1702 / tarifa comprovada pela adquirente) também contam como casadas —
    # sem isso, uma linha consumida pelo grupo mas com flag "não conciliada"
    # no ERP continuava inflando o KPI de divergência (caso real: tarifa −0,45).
    if linhas_casadas_grupos_sis is not None and not getattr(linhas_casadas_grupos_sis, "empty", True):
        for _, row in linhas_casadas_grupos_sis.iterrows():
            d_v, v_v = row.get("data"), row.get("valor")
            if d_v is not None and v_v is not None:
                chaves_casadas_sis.add(
                    (str(d_v), round(float(v_v), 2), str(row.get("conta", "")), str(row.get("historico", "")))
                )

    def _remover_casadas(df_sis: pd.DataFrame) -> pd.DataFrame:
        if df_sis.empty or not chaves_casadas_sis:
            return df_sis
        def _key(linha):
            return (
                str(linha.get("data")),
                round(float(linha.get("valor", 0)), 2),
                str(linha.get("conta", "")),
                str(linha.get("historico", "")),
            )
        return df_sis[~df_sis.apply(lambda r: _key(r) in chaves_casadas_sis, axis=1)]

    if usa_conciliado_sankhya and not falta_lancar_sankhya.empty:
        sem_par_banco = _remover_casadas(_eh_movimentado(falta_lancar_sankhya))
    else:
        sem_par_banco = _remover_casadas(_eh_movimentado(pendentes_sistema))

    # Junta com excesso e divergências de valor
    frames_diverg = []
    if not sem_par_banco.empty:
        d = sem_par_banco[["data", "valor", "historico", "conta"]].copy()
        d["origem_divergencia"] = "Sem par no banco"
        frames_diverg.append(d)
    if excesso_sankhya is not None and not excesso_sankhya.empty:
        d = excesso_sankhya[["data", "valor", "historico", "conta"]].copy()
        d["origem_divergencia"] = "Excesso no Sankhya"
        frames_diverg.append(d)
    if not divergencias.empty and "valor_sistema" in divergencias.columns:
        d = divergencias[["data", "valor_sistema", "historico_sistema"]].copy()
        d.columns = ["data", "valor", "historico"]
        d["conta"] = divergencias.get("conta", "")
        d["origem_divergencia"] = "Valor diferente"
        frames_diverg.append(d)

    if frames_diverg:
        divergencia_total_df = pd.concat(frames_diverg, ignore_index=True)
        # Dedup por (data, valor, hist, conta) — uma linha pode estar em 2 grupos
        divergencia_total_df = divergencia_total_df.drop_duplicates(
            subset=["data", "valor", "historico", "conta"]
        )
    else:
        divergencia_total_df = pd.DataFrame(
            columns=["data", "valor", "historico", "conta", "origem_divergencia"]
        )

    # v5.38: LÍQUIDO e depois MÓDULO. Soma com sinal (pra +13,06 e −9,33 anularem
    # → 3,73, em vez de 22,39 do absoluto), e tira o módulo pra exibir positivo
    # (Santander, despesa única −160,59 → 160,59). A contagem (qtd) preserva a
    # visibilidade dos itens.
    falta_lancar = abs(float(divergencia_total_df["valor"].sum())) if not divergencia_total_df.empty else 0.0
    if not divergencia_total_df.empty:
        falta_lancar_receitas = float(divergencia_total_df[divergencia_total_df["valor"] > 0]["valor"].sum())
        falta_lancar_despesas = float(divergencia_total_df[divergencia_total_df["valor"] < 0]["valor"].abs().sum())
    else:
        falta_lancar_receitas = falta_lancar_despesas = 0.0
    qtd_divergencia_total = int(len(divergencia_total_df))

    valor_divergencia = (
        float(divergencias["valor_banco"].abs().sum())
        if not divergencias.empty and "valor_banco" in divergencias.columns
        else 0.0
    )
    # v5.49: percentual com base CONSISTENTE — só movimentação nos dois lados.
    percentual = 100.0 * total_conciliado_mov / total_banco if total_banco > 0 else 0.0

    return {
        # v3: renomeado de "Total Extrato Bancário" → "Total Movimentado no Banco".
        # Mantém o nome antigo como alias por retrocompatibilidade.
        "total_movimentado_banco": total_banco,
        "total_extrato_bancario": total_banco,
        "total_extrato_sistema": total_sistema,
        "total_conciliado": total_conciliado,
        "total_conciliado_movimentacao": total_conciliado_mov,
        "total_conciliado_investimentos": total_conciliado_invest,
        "falta_conciliar": falta_conciliar,
        "falta_conciliar_receitas": falta_conciliar_receitas,
        "falta_conciliar_despesas": falta_conciliar_despesas,
        # v3.4: 'Divergência (Sankhya × Banco)' agrega 3 origens.
        # Aliases novos:
        "divergencia_sankhya_banco": falta_lancar,
        "divergencia_sankhya_banco_receitas": falta_lancar_receitas,
        "divergencia_sankhya_banco_despesas": falta_lancar_despesas,
        "qtd_divergencia_sankhya_banco": qtd_divergencia_total,
        # Aliases antigos (Falta Lançar) mantidos por retrocompat:
        "falta_lancar": falta_lancar,
        "falta_lancar_receitas": falta_lancar_receitas,
        "falta_lancar_despesas": falta_lancar_despesas,
        "valor_divergencia": valor_divergencia,
        "percentual_conciliado": percentual,
        "receitas_banco": receitas_banco,
        "despesas_banco": despesas_banco,
        "receitas_sistema": receitas_sistema,
        "despesas_sistema": despesas_sistema,
        "receitas_conciliadas": receitas_conciliadas,
        "despesas_conciliadas": despesas_conciliadas,
        "total_absoluto_processado": total_banco + total_sistema,
        "qtd_registros_banco": int(len(banco_completo)),
        "qtd_registros_sistema": int(len(sistema_completo)),
        "qtd_movimentacoes_banco": int(len(banco_mov)),
        "qtd_movimentacoes_sistema": int(len(sistema_mov)),
        "qtd_conciliados": int(len(conciliados)),
        "qtd_pendentes_banco": int(len(pendentes_banco)),
        "qtd_pendentes_sistema": int(len(pendentes_sistema)),
        "qtd_divergencias": int(len(divergencias)),
        "qtd_total_processado": int(len(banco_completo) + len(sistema_completo)),
        "fonte_falta_lancar": (
            "sankhya_conciliado_nao" if usa_conciliado_sankhya else "pendentes_pos_match"
        ),
        # v5.0: estornos e TOP 1722
        "qtd_estornos_anulados": int(len(estornos_anulados)) if estornos_anulados is not None else 0,
        "valor_estornos_anulados": (
            float(estornos_anulados["valor_original"].abs().sum())
            if (estornos_anulados is not None and not estornos_anulados.empty
                and "valor_original" in estornos_anulados.columns) else 0.0
        ),
        "qtd_estornos_parciais": int(len(estornos_parciais)) if estornos_parciais is not None else 0,
        "saldo_estornos_parciais": (
            float(estornos_parciais["saldo_liquido"].sum())
            if (estornos_parciais is not None and not estornos_parciais.empty
                and "saldo_liquido" in estornos_parciais.columns) else 0.0
        ),
        "qtd_top1722_grupos": int(len(top1722_grupos)) if top1722_grupos is not None else 0,
        "valor_top1722_conciliado": (
            float(top1722_grupos["valor_banco_total"].sum())
            if (top1722_grupos is not None and not top1722_grupos.empty
                and "valor_banco_total" in top1722_grupos.columns) else 0.0
        ),
        "qtd_top1702_grupos": int(len(top1702_grupos)) if top1702_grupos is not None else 0,
        "valor_top1702_conciliado": (
            float(top1702_grupos["valor_banco_total"].sum())
            if (top1702_grupos is not None and not top1702_grupos.empty
                and "valor_banco_total" in top1702_grupos.columns) else 0.0
        ),
    }


# ===========================================================================
# Detecção de "Conciliado=Não" no Sankhya
# ===========================================================================

def _coluna_conciliado_util(df: pd.DataFrame) -> bool:
    if df.empty or "conciliado" not in df.columns:
        return False
    valores = df["conciliado"].dropna().astype(str).str.strip().str.upper()
    valores = valores[valores != ""]
    if valores.empty:
        return False
    valores_validos = valores.isin({"SIM", "NAO", "NÃO", "S", "N", "TRUE", "FALSE", "1", "0"})
    return bool(valores_validos.any())


def _filtrar_conciliado_nao(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "conciliado" not in df.columns:
        return df
    valores = df["conciliado"].fillna("").astype(str).str.strip().str.upper()
    return df[~valores.isin({"SIM", "S", "TRUE", "1"})].copy()


# ===========================================================================
# Extração de Aplicações e Resgates
# ===========================================================================

def _extrair_aplicacoes_resgates(banco: pd.DataFrame, sistema: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for nome, df in [("Banco", banco), ("Sankhya", sistema)]:
        if df.empty or "categoria_mov" not in df.columns:
            continue
        d = df[df["categoria_mov"].isin(
            ["aplicacao", "resgate", "investimento_outro", "rendimento"]
        )].copy()
        if d.empty:
            continue
        d["origem"] = nome
        d["tipo_aplicacao"] = d["categoria_mov"].map({
            "aplicacao": "Aplicação",
            "resgate": "Resgate",
            "investimento_outro": "Investimento",
            "rendimento": "Rendimento",
        }).fillna("Indefinido")
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ===========================================================================
# Pipeline principal
# ===========================================================================

def executar_pipeline(
    banco: pd.DataFrame,
    sistema: pd.DataFrame,
    data_referencia: datetime | None = None,
    tolerancia_dias: int = 2,
    rodar_fuzzy: bool = True,
    tarifas_adquirente: pd.DataFrame | None = None,
) -> ResultadoConciliacao:
    if data_referencia is None:
        data_referencia = datetime.now()

    banco = adicionar_classificacao(banco)
    banco = adicionar_categoria_movimento(banco)
    sistema = adicionar_classificacao(sistema)
    sistema = adicionar_categoria_movimento(sistema)

    # Match exato — v3: usa TUDO que é movimentado (movimentacao + aplic + resgate + investimento).
    # Só exclui linhas de SALDO, que não são movimentação real.
    banco_mov = _eh_movimentado(banco).copy() if not banco.empty else banco
    sistema_mov = _eh_movimentado(sistema).copy() if not sistema.empty else sistema

    # v5.0/v5.46: detector de estornos (banco × banco) ANTES do match, agora
    # CONSCIENTE DO SANKHYA. Se o lançamento original (ex.: recebimento PIX) tem
    # par exato disponível no Sankhya (mesma conta, mesmo valor, data dentro da
    # tolerância), o par recebimento+devolução NÃO é anulado: o recebimento
    # concilia normalmente no match (a baixa do Sankhya está certa — o dinheiro
    # entrou) e a devolução fica visível em Pendentes como "no banco · falta
    # lançar no Sankhya" (ação real: lançar a devolução/estornar a baixa no ERP).
    # Com dois recebimentos iguais e só uma baixa, o app distribui: protege um
    # (concilia) e anula o outro por estorno. Pares sem nada no Sankhya
    # continuam anulados como sempre. Corrige a divergência falsa "baixado no
    # Sankhya · sem par no banco" que aparecia nesses casos.
    from src.matching.estornos import detectar_estornos
    res_estornos = detectar_estornos(
        banco_mov, sistema=sistema_mov, tolerancia_dias=tolerancia_dias
    )
    if res_estornos.indices_anulados or res_estornos.indices_parciais_removidos:
        idx_remover = res_estornos.indices_anulados | res_estornos.indices_parciais_removidos
        banco_mov = banco_mov.reset_index(drop=True)
        banco_mov = banco_mov.drop(index=[i for i in idx_remover if i < len(banco_mov)]).reset_index(drop=True)
        # Adiciona saldos restantes de estornos parciais
        if not res_estornos.saldos_parciais.empty:
            saldos = res_estornos.saldos_parciais.copy()
            # Adiciona colunas que o banco normalmente tem
            for col in banco_mov.columns:
                if col not in saldos.columns:
                    saldos[col] = "" if banco_mov[col].dtype == object else 0
            banco_mov = pd.concat([banco_mov, saldos[banco_mov.columns]], ignore_index=True)

    # =================================================================
    # v5.71: REGRAS DE AGRUPAMENTO agora rodam ANTES do match_exato.
    #
    # Motivo: match_exato casa data+valor 1-pra-1 e não sabe distinguir uma
    # linha componente de um grupo (ex.: 1 SISPAG SALARIO de -R$304,62) de
    # uma despesa avulsa do Sankhya com o mesmo valor (ex.: PEDRO HENRIQUE
    # -R$304,62). Se casa por acidente, o grupo perde um componente, a soma
    # total não fecha mais, e a regra de agrupamento rejeita — devolvendo
    # dezenas ou centenas de linhas como divergência falsa.
    #
    # Solução: cada regra de agrupamento roda primeiro sobre banco_mov /
    # sistema_mov completos. Consome os grupos que fecham por soma. Só o que
    # sobra é entregue ao match_exato 1-pra-1.
    #
    # Ordem interna preservada (TOP 1722 antes de folha, etc.) porque as
    # regras não competem entre si — TOP 1722 procura CARTÃO no banco; folha
    # procura SISPAG SALARIOS; nenhuma pega o que a outra pega. A ordem só
    # importa em relação ao match_exato.
    # =================================================================

    # v5.0: TOP 1722 (cartão de crédito). N recebimentos cartão banco → 1
    # linha 1722 no Sankhya (soma do dia). v5.59: com a adquirente presente
    # o dia pode fechar líquido de tarifa.
    from src.matching.cartao_top1722 import detectar_top_1722
    res_top1722 = detectar_top_1722(
        banco_mov, sistema_mov, janela_dias=tolerancia_dias,
        tarifas_adquirente=tarifas_adquirente,
    )
    banco_mov = _remover_por_indices(banco_mov, res_top1722.indices_banco_casados)
    sistema_mov = _remover_por_indices(sistema_mov, res_top1722.indices_sankhya_casados)

    # v5.35: TOP 1702 (boleto). Irmão do 1722.
    from src.matching.boleto_top1702 import detectar_top_1702
    res_top1702 = detectar_top_1702(banco_mov, sistema_mov, janela_dias=tolerancia_dias)
    banco_mov = _remover_por_indices(banco_mov, res_top1702.indices_banco_casados)
    sistema_mov = _remover_por_indices(sistema_mov, res_top1702.indices_sankhya_casados)

    # v5.21: FOLHA DE PAGAMENTO (SISPAG SALARIOS). N banco → 1 Sankhya.
    from src.matching.folha_pagamento import detectar_folha_pagamento
    res_folha = detectar_folha_pagamento(banco_mov, sistema_mov)
    banco_mov = _remover_por_indices(banco_mov, res_folha.indices_banco_casados)
    sistema_mov = _remover_por_indices(sistema_mov, res_folha.indices_sankhya_casados)

    # v5.28: SALÁRIOS N→M. Sankhya lança salários individuais em vez de
    # consolidar em FOLHA.
    from src.matching.salarios_n_m import detectar_salarios_n_m
    res_salarios_nm = detectar_salarios_n_m(banco_mov, sistema_mov)
    banco_mov = _remover_por_indices(banco_mov, res_salarios_nm.indices_banco_casados)
    sistema_mov = _remover_por_indices(sistema_mov, res_salarios_nm.indices_sankhya_casados)

    # v5.24: depósitos abertos (1 banco → N Sankhya). Ex.: 1 PIX de R$X
    # aberto em várias notas fiscais no Sankhya.
    from src.matching.depositos_abertos import detectar_depositos_abertos
    res_depositos = detectar_depositos_abertos(banco_mov, sistema_mov)
    banco_mov = _remover_por_indices(banco_mov, res_depositos.indices_banco_casados)
    sistema_mov = _remover_por_indices(sistema_mov, res_depositos.indices_sankhya_casados)

    # =================================================================
    # Agora sim: match_exato 1-pra-1 sobre o que sobrou.
    # =================================================================
    conciliados, pend_banco, pend_sistema = match_exato(
        banco_mov, sistema_mov, tolerancia_dias=tolerancia_dias
    )

    # v5.27: tarifas/pagamentos repetidos N pra N — REDE DE SEGURANÇA
    # DEPOIS do match_exato. Casos onde o banco tem N linhas idênticas
    # (data + valor) e o Sankhya tem a mesma quantidade — na maioria dos
    # dias o match_exato já resolve, esta regra só pega o que sobrou.
    from src.matching.tarifas_repetidas import detectar_tarifas_repetidas
    res_tarifas = detectar_tarifas_repetidas(pend_banco, pend_sistema)
    if res_tarifas.indices_banco_casados or res_tarifas.indices_sankhya_casados:
        pend_banco = pend_banco.reset_index(drop=True)
        pend_sistema = pend_sistema.reset_index(drop=True)
        pend_banco = pend_banco.drop(
            index=[i for i in res_tarifas.indices_banco_casados if i < len(pend_banco)]
        ).reset_index(drop=True)
        pend_sistema = pend_sistema.drop(
            index=[i for i in res_tarifas.indices_sankhya_casados if i < len(pend_sistema)]
        ).reset_index(drop=True)

    if not conciliados.empty:
        # Preserva a categoria_mov no resultado conciliado (pra dashboards)
        pass

    # v5.24: AUT MAIS sem par no banco — antes de detectar divergências.
    # O XLS bancário não exporta APL APLIC AUT MAIS / RES APLIC AUT MAIS (só o PDF exporta).
    # Como o Sankhya tem esses lançamentos e o XLS não, eles ficavam em "Divergência
    # sem par no banco" como falso positivo. Movemos pro card Investimentos.
    from src.matching.aut_mais import detectar_aut_mais_sem_par
    res_aut_mais = detectar_aut_mais_sem_par(pend_banco, pend_sistema)
    if res_aut_mais.indices_sankhya_consumidos:
        pend_sistema = pend_sistema.reset_index(drop=True)
        pend_sistema = pend_sistema.drop(
            index=[i for i in res_aut_mais.indices_sankhya_consumidos if i < len(pend_sistema)]
        ).reset_index(drop=True)

    # v5.28: tarifas de adquirente (TARIFA ALUGUEL GETNET) já descontadas pela GETNET.
    # No Sankhya essas tarifas são lançadas separadamente, mas no banco elas vêm
    # JÁ DESCONTADAS do valor líquido. Por isso jamais terão par individual no
    # extrato. Removemos das pendências do Sankhya pra não virarem divergência.
    from src.matching.tarifas_adquirente import detectar_tarifas_adquirente
    res_tarifas_adq = detectar_tarifas_adquirente(pend_sistema)
    if res_tarifas_adq.indices_sankhya_consumidos:
        pend_sistema = pend_sistema.reset_index(drop=True)
        pend_sistema = pend_sistema.drop(
            index=[i for i in res_tarifas_adq.indices_sankhya_consumidos if i < len(pend_sistema)]
        ).reset_index(drop=True)

    # v5.31: resgates/aplicações/rendimentos NÃO são "banco sem explicação" —
    # são movimento de investimento (já listados na aba Investimentos, que vem do
    # banco completo). Removê-los do pend_banco evita inflar Falta Conciliar e
    # Pendentes. A categoria_mov já foi classificada no início do pipeline.
    if "categoria_mov" in pend_banco.columns:
        pend_banco = pend_banco[
            ~pend_banco["categoria_mov"].isin(
                ["aplicacao", "resgate", "rendimento", "investimento_outro"]
            )
        ].reset_index(drop=True)

    divergencias = detectar_divergencia_valor(pend_banco, pend_sistema)
    # v5.71: duplicidades e possíveis_duplicidades usam os DataFrames originais
    # ANTES da limpeza dos grupos (banco original _eh_movimentado). Aqui
    # recuperamos a versão completa para o cálculo delas.
    banco_mov_completo = _eh_movimentado(banco).copy() if not banco.empty else banco
    sistema_mov_completo = _eh_movimentado(sistema).copy() if not sistema.empty else sistema
    duplicidades = detectar_duplicidades(banco_mov_completo, sistema_mov_completo)

    # v5.23: antes de detectar possíveis duplicidades, remove do escopo as linhas
    # que JÁ FORAM consumidas pelos agrupamentos (TOP 1722 cartão + Folha N→1).
    # Sem isso, os 150 SISPAG SALARIOS conciliados em bloco apareciam como
    # "possíveis duplicidades" (mesma data + histórico), gerando alarme falso.
    # Filtra por CONTEÚDO (data + valor + histórico) — não por índice — porque o
    # banco_mov/sistema_mov originais têm índices diferentes dos pend_banco/pend_sistema.
    def _chave_conteudo(df: pd.DataFrame) -> pd.Series:
        return (
            df["data"].astype(str)
            + "|" + df["historico"].fillna("").astype(str)
            + "|" + df["valor"].round(2).astype(str)
        )

    banco_para_dup = banco_mov_completo.copy()
    sistema_para_dup = sistema_mov_completo.copy()

    # Constrói set de chaves já consumidas no banco
    chaves_banco_consumidas: set[str] = set()
    if not res_top1722.linhas_banco_casadas.empty:
        chaves_banco_consumidas.update(_chave_conteudo(res_top1722.linhas_banco_casadas).tolist())
    if not res_folha.linhas_banco_casadas.empty:
        chaves_banco_consumidas.update(_chave_conteudo(res_folha.linhas_banco_casadas).tolist())
    # v5.27: também exclui linhas consumidas por depósitos abertos e tarifas repetidas
    if not res_depositos.linhas_banco_casadas.empty:
        chaves_banco_consumidas.update(_chave_conteudo(res_depositos.linhas_banco_casadas).tolist())
    if not res_tarifas.linhas_banco_casadas.empty:
        chaves_banco_consumidas.update(_chave_conteudo(res_tarifas.linhas_banco_casadas).tolist())
    # v5.28: idem para Salários N→M
    if not res_salarios_nm.linhas_banco_casadas.empty:
        chaves_banco_consumidas.update(_chave_conteudo(res_salarios_nm.linhas_banco_casadas).tolist())
    # v5.35: idem para Boleto TOP 1702
    if not res_top1702.linhas_banco_casadas.empty:
        chaves_banco_consumidas.update(_chave_conteudo(res_top1702.linhas_banco_casadas).tolist())

    # Constrói set de chaves já consumidas no sankhya
    chaves_sistema_consumidas: set[str] = set()
    if not res_top1722.linhas_sankhya_casadas.empty:
        chaves_sistema_consumidas.update(_chave_conteudo(res_top1722.linhas_sankhya_casadas).tolist())
    if not res_folha.linhas_sankhya_casadas.empty:
        chaves_sistema_consumidas.update(_chave_conteudo(res_folha.linhas_sankhya_casadas).tolist())
    # v5.27: idem pra sankhya
    if not res_depositos.linhas_sankhya_casadas.empty:
        chaves_sistema_consumidas.update(_chave_conteudo(res_depositos.linhas_sankhya_casadas).tolist())
    if not res_tarifas.linhas_sankhya_casadas.empty:
        chaves_sistema_consumidas.update(_chave_conteudo(res_tarifas.linhas_sankhya_casadas).tolist())
    # v5.28: idem para Salários N→M
    if not res_salarios_nm.linhas_sankhya_casadas.empty:
        chaves_sistema_consumidas.update(_chave_conteudo(res_salarios_nm.linhas_sankhya_casadas).tolist())
    # v5.35: idem para Boleto TOP 1702
    if not res_top1702.linhas_sankhya_casadas.empty:
        chaves_sistema_consumidas.update(_chave_conteudo(res_top1702.linhas_sankhya_casadas).tolist())

    # v5.27: TAMBÉM exclui linhas conciliadas no match 1-pra-1 (exact_match/fuzzy).
    # Sem isso, tarifas TAR C/C SISPAG que já casaram 1-pra-1 com pares no Sankhya
    # apareciam em "Possíveis Duplicidades" — alarme falso.
    if not conciliados.empty:
        # Os conciliados têm colunas banco_data, banco_historico, banco_valor etc.
        if all(c in conciliados.columns for c in ["banco_data", "banco_historico", "banco_valor"]):
            conc_banco_keys = (
                conciliados["banco_data"].astype(str)
                + "|" + conciliados["banco_historico"].fillna("").astype(str)
                + "|" + conciliados["banco_valor"].round(2).astype(str)
            )
            chaves_banco_consumidas.update(conc_banco_keys.tolist())
        if all(c in conciliados.columns for c in ["sistema_data", "sistema_historico", "sistema_valor"]):
            conc_sis_keys = (
                conciliados["sistema_data"].astype(str)
                + "|" + conciliados["sistema_historico"].fillna("").astype(str)
                + "|" + conciliados["sistema_valor"].round(2).astype(str)
            )
            chaves_sistema_consumidas.update(conc_sis_keys.tolist())

    if chaves_banco_consumidas:
        banco_para_dup = banco_para_dup[
            ~_chave_conteudo(banco_para_dup).isin(chaves_banco_consumidas)
        ].reset_index(drop=True)
    if chaves_sistema_consumidas:
        sistema_para_dup = sistema_para_dup[
            ~_chave_conteudo(sistema_para_dup).isin(chaves_sistema_consumidas)
        ].reset_index(drop=True)

    possiveis_dup = detectar_possiveis_duplicidades(banco_para_dup, sistema_para_dup)

    # v3.1: excesso_sankhya considera APENAS as pendências do sistema (o que não casou).
    # Conta quantas linhas pendentes do Sankhya excedem as pendências do banco
    # para o mesmo perfil (data + valor + conta).
    excesso_sis = detectar_excesso_sankhya_pos_match(pend_banco, pend_sistema)
    nao_pertence = detectar_nao_pertence(pend_banco, pend_sistema, tolerancia_dias)
    sugestoes = sugerir_matches_fuzzy(pend_banco, pend_sistema) if rodar_fuzzy else pd.DataFrame()
    aplicacoes_resgates = _extrair_aplicacoes_resgates(banco, sistema)

    usa_conciliado = _coluna_conciliado_util(sistema)
    if usa_conciliado:
        falta_lancar_df = _filtrar_conciliado_nao(sistema)
        if "categoria_mov" in falta_lancar_df.columns:
            falta_lancar_df = falta_lancar_df[falta_lancar_df["categoria_mov"] == "movimentacao"]
    else:
        falta_lancar_df = pd.DataFrame()

    contas = sorted(set(banco["conta"].unique()) | set(sistema["conta"].unique()))
    contas = [c for c in contas if c and c != "—"]

    return ResultadoConciliacao(
        conciliados=conciliados,
        pendentes_banco=pend_banco,
        pendentes_sistema=pend_sistema,
        divergencias=divergencias,
        duplicidades=duplicidades,
        possiveis_duplicidades=possiveis_dup,
        excesso_sankhya=excesso_sis,
        nao_pertence=nao_pertence,
        sugestoes_fuzzy=sugestoes,
        aplicacoes_resgates=aplicacoes_resgates,
        falta_lancar_sankhya=falta_lancar_df,
        estornos_anulados=res_estornos.anulados,
        estornos_parciais=res_estornos.parciais,
        top1722_grupos=res_top1722.grupos_conciliados,
        top1722_linhas=res_top1722.linhas_sankhya_casadas,
        top1722_linhas_banco=res_top1722.linhas_banco_casadas,
        top1722_diferencas=res_top1722.com_diferenca,
        top1702_grupos=res_top1702.grupos_conciliados,
        top1702_linhas=res_top1702.linhas_sankhya_casadas,
        top1702_linhas_banco=res_top1702.linhas_banco_casadas,
        top1702_diferencas=res_top1702.com_diferenca,
        banco_completo=banco,
        sistema_completo=sistema,
        data_referencia=data_referencia,
        contas_processadas=contas,
        tolerancia_dias=tolerancia_dias,
        usa_conciliado_sankhya=usa_conciliado,
    )
