"""
Asignación del nivel de confianza de dato (requisito 15), a nivel de fuente.

Puro stdlib. La taxonomía completa vive en config/scoring_variables.yaml
(niveles_confianza_dato) para que scoring y enriquecimiento compartan la
misma definición.
"""

from __future__ import annotations

from sales_intel.utils.config import cargar_scoring_variables, listar_fuentes


def nivel_confianza_de_fuente(fuente_id: str) -> str:
    """Devuelve el nivel de confianza declarado en fuentes.yaml para una
    fuente dada ('confirmado' o 'externo' — los niveles 'inferido' y
    'validado_manual' se asignan a nivel de CAMPO, no de fuente completa, ver
    nivel_confianza_de_campo_inferido más abajo).
    """
    fuentes = {f.id: f for f in listar_fuentes(excluir_duplicados=False)}
    if fuente_id not in fuentes:
        raise KeyError(f"'{fuente_id}' no está declarado en fuentes.yaml")
    return fuentes[fuente_id].nivel_confianza_fuente


def nivel_confianza_de_campo_inferido() -> str:
    """Nivel a usar para cualquier campo calculado/derivado por el sistema
    (ej. sector_comercial, tamano_empresa cuando se infiere por empleados)."""
    return "inferido"


def descripcion_nivel(nivel: str) -> str:
    """Devuelve la descripción textual de un nivel de confianza, tal como
    está documentada en scoring_variables.yaml, para mostrarla en reportes."""
    config = cargar_scoring_variables()
    niveles = config.get("niveles_confianza_dato", {})
    if nivel not in niveles:
        raise KeyError(f"Nivel de confianza desconocido: '{nivel}'")
    return niveles[nivel]
