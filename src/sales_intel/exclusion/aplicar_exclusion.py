"""
Cruce de la base maestra contra las claves de exclusión (NIT/matrícula del
CRM y HUBS), sin eliminar filas — solo marca.
"""

from __future__ import annotations


def aplicar_flag_exclusion(base_maestra, claves_exclusion):
    """Agrega a la base maestra las columnas `en_pipeline_bold` (bool) y
    `motivo_exclusion` (str | None), vía LEFT JOIN sobre
    nit_o_matricula_normalizado. No elimina ninguna fila.

    NO IMPLEMENTADO TODAVÍA — requiere pandas.
    """
    raise NotImplementedError(
        "aplicar_flag_exclusion requiere pandas, no instalado todavía. "
        "Ver 04_SISTEMA/docs/GUIA_EJECUCION.md."
    )
