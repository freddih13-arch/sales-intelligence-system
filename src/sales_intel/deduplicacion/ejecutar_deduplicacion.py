"""
Orquestación de la fase de deduplicación (conservadora) sobre
02_PROCESADAS/02_normalizado/empresas_normalizado.parquet.

DISEÑO (aprobado 2026-09-01, ver DECISIONES.md y
auditoria_previa_deduplicacion.md):

Solo dos mecanismos CONSOLIDAN (fusionan) registros automáticamente:
  1. NIT válido idéntico (excluyendo placeholders). Si el mismo NIT aparece
     en más de un municipio, se interpreta como evidencia de sucursales: se
     consolida POR (NIT, municipio), nunca se colapsan todas las sedes en
     una sola fila. Las filas de ese NIT sin municipio conocido no se
     asignan a ninguna sede específica — quedan sin consolidar.
  2. Matrícula válida + cámara/fuente compatible (nunca matrícula sola —
     confirmado en la auditoría que se reutiliza entre cámaras distintas).
     Solo aplica a registros que el NIT no logró consolidar.

Todo lo demás — razón_social+municipio y fuzzy matching — genera
CANDIDATOS (quedan marcados y trazables) pero NUNCA fusiona
automáticamente, tal como se pidió explícitamente.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from sales_intel.deduplicacion.dedup_registros import es_placeholder_identificador
from sales_intel.deduplicacion.union_find import UnionFind
from sales_intel.utils.config import (
    DEDUPLICADO_DIR,
    NORMALIZADO_DIR,
    RESULTADOS_DIR,
    cargar_mapeo_columnas,
)

UMBRAL_FUZZY_CANDIDATO = 85     # rapidfuzz token_sort_ratio (0-100)
TAMANO_MAX_BLOQUE_FUZZY = 300   # bloques (municipio+prefijo) más grandes se omiten por costo; se documenta cuántos

# Agrupación de fuentes por cámara/región de origen — SOLO para las fuentes
# que comparten un mismo espacio de numeración de matrícula (misma cámara de
# comercio) o que son un par ya documentado como casi-duplicado. Cualquier
# fuente no listada aquí se trata como su propia "cámara" (grupo de tamaño 1),
# lo que impide automáticamente cualquier cruce de matrícula entre fuentes no
# relacionadas — es el comportamiento conservador por defecto.
CAMARA_GRUPO: dict[str, str] = {
    # Cámara de Comercio de Pereira (Risaralda)
    "ccp_comerciantes_matriculados_20260125": "pereira",
    "ccp_comerciantes_registrados_20260414": "pereira",
    "empresas_con_empleados_20260122": "pereira",
    "empresas_con_empleados_20260327": "pereira",
    "empresas_y_empleados_20260327": "pereira",
    "sociedades_pereira_20260125": "pereira",
    "sociedades_bic_pereira_20260125": "pereira",
    "pymes_ccp_20260125": "pereira",
    "pymes_ccp_20260327": "pereira",
    "ciiu_g4773_farmacias_20260125": "pereira",
    "ciiu_g4773_farmacias_20260327": "pereira",
    "contadores_publicos_ccp_20260125": "pereira",
    "ferreterias_ccp_20260125": "pereira",
    "alojamiento_restaurantes_pereira_20260327": "pereira",
    # Cámara de Comercio del Magdalena Medio y Nordeste Antioqueño (CCMMNA)
    "ccmmna_general_20260414": "ccmmna",
    "ccmmna_general_20260606": "ccmmna",
    "ccmmna_empleados_20260608": "ccmmna",
    "ccmmna_pymes_20260414": "ccmmna",
    # Cámara de Comercio de Ibagué (Tolima)
    "ibague_empresas_activas_20260125": "ibague",
    "restaurantes_ibague_20260125": "ibague",
    # Cámara de Comercio de Cúcuta (Norte de Santander)
    "cucuta_empresas_20260607": "cucuta",
    "cucuta_pymes_20260607": "cucuta",
    # Par casi-duplicado documentado en la auditoría original (mismo
    # contenido, dos exportaciones con distinta codificación)
    "cx_plastica_20250701": "cx_plastica_par",
    "medicos_clinicas_esteticas": "cx_plastica_par",
}


def _camara_de(source_id: str) -> str:
    return CAMARA_GRUPO.get(source_id, source_id)


def ejecutar_deduplicacion() -> dict:
    ruta_entrada = NORMALIZADO_DIR / "empresas_normalizado.parquet"
    df = pd.read_parquet(ruta_entrada).reset_index(drop=True)
    n = len(df)
    esquema = cargar_mapeo_columnas()["esquema_canonico"]

    # --- columnas de trabajo (no se escriben de vuelta al archivo de entrada) ---
    nit_es_placeholder = df["nit"].map(lambda v: es_placeholder_identificador(v) if pd.notna(v) else True)
    df["nit_valido"] = df["nit"].where(df["nit"].notna() & ~nit_es_placeholder)

    mat_es_placeholder = df["matricula"].map(lambda v: es_placeholder_identificador(v) if pd.notna(v) else True)
    df["matricula_valida"] = df["matricula"].where(df["matricula"].notna() & ~mat_es_placeholder)

    df["camara_grupo"] = df["source_id"].map(_camara_de)
    df["completitud"] = df[esquema].notna().sum(axis=1)

    uf = UnionFind(n)
    metodo: list[str | None] = [None] * n
    confianza: list[str | None] = [None] * n
    candidato_grupo_id: list[str | None] = [None] * n
    candidato_metodo: list[str | None] = [None] * n
    candidato_confianza: list[str | None] = [None] * n

    # =========================================================================
    # PASE 1 — NIT válido (con partición por municipio si hay evidencia de sucursales)
    # =========================================================================
    n_grupos_nit = n_registros_nit = n_nit_multisede = n_filas_nit_multisede_sin_municipio = 0
    validos = df.loc[df["nit_valido"].notna(), ["nit_valido", "municipio_nombre_normalizado"]]
    for nit_val, sub in validos.groupby("nit_valido", sort=False):
        municipios = sub["municipio_nombre_normalizado"].dropna().unique()
        if len(municipios) <= 1:
            idxs = sub.index.tolist()
            if len(idxs) > 1:
                base = idxs[0]
                for i in idxs[1:]:
                    uf.union(base, i)
                for i in idxs:
                    metodo[i] = "nit"
                    confianza[i] = "alta"
                n_grupos_nit += 1
                n_registros_nit += len(idxs)
        else:
            n_nit_multisede += 1
            for muni, subsub in sub.groupby("municipio_nombre_normalizado"):
                idxs = subsub.index.tolist()
                if len(idxs) > 1:
                    base = idxs[0]
                    for i in idxs[1:]:
                        uf.union(base, i)
                    for i in idxs:
                        metodo[i] = "nit_multisede"
                        confianza[i] = "alta"
                    n_grupos_nit += 1
                    n_registros_nit += len(idxs)
            n_filas_nit_multisede_sin_municipio += int(sub["municipio_nombre_normalizado"].isna().sum())

    # =========================================================================
    # PASE 2 — matrícula válida + cámara/fuente compatible (solo filas aún sin método)
    # =========================================================================
    sin_metodo = np.array([m is None for m in metodo])
    cand2 = df.loc[sin_metodo & df["matricula_valida"].notna(), ["matricula_valida", "camara_grupo"]]
    n_grupos_matricula = n_registros_matricula = 0
    for (mat, cam), sub in cand2.groupby(["matricula_valida", "camara_grupo"], sort=False):
        idxs = sub.index.tolist()
        if len(idxs) > 1:
            base = idxs[0]
            for i in idxs[1:]:
                uf.union(base, i)
            for i in idxs:
                metodo[i] = "matricula_camara"
                confianza[i] = "media_alta"
            n_grupos_matricula += 1
            n_registros_matricula += len(idxs)

    # =========================================================================
    # PASE 3 — candidatos por razón_social + municipio (NUNCA fusiona)
    # =========================================================================
    sin_metodo = np.array([m is None for m in metodo])
    cand3 = df.loc[
        sin_metodo & df["razon_social_normalizada"].notna() & df["municipio_nombre_normalizado"].notna(),
        ["razon_social_normalizada", "municipio_nombre_normalizado", "direccion_comercial",
         "telefono_comercial_1", "email_comercial"],
    ]
    n_grupos_rs_mun = n_registros_rs_mun = n_grupos_rs_mun_corroborados = 0
    contador_rs = 0
    for (rs, mun), sub in cand3.groupby(["razon_social_normalizada", "municipio_nombre_normalizado"], sort=False):
        if len(sub) > 1:
            idxs = sub.index.tolist()
            contador_rs += 1
            gid = f"CAND-RSMUN-{contador_rs:06d}"
            corrobora_dir = sub["direccion_comercial"].notna().all() and sub["direccion_comercial"].nunique() == 1
            corrobora_tel = sub["telefono_comercial_1"].notna().all() and sub["telefono_comercial_1"].nunique() == 1
            corrobora_email = sub["email_comercial"].notna().all() and sub["email_comercial"].nunique() == 1
            corroborado = corrobora_dir or corrobora_tel or corrobora_email
            for i in idxs:
                candidato_grupo_id[i] = gid
                candidato_metodo[i] = "razon_social+municipio"
                candidato_confianza[i] = "media" if corroborado else "baja"
            n_grupos_rs_mun += 1
            n_registros_rs_mun += len(idxs)
            if corroborado:
                n_grupos_rs_mun_corroborados += 1

    # =========================================================================
    # PASE 4 — candidatos por fuzzy matching (RapidFuzz), NUNCA fusiona
    # =========================================================================
    sin_metodo = np.array([m is None for m in metodo])
    sin_candidato = np.array([c is None for c in candidato_grupo_id])
    elegibles = df.loc[
        sin_metodo & sin_candidato & df["razon_social_normalizada"].notna() & df["municipio_nombre_normalizado"].notna(),
        ["razon_social_normalizada", "municipio_nombre_normalizado"],
    ].copy()
    elegibles["prefijo"] = elegibles["razon_social_normalizada"].str[:4]

    n_grupos_fuzzy = n_registros_fuzzy = 0
    n_bloques_omitidos_por_tamano = n_registros_en_bloques_omitidos = 0
    contador_fuzzy = 0
    for (mun, pref), bloque in elegibles.groupby(["municipio_nombre_normalizado", "prefijo"], sort=False):
        if len(bloque) < 2:
            continue
        if len(bloque) > TAMANO_MAX_BLOQUE_FUZZY:
            n_bloques_omitidos_por_tamano += 1
            n_registros_en_bloques_omitidos += len(bloque)
            continue
        nombres = bloque["razon_social_normalizada"].tolist()
        idxs = bloque.index.tolist()
        usados: set[int] = set()
        for a in range(len(nombres)):
            if idxs[a] in usados:
                continue
            grupo_actual = [idxs[a]]
            for b in range(a + 1, len(nombres)):
                if idxs[b] in usados:
                    continue
                score = fuzz.token_sort_ratio(nombres[a], nombres[b])
                if score >= UMBRAL_FUZZY_CANDIDATO:
                    grupo_actual.append(idxs[b])
            if len(grupo_actual) > 1:
                contador_fuzzy += 1
                gid = f"CAND-FUZZY-{contador_fuzzy:06d}"
                for i in grupo_actual:
                    usados.add(i)
                    candidato_grupo_id[i] = gid
                    candidato_metodo[i] = "fuzzy_razon_social"
                    candidato_confianza[i] = "baja"
                n_grupos_fuzzy += 1
                n_registros_fuzzy += len(grupo_actual)

    # =========================================================================
    # Ensamblar entidad_dedup_id a partir de las raíces del union-find
    # =========================================================================
    roots = [uf.find(i) for i in range(n)]
    root_a_id: dict[int, str] = {}
    entidad_ids: list[str] = []
    contador_ent = 0
    for r in roots:
        eid = root_a_id.get(r)
        if eid is None:
            contador_ent += 1
            eid = f"ENT-{contador_ent:07d}"
            root_a_id[r] = eid
        entidad_ids.append(eid)

    metodo_final = [m if m is not None else "sin_consolidar" for m in metodo]

    df["entidad_dedup_id"] = entidad_ids
    df["metodo_deduplicacion"] = metodo_final
    df["confianza_deduplicacion"] = confianza
    df["candidato_grupo_id"] = candidato_grupo_id
    df["candidato_metodo"] = candidato_metodo
    df["candidato_confianza"] = candidato_confianza
    df["_orden_original"] = np.arange(n)

    tamano_grupo = df.groupby("entidad_dedup_id")["entidad_dedup_id"].transform("size")
    df["tamano_grupo"] = tamano_grupo

    # Registro maestro por entidad: mayor completitud, desempate por orden original
    df_orden_maestro = df.sort_values(
        ["entidad_dedup_id", "completitud", "_orden_original"], ascending=[True, False, True]
    )
    es_maestro = ~df_orden_maestro["entidad_dedup_id"].duplicated(keep="first")
    df_orden_maestro = df_orden_maestro.assign(es_registro_maestro=es_maestro)
    # devolver al orden original para el archivo de grupos (más legible)
    df = df.merge(
        df_orden_maestro[["_orden_original", "es_registro_maestro"]], on="_orden_original", how="left"
    )

    # =========================================================================
    # empresas_deduplicado.parquet (1 fila por entidad)
    # =========================================================================
    campos_identidad_maestro = ["source_id", "fuente_archivo", "hoja_origen", "fila_origen"]
    maestro = (
        df_orden_maestro.groupby("entidad_dedup_id", sort=False)[campos_identidad_maestro + esquema]
        .first()
        .reset_index()
    )

    n_fuentes = df.groupby("entidad_dedup_id")["source_id"].nunique()
    fuentes_str = df.groupby("entidad_dedup_id")["source_id"].apply(lambda s: ";".join(sorted(s.unique())))
    registros_consolidados = df.groupby("entidad_dedup_id").size()
    metodo_predom = df.groupby("entidad_dedup_id")["metodo_deduplicacion"].first()
    confianza_predom = df.groupby("entidad_dedup_id")["confianza_deduplicacion"].first()

    # --- detección de conflictos de valor dentro de cada entidad (solo entidades con >1 registro) ---
    multi = df[df["tamano_grupo"] > 1]
    campos_en_conflicto = pd.Series("", index=maestro["entidad_dedup_id"], dtype=object)
    detalle_conflictos = pd.Series("", index=maestro["entidad_dedup_id"], dtype=object)
    if len(multi):
        nunique_por_campo = {campo: multi.groupby("entidad_dedup_id")[campo].nunique(dropna=True) for campo in esquema}
        conflicto_df = pd.DataFrame(nunique_por_campo) > 1
        entidades_con_conflicto = conflicto_df[conflicto_df.any(axis=1)].index
        for eid in entidades_con_conflicto:
            campos_afectados = [c for c in esquema if conflicto_df.loc[eid, c]]
            campos_en_conflicto.loc[eid] = ";".join(campos_afectados)
        if len(entidades_con_conflicto):
            subset = multi[multi["entidad_dedup_id"].isin(entidades_con_conflicto)]
            for eid, grupo in subset.groupby("entidad_dedup_id"):
                campos_afectados = campos_en_conflicto.loc[eid].split(";")
                d = {}
                for c in campos_afectados:
                    vals = sorted(v for v in grupo[c].dropna().unique().tolist())
                    if len(vals) > 1:
                        d[c] = vals
                detalle_conflictos.loc[eid] = json.dumps(d, ensure_ascii=False)

    maestro = maestro.set_index("entidad_dedup_id")
    maestro["numero_fuentes_consolidadas"] = n_fuentes
    maestro["fuentes_consolidadas"] = fuentes_str
    maestro["registros_consolidados"] = registros_consolidados
    maestro["metodo_deduplicacion"] = metodo_predom
    maestro["confianza_deduplicacion"] = confianza_predom
    maestro["campos_en_conflicto"] = campos_en_conflicto
    maestro["detalle_conflictos"] = detalle_conflictos
    maestro["es_registro_maestro"] = True
    maestro["fecha_deduplicacion_utc"] = datetime.now(timezone.utc).isoformat()
    maestro = maestro.reset_index()

    # =========================================================================
    # Escritura de salidas
    # =========================================================================
    DEDUPLICADO_DIR.mkdir(parents=True, exist_ok=True)
    destino_maestro = DEDUPLICADO_DIR / "empresas_deduplicado.parquet"
    maestro.to_parquet(destino_maestro, index=False)

    columnas_grupos = [
        "source_id", "hoja_origen", "fila_origen", "fuente_archivo",
        "entidad_dedup_id", "tamano_grupo", "metodo_deduplicacion", "confianza_deduplicacion",
        "es_registro_maestro", "candidato_grupo_id", "candidato_metodo", "candidato_confianza",
    ]
    grupos = df[columnas_grupos].copy()
    destino_grupos = RESULTADOS_DIR / "grupos_deduplicacion.parquet"
    grupos.to_parquet(destino_grupos, index=False)

    stats = {
        "registros_entrada": n,
        "registros_salida": len(maestro),
        "n_grupos_nit": n_grupos_nit,
        "n_registros_nit": n_registros_nit,
        "n_nit_multisede": n_nit_multisede,
        "n_filas_nit_multisede_sin_municipio": n_filas_nit_multisede_sin_municipio,
        "n_grupos_matricula": n_grupos_matricula,
        "n_registros_matricula": n_registros_matricula,
        "n_grupos_rs_mun": n_grupos_rs_mun,
        "n_registros_rs_mun": n_registros_rs_mun,
        "n_grupos_rs_mun_corroborados": n_grupos_rs_mun_corroborados,
        "n_grupos_fuzzy": n_grupos_fuzzy,
        "n_registros_fuzzy": n_registros_fuzzy,
        "n_bloques_fuzzy_omitidos": n_bloques_omitidos_por_tamano,
        "n_registros_en_bloques_omitidos": n_registros_en_bloques_omitidos,
    }

    return {
        "df_grupos": grupos,
        "df_maestro": maestro,
        "stats": stats,
        "destino_maestro": destino_maestro,
        "destino_grupos": destino_grupos,
    }
