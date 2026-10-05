"""
Aplicación del mapeo declarado en config/mapeo_columnas.yaml.

`normalizar_nombre_columna` y `construir_diccionario_columna_a_canonico` son
puro stdlib y funcionan hoy. `aplicar_mapeo_a_tabla` (sobre un archivo/tabla
completa) requiere pandas y está sin implementar todavía.
"""

from __future__ import annotations

import re

from sales_intel.utils.config import cargar_mapeo_columnas

_ESPACIOS_MULTIPLES = re.compile(r"\s+")
_TILDES = str.maketrans("ÁÉÍÓÚÑáéíóúñ", "AEIOUNaeioun")


def normalizar_nombre_columna(nombre: str) -> str:
    """Normaliza un nombre de columna para poder compararlo contra
    mapeo_columnas.yaml: mayúsculas, sin tildes, espacios colapsados,
    recortado. Debe coincidir con la convención declarada en ese YAML
    (metadata.normalizacion_clave).
    """
    limpio = nombre.translate(_TILDES).upper().strip()
    limpio = _ESPACIOS_MULTIPLES.sub(" ", limpio)
    return limpio


def construir_diccionario_columna_a_canonico() -> dict[str, str]:
    """Invierte config/mapeo_columnas.yaml: de {canonico: [sinonimos]} a
    {sinonimo_normalizado: canonico}, para lookup O(1) por columna.
    """
    config = cargar_mapeo_columnas()
    resultado: dict[str, str] = {}
    for campo_canonico, sinonimos in config["sinonimos"].items():
        for sinonimo in sinonimos:
            clave = normalizar_nombre_columna(sinonimo)
            if clave in resultado and resultado[clave] != campo_canonico:
                raise ValueError(
                    f"Conflicto de mapeo: la columna '{sinonimo}' está declarada "
                    f"para dos campos canónicos distintos: '{resultado[clave]}' y "
                    f"'{campo_canonico}'. Revisar config/mapeo_columnas.yaml."
                )
            resultado[clave] = campo_canonico
    return resultado


def mapear_columnas_de_fuente(columnas_originales: list[str]) -> dict[str, str | None]:
    """Dada la lista de columnas de UNA fuente (tal como vienen en el CSV/XLSX
    original), devuelve {columna_original: campo_canonico | None}.

    None significa que la columna no tiene mapeo declarado todavía — debe
    revisarse manualmente antes de descartarla (ver 'sin_mapear_v1' en el
    YAML para las que ya se decidió excluir a propósito).
    """
    diccionario = construir_diccionario_columna_a_canonico()
    return {
        col: diccionario.get(normalizar_nombre_columna(col))
        for col in columnas_originales
    }


def aplicar_mapeo_a_tabla(tabla, fuente_id: str):
    """Renombra las columnas de una tabla completa al esquema canónico.

    NO IMPLEMENTADO TODAVÍA — requiere pandas. Diseño previsto: recibir un
    pandas.DataFrame, usar mapear_columnas_de_fuente sobre tabla.columns,
    renombrar, y registrar en log si alguna columna queda sin mapeo.
    """
    raise NotImplementedError(
        "aplicar_mapeo_a_tabla requiere pandas, no instalado todavía. "
        "Ver 04_SISTEMA/docs/GUIA_EJECUCION.md."
    )
