"""Módulo CARTÃO — auditoria de taxas e cadastro contratual.

Aproveita a estrutura atual do app (parsers, formatadores, identidade visual)
sem mexer no fluxo de conciliação bancária existente.
"""
from .cadastro_taxas import (
    MODALIDADES_VALIDAS,
    carregar_cadastro_taxas,
    encontrar_taxa_vigente,
)
from .auditoria_taxas import (
    carregar_relatorio_adquirente,
    auditar_taxas,
    carregar_auditoria_anterior,
    consolidar_historico,
    ResultadoAuditoriaTaxas,
)

__all__ = [
    "MODALIDADES_VALIDAS",
    "carregar_cadastro_taxas",
    "encontrar_taxa_vigente",
    "carregar_relatorio_adquirente",
    "auditar_taxas",
    "carregar_auditoria_anterior",
    "consolidar_historico",
    "ResultadoAuditoriaTaxas",
]
