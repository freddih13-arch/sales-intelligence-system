"""
Motor de cálculo del Score de Prioridad Comercial — implementación real,
vectorizada con pandas, de la arquitectura final aprobada (2026-09-01, ver
config/scoring_variables.yaml y docs/DECISIONES.md).

RECORDATORIO: este score es un índice de priorización relativa basado en
señales/proxies. NUNCA debe documentarse, mostrarse ni comunicarse como una
predicción de TPV, facturación o ingresos.

Alcance de este módulo: SOLO calcula las columnas de score sobre un
DataFrame ya preparado (dataset_preparado_scoring.parquet). NO genera Top N,
NO hace análisis de distribución/sectorial/geográfico ni de sensibilidad de
pesos — eso es intencionalmente un paso posterior, fuera de este archivo.

Principio de no imputación: ninguna dimensión sin dato se reemplaza por 0.
Ver `_score_base_y_cobertura` para el mecanismo exacto (promedio ponderado
renormalizado solo sobre dimensiones disponibles).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sales_intel.scoring.variables_scoring import (
    NOMBRE_SCORE,
    obtener_escala_fit,
    obtener_ordinal_tamano,
    obtener_valores_contactabilidad,
    pesos_definidos,
)

# Constantes de la fórmula de cobertura aprobada. Fijadas aquí, junto a la
# implementación, porque son parte indisociable de la fórmula acordada (no
# "valores sectoriales" que deban poder ajustarse sin tocar código) — el
# documento de referencia (config/scoring_variables.yaml, formula_cobertura)
# describe la misma fórmula en texto para trazabilidad.
FACTOR_COBERTURA_BASE = 0.70
FACTOR_COBERTURA_RANGO = 0.30
N_DIMENSIONES_PONDERADAS = 3

# Universo de aplicación del score (ver config/scoring_variables.yaml: universo).
ESTADOS_SCOREABLES = {"SIN_COINCIDENCIA", "CANDIDATO_AMBIGUO"}
ESTADO_POBLACION_REFERENCIA_PERCENTILES = "SIN_COINCIDENCIA"

RANGO_ANIO_PLAUSIBLE = (1990, 2026)


class PesosNoDefinidosError(RuntimeError):
    """Se lanza si config/scoring_variables.yaml deja de declarar pesos
    válidos (salvaguarda defensiva; en la versión vigente los pesos SÍ están
    aprobados y definidos)."""


# ---------------------------------------------------------------------------
# Dimensión 1: FIT COMERCIAL (peso 0.40)
# ---------------------------------------------------------------------------

def _score_fit(df: pd.DataFrame) -> pd.Series:
    """Usa sector_vertical exclusivamente. NO usa geografía. Dimensión
    faltante cuando sector_vertical es NULL."""
    escala = obtener_escala_fit()
    sector = df["sector_vertical"]

    fit = sector.map(escala["sectores_estrategicos"]).astype(float)
    fallback = df["encaje_pagos_declarado"].map(escala["encaje_generico"]).astype(float)
    fit = fit.where(fit.notna(), fallback)
    return fit


# ---------------------------------------------------------------------------
# Dimensión 2: ESCALA / POTENCIAL (peso 0.35)
# ---------------------------------------------------------------------------

def _normalizar_tamano_empresa(serie: pd.Series) -> pd.Series:
    """Normaliza tamano_empresa a {'micro','pequena','mediana','grande'} de
    forma insensible a mayúsculas/tildes ('MICRO EMPRESA', 'micro',
    'PEQUEÑA EMPRESA', 'pequena', 'GRAN EMPRESA', 'gran' -> mismo bucket).
    Cualquier valor sin ninguno de estos 4 patrones (incluye el residuo 'N')
    queda como faltante (None), NUNCA se adivina."""
    s = serie.astype("string").str.strip().str.lower().str.replace("ñ", "n", regex=False)
    normalizado = pd.Series(pd.array([pd.NA] * len(s), dtype="string"), index=serie.index)
    normalizado = normalizado.mask(s.str.contains("micro", na=False), "micro")
    normalizado = normalizado.mask(s.str.contains("pequen", na=False), "pequena")
    normalizado = normalizado.mask(s.str.contains("median", na=False), "mediana")
    normalizado = normalizado.mask(s.str.contains("gran", na=False), "grande")
    return normalizado


def _limpiar_ultimo_ano_renovado(serie: pd.Series) -> pd.Series:
    """Quita separadores de miles ('2,020' / '2.019' -> '2020') y descarta
    (deja NaN) cualquier valor que, tras limpiar, no sea un año de 4 dígitos
    plausible (1990-2026)."""
    limpio = (
        serie.astype("string")
        .str.replace(",", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.strip()
    )
    es_4_digitos = limpio.str.match(r"^\d{4}$", na=False)
    numero = pd.to_numeric(limpio.where(es_4_digitos), errors="coerce")
    lo, hi = RANGO_ANIO_PLAUSIBLE
    return numero.where((numero >= lo) & (numero <= hi))


def _percentil_contra_referencia(valores: pd.Series, mask_referencia: pd.Series) -> pd.Series:
    """Percentil ascendente (mayor valor -> mayor percentil) de `valores`,
    calculado SIEMPRE contra la distribución de la población de referencia
    (SIN_COINCIDENCIA), para que el percentil signifique lo mismo tanto para
    filas SIN_COINCIDENCIA como para CANDIDATO_AMBIGUO (en vez de rankear
    cada grupo contra sí mismo). Devuelve NaN donde `valores` es NaN."""
    referencia = valores[mask_referencia].dropna().sort_values().to_numpy()
    n_ref = len(referencia)
    resultado = pd.Series(np.nan, index=valores.index, dtype=float)
    if n_ref == 0:
        return resultado
    validos = valores.notna()
    posiciones = np.searchsorted(referencia, valores[validos].to_numpy(), side="right")
    resultado.loc[validos] = posiciones / n_ref
    return resultado


def _score_escala(df: pd.DataFrame, mask_referencia: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Devuelve (escala_score, senal_tamano, senal_vigencia)."""
    ordinal = obtener_ordinal_tamano()

    tamano_normalizado = _normalizar_tamano_empresa(df["tamano_empresa"])
    senal_tamano_directa = tamano_normalizado.map(lambda v: ordinal.get(v) if pd.notna(v) else np.nan).astype(float)

    empleados = pd.to_numeric(df["num_empleados"].astype("string"), errors="coerce")
    senal_tamano_percentil = _percentil_contra_referencia(empleados, mask_referencia)

    senal_tamano = senal_tamano_directa.where(senal_tamano_directa.notna(), senal_tamano_percentil)

    anio_limpio = _limpiar_ultimo_ano_renovado(df["ultimo_ano_renovado"])
    senal_vigencia = _percentil_contra_referencia(anio_limpio, mask_referencia)

    escala_score = pd.concat([senal_tamano, senal_vigencia], axis=1).mean(axis=1, skipna=True)
    return escala_score, senal_tamano, senal_vigencia


# ---------------------------------------------------------------------------
# Dimensión 3: CONTACTABILIDAD (peso 0.25) — nunca faltante
# ---------------------------------------------------------------------------

def _score_contactabilidad(df: pd.DataFrame) -> pd.Series:
    valores = obtener_valores_contactabilidad()
    tiene_telefono = df[["telefono_comercial_1", "telefono_comercial_2", "telefono_comercial_3"]].notna().any(axis=1)
    tiene_email = df["email_comercial"].notna()
    n_canales = tiene_telefono.astype(int) + tiene_email.astype(int)

    contacto = pd.Series(float(valores["ninguno"]), index=df.index, dtype=float)
    contacto = contacto.mask(n_canales == 1, float(valores["solo_uno"]))
    contacto = contacto.mask(n_canales == 2, float(valores["telefono_y_email"]))
    return contacto


# ---------------------------------------------------------------------------
# Agregación: score_base, factor_cobertura, score_prioridad_comercial
# ---------------------------------------------------------------------------

def _score_base_y_cobertura(
    fit: pd.Series, escala: pd.Series, contacto: pd.Series, pesos: dict[str, float]
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Promedio ponderado SOLO sobre dimensiones disponibles (nunca imputa
    0 a una dimensión faltante — la excluye tanto del numerador como del
    denominador), más el factor de cobertura acordado. Devuelve
    (score_base, factor_cobertura, dimensiones_con_dato, score_final)."""
    disponible_fit = fit.notna()
    disponible_escala = escala.notna()
    disponible_contacto = contacto.notna()

    suma_pesos = (
        disponible_fit * pesos["fit_comercial"]
        + disponible_escala * pesos["escala_potencial"]
        + disponible_contacto * pesos["contactabilidad"]
    )
    suma_ponderada = (
        fit.fillna(0) * pesos["fit_comercial"] * disponible_fit
        + escala.fillna(0) * pesos["escala_potencial"] * disponible_escala
        + contacto.fillna(0) * pesos["contactabilidad"] * disponible_contacto
    )

    score_base = pd.Series(np.nan, index=fit.index, dtype=float)
    tiene_alguna_dimension = suma_pesos > 0
    score_base.loc[tiene_alguna_dimension] = (
        100 * suma_ponderada[tiene_alguna_dimension] / suma_pesos[tiene_alguna_dimension]
    )

    dimensiones_con_dato = (
        disponible_fit.astype(int) + disponible_escala.astype(int) + disponible_contacto.astype(int)
    )
    factor_cobertura = FACTOR_COBERTURA_BASE + FACTOR_COBERTURA_RANGO * (
        dimensiones_con_dato / N_DIMENSIONES_PONDERADAS
    )

    score_final = score_base * factor_cobertura
    return score_base, factor_cobertura, dimensiones_con_dato, score_final


# ---------------------------------------------------------------------------
# Capa paralela: nivel_confianza_score (Calidad/Confianza, peso 0)
# ---------------------------------------------------------------------------

def _nivel_confianza_score(df: pd.DataFrame) -> pd.Series:
    """Deriva ÚNICAMENTE de confianza_deduplicacion, campos_en_conflicto y
    flag_codigo_dane_ambiguo (ver config: campos_fuente_explicitamente_prohibidos
    para la lista de señales que NUNCA deben entrar aquí). No afecta,
    en ningún sentido, a score_prioridad_comercial."""
    conf = df["confianza_deduplicacion"]
    tiene_conflicto = df["campos_en_conflicto"].astype("string").fillna("") != ""
    dane_ambiguo = df["flag_codigo_dane_ambiguo"].fillna(False).astype(bool)
    defectos = tiene_conflicto.astype(int) + dane_ambiguo.astype(int)

    base = pd.Series("Media", index=df.index, dtype=object)  # neutral: alta/media_alta/sin_consolidar
    base = base.mask(conf == "alta", "Alta")
    base = base.mask(conf == "media_alta", "Media")

    nivel = base.copy()
    un_defecto = defectos == 1
    nivel = nivel.mask(un_defecto & (base == "Alta"), "Media")
    nivel = nivel.mask(un_defecto & (base == "Media"), "Baja")
    nivel = nivel.mask(defectos == 2, "Baja")
    return nivel


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------

def calcular_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula todas las columnas del Score de Prioridad Comercial sobre
    `df` (dataset_preparado_scoring.parquet ya cargado). NO modifica `df` en
    el llamador — devuelve un DataFrame nuevo con únicamente las columnas de
    score, mismo índice que `df`, listo para unir por columnas (pd.concat)
    o asignar de vuelta.

    El score y todas sus columnas auxiliares quedan NULL para las filas cuyo
    estado_exclusion no está en ESTADOS_SCOREABLES ({SIN_COINCIDENCIA,
    CANDIDATO_AMBIGUO}) — no aplica, por diseño (ver universo en
    config/scoring_variables.yaml), NO por falta de dato.
    """
    if not pesos_definidos():
        raise PesosNoDefinidosError(
            f"No se puede calcular el '{NOMBRE_SCORE}': config/scoring_variables.yaml "
            "no declara pesos válidos (metadata.pesos_definidos debe ser true y los "
            "3 pesos activos deben sumar 1.00)."
        )
    from sales_intel.scoring.variables_scoring import obtener_pesos

    pesos = obtener_pesos()
    scoreable = df["estado_exclusion"].isin(ESTADOS_SCOREABLES)
    mask_referencia = df["estado_exclusion"] == ESTADO_POBLACION_REFERENCIA_PERCENTILES

    fit = _score_fit(df)
    escala, senal_tamano, senal_vigencia = _score_escala(df, mask_referencia)
    contacto = _score_contactabilidad(df)
    score_base, factor_cobertura, dimensiones_con_dato, score_final = _score_base_y_cobertura(
        fit, escala, contacto, pesos
    )
    nivel_confianza = _nivel_confianza_score(df)

    salida = pd.DataFrame(
        {
            "score_fit": fit,
            "score_escala": escala,
            "score_escala_senal_tamano": senal_tamano,
            "score_escala_senal_vigencia": senal_vigencia,
            "score_contactabilidad": contacto,
            "score_base": score_base,
            "factor_cobertura": factor_cobertura,
            "dimensiones_con_dato": dimensiones_con_dato.astype("Int64"),
            "score_prioridad_comercial": score_final,
            "nivel_confianza_score": nivel_confianza,
        },
        index=df.index,
    )

    # Fuera del universo scoreable: NULL en TODAS las columnas de score, no
    # solo en el score final — el ejercicio completo de puntuación "no
    # aplica" a EXCLUSION_ALTA/EXCLUSION_MEDIA (ya tienen coincidencia con
    # Client), no es un dato faltante.
    columnas_texto = {"nivel_confianza_score"}
    for col in salida.columns:
        if col in columnas_texto:
            salida.loc[~scoreable, col] = None
        elif col == "dimensiones_con_dato":
            salida.loc[~scoreable, col] = pd.NA
        else:
            salida.loc[~scoreable, col] = np.nan

    return salida
