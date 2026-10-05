"""
Funciones de limpieza de valores a nivel de celda.

Todo este módulo es puro stdlib (re, unicodedata) — no depende de pandas ni
de ningún paquete externo. Funciona hoy y se puede probar de forma aislada
(ver 04_SISTEMA/tests/test_limpieza.py).
"""

from __future__ import annotations

import re
import unicodedata

_ESPACIOS_MULTIPLES = re.compile(r"\s+")
_SOLO_DIGITOS = re.compile(r"\D+")
_VALORES_NULOS_CONOCIDOS = {
    "", "N/A", "NA", "NO REPORTA", "NO APLICA", "NO REPORTADO", "SIN DATO", "null", "None",
    # Salvaguarda: representación en texto de un nulo de pandas (pd.NA/NaT/NaN)
    # si llega a colarse como string antes de pasar por esta función — ver
    # DECISIONES.md, bug encontrado y corregido en la fase de normalización.
    "<NA>", "NAN", "NAT",
}


def quitar_tildes(texto: str) -> str:
    """Quita tildes/diacríticos preservando la letra base (á -> a, ñ -> n)."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar_texto(valor: str | None) -> str | None:
    """Normaliza texto para comparación/matching: mayúsculas, sin tildes,
    espacios colapsados y recortados. Preserva None tal cual.

    Esta es la normalización usada como clave de comparación (ej. para
    deduplicación por razón social), NO reemplaza el valor original que se
    conserva para mostrar al usuario.
    """
    if valor is None:
        return None
    limpio = quitar_tildes(str(valor)).upper().strip()
    limpio = _ESPACIOS_MULTIPLES.sub(" ", limpio)
    return limpio if limpio not in _VALORES_NULOS_CONOCIDOS else None


def normalizar_nit(valor: str | None) -> str | None:
    """Deja solo dígitos de un NIT/identificación (quita puntos, comas,
    guiones y dígito de verificación separado por guión).

    Ejemplos observados en la auditoría: "8.160.024.518" -> "8160024518",
    "9015371367" -> "9015371367".
    """
    if valor is None:
        return None
    solo_digitos = _SOLO_DIGITOS.sub("", str(valor))
    return solo_digitos or None


def normalizar_telefono(valor: str | None) -> str | None:
    """Deja solo dígitos de un teléfono. No valida longitud ni indicativo —
    eso se deja para una fase de validación posterior si se necesita."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if normalizar_texto(texto) is None:  # captura "N/A", "NO REPORTA", etc.
        return None
    solo_digitos = _SOLO_DIGITOS.sub("", texto)
    return solo_digitos or None


def normalizar_email(valor: str | None) -> str | None:
    """Normaliza un email a minúsculas y recortado. Validación de formato
    deliberadamente mínima en V1 (solo exige un '@')."""
    if valor is None:
        return None
    texto = str(valor).strip().lower()
    if normalizar_texto(texto) is None:
        return None
    return texto if "@" in texto else None


def es_valor_nulo_declarado(valor: str | None) -> bool:
    """True si el valor es uno de los marcadores de nulo usados por las
    Cámaras de Comercio ("N/A", "No reporta", "No aplica", etc.), no un dato
    real. Útil para no contar estos como "campo completo" en reportes de
    calidad de datos.
    """
    if valor is None:
        return True
    return normalizar_texto(str(valor)) is None
