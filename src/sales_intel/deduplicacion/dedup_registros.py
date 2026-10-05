"""
Detección de duplicados de REGISTRO (Nivel 2 — el mismo negocio aparece en
varias fuentes distintas). Ver ARQUITECTURA.md sección E.

`generar_clave_negocio` es puro stdlib y funciona hoy. La fusión de registros
sobre la base normalizada completa requiere pandas + rapidfuzz y está sin
implementar todavía.
"""

from __future__ import annotations

import re

from sales_intel.normalizacion.limpieza import normalizar_nit, normalizar_texto

_LONGITUD_MINIMA_NIT_VALIDO = 6  # NITs colombianos reales tienen 9-10 dígitos;
# se deja un mínimo laxo para no descartar de entrada formatos atípicos.

_PATRON_DIGITO_REPETIDO = re.compile(r"^(\d)\1*$")


def es_placeholder_identificador(valor: str | None) -> bool:
    """True si un NIT/matrícula ya normalizado (solo dígitos) es un
    placeholder claramente inválido — el mismo dígito repetido ("0",
    "0000000000000", "999999999", etc.), confirmado en la auditoría previa
    de deduplicación como el patrón real encontrado en los datos (2,124+42
    registros con NIT="0", 713 con NIT="0000000000000").

    Deliberadamente NO se aplica ningún filtro adicional por longitud — solo
    se trata como placeholder lo que es inequívocamente un valor vacío
    disfrazado de número, tal como pidió el usuario. Un NIT corto pero no
    repetido (ej. un formato antiguo de 7 dígitos) NO se descarta aquí.
    """
    if not valor:
        return True
    return bool(_PATRON_DIGITO_REPETIDO.match(valor))


def generar_clave_negocio(
    nit: str | None,
    razon_social: str | None,
    municipio: str | None,
) -> tuple[str, str]:
    """Genera la clave de deduplicación de un registro y el método usado.

    Prioridad (documentada en ARQUITECTURA.md):
      1. NIT normalizado, si existe y es plausible -> clave = "nit:<digitos>"
      2. Si no, razón social normalizada + municipio -> clave =
         "razon_municipio:<...>"

    Retorna (clave, metodo) donde metodo es "nit" o "razon_municipio", para
    que el log de deduplicación pueda registrar con qué criterio se generó
    cada fusión.
    """
    nit_norm = normalizar_nit(nit)
    if nit_norm and len(nit_norm) >= _LONGITUD_MINIMA_NIT_VALIDO:
        return f"nit:{nit_norm}", "nit"

    razon_norm = normalizar_texto(razon_social) or ""
    municipio_norm = normalizar_texto(municipio) or ""
    return f"razon_municipio:{razon_norm}|{municipio_norm}", "razon_municipio"


def fusionar_registros_duplicados(tabla_normalizada):
    """Superseded por `sales_intel.deduplicacion.ejecutar_deduplicacion`, que
    implementa el diseño conservador multi-pase real (NIT válido, matrícula+
    cámara, candidatos por razón_social+municipio y por fuzzy matching sin
    fusión automática) aprobado el 2026-09-01. Esta función queda como
    referencia del diseño de 2 niveles original, ya no se usa.
    """
    raise NotImplementedError(
        "Usar sales_intel.deduplicacion.ejecutar_deduplicacion.ejecutar_deduplicacion() "
        "en su lugar — implementa el diseño conservador real de esta fase."
    )
