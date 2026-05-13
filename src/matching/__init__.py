"""Lógica de conciliação e auditoria."""

from .auditorias import (
    detectar_banco_errado,
    detectar_divergencia_valor,
    detectar_duplicidades,
)
from .exact_match import conciliar_exato
from .fuzzy_match import sugestoes_fuzzy

__all__ = [
    "conciliar_exato",
    "sugestoes_fuzzy",
    "detectar_duplicidades",
    "detectar_divergencia_valor",
    "detectar_banco_errado",
]
