"""
Escritor del artefacto de salida del enriquecimiento legal — la única pieza
de este subpaquete que escribe un archivo. Recibe la lista de registros ya
producida en memoria por `orquestador_enriquecimiento.enriquecer_prospectos`
/ `enriquecer_top_n_desde_csv` y la persiste como un CSV nuevo y separado.

Deliberadamente en su propio módulo, separado de la orquestación: no
modifica `orquestador_enriquecimiento.py`, `capa_enriquecimiento_legal.py`
ni `cliente_confecamaras.py`, y no depende de HTTP ni de ningún cliente —
solo recibe datos ya en memoria.

Valida agresivamente ANTES de escribir una sola línea (spec del turno
"Escritor del artefacto de salida", 2026-09-02):
- exactamente los 12 campos comerciales aprobados, ni uno más ni uno menos
  (`num_identificacion_representante_legal` -- que nunca debe llegar aquí --
  se rechaza con un mensaje explícito, no solo como "columna no aprobada"
  genérica);
- `entidad_dedup_id` único, `posicion_diversificada` única y dentro de
  [1, n_esperado];
- exactamente `n_esperado` registros (una fila por prospecto, ni una más ni
  una menos);
- `resultado_match` dentro de la taxonomía aprobada de 5 estados.

No sobrescribe nada en silencio: si `ruta_salida` ya existe, falla con
`FileExistsError` salvo que se pase `overwrite=True` explícitamente (no
usado en la primera ejecución de producción). Escritura determinista: mismo
orden de entrada -> mismos bytes de salida, sin pandas (evita cualquier
comportamiento no determinista de formateo/índice) -- solo `csv` de la
librería estándar.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sales_intel.enriquecimiento_legal.capa_enriquecimiento_legal import (
    CAMPOS_COMERCIALES,
    RESULTADOS_MATCH,
)
from sales_intel.utils.config import TOP_PROSPECTOS_DIR, assert_no_escritura_en_raw

# Campo que NUNCA debe llegar al dataset comercial -- se valida aparte de
# "columnas no aprobadas" en general porque es, con diferencia, el error más
# grave posible aquí (un dato personal de identificación que se filtraría a
# un artefacto comercial) y merece su propio mensaje inequívoco.
_CAMPO_PROHIBIDO = "num_identificacion_representante_legal"

# Ruta de producción propuesta para el Top 100 del 2026-09-02. Es solo una
# referencia -- definir esta constante no escribe nada; quien llame a
# `escribir_enriquecimiento_comercial` decide la ruta explícitamente.
RUTA_PRODUCCION_TOP100_20260902 = TOP_PROSPECTOS_DIR / "enriquecimiento_legal_top100_20260902.csv"


class ErrorValidacionEnriquecimiento(ValueError):
    """Cualquier violación de las invariantes del dataset comercial
    enriquecido -- nunca se llega a abrir el archivo de salida si se lanza
    esta excepción."""


def _validar_registros(registros: list[dict], n_esperado: int) -> None:
    if len(registros) != n_esperado:
        raise ErrorValidacionEnriquecimiento(
            f"Se esperaban exactamente {n_esperado} registros (uno por prospecto "
            f"del Top N de entrada), llegaron {len(registros)}."
        )

    entidades_vistas: set = set()
    posiciones_vistas: set = set()

    for indice, registro in enumerate(registros):
        entidad_id = registro.get("entidad_dedup_id")
        etiqueta = f"registro #{indice} (entidad_dedup_id={entidad_id!r})"
        claves = set(registro.keys())

        if _CAMPO_PROHIBIDO in claves:
            raise ErrorValidacionEnriquecimiento(
                f"{etiqueta} incluye '{_CAMPO_PROHIBIDO}' -- campo NUNCA aprobado "
                "para el dataset comercial (identifica a una persona natural)."
            )

        faltantes = set(CAMPOS_COMERCIALES) - claves
        if faltantes:
            raise ErrorValidacionEnriquecimiento(
                f"{etiqueta} le faltan columnas comerciales aprobadas: {sorted(faltantes)}."
            )

        extra = claves - set(CAMPOS_COMERCIALES)
        if extra:
            raise ErrorValidacionEnriquecimiento(
                f"{etiqueta} trae columnas no aprobadas: {sorted(extra)}."
            )

        if entidad_id in entidades_vistas:
            raise ErrorValidacionEnriquecimiento(f"entidad_dedup_id duplicado: {entidad_id!r}.")
        entidades_vistas.add(entidad_id)

        posicion = registro["posicion_diversificada"]
        if not isinstance(posicion, int) or isinstance(posicion, bool):
            raise ErrorValidacionEnriquecimiento(
                f"{etiqueta}: posicion_diversificada debe ser int, llegó "
                f"{posicion!r} ({type(posicion).__name__})."
            )
        if posicion in posiciones_vistas:
            raise ErrorValidacionEnriquecimiento(f"posicion_diversificada duplicada: {posicion!r}.")
        posiciones_vistas.add(posicion)
        if not (1 <= posicion <= n_esperado):
            raise ErrorValidacionEnriquecimiento(
                f"{etiqueta}: posicion_diversificada {posicion!r} fuera del rango "
                f"esperado [1, {n_esperado}]."
            )

        resultado_match = registro["resultado_match"]
        if resultado_match not in RESULTADOS_MATCH:
            raise ErrorValidacionEnriquecimiento(
                f"{etiqueta}: resultado_match {resultado_match!r} no pertenece a la "
                f"taxonomía aprobada {RESULTADOS_MATCH}."
            )


def escribir_enriquecimiento_comercial(
    registros: list[dict],
    ruta_salida: str | Path,
    n_esperado: int,
    overwrite: bool = False,
) -> Path:
    """Valida `registros` (ver docstring del módulo) y los escribe como CSV
    en `ruta_salida`, con las 12 columnas comerciales aprobadas EN ORDEN
    (`CAMPOS_COMERCIALES`) y en el mismo orden de filas recibido -- no
    reordena por posición ni por ningún otro criterio, para que la misma
    entrada produzca siempre exactamente los mismos bytes de salida.

    `n_esperado` es obligatorio y explícito (nunca se infiere de
    `len(registros)`): es el número de prospectos del Top N de entrada que
    quien llama espera recibir de vuelta -- si no coincide, es una señal de
    que se perdieron o se inventaron filas en algún punto anterior.

    No escribe nada si cualquier registro es inválido: toda la validación
    ocurre antes de abrir el archivo. Si `ruta_salida` ya existe y
    `overwrite=False` (default), falla con `FileExistsError` sin tocar el
    archivo existente. Crea el directorio contenedor si no existe.

    Devuelve la ruta absoluta escrita.
    """
    ruta_salida = Path(ruta_salida)
    assert_no_escritura_en_raw(ruta_salida)

    _validar_registros(registros, n_esperado)

    if ruta_salida.exists() and not overwrite:
        raise FileExistsError(
            f"'{ruta_salida}' ya existe -- este escritor nunca sobrescribe en "
            "silencio. Pase overwrite=True explícitamente si de verdad quiere "
            "reemplazarlo."
        )

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    with open(ruta_salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CAMPOS_COMERCIALES), extrasaction="raise")
        writer.writeheader()
        for registro in registros:
            writer.writerow(registro)

    return ruta_salida
