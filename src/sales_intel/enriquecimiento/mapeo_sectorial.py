"""
Mapeo de código CIIU a sector_comercial, usando config/mapeo_ciiu_sector.yaml.

Puro stdlib — funciona hoy sobre un código individual. Aplicarlo a una tabla
completa requiere pandas.
"""

from __future__ import annotations

import re

from sales_intel.utils.config import cargar_mapeo_ciiu_sector

_PATRON_CODIGO_CIIU = re.compile(r"^([A-Z])(\d{3,4})")


def obtener_sector_comercial(codigo_o_texto_ciiu: str | None) -> dict:
    """Dado un valor de columna CIIU tal como aparece en las fuentes (ej.
    "G4773 ** Comercio al por menor de productos farmaceuticos..." o
    simplemente "G4773"), devuelve:
        {"seccion": "G", "codigo_especifico": "G4773" | None,
         "sector_comercial": ..., "encaje_pagos": ..., "nota": ...}

    Aplica primero las excepciones por código específico
    (excepciones_codigo_especifico) y si no hay coincidencia, cae al mapeo
    por sección (letra inicial).
    """
    if not codigo_o_texto_ciiu:
        return {"seccion": None, "codigo_especifico": None, "sector_comercial": None,
                "encaje_pagos": None, "nota": "Sin código CIIU"}

    texto = str(codigo_o_texto_ciiu).strip().upper()
    match = _PATRON_CODIGO_CIIU.match(texto)
    if not match:
        return {"seccion": None, "codigo_especifico": None, "sector_comercial": None,
                "encaje_pagos": None, "nota": f"No se reconoce el formato CIIU: '{texto[:20]}'"}

    seccion, digitos = match.group(1), match.group(2)
    codigo_especifico = f"{seccion}{digitos}"

    config = cargar_mapeo_ciiu_sector()

    excepciones = config.get("excepciones_codigo_especifico", {})
    if codigo_especifico in excepciones:
        exc = excepciones[codigo_especifico]
        return {
            "seccion": seccion,
            "codigo_especifico": codigo_especifico,
            "sector_comercial": exc["sector_comercial"],
            "encaje_pagos": exc["encaje_pagos"],
            "nota": exc.get("nota"),
        }

    seccion_info = config["secciones"].get(seccion)
    if seccion_info is None:
        return {"seccion": seccion, "codigo_especifico": codigo_especifico, "sector_comercial": None,
                "encaje_pagos": None, "nota": f"Sección CIIU '{seccion}' no mapeada"}

    return {
        "seccion": seccion,
        "codigo_especifico": codigo_especifico,
        "sector_comercial": seccion_info["sector_comercial"],
        "encaje_pagos": seccion_info["encaje_pagos"],
        "nota": seccion_info.get("nota"),
    }


def aplicar_sector_comercial_a_tabla(tabla):
    """Aplica obtener_sector_comercial sobre la columna ciiu_1 de una tabla
    completa. NO IMPLEMENTADO TODAVÍA — requiere pandas."""
    raise NotImplementedError(
        "aplicar_sector_comercial_a_tabla requiere pandas, no instalado todavía."
    )
