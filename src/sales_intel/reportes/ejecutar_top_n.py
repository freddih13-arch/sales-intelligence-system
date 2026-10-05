"""
Ejecutor VERSIONADO del artefacto comercial Top N diversificado.

Cierra el gap de reproducibilidad identificado en la auditoría de
`03_RESULTADOS/top_prospectos/top100_diversificado_20260902_auditoria.md`
(§10 "Esquema del artefacto"): esa auditoría documenta que el CSV de
producción es el resultado de un join + rename que, hasta ahora, NUNCA
vivió en ningún archivo de código -- solo en la descripción de esa
auditoría. Este módulo es esa pieza que faltaba, versionada.

NO reimplementa NINGUNA lógica de diversificación ni de negocio: delega
TODA la selección/ranking a `diversificacion.ejecutar_diversificacion`
(que a su vez delega en `capa_diversificacion.construir_ranking_diversificado`,
sin tocarla). Este módulo solo:
1. llama a `ejecutar_diversificacion(n, entrada, config)`;
2. lee el MISMO snapshot de `empresas_scored.parquet` que usó esa llamada
   (la ruta exacta que `ejecutar_diversificacion` reporta en sus stats, no
   una ruta recalculada aparte -- garantiza que ambos leen el mismo archivo);
3. hace un join EXACTO por `entidad_dedup_id` (sin fuzzy matching, sin
   ninguna otra lógica de coincidencia) para traer las columnas comerciales
   documentadas en la auditoría;
4. aplica los renames documentados;
5. valida agresivamente antes de escribir una sola línea;
6. escribe un CSV determinista, sin sobrescribir nada en silencio.

`score_prioridad_comercial` en el artefacto final viene SIEMPRE del join
contra el snapshot scored (spec explícita de este turno) -- nunca de
`score_base` (la columna interna de `construir_ranking_diversificado`,
que no se expone en el esquema final).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sales_intel.diversificacion.capa_diversificacion import ConfiguracionDiversificacion
from sales_intel.diversificacion.ejecutar_diversificacion import ejecutar_diversificacion
from sales_intel.utils.config import assert_no_escritura_en_raw

# ---------------------------------------------------------------------------
# Esquema comercial del Top N -- EXACTAMENTE el documentado en la auditoría
# de producción 2026-09-02 (§10), en el mismo orden que el CSV ya existente
# en producción.
# ---------------------------------------------------------------------------

CAMPOS_TOP_N_COMERCIAL = (
    "posicion_diversificada", "entidad_dedup_id", "razon_social", "nit",
    "sector_vertical", "sector_bucket_diversificacion", "municipio_nombre_normalizado",
    "direccion_comercial", "telefono_comercial_1", "telefono_comercial_2",
    "telefono_comercial_3", "email_comercial", "representante_legal",
    "score_prioridad_comercial", "posicion_ranking_puro", "metodo_seleccion",
    "motivo_diversificacion", "candidato_desplazado_id", "score_candidato_desplazado",
    "diferencia_score",
)

# Columnas que se recuperan de `empresas_scored.parquet` vía join por
# `entidad_dedup_id` (spec de este turno, punto 6) -- `estado_exclusion` se
# incluye además, solo para la validación defensiva de universo, y nunca
# llega al esquema final (no está en CAMPOS_TOP_N_COMERCIAL).
_CAMPOS_JOIN_SCORED = (
    "entidad_dedup_id", "razon_social", "nit", "direccion_comercial",
    "telefono_comercial_1", "telefono_comercial_2", "telefono_comercial_3",
    "email_comercial", "representante_legal", "sector_vertical",
    "score_prioridad_comercial", "estado_exclusion",
)

# Subconjunto de los campos anteriores sobre los que se valida cobertura no
# nula (spec punto 10, "cobertura de las columnas comerciales esperadas").
# Deliberadamente NO incluye telefono_comercial_2/3, direccion_comercial ni
# representante_legal: son campos de contacto legítimamente dispersos en la
# fuente (la propia auditoría de producción del Top100 real solo garantizó
# 100% de cobertura en razon_social/telefono_comercial_1/email_comercial,
# nunca en _2/_3) -- exigirles cobertura no nula generaría falsos positivos
# en un Top N legítimo donde, por azar, nadie tenga segundo teléfono.
# `razon_social`/`nit`/`sector_vertical`/`score_prioridad_comercial` sí son
# estructurales: si vinieran 100% vacíos, es señal inequívoca de que el join
# falló silenciosamente (columna mal nombrada, snapshot equivocado), nunca
# de que la fuente legítimamente carezca del dato para las N filas.
_CAMPOS_COBERTURA_MINIMA = (
    "razon_social", "nit", "sector_vertical", "score_prioridad_comercial",
)

_RENAMES_DOCUMENTADOS = {
    "posicion_ranking_diversificado": "posicion_diversificada",
    "sector": "sector_bucket_diversificacion",
    "municipio": "municipio_nombre_normalizado",
    "candidato_desplazado": "candidato_desplazado_id",
}

_ESTADO_UNIVERSO_ESPERADO = "SIN_COINCIDENCIA"


class ErrorValidacionTopN(ValueError):
    """Cualquier violación de las invariantes del artefacto comercial Top N
    -- nunca se llega a escribir el archivo de salida si se lanza esta
    excepción."""


# ---------------------------------------------------------------------------
# Validaciones -- funciones pequeñas e independientes, cada una testeable
# por separado sin necesidad de simular un universo de diversificación
# completo para cada caso límite.
# ---------------------------------------------------------------------------

def _validar_unicidad_scored(scored: pd.DataFrame, ruta_entrada_scored: Path) -> None:
    """Spec punto 5: ANTES de cualquier join, `entidad_dedup_id` debe ser
    único en el snapshot scored. Si no lo es, no se produce ninguna
    salida."""
    if not scored["entidad_dedup_id"].is_unique:
        duplicados = scored.loc[scored["entidad_dedup_id"].duplicated(), "entidad_dedup_id"].unique().tolist()
        raise ErrorValidacionTopN(
            f"entidad_dedup_id no es único en el snapshot scored ({ruta_entrada_scored}) -- "
            f"{len(duplicados)} valores duplicados (ej. {duplicados[:5]}). No se produce ninguna salida."
        )


def _validar_todos_coinciden(merged: pd.DataFrame) -> None:
    """Spec punto 10: ningún ID del Top N puede quedar sin correspondencia
    en el snapshot scored tras el join (`merged` debe venir de un
    `pd.merge(..., indicator=True)`)."""
    sin_correspondencia = merged.loc[merged["_merge"] != "both", "entidad_dedup_id"].tolist()
    if sin_correspondencia:
        raise ErrorValidacionTopN(
            f"{len(sin_correspondencia)} entidad_dedup_id del Top N no tienen correspondencia en el "
            f"snapshot scored tras el join: {sin_correspondencia[:5]}. No se produce ninguna salida."
        )


def _validar_estado_exclusion(merged: pd.DataFrame) -> None:
    """Spec punto 10: ningún registro fuera de estado_exclusion ==
    SIN_COINCIDENCIA. `ejecutar_diversificacion` ya filtra esto antes de
    construir el ranking -- esta es una segunda comprobación defensiva
    sobre el resultado ya unido, no una re-implementación del filtro."""
    fuera_de_universo = merged.loc[merged["estado_exclusion"] != _ESTADO_UNIVERSO_ESPERADO, "entidad_dedup_id"].tolist()
    if fuera_de_universo:
        raise ErrorValidacionTopN(
            f"{len(fuera_de_universo)} entidad_dedup_id tienen estado_exclusion distinto de "
            f"'{_ESTADO_UNIVERSO_ESPERADO}' tras el join: {fuera_de_universo[:5]}. No se produce ninguna salida."
        )


def _validar_esquema_final(resultado: pd.DataFrame, n: int) -> None:
    """Spec punto 10 (resto): n filas exactas, entidad_dedup_id único,
    posicion_diversificada == {1..n} sin huecos, columnas exactas (ni una de
    más ni una de menos) y cobertura no nula de los campos comerciales
    esperados."""
    if len(resultado) != n:
        raise ErrorValidacionTopN(f"Se esperaban exactamente {n} filas, hay {len(resultado)}.")

    if not resultado["entidad_dedup_id"].is_unique:
        raise ErrorValidacionTopN("entidad_dedup_id no es único en el resultado final.")

    posiciones = set(resultado["posicion_diversificada"])
    if posiciones != set(range(1, n + 1)):
        raise ErrorValidacionTopN(
            f"posicion_diversificada no cubre exactamente 1..{n} sin huecos ni duplicados "
            f"(faltan: {sorted(set(range(1, n + 1)) - posiciones)}, sobran: {sorted(posiciones - set(range(1, n + 1)))})."
        )

    columnas_reales = set(resultado.columns)
    columnas_esperadas = set(CAMPOS_TOP_N_COMERCIAL)
    if columnas_reales != columnas_esperadas:
        raise ErrorValidacionTopN(
            f"Columnas del artefacto final no coinciden con el esquema aprobado. "
            f"Inesperadas: {sorted(columnas_reales - columnas_esperadas)}. "
            f"Faltantes: {sorted(columnas_esperadas - columnas_reales)}."
        )

    for campo in _CAMPOS_COBERTURA_MINIMA:
        if resultado[campo].notna().sum() == 0:
            raise ErrorValidacionTopN(
                f"Cobertura 0/{n} en '{campo}' -- posible fallo silencioso del join contra el "
                "snapshot scored (columna esperada, nunca debería quedar completamente vacía)."
            )


# ---------------------------------------------------------------------------
# Ejecutor
# ---------------------------------------------------------------------------

def ejecutar_top_n(
    n: int,
    entrada: str | None = None,
    config: ConfiguracionDiversificacion | None = None,
    ruta_salida: str | Path | None = None,
    overwrite: bool = False,
) -> dict:
    """Top N diversificado (`ejecutar_diversificacion`, sin tocar su
    lógica) -> join comercial por `entidad_dedup_id` contra el MISMO
    snapshot de `empresas_scored.parquet` -> validación agresiva -> CSV
    determinista en `ruta_salida`.

    `entrada`/`config` se pasan tal cual a `ejecutar_diversificacion` (ver
    ese docstring). `ruta_salida` es OBLIGATORIO Y EXPLÍCITO -- este
    ejecutor nunca elige una ruta de producción por defecto. Si
    `ruta_salida` ya existe y `overwrite=False` (default), falla con
    `FileExistsError` sin escribir nada.

    Devuelve `{'top_n_comercial': DataFrame (n filas, columnas
    CAMPOS_TOP_N_COMERCIAL), 'ruta_salida': Path, 'stats': ..., 'config':
    ...}` -- `stats`/`config` son exactamente los que devolvió
    `ejecutar_diversificacion`, sin modificar.
    """
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ValueError(f"n debe ser un entero positivo, llegó {n!r}")
    if ruta_salida is None:
        raise ValueError(
            "ruta_salida es obligatorio y explícito -- este ejecutor nunca elige una ruta de "
            "producción por defecto."
        )
    ruta_salida = Path(ruta_salida)
    assert_no_escritura_en_raw(ruta_salida)

    resultado_div = ejecutar_diversificacion(n, entrada=entrada, config=config)
    top_n = resultado_div["top_n"]

    # Punto 3: el MISMO snapshot que usó la diversificación -- se relee la
    # ruta que `ejecutar_diversificacion` reportó, nunca se recalcula aparte.
    ruta_entrada_scored = Path(resultado_div["stats"]["universo"]["entrada"])
    scored = pd.read_parquet(ruta_entrada_scored)

    _validar_unicidad_scored(scored, ruta_entrada_scored)

    columnas_faltantes = [c for c in _CAMPOS_JOIN_SCORED if c not in scored.columns]
    if columnas_faltantes:
        raise ErrorValidacionTopN(
            f"Faltan columnas en el snapshot scored ({ruta_entrada_scored}) necesarias para el "
            f"join: {columnas_faltantes}."
        )

    # Punto 4: join EXACTO por entidad_dedup_id -- sin fuzzy matching, sin
    # ninguna otra lógica de coincidencia. `validate="one_to_one"` es una
    # segunda comprobación defensiva (la unicidad del lado scored ya se
    # validó explícitamente arriba con un mensaje propio).
    merged = top_n.merge(
        scored[list(_CAMPOS_JOIN_SCORED)], on="entidad_dedup_id", how="left",
        validate="one_to_one", indicator=True,
    )
    _validar_todos_coinciden(merged)
    _validar_estado_exclusion(merged)

    merged = merged.rename(columns=_RENAMES_DOCUMENTADOS)

    columnas_finales_faltantes = [c for c in CAMPOS_TOP_N_COMERCIAL if c not in merged.columns]
    if columnas_finales_faltantes:
        raise ErrorValidacionTopN(f"Faltan columnas para el esquema final: {columnas_finales_faltantes}")

    # Orden explícito por posición (determinismo, punto 11) -- no se confía
    # en que el orden de filas sobreviva al merge, se fija aquí sin ambigüedad.
    resultado = (
        merged[list(CAMPOS_TOP_N_COMERCIAL)]
        .sort_values("posicion_diversificada", kind="mergesort")
        .reset_index(drop=True)
    )

    _validar_esquema_final(resultado, n)

    if ruta_salida.exists() and not overwrite:
        raise FileExistsError(
            f"'{ruta_salida}' ya existe -- este ejecutor nunca sobrescribe en silencio. "
            "Pase overwrite=True explícitamente si de verdad quiere reemplazarlo."
        )
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(ruta_salida, index=False)

    return {
        "top_n_comercial": resultado,
        "ruta_salida": ruta_salida,
        "stats": resultado_div["stats"],
        "config": resultado_div["config"],
    }
