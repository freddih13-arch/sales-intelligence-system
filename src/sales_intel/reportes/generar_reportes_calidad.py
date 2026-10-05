"""
Reportes de calidad y cobertura sobre la base procesada.
"""

from __future__ import annotations


def generar_reporte_calidad_datos(tabla=None):
    """Calcula % de campos completos (excluyendo valores nulos declarados,
    ver normalizacion.limpieza.es_valor_nulo_declarado) y cobertura de
    contacto, y escribe 03_RESULTADOS/reportes/reporte_calidad_datos.md.

    NO IMPLEMENTADO TODAVÍA — requiere pandas.
    """
    raise NotImplementedError("generar_reporte_calidad_datos requiere pandas, no instalado todavía.")


def generar_reporte_duplicados(log_duplicados=None):
    """Resume duplicados exactos/casi-exactos y fusiones de registro
    detectadas, y escribe 03_RESULTADOS/reportes/reporte_duplicados.md.

    NO IMPLEMENTADO TODAVÍA — requiere pandas.
    """
    raise NotImplementedError("generar_reporte_duplicados requiere pandas, no instalado todavía.")


def generar_reporte_cobertura_geografica(tabla=None):
    """Cuenta negocios por municipio/departamento y escribe
    03_RESULTADOS/reportes/reporte_cobertura_geografica.md.

    NO IMPLEMENTADO TODAVÍA — requiere pandas.
    """
    raise NotImplementedError("generar_reporte_cobertura_geografica requiere pandas, no instalado todavía.")
