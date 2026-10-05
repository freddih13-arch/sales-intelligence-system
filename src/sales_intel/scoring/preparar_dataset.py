"""
Preparación del dataset para el futuro Score de Prioridad Comercial.

NO calcula ningún score, NO asigna pesos, NO genera rankings. Solo corrige
defectos de datos ya identificados en la auditoría de variables y persiste
variables derivadas usando ÚNICAMENTE lógica ya existente en el código.

Reglas duras de este módulo:
  - Nunca escribe sobre 01_BASES_RAW, 01_ingesta, empresas_normalizado.parquet,
    empresas_deduplicado.parquet ni empresas_con_exclusion.parquet — todos se
    abren solo en modo lectura. La corrección de tamano_empresa se REcalcula
    en memoria (reproduciendo el mismo criterio de selección de "registro
    maestro" de la fase de deduplicación) y se escribe únicamente en el
    dataset nuevo de 06_scoring/.
  - Ningún valor faltante se convierte en 0 ni se imputa. Los valores
    claramente inválidos se convierten en NULL, nunca en una estimación.
  - No se elimina ninguna entidad.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

from sales_intel.enriquecimiento.mapeo_sectorial import obtener_sector_comercial
from sales_intel.normalizacion.ejecutar_normalizacion import _limpiar_texto_ligero
from sales_intel.normalizacion.normalizador_geografico import extraer_codigo_dane_si_viene_incluido
from sales_intel.utils.config import (
    DEDUPLICADO_DIR,
    EXCLUSION_DIR,
    INGESTA_DIR,
    NORMALIZADO_DIR,
    RESULTADOS_DIR,
    SCORING_DIR,
    cargar_mapeo_columnas,
)

UMBRAL_NUM_EMPLEADOS_IMPLAUSIBLE = 100_000  # ver reporte: salto natural en los datos (60,000 -> 100,000 -> millones)
FUENTE_CONTAMINADA_TAMANO = "ibague_empresas_activas_20260125"


# ---------------------------------------------------------------------------
# 1. Corrección de tamano_empresa (re-simulación fiel de la selección de
#    registro maestro de la fase de deduplicación, con el valor corregido)
# ---------------------------------------------------------------------------

def _recalcular_tamano_empresa_por_entidad() -> tuple[pd.Series, dict]:
    esquema = cargar_mapeo_columnas()["esquema_canonico"]

    norm = pd.read_parquet(NORMALIZADO_DIR / "empresas_normalizado.parquet")
    grupos = pd.read_parquet(
        RESULTADOS_DIR / "grupos_deduplicacion.parquet",
        columns=["source_id", "hoja_origen", "fila_origen", "entidad_dedup_id"],
    )

    # Completitud calculada con los valores ORIGINALES (incluida la
    # contaminación) para reproducir EXACTAMENTE el mismo orden de
    # desempate que usó la deduplicación real — así el único cambio es el
    # CONTENIDO de tamano_empresa, nunca qué fila "gana" para los demás
    # campos.
    completitud_original = norm[esquema].notna().sum(axis=1)

    ib = pd.read_parquet(
        INGESTA_DIR / f"{FUENTE_CONTAMINADA_TAMANO}__ingestado.parquet",
        columns=["source_id", "fila_origen", "TAMAÑO EMPRESA"],
    )
    ib["tamano_empresa_corregido"] = ib["TAMAÑO EMPRESA"].map(_limpiar_texto_ligero)
    ib = ib.drop(columns=["TAMAÑO EMPRESA"])

    n_antes_contaminado = int(
        (norm["tamano_empresa"].dropna().str.match(r"^[A-Z]\d{3,4}$")).sum()
    )

    trabajo = norm[["source_id", "hoja_origen", "fila_origen", "tamano_empresa"]].copy()
    trabajo = trabajo.merge(ib, on=["source_id", "fila_origen"], how="left")
    es_fuente_afectada = trabajo["source_id"] == FUENTE_CONTAMINADA_TAMANO
    trabajo["tamano_empresa_final"] = trabajo["tamano_empresa"]
    trabajo.loc[es_fuente_afectada, "tamano_empresa_final"] = trabajo.loc[es_fuente_afectada, "tamano_empresa_corregido"]

    trabajo = trabajo.merge(grupos, on=["source_id", "hoja_origen", "fila_origen"], how="left")
    trabajo["completitud_original"] = completitud_original.values
    trabajo["_orden_original"] = range(len(trabajo))

    trabajo_sorted = trabajo.sort_values(
        ["entidad_dedup_id", "completitud_original", "_orden_original"], ascending=[True, False, True]
    )
    tamano_por_entidad = trabajo_sorted.groupby("entidad_dedup_id", sort=False)["tamano_empresa_final"].first()

    n_despues_contaminado = int(tamano_por_entidad.dropna().str.match(r"^[A-Z]\d{3,4}$").sum())

    stats = {
        "n_filas_recalculadas_fuente_afectada": int(es_fuente_afectada.sum()),
        "n_entidad_valores_ciiu_antes": n_antes_contaminado,
        "n_entidad_valores_ciiu_despues": n_despues_contaminado,
    }
    return tamano_por_entidad, stats


# ---------------------------------------------------------------------------
# 2. num_empleados — anomalías a NULL (validación por valor, no requiere
#    tocar la fase de mapeo/dedup)
# ---------------------------------------------------------------------------

def _corregir_num_empleados(serie: pd.Series) -> tuple[pd.Series, pd.Series, dict]:
    es_numerico = serie.notna() & serie.str.match(r"^\d+$", na=False)
    valor_numerico = pd.to_numeric(serie.where(es_numerico), errors="coerce")

    anomalo = valor_numerico >= UMBRAL_NUM_EMPLEADOS_IMPLAUSIBLE
    anomalo = anomalo.fillna(False)

    corregido = serie.where(~anomalo, other=None)

    rango_antes = (int(valor_numerico.min()) if valor_numerico.notna().any() else None,
                   int(valor_numerico.max()) if valor_numerico.notna().any() else None)
    valores_ok = valor_numerico.where(~anomalo)
    rango_despues = (int(valores_ok.min()) if valores_ok.notna().any() else None,
                      int(valores_ok.max()) if valores_ok.notna().any() else None)

    stats = {
        "umbral_usado": UMBRAL_NUM_EMPLEADOS_IMPLAUSIBLE,
        "n_corregidos_a_null": int(anomalo.sum()),
        "rango_antes": rango_antes,
        "rango_despues": rango_despues,
        "criterio": (
            f"num_empleados puramente numérico y >= {UMBRAL_NUM_EMPLEADOS_IMPLAUSIBLE:,} se considera "
            "implausible para una entidad registrada regionalmente. Hay un salto natural en los datos: "
            "el mayor valor 'creíble' observado es 60,000 y el siguiente valor es 100,000, seguido de "
            "cifras que llegan a decenas de millones — consistente con cifras monetarias mal separadas, "
            "no con conteo de personal. Los valores entre 1,000 y 60,000 NO se tocan (son altos pero no "
            "'claramente imposibles')."
        ),
    }
    return corregido, anomalo, stats


# ---------------------------------------------------------------------------
# 3. sector_vertical (reutiliza obtener_sector_comercial, sin inventar categorías)
# ---------------------------------------------------------------------------

def _derivar_sector_vertical(ciiu_1: pd.Series) -> tuple[pd.Series, pd.Series, dict]:
    # obtener_sector_comercial() relee config/mapeo_ciiu_sector.yaml en cada
    # llamada — con ~1,360 valores distintos de ciiu_1 (de 408,907 filas) se
    # resuelve una sola vez por valor distinto, no por fila.
    valores_distintos = ciiu_1.dropna().unique()
    lookup = {v: obtener_sector_comercial(v) for v in valores_distintos}

    resultados = ciiu_1.map(lookup)
    sector_vertical = resultados.map(lambda d: d["sector_comercial"] if isinstance(d, dict) else None)
    encaje_declarado = resultados.map(lambda d: d["encaje_pagos"] if isinstance(d, dict) else None)

    con_ciiu = ciiu_1.notna()
    no_mapeado = con_ciiu & sector_vertical.isna()
    ciiu_no_mapeados = ciiu_1[no_mapeado].value_counts()

    stats = {
        "con_ciiu_1": int(con_ciiu.sum()),
        "mapeados": int((con_ciiu & sector_vertical.notna()).sum()),
        "no_mapeados": int(no_mapeado.sum()),
        "ciiu_no_mapeados_top": ciiu_no_mapeados.head(20).to_dict(),
        "distribucion_sector": sector_vertical.value_counts(dropna=False).to_dict(),
    }
    return sector_vertical, encaje_declarado, stats


# ---------------------------------------------------------------------------
# 4. Geografía — extracción mecánica de código embebido + bandera de ambigüedad
#    recalculada a nivel de la población final de entidades (no por fuente,
#    como en normalización, sino sobre el dataset consolidado).
# ---------------------------------------------------------------------------

def _derivar_geografia(municipio_comercial: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series, dict]:
    extraido = municipio_comercial.map(extraer_codigo_dane_si_viene_incluido)
    codigo = extraido.map(lambda t: t[0])
    nombre = extraido.map(lambda t: t[1])

    tmp = pd.DataFrame({"nombre": nombre, "codigo": codigo}).dropna()
    ambiguos = set()
    if not tmp.empty:
        conteo = tmp.groupby("nombre")["codigo"].nunique()
        ambiguos = set(conteo[conteo > 1].index)
    flag_ambiguo = nombre.isin(ambiguos)

    stats = {
        "con_municipio_comercial": int(municipio_comercial.notna().sum()),
        "con_codigo_dane_extraido": int(codigo.notna().sum()),
        "con_municipio_normalizado": int(nombre.notna().sum()),
        "n_flag_ambiguo": int(flag_ambiguo.sum()),
        "n_nombres_ambiguos_distintos": len(ambiguos),
    }
    return nombre, codigo, flag_ambiguo, stats


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def preparar_dataset_scoring() -> dict:
    excl = pd.read_parquet(EXCLUSION_DIR / "empresas_con_exclusion.parquet").reset_index(drop=True)
    n = len(excl)

    # --- 1. tamano_empresa ---
    tamano_corregido, stats_tamano = _recalcular_tamano_empresa_por_entidad()
    tamano_corregido = tamano_corregido.reindex(excl["entidad_dedup_id"]).reset_index(drop=True)
    excl["tamano_empresa_original"] = excl["tamano_empresa"]
    excl["tamano_empresa"] = tamano_corregido
    excl["tamano_empresa_corregido_flag"] = (
        excl["tamano_empresa_original"].notna()
        & excl["tamano_empresa_original"].str.match(r"^[A-Z]\d{3,4}$", na=False)
    )

    # --- 2. num_empleados ---
    num_emp_corregido, anomalo_flag, stats_num_emp = _corregir_num_empleados(excl["num_empleados"])
    excl["num_empleados_original"] = excl["num_empleados"]
    excl["num_empleados"] = num_emp_corregido
    excl["num_empleados_anomalia_flag"] = anomalo_flag

    # --- 3. sector_vertical ---
    sector_vertical, encaje_declarado, stats_sector = _derivar_sector_vertical(excl["ciiu_1"])
    excl["sector_vertical"] = sector_vertical
    excl["encaje_pagos_declarado"] = encaje_declarado

    # --- 4. geografía ---
    municipio_norm, codigo_dane, flag_ambiguo, stats_geo = _derivar_geografia(excl["municipio_comercial"])
    excl["municipio_nombre_normalizado"] = municipio_norm
    excl["municipio_codigo_dane_extraido"] = codigo_dane
    excl["flag_codigo_dane_ambiguo"] = flag_ambiguo

    # --- 5. contactabilidad: verificación de disponibilidad, sin fórmula nueva ---
    stats_contacto = {
        "telefono_comercial_1": int(excl["telefono_comercial_1"].notna().sum()),
        "email_comercial": int(excl["email_comercial"].notna().sum()),
        "direccion_comercial": int(excl["direccion_comercial"].notna().sum()),
    }

    # --- 6. calidad: se conservan tal cual, no se usan como score ---
    excl["fecha_preparacion_scoring_utc"] = datetime.now(timezone.utc).isoformat()

    SCORING_DIR.mkdir(parents=True, exist_ok=True)
    destino = SCORING_DIR / "dataset_preparado_scoring.parquet"
    excl.to_parquet(destino, index=False)

    return {
        "df": excl,
        "n": n,
        "destino": destino,
        "stats_tamano": stats_tamano,
        "stats_num_emp": stats_num_emp,
        "stats_sector": stats_sector,
        "stats_geo": stats_geo,
        "stats_contacto": stats_contacto,
    }
