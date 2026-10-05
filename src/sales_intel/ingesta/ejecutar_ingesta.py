"""
Orquestación de la fase de ingesta sobre las fuentes pequeñas/medianas.

Reglas duras de esta corrida (ver 04_SISTEMA/docs/DECISIONES.md):
  - Excluye SIEMPRE la(s) fuente(s) categoria == 'general_nacional_maestro'
    (hoy: el archivo de 1.4GB / ~6.26M registros). Nunca se abre ese archivo.
  - Guarda de seguridad adicional por tamaño: cualquier fuente que declare
    más de UMBRAL_EXCLUSION_BYTES en fuentes.yaml se excluye igual, aunque su
    categoría no lo marque explícitamente.
  - Omite (no re-ingiere) las fuentes marcadas duplicado_exacto con
    referencia a otra (no canónicas) — quedan registradas en el catálogo
    como duplicado, apuntando a su fuente canónica.
  - Solo lee de 01_BASES_RAW (nunca escribe ahí) y solo escribe en
    02_PROCESADAS/01_ingesta/ y 02_PROCESADAS/00_catalogo/.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sales_intel.ingesta.leer_csv import leer_y_escribir_csv_a_parquet
from sales_intel.ingesta.leer_xlsx import leer_y_escribir_xlsx_a_parquet
from sales_intel.ingesta.registro_fuentes import calcular_hash_archivo
from sales_intel.utils.config import (
    CATALOGO_DIR,
    INGESTA_DIR,
    cargar_fuentes,
    listar_fuentes,
)
from sales_intel.utils.logging_config import configurar_logging

UMBRAL_EXCLUSION_BYTES = 500_000_000  # 500MB — guarda de seguridad adicional
CATEGORIA_NACIONAL = "general_nacional_maestro"

logger = configurar_logging()
_log = logging.getLogger("sales_intel.ingesta.ejecutar_ingesta")


@dataclass
class ResultadoFuente:
    id: str
    archivo: str
    formato: str
    categoria: str
    tratamiento: str  # 'ingerido' | 'omitido_duplicado' | 'excluido_nacional' | 'error'
    registros_ingeridos: int = 0
    columnas_ingeridas: int | None = None
    filas_vacias_descartadas: int = 0
    hojas_ingeridas: dict[str, int] = field(default_factory=dict)
    registros_aprox_auditoria: int = 0
    tamano_original_bytes: int = 0
    hash_sha256_original: str | None = None
    destino_parquet: str | None = None
    tamano_parquet_bytes: int = 0
    duplicado_de: str | None = None
    error: str | None = None


def _clasificar_fuentes() -> tuple[list, list, list]:
    """Devuelve (a_ingerir, excluidas_nacional, omitidas_duplicado) usando
    fuentes.yaml como única fuente de verdad."""
    todas = {f.id: f for f in listar_fuentes(excluir_duplicados=False)}
    data = cargar_fuentes()
    categoria_por_id = {f["id"]: f.get("categoria") for f in data["fuentes"]}

    a_ingerir, excluidas_nacional, omitidas_duplicado = [], [], []
    for fid, info in todas.items():
        es_nacional_declarado = categoria_por_id.get(fid) == CATEGORIA_NACIONAL
        es_demasiado_grande = info.tamano_bytes > UMBRAL_EXCLUSION_BYTES
        if es_nacional_declarado or es_demasiado_grande:
            excluidas_nacional.append(info)
            continue
        if info.duplicado_estado == "duplicado_exacto" and info.duplicado_referencia:
            omitidas_duplicado.append(info)
            continue
        a_ingerir.append(info)
    return a_ingerir, excluidas_nacional, omitidas_duplicado


def ejecutar_ingesta_pequenas(limite: int | None = None) -> dict:
    """Ejecuta la ingesta sobre todas las fuentes pequeñas/medianas (todas
    menos el/los maestro(s) nacional(es) y menos los duplicados exactos no
    canónicos). `limite` es solo para pruebas (procesar solo N fuentes).
    """
    INGESTA_DIR.mkdir(parents=True, exist_ok=True)
    CATALOGO_DIR.mkdir(parents=True, exist_ok=True)

    a_ingerir, excluidas_nacional, omitidas_duplicado = _clasificar_fuentes()

    _log.info("Fuentes a ingerir: %d | excluidas (nacional): %d | omitidas (duplicado): %d",
              len(a_ingerir), len(excluidas_nacional), len(omitidas_duplicado))

    resultados: list[ResultadoFuente] = []

    for info in excluidas_nacional:
        _log.info("EXCLUIDA (maestro nacional / >500MB): %s (%s, %.1f MB)",
                   info.id, info.archivo, info.tamano_bytes / 1_000_000)
        resultados.append(ResultadoFuente(
            id=info.id, archivo=info.archivo, formato=info.formato, categoria=info.categoria,
            tratamiento="excluido_nacional", registros_aprox_auditoria=info.registros_aprox,
            tamano_original_bytes=info.tamano_bytes,
        ))

    for info in omitidas_duplicado:
        _log.info("OMITIDA (duplicado exacto de %s): %s", info.duplicado_referencia, info.id)
        resultados.append(ResultadoFuente(
            id=info.id, archivo=info.archivo, formato=info.formato, categoria=info.categoria,
            tratamiento="omitido_duplicado", registros_aprox_auditoria=info.registros_aprox,
            tamano_original_bytes=info.tamano_bytes, duplicado_de=info.duplicado_referencia,
        ))

    fuentes_a_procesar = a_ingerir[:limite] if limite else a_ingerir

    for info in fuentes_a_procesar:
        ruta = info.ruta_absoluta
        _log.info("Ingiriendo %s (%s, %.1f MB)...", info.id, info.formato, info.tamano_bytes / 1_000_000)

        if not ruta.exists():
            resultados.append(ResultadoFuente(
                id=info.id, archivo=info.archivo, formato=info.formato, categoria=info.categoria,
                tratamiento="error", registros_aprox_auditoria=info.registros_aprox,
                tamano_original_bytes=info.tamano_bytes,
                error="Archivo declarado en fuentes.yaml pero no encontrado en 01_BASES_RAW.",
            ))
            _log.error("No encontrado: %s", ruta)
            continue

        hash_original = calcular_hash_archivo(ruta)

        if info.formato == "csv":
            r = leer_y_escribir_csv_a_parquet(
                path=ruta, source_id=info.id, encoding=info.encoding or "utf-8",
                delimitador=info.delimitador or ",", destino_dir=INGESTA_DIR,
            )
            hojas = {}
        elif info.formato == "xlsx":
            r = leer_y_escribir_xlsx_a_parquet(path=ruta, source_id=info.id, destino_dir=INGESTA_DIR)
            hojas = r.get("hojas", {})
        else:
            r = {"ok": False, "registros": 0, "columnas": None, "destino": None,
                 "tamano_parquet_bytes": 0, "error": f"Formato no soportado: {info.formato}"}
            hojas = {}

        resultados.append(ResultadoFuente(
            id=info.id, archivo=info.archivo, formato=info.formato, categoria=info.categoria,
            tratamiento="ingerido" if r["ok"] else "error",
            registros_ingeridos=r.get("registros", 0),
            columnas_ingeridas=r.get("columnas"),
            filas_vacias_descartadas=r.get("filas_vacias_descartadas", 0),
            hojas_ingeridas=hojas,
            registros_aprox_auditoria=info.registros_aprox,
            tamano_original_bytes=info.tamano_bytes,
            hash_sha256_original=hash_original,
            destino_parquet=r.get("destino"),
            tamano_parquet_bytes=r.get("tamano_parquet_bytes", 0),
            error=r.get("error"),
        ))
        if r["ok"]:
            _log.info("  OK -> %s registros, %s columnas", r.get("registros"), r.get("columnas"))
        else:
            _log.error("  ERROR: %s", r.get("error"))

    destino_catalogo = _escribir_catalogo(resultados)

    return {
        "resultados": resultados,
        "catalogo": destino_catalogo,
        "resumen": _resumir(resultados),
    }


def _escribir_catalogo(resultados: list[ResultadoFuente]) -> Path:
    destino = CATALOGO_DIR / "fuentes_registradas.csv"
    ahora = datetime.now(timezone.utc).isoformat()
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "source_id", "archivo", "formato", "categoria", "tratamiento",
            "registros_ingeridos", "registros_aprox_auditoria", "columnas_ingeridas",
            "filas_vacias_descartadas", "num_hojas", "tamano_original_bytes",
            "hash_sha256_original", "destino_parquet", "tamano_parquet_bytes",
            "duplicado_de", "error", "fecha_ingesta_utc",
        ])
        for r in resultados:
            writer.writerow([
                r.id, r.archivo, r.formato, r.categoria, r.tratamiento,
                r.registros_ingeridos, r.registros_aprox_auditoria, r.columnas_ingeridas,
                r.filas_vacias_descartadas,
                len(r.hojas_ingeridas) if r.hojas_ingeridas else "", r.tamano_original_bytes,
                r.hash_sha256_original or "", r.destino_parquet or "", r.tamano_parquet_bytes,
                r.duplicado_de or "", r.error or "", ahora,
            ])
    return destino


def _resumir(resultados: list[ResultadoFuente]) -> dict:
    ingeridos = [r for r in resultados if r.tratamiento == "ingerido"]
    errores = [r for r in resultados if r.tratamiento == "error"]
    duplicados = [r for r in resultados if r.tratamiento == "omitido_duplicado"]
    nacional = [r for r in resultados if r.tratamiento == "excluido_nacional"]
    return {
        "procesados": len(ingeridos),
        "omitidos_duplicado": len(duplicados),
        "excluidos_nacional": len(nacional),
        "errores": len(errores),
        "registros_totales_ingeridos": sum(r.registros_ingeridos for r in ingeridos),
        "tamano_parquet_total_bytes": sum(r.tamano_parquet_bytes for r in ingeridos),
    }
