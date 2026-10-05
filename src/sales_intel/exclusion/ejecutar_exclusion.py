"""
Orquestación de la fase de exclusión contra Client (CRM + HUBS).

PRINCIPIO NO NEGOCIABLE: las 5 fuentes internas de Client se leen SOLO para
extraer identificadores empresariales mínimos (NIT, matrícula, razón social
normalizada, municipio, y — solo para el CRM — un tipo de antecedente y una
fecha de referencia). Nunca se copian nombres de asesores, teléfonos/emails
(personales o comerciales), direcciones ni comentarios internos. Las fuentes
internas NUNCA se incorporan como registros de prospecto.

Diseño (ver DECISIONES.md):
  - NIT válido exacto (ignorando placeholders) -> EXCLUSION_ALTA.
  - Matrícula válida + contexto de cámara compatible (reutilizando
    CAMARA_GRUPO de la fase de deduplicación) -> EXCLUSION_MEDIA. Nunca
    matrícula sola.
  - Razón_social (+municipio si hay) exacta o por fuzzy matching ->
    CANDIDATO_AMBIGUO. Nunca exclusión automática.
  - Ante duda, CANDIDATO_AMBIGUO, nunca EXCLUSION_*  (preferir falso
    negativo sobre falso positivo, tal como se pidió).
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from sales_intel.deduplicacion.dedup_registros import es_placeholder_identificador
from sales_intel.deduplicacion.ejecutar_deduplicacion import CAMARA_GRUPO
from sales_intel.normalizacion.limpieza import normalizar_nit, normalizar_texto
from sales_intel.normalizacion.normalizador_geografico import extraer_codigo_dane_si_viene_incluido
from sales_intel.utils.config import DEDUPLICADO_DIR, EXCLUSION_DIR, INGESTA_DIR, RESULTADOS_DIR

UMBRAL_FUZZY_CANDIDATO = 85
TAMANO_MAX_BLOQUE_FUZZY = 300

FUENTES_INTERNAS = [
    "crm_detalle_lead_oportunidades",
    "hubs_pereira_2026_base",
    "hubs_pereira_2026_v3",
    "hubs_pereira_2026_primera_toma",
    "hubs_para_hubs_curada",
]


def _valido_nit(valor: str | None) -> str | None:
    # pd.NA no es 'is None' (ver bug corregido en la fase de normalización) —
    # normalizar_nit ya se comporta bien con pd.NA (str(pd.NA)="<NA>" no
    # tiene dígitos -> devuelve None), pero se agrega el chequeo explícito
    # por claridad y como salvaguarda si esa función cambia en el futuro.
    if valor is None or pd.isna(valor):
        return None
    n = normalizar_nit(valor)
    if n and not es_placeholder_identificador(n):
        return n
    return None


def _valido_matricula(valor: str | None) -> str | None:
    # Chequeo explícito de pd.isna: sin él, un valor faltante de pandas
    # (pd.NA) se convertía en el texto literal "<NA>", que NO coincide con
    # el patrón de placeholder (dígito repetido) y por lo tanto se colaba
    # como si fuera una matrícula válida — mismo bug ya visto y corregido en
    # normalización, atajado aquí antes de ejecutar.
    if valor is None or pd.isna(valor):
        return None
    v = str(valor).strip()
    if not v or es_placeholder_identificador(v):
        return None
    return v


# ---------------------------------------------------------------------------
# Extracción — CRM
# ---------------------------------------------------------------------------

def _clasificar_antecedente_crm(df: pd.DataFrame) -> pd.Series:
    """Distingue lead / oportunidad calificada / cliente convertido / cliente
    previo / sin resolución clara, usando SOLO los campos de estado ya
    presentes en el CRM (sin inventar), en orden de prioridad descendente."""
    condiciones = [
        df["Convertido"] == "1",
        df["cliente_antiguo"] == "1",
        df["Descartado"] == "1",
        df["Calificado"] == "1",
    ]
    resultados = ["cliente_convertido", "cliente_previo", "lead_descartado", "oportunidad_calificada"]
    return pd.Series(np.select(condiciones, resultados, default="lead_sin_resolucion_clara"), index=df.index)


def _extraer_claves_crm() -> tuple[pd.DataFrame, dict]:
    df = pd.read_parquet(INGESTA_DIR / "crm_detalle_lead_oportunidades__ingestado.parquet")
    n = len(df)

    # Solo se usa numero_documento como NIT cuando tipo_documento == "NIT"
    # explícitamente — nunca cédulas de la persona de contacto (ver
    # DECISIONES.md, punto abierto #1, resuelto en esta fase).
    nit_bruto = df["numero_documento"].where(df["tipo_documento"] == "NIT")
    nit_valido = nit_bruto.map(_valido_nit)

    out = pd.DataFrame({
        "fuente_interna": "crm_detalle_lead_oportunidades",
        "nit_valido": nit_valido,
        "matricula_valida": None,  # el CRM no tiene matrícula
        "razon_social_normalizada": df["nombre_comercio_lead"].map(normalizar_texto),
        "municipio_normalizado": df["ciudad"].map(normalizar_texto),
        "fecha_referencia": df["ultima_actualizacion"].where(df["ultima_actualizacion"].fillna("") != ""),
        "tipo_antecedente": _clasificar_antecedente_crm(df),
    })

    n_con_nit = int(nit_valido.notna().sum())
    n_sin_identificador_alguno = int(
        (nit_valido.isna() & out["razon_social_normalizada"].isna()).sum()
    )
    stats = {
        "registros": n,
        "con_nit_valido": n_con_nit,
        "con_solo_cedula_u_otro_doc": int((df["tipo_documento"] != "NIT").sum() - (df["tipo_documento"] == "").sum()),
        "sin_documento": int((df["tipo_documento"] == "").sum()),
        "sin_ningun_identificador_util": n_sin_identificador_alguno,
    }
    return out, stats


# ---------------------------------------------------------------------------
# Extracción — HUBS (columnas nombradas: MATRICULA/IDENTIFICACION/...)
# ---------------------------------------------------------------------------

def _extraer_claves_hubs_nombradas(df: pd.DataFrame, fuente_interna: str) -> pd.DataFrame:
    return pd.DataFrame({
        "fuente_interna": fuente_interna,
        "nit_valido": df["IDENTIFICACION"].map(_valido_nit) if "IDENTIFICACION" in df.columns else None,
        "matricula_valida": df["MATRICULA"].map(_valido_matricula) if "MATRICULA" in df.columns else None,
        "razon_social_normalizada": df["RAZON SOCIAL"].map(normalizar_texto) if "RAZON SOCIAL" in df.columns else None,
        "municipio_normalizado": df["MUNICIPIO COMERCIAL"].map(normalizar_texto) if "MUNICIPIO COMERCIAL" in df.columns else None,
        "fecha_referencia": df["AÑO DE MATRICULA"] if "AÑO DE MATRICULA" in df.columns else None,
        "tipo_antecedente": None,  # no aplica fuera del CRM
    })


# ---------------------------------------------------------------------------
# Extracción — hojas HUBS sin encabezado (posicional, ver leer_xlsx.py)
# col_0=asesor(no se usa) col_2=matricula col_4=razon_social col_5=NIT
# col_6=año_matricula col_9=municipio — verificado contra 01_BASES_RAW en esta
# misma fase (confirmado con openpyxl sobre las 3 filas de MILTON OSORIO y
# las 520 de "BASE DE DATOS PARA HUBS.xlsx").
# ---------------------------------------------------------------------------

def _extraer_claves_hubs_posicional(df: pd.DataFrame, fuente_interna: str) -> pd.DataFrame:
    return pd.DataFrame({
        "fuente_interna": fuente_interna,
        "nit_valido": df["col_5"].map(_valido_nit),
        "matricula_valida": df["col_2"].map(_valido_matricula),
        "razon_social_normalizada": df["col_4"].map(normalizar_texto),
        "municipio_normalizado": df["col_9"].map(normalizar_texto),
        "fecha_referencia": df["col_6"],
        "tipo_antecedente": None,
    })


def _extraer_todas_las_claves_internas() -> tuple[pd.DataFrame, dict]:
    bloques = []
    stats_por_fuente: dict[str, dict] = {}

    crm_claves, crm_stats = _extraer_claves_crm()
    bloques.append(crm_claves)
    stats_por_fuente["crm_detalle_lead_oportunidades"] = crm_stats

    base = pd.read_parquet(INGESTA_DIR / "hubs_pereira_2026_base__ingestado.parquet")
    claves_base = _extraer_claves_hubs_nombradas(base, "hubs_pereira_2026_base")
    bloques.append(claves_base)
    stats_por_fuente["hubs_pereira_2026_base"] = _stats_hubs(base, claves_base)

    v3 = pd.read_parquet(INGESTA_DIR / "hubs_pereira_2026_v3__ingestado.parquet")
    v3_nombrada = v3[v3["hoja_origen"] == "Basemaestra"]
    v3_posicional = v3[v3["hoja_origen"] != "Basemaestra"]
    claves_v3 = pd.concat([
        _extraer_claves_hubs_nombradas(v3_nombrada, "hubs_pereira_2026_v3"),
        _extraer_claves_hubs_posicional(v3_posicional, "hubs_pereira_2026_v3"),
    ], ignore_index=True)
    bloques.append(claves_v3)
    stats_por_fuente["hubs_pereira_2026_v3"] = _stats_hubs(v3, claves_v3)

    primera_toma = pd.read_parquet(INGESTA_DIR / "hubs_pereira_2026_primera_toma__ingestado.parquet")
    claves_pt = _extraer_claves_hubs_nombradas(primera_toma, "hubs_pereira_2026_primera_toma")
    bloques.append(claves_pt)
    stats_por_fuente["hubs_pereira_2026_primera_toma"] = _stats_hubs(primera_toma, claves_pt)

    curada = pd.read_parquet(INGESTA_DIR / "hubs_para_hubs_curada__ingestado.parquet")
    claves_curada = _extraer_claves_hubs_posicional(curada, "hubs_para_hubs_curada")
    bloques.append(claves_curada)
    stats_por_fuente["hubs_para_hubs_curada"] = _stats_hubs(curada, claves_curada)

    combinado = pd.concat(bloques, ignore_index=True)
    return combinado, stats_por_fuente


def _stats_hubs(df_original: pd.DataFrame, claves: pd.DataFrame) -> dict:
    sin_nada = claves["nit_valido"].isna() & claves["matricula_valida"].isna() & claves["razon_social_normalizada"].isna()
    return {
        "registros": len(df_original),
        "con_nit_valido": int(claves["nit_valido"].notna().sum()),
        "con_matricula_valida": int(claves["matricula_valida"].notna().sum()),
        "sin_ningun_identificador_util": int(sin_nada.sum()),
    }


# ---------------------------------------------------------------------------
# Matching contra empresas_deduplicado.parquet
# ---------------------------------------------------------------------------

def _camara_de(source_id: str) -> str:
    return CAMARA_GRUPO.get(source_id, source_id)


def ejecutar_exclusion() -> dict:
    maestro = pd.read_parquet(DEDUPLICADO_DIR / "empresas_deduplicado.parquet").reset_index(drop=True)
    n = len(maestro)

    claves_internas, stats_fuentes = _extraer_todas_las_claves_internas()

    maestro["nit_valido"] = maestro["nit"].map(_valido_nit)
    # empresas_deduplicado.parquet no conserva las columnas *_normalizada
    # (eran auxiliares de la fase de normalización/deduplicación) — se
    # recalculan aquí desde los campos canónicos del propio maestro, con las
    # mismas funciones ya usadas en esas fases, para no depender de un join.
    maestro["razon_social_normalizada"] = maestro["razon_social"].map(normalizar_texto)
    _muni_extraido = maestro["municipio_comercial"].map(extraer_codigo_dane_si_viene_incluido)
    maestro["municipio_nombre_normalizado"] = [nm for _, nm in _muni_extraido]

    maestro["camara_grupo_entidad"] = maestro["fuentes_consolidadas"].map(
        lambda s: {_camara_de(sid) for sid in str(s).split(";")} if pd.notna(s) else set()
    )

    estado = np.full(n, "SIN_COINCIDENCIA", dtype=object)
    filas_matches: list[dict] = []

    # ================= PASE A: NIT válido exacto =================
    nit_a_registros: dict[str, list[dict]] = {}
    for _, r in claves_internas.dropna(subset=["nit_valido"]).iterrows():
        nit_a_registros.setdefault(r["nit_valido"], []).append(r.to_dict())

    idx_con_nit = maestro.index[maestro["nit_valido"].notna()]
    for i in idx_con_nit:
        nit_val = maestro.at[i, "nit_valido"]
        coincidencias = nit_a_registros.get(nit_val)
        if not coincidencias:
            continue
        estado[i] = "EXCLUSION_ALTA"
        fuentes_vistas = set()
        for c in coincidencias:
            fuentes_vistas.add(c["fuente_interna"])
        for fte in fuentes_vistas:
            reg = next(c for c in coincidencias if c["fuente_interna"] == fte)
            filas_matches.append({
                "entidad_dedup_id": maestro.at[i, "entidad_dedup_id"],
                "identificador_tipo": "nit",
                "identificador_valor": nit_val,
                "fuente_interna": fte,
                "tipo_coincidencia": "nit_exacto",
                "confianza": "alta",
                "estado_resultante": "EXCLUSION_ALTA",
                "tipo_antecedente_crm": reg.get("tipo_antecedente"),
                "fecha_referencia": reg.get("fecha_referencia"),
            })

    # ================= PASE B: matrícula + cámara compatible =================
    mat_a_registros: dict[str, list[dict]] = {}
    for _, r in claves_internas.dropna(subset=["matricula_valida"]).iterrows():
        mat_a_registros.setdefault(r["matricula_valida"], []).append(r.to_dict())

    idx_pendientes = maestro.index[(estado == "SIN_COINCIDENCIA") & maestro["matricula"].notna()]
    for i in idx_pendientes:
        mat_val = maestro.at[i, "matricula"]
        if es_placeholder_identificador(mat_val):
            continue
        coincidencias = mat_a_registros.get(mat_val)
        if not coincidencias:
            continue
        # contexto: la entidad debe tener al menos una fuente en el mismo
        # grupo de cámara que las fuentes HUBS (todas "pereira")
        camaras_entidad = maestro.at[i, "camara_grupo_entidad"]
        if "pereira" not in camaras_entidad:
            continue  # sin contexto compatible -> no se usa matrícula
        estado[i] = "EXCLUSION_MEDIA"
        fuentes_vistas = {c["fuente_interna"] for c in coincidencias}
        for fte in fuentes_vistas:
            filas_matches.append({
                "entidad_dedup_id": maestro.at[i, "entidad_dedup_id"],
                "identificador_tipo": "matricula",
                "identificador_valor": mat_val,
                "fuente_interna": fte,
                "tipo_coincidencia": "matricula_contexto_camara",
                "confianza": "media",
                "estado_resultante": "EXCLUSION_MEDIA",
                "tipo_antecedente_crm": None,
                "fecha_referencia": None,
            })

    # ================= PASE C1: razón_social (+municipio) exacta -> candidato =================
    rs_a_registros: dict[tuple, list[dict]] = {}
    for _, r in claves_internas.dropna(subset=["razon_social_normalizada"]).iterrows():
        clave = (r["razon_social_normalizada"], r["municipio_normalizado"])
        rs_a_registros.setdefault(clave, []).append(r.to_dict())
    rs_solo_a_registros: dict[str, list[dict]] = {}
    for _, r in claves_internas.dropna(subset=["razon_social_normalizada"]).iterrows():
        rs_solo_a_registros.setdefault(r["razon_social_normalizada"], []).append(r.to_dict())

    idx_pendientes = maestro.index[(estado == "SIN_COINCIDENCIA") & maestro["razon_social_normalizada"].notna()]
    for i in idx_pendientes:
        rs = maestro.at[i, "razon_social_normalizada"]
        mun = maestro.at[i, "municipio_nombre_normalizado"] if pd.notna(maestro.at[i, "municipio_nombre_normalizado"]) else None
        coincidencias = rs_a_registros.get((rs, mun)) if mun is not None else None
        tipo = "razon_social_municipio"
        if not coincidencias:
            coincidencias = rs_solo_a_registros.get(rs)
            tipo = "razon_social_sola"
        if not coincidencias:
            continue
        estado[i] = "CANDIDATO_AMBIGUO"
        fuentes_vistas = {c["fuente_interna"] for c in coincidencias}
        for fte in fuentes_vistas:
            filas_matches.append({
                "entidad_dedup_id": maestro.at[i, "entidad_dedup_id"],
                "identificador_tipo": "razon_social",
                "identificador_valor": None,  # no se copia el texto para minimizar
                "fuente_interna": fte,
                "tipo_coincidencia": tipo,
                "confianza": "media" if tipo == "razon_social_municipio" else "baja",
                "estado_resultante": "CANDIDATO_AMBIGUO",
                "tipo_antecedente_crm": None,
                "fecha_referencia": None,
            })

    # ================= PASE C2: fuzzy razón_social -> candidato =================
    elegibles_internas = claves_internas.dropna(subset=["razon_social_normalizada", "municipio_normalizado"])
    idx_pendientes = maestro.index[(estado == "SIN_COINCIDENCIA") & maestro["razon_social_normalizada"].notna()
                                    & maestro["municipio_nombre_normalizado"].notna()]
    n_fuzzy_matches = 0
    if len(elegibles_internas) and len(idx_pendientes):
        internas_por_municipio: dict[str, list[str]] = {}
        for _, r in elegibles_internas.iterrows():
            internas_por_municipio.setdefault(r["municipio_normalizado"], []).append(r["razon_social_normalizada"])
        pendientes_por_municipio: dict[str, list[int]] = {}
        for i in idx_pendientes:
            pendientes_por_municipio.setdefault(maestro.at[i, "municipio_nombre_normalizado"], []).append(i)

        for mun, idxs in pendientes_por_municipio.items():
            nombres_internos = internas_por_municipio.get(mun)
            if not nombres_internos:
                continue
            nombres_internos_unicos = list(set(nombres_internos))
            if len(idxs) > TAMANO_MAX_BLOQUE_FUZZY or len(nombres_internos_unicos) > TAMANO_MAX_BLOQUE_FUZZY:
                continue
            for i in idxs:
                rs = maestro.at[i, "razon_social_normalizada"]
                mejor = max(nombres_internos_unicos, key=lambda x: fuzz.token_sort_ratio(rs, x))
                score = fuzz.token_sort_ratio(rs, mejor)
                if score >= UMBRAL_FUZZY_CANDIDATO:
                    estado[i] = "CANDIDATO_AMBIGUO"
                    n_fuzzy_matches += 1
                    filas_matches.append({
                        "entidad_dedup_id": maestro.at[i, "entidad_dedup_id"],
                        "identificador_tipo": "razon_social",
                        "identificador_valor": None,
                        "fuente_interna": "multiples" ,
                        "tipo_coincidencia": "fuzzy_razon_social",
                        "confianza": "baja",
                        "estado_resultante": "CANDIDATO_AMBIGUO",
                        "tipo_antecedente_crm": None,
                        "fecha_referencia": None,
                    })

    maestro["estado_exclusion"] = estado
    maestro = maestro.drop(columns=["nit_valido", "camara_grupo_entidad", "razon_social_normalizada", "municipio_nombre_normalizado"])
    maestro["fecha_exclusion_utc"] = datetime.now(timezone.utc).isoformat()

    matches_df = pd.DataFrame(filas_matches)

    # ================= Resumen por entidad para empresas_con_exclusion =================
    if len(matches_df):
        resumen = matches_df.groupby("entidad_dedup_id").agg(
            num_fuentes_internas_coincidentes=("fuente_interna", "nunique"),
            fuentes_internas_coincidentes=("fuente_interna", lambda s: ";".join(sorted(set(s)))),
            mejor_tipo_coincidencia=("tipo_coincidencia", "first"),
            mejor_confianza=("confianza", "first"),
        )
        maestro = maestro.merge(resumen, on="entidad_dedup_id", how="left")
    else:
        maestro["num_fuentes_internas_coincidentes"] = 0
        maestro["fuentes_internas_coincidentes"] = None
        maestro["mejor_tipo_coincidencia"] = None
        maestro["mejor_confianza"] = None
    maestro["num_fuentes_internas_coincidentes"] = maestro["num_fuentes_internas_coincidentes"].fillna(0).astype(int)

    EXCLUSION_DIR.mkdir(parents=True, exist_ok=True)
    destino_maestro = EXCLUSION_DIR / "empresas_con_exclusion.parquet"
    maestro.to_parquet(destino_maestro, index=False)

    destino_matches = RESULTADOS_DIR / "matches_bold.parquet"
    matches_df.to_parquet(destino_matches, index=False)

    return {
        "maestro": maestro,
        "matches": matches_df,
        "stats_fuentes": stats_fuentes,
        "destino_maestro": destino_maestro,
        "destino_matches": destino_matches,
        "n_entrada": n,
    }
