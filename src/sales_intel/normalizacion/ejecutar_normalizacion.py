"""
Orquestación de la fase de normalización sobre lo ya ingerido en
02_PROCESADAS/01_ingesta/.

Reglas duras de esta corrida (ver 04_SISTEMA/docs/DECISIONES.md):
  - Lee SOLO de 02_PROCESADAS/01_ingesta/ (nunca 01_BASES_RAW directamente,
    nunca escribe sobre lo ya ingerido).
  - Escribe SOLO en 02_PROCESADAS/02_normalizado/.
  - Las fuentes internas de Client (CRM + 4 HUBS) fueron ingeridas en la fase
    anterior, pero NO se incluyen en esta normalización ni se fusionan con
    la base de prospección — es el principio no negociable #4 de
    ARQUITECTURA.md ("el CRM interno de Client y los archivos HUBS nunca se
    copian ni se fusionan con la base de prospección"). Quedan registradas
    aparte como "pendientes de fase de exclusión".
  - Ningún campo se infiere: donde el mapeo o el formato no dan confianza
    suficiente (fechas, montos con separador ambiguo, DANE no validado), el
    valor se conserva como texto original y se documenta como problema de
    calidad — nunca se reformatea adivinando la convención.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from sales_intel.normalizacion.limpieza import (
    es_valor_nulo_declarado,
    normalizar_email,
    normalizar_nit,
    normalizar_telefono,
    normalizar_texto,
)
from sales_intel.normalizacion.mapeo_columnas import mapear_columnas_de_fuente
from sales_intel.normalizacion.normalizador_geografico import extraer_codigo_dane_si_viene_incluido
from sales_intel.utils.config import (
    INGESTA_DIR,
    NORMALIZADO_DIR,
    cargar_fuentes,
    cargar_mapeo_columnas,
)

TRACE_COLS = ["source_id", "hoja_origen", "fila_origen"]

# Campos que se dejan EXPRESAMENTE sin parseo/reformateo en V1 porque el
# formato varía de forma ambigua entre fuentes (separador de miles "." en
# unas, "," en otras, para el MISMO tipo de dato — confirmado en la
# auditoría) e intentar unificarlos ahora implicaría adivinar la convención.
CAMPOS_SIN_PARSEO_NUMERICO_O_FECHA = {
    "fecha_matricula", "fecha_renovacion", "ultimo_ano_renovado", "fecha_constitucion",
    "num_empleados", "activo_total",
}

_ESPACIOS = re.compile(r"\s+")


def _limpiar_texto_ligero(valor: Any) -> str | None:
    """Trim + colapso de espacios + reconocimiento de nulos declarados
    ('N/A', 'No reporta', ...). Preserva mayúsculas/tildes originales — la
    normalización agresiva (mayúsculas sin tildes) se guarda aparte en
    columnas *_normalizada, para no perder el valor original.
    """
    # OJO: pd.NA no es 'is None' (bug encontrado y corregido en esta corrida
    # — con dtype "string" de pandas, un valor faltante es pd.NA, y
    # `str(pd.NA)` produce el texto literal "<NA>" si no se filtra antes).
    if valor is None or pd.isna(valor):
        return None
    texto = _ESPACIOS.sub(" ", str(valor).strip())
    if not texto or es_valor_nulo_declarado(texto):
        return None
    return texto


def _vacio(serie: pd.Series) -> pd.Series:
    return serie.isna() | (serie.fillna("").astype(str).str.strip() == "")


@dataclass
class ReporteFuente:
    source_id: str
    archivo: str
    categoria: str
    registros: int
    columnas_originales: int
    columnas_mapeadas: int
    columnas_sin_mapear: list[str] = field(default_factory=list)
    colisiones: dict[str, list[str]] = field(default_factory=dict)
    registros_sin_identificador: int = 0
    registros_dane_ambiguo: int = 0


def _normalizar_una_fuente(
    source_id: str,
    archivo: str,
    categoria: str,
    esquema_canonico: list[str],
) -> tuple[pd.DataFrame, ReporteFuente]:
    parquet_path = INGESTA_DIR / f"{source_id}__ingestado.parquet"
    df_raw = pd.read_parquet(parquet_path)
    n = len(df_raw)

    columnas_originales = [c for c in df_raw.columns if c not in TRACE_COLS]
    mapeo = mapear_columnas_de_fuente(columnas_originales)  # {original: canonico|None}

    canon_a_originales: dict[str, list[str]] = {}
    for orig, can in mapeo.items():
        if can is not None:
            canon_a_originales.setdefault(can, []).append(orig)
    columnas_sin_mapear = sorted(orig for orig, can in mapeo.items() if can is None)
    colisiones = {can: origs for can, origs in canon_a_originales.items() if len(origs) > 1}

    out = pd.DataFrame(index=df_raw.index)
    out["source_id"] = df_raw["source_id"].astype(str)
    out["hoja_origen"] = df_raw["hoja_origen"].astype(str)
    # fila_origen viene como int64 desde CSV pero como string desde XLSX
    # (decisión de ingesta: ver leer_xlsx.py). Se unifica aquí a int64 sin
    # tocar los Parquet ya escritos en 01_ingesta/ (no se deben modificar).
    out["fila_origen"] = pd.to_numeric(df_raw["fila_origen"], errors="coerce").astype("Int64")
    out["fuente_archivo"] = archivo

    for campo in esquema_canonico:
        origenes = canon_a_originales.get(campo)
        if not origenes:
            out[campo] = pd.array([None] * n, dtype="string")
            continue
        serie = df_raw[origenes[0]].astype("string")
        for extra in origenes[1:]:
            otra = df_raw[extra].astype("string")
            vacia = _vacio(serie)
            serie = serie.mask(vacia, otra)
        out[campo] = serie

    # --- Normalización por tipo de campo ---
    out["nit"] = out["nit"].map(normalizar_nit)
    for col_tel in ("telefono_comercial_1", "telefono_comercial_2", "telefono_comercial_3"):
        out[col_tel] = out[col_tel].map(normalizar_telefono)
    out["email_comercial"] = out["email_comercial"].map(normalizar_email)

    campos_texto_ligero = [
        c for c in esquema_canonico
        if c not in CAMPOS_SIN_PARSEO_NUMERICO_O_FECHA
        and c not in ("nit", "telefono_comercial_1", "telefono_comercial_2", "telefono_comercial_3", "email_comercial")
    ]
    for campo in campos_texto_ligero:
        out[campo] = out[campo].map(_limpiar_texto_ligero)

    # Campos numéricos/fecha: SOLO trim + reconocimiento de nulo declarado,
    # sin tocar separadores ni reformatear (ver advertencia del módulo).
    for campo in CAMPOS_SIN_PARSEO_NUMERICO_O_FECHA:
        out[campo] = out[campo].map(_limpiar_texto_ligero)

    out["razon_social_normalizada"] = out["razon_social"].map(normalizar_texto)

    extraido = out["municipio_comercial"].map(extraer_codigo_dane_si_viene_incluido)
    out["municipio_codigo_dane_extraido"] = [c for c, _ in extraido]
    out["municipio_nombre_normalizado"] = [nm for _, nm in extraido]

    tmp = pd.DataFrame({
        "nombre": out["municipio_nombre_normalizado"],
        "codigo": out["municipio_codigo_dane_extraido"],
    }).dropna()
    ambiguos: set[str] = set()
    if not tmp.empty:
        conteo = tmp.groupby("nombre")["codigo"].nunique()
        ambiguos = set(conteo[conteo > 1].index)
    out["flag_codigo_dane_ambiguo"] = out["municipio_nombre_normalizado"].isin(ambiguos)

    out["sin_identificador"] = _vacio(out["nit"]) & _vacio(out["razon_social"])
    out["fecha_normalizacion_utc"] = datetime.now(timezone.utc).isoformat()

    reporte = ReporteFuente(
        source_id=source_id,
        archivo=archivo,
        categoria=categoria,
        registros=n,
        columnas_originales=len(columnas_originales),
        columnas_mapeadas=len(columnas_originales) - len(columnas_sin_mapear),
        columnas_sin_mapear=columnas_sin_mapear,
        colisiones=colisiones,
        registros_sin_identificador=int(out["sin_identificador"].sum()),
        registros_dane_ambiguo=int(out["flag_codigo_dane_ambiguo"].sum()),
    )
    return out, reporte


def ejecutar_normalizacion() -> dict:
    NORMALIZADO_DIR.mkdir(parents=True, exist_ok=True)

    config_mapeo = cargar_mapeo_columnas()
    esquema_canonico = config_mapeo["esquema_canonico"]

    fuentes_yaml = {f["id"]: f for f in cargar_fuentes()["fuentes"]}
    parquets_disponibles = {p.stem.replace("__ingestado", "") for p in INGESTA_DIR.glob("*__ingestado.parquet")}

    a_normalizar: list[tuple[str, str, str]] = []   # (source_id, archivo, categoria)
    excluidas_internas: list[tuple[str, str, str]] = []

    for source_id in sorted(parquets_disponibles):
        meta = fuentes_yaml.get(source_id, {})
        archivo = meta.get("archivo", source_id)
        categoria = meta.get("categoria", "")
        if categoria.startswith("interno_bold"):
            excluidas_internas.append((source_id, archivo, categoria))
        else:
            a_normalizar.append((source_id, archivo, categoria))

    bloques: list[pd.DataFrame] = []
    reportes: list[ReporteFuente] = []
    for source_id, archivo, categoria in a_normalizar:
        df_norm, rep = _normalizar_una_fuente(source_id, archivo, categoria, esquema_canonico)
        bloques.append(df_norm)
        reportes.append(rep)

    combinado = pd.concat(bloques, ignore_index=True) if bloques else pd.DataFrame()

    destino = NORMALIZADO_DIR / "empresas_normalizado.parquet"
    combinado.to_parquet(destino, index=False)

    destino_reporte = NORMALIZADO_DIR / "reporte_calidad_normalizacion.csv"
    _escribir_reporte_csv(reportes, destino_reporte)

    return {
        "destino_parquet": destino,
        "destino_reporte": destino_reporte,
        "combinado": combinado,
        "reportes": reportes,
        "fuentes_normalizadas": a_normalizar,
        "fuentes_internas_excluidas": excluidas_internas,
        "esquema_canonico": esquema_canonico,
    }


def _escribir_reporte_csv(reportes: list[ReporteFuente], destino: Path) -> None:
    import csv

    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_id", "archivo", "categoria", "registros", "columnas_originales",
            "columnas_mapeadas", "columnas_sin_mapear", "colisiones",
            "registros_sin_identificador", "pct_sin_identificador", "registros_dane_ambiguo",
        ])
        for r in reportes:
            pct = (r.registros_sin_identificador / r.registros * 100) if r.registros else 0.0
            writer.writerow([
                r.source_id, r.archivo, r.categoria, r.registros, r.columnas_originales,
                r.columnas_mapeadas, "; ".join(r.columnas_sin_mapear),
                "; ".join(f"{k}<-{','.join(v)}" for k, v in r.colisiones.items()),
                r.registros_sin_identificador, f"{pct:.1f}", r.registros_dane_ambiguo,
            ])
