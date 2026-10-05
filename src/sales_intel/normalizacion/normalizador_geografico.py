"""
Estandarización de municipio/departamento contra la codificación DANE.

NO IMPLEMENTADO TODAVÍA: requiere una tabla de referencia
(config/municipios_dane.csv) que aún no se ha creado — no estaba en el
alcance de esta fase de infraestructura inicial. Este módulo queda como
punto de extensión declarado.
"""

from __future__ import annotations

from sales_intel.normalizacion.limpieza import normalizar_texto


def extraer_codigo_dane_si_viene_incluido(valor_municipio: str | None) -> tuple[str | None, str | None]:
    """Varias fuentes ya traen el código DANE dentro del mismo campo, con el
    patrón observado "05579 - PUERTO BERRIO" o "66001 - PEREIRA". Esta función
    separa código y nombre cuando ese patrón está presente; si no, devuelve
    (None, texto_normalizado).

    Funciona hoy (puro stdlib) para el caso simple; no reemplaza la tabla de
    referencia DANE completa que se necesita para los casos SIN código
    embebido (ej. fuentes que solo traen "PEREIRA" sin prefijo numérico).
    """
    if not valor_municipio:
        return None, None
    texto = str(valor_municipio).strip()
    if " - " in texto:
        codigo, nombre = texto.split(" - ", 1)
        codigo = codigo.strip()
        if codigo.isdigit():
            return codigo, normalizar_texto(nombre)
    return None, normalizar_texto(texto)


def normalizar_municipio(valor_municipio: str | None, codigo_dane_hint: str | None = None) -> dict:
    """Devuelve {'municipio_dane': ..., 'municipio_nombre': ...} estandarizado.

    NO IMPLEMENTADO TODAVÍA para el caso general — requiere
    config/municipios_dane.csv (tabla de referencia DANE) para resolver
    nombres sin código embebido y para detectar/corregir inconsistencias
    (ej. "68669 - SAN ANDRES" visto en la auditoría, que es un código DANE de
    Santander mal asignado a un registro de San Andrés).
    """
    raise NotImplementedError(
        "normalizar_municipio requiere config/municipios_dane.csv, que todavía "
        "no existe. Ver punto abierto en 04_SISTEMA/docs/DECISIONES.md antes "
        "de crear esa tabla de referencia."
    )
