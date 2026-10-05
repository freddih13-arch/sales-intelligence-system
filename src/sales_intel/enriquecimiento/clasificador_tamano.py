"""
Normalización del tamaño de empresa a partir de señales disponibles.

Puro stdlib. Los umbrales de número de empleados son un BORRADOR inicial
razonable (alineado a la clasificación MIPYME colombiana vigente al momento
del diseño), sujeto a validación con negocio antes de usarse en scoring real
— igual que encaje_pagos en mapeo_ciiu_sector.yaml.
"""

from __future__ import annotations

from sales_intel.normalizacion.limpieza import normalizar_texto

_UMBRALES_EMPLEADOS = (
    (10, "micro"),
    (50, "pequeña"),
    (200, "mediana"),
)  # > 200 -> "grande"

_ETIQUETAS_DECLARADAS = {
    "MICRO": "micro", "MICROEMPRESA": "micro", "MICRO EMPRESA": "micro",
    "PEQUEÑA": "pequeña", "PEQUEÑA EMPRESA": "pequeña",
    "MEDIANA": "mediana", "MEDIANA EMPRESA": "mediana",
    "GRANDE": "grande", "GRAN EMPRESA": "grande",
}


def clasificar_tamano(
    num_empleados: int | None = None,
    tamano_declarado: str | None = None,
) -> dict:
    """Devuelve {'tamano_empresa': ..., 'metodo': ..., 'nivel_confianza': ...}.

    Prioridad: si la fuente ya declara un tamaño explícito (ej. "MICRO
    EMPRESA", visto en varias fuentes auditadas), se usa tal cual
    (confirmado). Si no, se infiere por número de empleados (inferido). Si no
    hay ningún dato, se marca 'sin_dato'.
    """
    declarado_norm = normalizar_texto(tamano_declarado) if tamano_declarado else None
    if declarado_norm and declarado_norm in _ETIQUETAS_DECLARADAS:
        return {
            "tamano_empresa": _ETIQUETAS_DECLARADAS[declarado_norm],
            "metodo": "declarado_por_fuente",
            "nivel_confianza": "confirmado",
        }

    if num_empleados is not None:
        try:
            n = int(num_empleados)
        except (TypeError, ValueError):
            n = None
        if n is not None:
            for umbral, etiqueta in _UMBRALES_EMPLEADOS:
                if n <= umbral:
                    return {"tamano_empresa": etiqueta, "metodo": "inferido_por_empleados", "nivel_confianza": "inferido"}
            return {"tamano_empresa": "grande", "metodo": "inferido_por_empleados", "nivel_confianza": "inferido"}

    return {"tamano_empresa": "sin_dato", "metodo": "sin_senal_disponible", "nivel_confianza": "inferido"}
