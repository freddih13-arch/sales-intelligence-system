"""
Lectura de archivos XLSX crudos de 01_BASES_RAW (todas las hojas) y escritura
de la copia técnica de ingesta (Parquet) en 02_PROCESADAS/01_ingesta/.

Caso especial detectado en la auditoría (ver fuentes.yaml / DECISIONES.md):
dos hojas NO tienen fila de encabezado — la primera fila ya es un registro de
datos. Tratarlas con header=0 corrompería un negocio real convirtiéndolo en
nombre de columna. Se listan explícitamente en HOJAS_SIN_ENCABEZADO y se leen
con header=None + nombres de columna posicionales (col_0, col_1, ...).
"""

from __future__ import annotations

import datetime as dt
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from sales_intel.utils.config import assert_no_escritura_en_raw

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# (source_id, nombre_de_hoja) -> confirmado sin fila de encabezado en la auditoría.
HOJAS_SIN_ENCABEZADO: frozenset[tuple[str, str]] = frozenset(
    {
        ("hubs_pereira_2026_v3", "MILTON OSORIO"),
        ("hubs_para_hubs_curada", "Hoja 1"),
    }
)

# (source_id, nombre_de_hoja) -> índice de fila (0-indexado) donde vive el
# encabezado real, para hojas donde la fila 0 NO es el encabezado (ej. un
# título fusionado antes de la tabla). Confirmado con openpyxl directamente
# sobre 01_BASES_RAW durante la ejecución de esta fase — ver DECISIONES.md.
HOJAS_ENCABEZADO_EN_FILA: dict[tuple[str, str], int] = {
    ("registro_activos_informacion_2026", "Registro de Activos"): 1,
}


def listar_hojas(path: Path) -> list[str]:
    """Lista los nombres de las hojas de un XLSX sin leer su contenido."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = root.find("m:sheets", _NS)
        return [sh.get("name") for sh in sheets.findall("m:sheet", _NS)]


def _valor_a_texto(v: Any) -> Any:
    """Convierte un valor nativo de Excel (float/int/datetime/str/None) a
    texto preservando la apariencia original, evitando notación científica
    y sufijos '.0' espurios en columnas que en realidad son IDs (matrícula,
    NIT) que Excel guardó como número.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return format(v, "f").rstrip("0").rstrip(".")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
        return v.isoformat()
    return v


def leer_y_escribir_xlsx_a_parquet(
    path: Path,
    source_id: str,
    destino_dir: Path,
) -> dict[str, Any]:
    """Lee TODAS las hojas de un XLSX, concatena agregando source_id,
    hoja_origen y fila_origen (1-indexado, reiniciado por hoja), y escribe un
    único Parquet por fuente en 02_PROCESADAS/01_ingesta/.

    Cada hoja puede tener columnas originales distintas: se preserva tal
    cual (sin unificar esquema — eso es tarea de normalización), rellenando
    con nulos donde una hoja no tiene una columna que otra sí tiene, al
    concatenar.
    """
    destino = destino_dir / f"{source_id}__ingestado.parquet"
    assert_no_escritura_en_raw(destino)

    try:
        hojas = listar_hojas(path)
        bloques: list[pd.DataFrame] = []
        detalle_hojas: dict[str, int] = {}
        filas_vacias_descartadas = 0

        for hoja in hojas:
            sin_encabezado = (source_id, hoja) in HOJAS_SIN_ENCABEZADO
            fila_header = HOJAS_ENCABEZADO_EN_FILA.get((source_id, hoja), 0)

            if sin_encabezado:
                df = pd.read_excel(path, sheet_name=hoja, header=None, engine="openpyxl", dtype=object)
                df.columns = [f"col_{i}" for i in range(df.shape[1])]
            else:
                df = pd.read_excel(path, sheet_name=hoja, header=fila_header, engine="openpyxl", dtype=object)
                # columnas 'Unnamed: N' de openpyxl -> nombre posicional legible
                df.columns = [
                    (str(c) if not str(c).startswith("Unnamed:") else f"col_sin_nombre_{i}")
                    for i, c in enumerate(df.columns)
                ]

            df = df.map(_valor_a_texto)

            # Descartar filas completamente vacías (frecuentes al final del
            # rango declarado por Excel, que puede sobreestimar el contenido
            # real — confirmado en al menos 2 fuentes durante esta ingesta).
            filas_antes = len(df)
            df = df.dropna(axis=0, how="all")
            filas_vacias_descartadas += filas_antes - len(df)

            df.insert(0, "source_id", source_id)
            df.insert(1, "hoja_origen", hoja)
            df.insert(2, "fila_origen", range(1, len(df) + 1))

            detalle_hojas[hoja] = len(df)
            bloques.append(df)

        combinado = pd.concat(bloques, ignore_index=True, sort=False) if bloques else pd.DataFrame()
        # Todo como string para el Parquet (consistente con el criterio de
        # fidelidad de ingesta: sin inferencia de tipos todavía).
        for col in combinado.columns:
            combinado[col] = combinado[col].astype("string")

        tabla = pa.Table.from_pandas(combinado, preserve_index=False)
        pq.write_table(tabla, destino)

        return {
            "ok": True,
            "registros": len(combinado),
            "columnas": combinado.shape[1] - 3,
            "hojas": detalle_hojas,
            "filas_vacias_descartadas": filas_vacias_descartadas,
            "destino": str(destino),
            "tamano_parquet_bytes": destino.stat().st_size,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001
        if destino.exists():
            destino.unlink()
        return {
            "ok": False,
            "registros": 0,
            "columnas": None,
            "hojas": {},
            "destino": None,
            "tamano_parquet_bytes": 0,
            "error": f"{type(e).__name__}: {e}",
        }
