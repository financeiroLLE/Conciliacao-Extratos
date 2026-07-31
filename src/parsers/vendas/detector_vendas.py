# -*- coding: utf-8 -*-
"""
Detector automático de tipo de arquivo para a Conciliação de Vendas.

Estratégia: detecção por CONTEÚDO, não por nome de arquivo — porque:
- O nome do Getnet muda a cada semana (contém hash);
- O nome do Cielo tem timestamp;
- Usuária pode renomear arquivos ao baixar.

Retorna um código curto que identifica o tipo:
- "financeiro_sankhya"
- "cielo_recebiveis"
- "getnet_recebiveis"
- "desconhecido"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import financeiro_sankhya
from . import cielo_recebiveis
from . import getnet_recebiveis
from . import cabecalho_nota_sankhya


TIPOS_CONHECIDOS = {
    "financeiro_sankhya": "Financeiro Sankhya",
    "cielo_recebiveis": "Cielo Recebíveis Detalhe",
    "getnet_recebiveis": "Getnet Recebíveis Completos",
    "cabecalho_nota_sankhya": "Cabeçalho da Nota Sankhya",
    "desconhecido": "Desconhecido",
}


@dataclass
class ResultadoDeteccao:
    tipo: str                        # código curto
    tipo_legivel: str                # nome amigável
    confianca: str                   # "alta" | "baixa" | "nenhuma"
    motivo: Optional[str] = None     # explicação em caso de falha


def detectar(dados: bytes) -> ResultadoDeteccao:
    """
    Roda todos os detectores em ordem e retorna o primeiro que casar.

    A ordem importa: começamos pelos mais específicos (Getnet exige aba 'Detalhado',
    Cielo exige cabeçalho na linha 10) e deixamos o Financeiro Sankhya por último
    porque é o de cabeçalho mais genérico.
    """
    if not dados or len(dados) < 32:
        return ResultadoDeteccao(
            tipo="desconhecido",
            tipo_legivel="Desconhecido",
            confianca="nenhuma",
            motivo="Arquivo vazio ou muito pequeno.",
        )

    # 1. Getnet (mais específico: exige aba 'Detalhado')
    try:
        if getnet_recebiveis.eh_getnet_recebiveis(dados):
            return ResultadoDeteccao(
                tipo="getnet_recebiveis",
                tipo_legivel=TIPOS_CONHECIDOS["getnet_recebiveis"],
                confianca="alta",
            )
    except Exception:
        pass

    # 2. Cielo
    try:
        if cielo_recebiveis.eh_cielo_recebiveis(dados):
            return ResultadoDeteccao(
                tipo="cielo_recebiveis",
                tipo_legivel=TIPOS_CONHECIDOS["cielo_recebiveis"],
                confianca="alta",
            )
    except Exception:
        pass

    # 3. Cabeçalho da Nota Sankhya (Entrega 2 · 31/07/2026)
    # DEVE vir ANTES do Financeiro Sankhya: o Cabeçalho tem colunas específicas
    # ("Nro. Nota", "Dt. Neg.", "Vlr. Nota") que o Financeiro não tem, e a
    # função `eh_cabecalho_nota` verifica ausência de marcadores exclusivos do
    # Financeiro pra evitar confusão bidirecional.
    try:
        if cabecalho_nota_sankhya.eh_cabecalho_nota(dados):
            return ResultadoDeteccao(
                tipo="cabecalho_nota_sankhya",
                tipo_legivel=TIPOS_CONHECIDOS["cabecalho_nota_sankhya"],
                confianca="alta",
            )
    except Exception:
        pass

    # 4. Financeiro Sankhya
    try:
        if financeiro_sankhya.eh_financeiro_sankhya(dados):
            return ResultadoDeteccao(
                tipo="financeiro_sankhya",
                tipo_legivel=TIPOS_CONHECIDOS["financeiro_sankhya"],
                confianca="alta",
            )
    except Exception:
        pass

    # Nada casou
    head = dados[:8]
    if head.startswith(b"\xD0\xCF\x11\xE0"):
        motivo = "Arquivo é .xls binário mas não bate com Financeiro Sankhya, Cabeçalho da Nota, Cielo nem Getnet."
    elif head.startswith(b"PK\x03\x04"):
        motivo = "Arquivo é .xlsx/zip — nenhum dos leitores esperados aceita este formato ainda."
    else:
        motivo = f"Formato desconhecido; primeiros bytes: {head!r}"

    return ResultadoDeteccao(
        tipo="desconhecido",
        tipo_legivel="Desconhecido",
        confianca="nenhuma",
        motivo=motivo,
    )
