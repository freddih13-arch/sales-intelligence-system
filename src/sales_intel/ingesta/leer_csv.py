"""
Lectura de archivos CSV crudos de 01_BASES_RAW y escritura de la copia
técnica de ingesta (Parquet) en 02_PROCESADAS/01_ingesta/.

Principios de fidelidad de la fase de ingesta (NO normalización todavía):
  - Todo se lee como texto (dtype=str), sin coerción de tipos. Decidir qué es
    numérico, qué es fecha, qué es nulo, es tarea de la fase de normalización.
  - Se agregan únicamente columnas de trazabilidad: source_id, hoja_origen
    (vacío para CSV), fila_origen (1-indexado sobre las filas de datos).
  - Nunca se abre 01_BASES_RAW en modo escritura.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from sales_intel.utils.config import assert_no_escritura_en_raw

_DELIMITADORES_CANDIDATOS = [",", ";", "\t", "|"]
UMBRAL_CHUNK_BYTES = 20_000_000  # por encima de esto, se lee por bloques
TAMANO_CHUNK_FILAS = 50_000


def detectar_encoding(path: Path, muestra_bytes: int = 200_000) -> str:
    """Detecta si un CSV está en utf-8 (con o sin BOM) o latin-1."""
    with open(path, "rb") as f:
        head = f.read(4)
        if head.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        f.seek(0)
        chunk = f.read(muestra_bytes)
    try:
        chunk.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def detectar_delimitador(path: Path, encoding: str) -> str:
    """Detecta el delimitador más probable a partir de la primera línea."""
    with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
        primera_linea = f.readline()
    conteos = {d: primera_linea.count(d) for d in _DELIMITADORES_CANDIDATOS}
    return max(conteos, key=conteos.get)


def _descartar_filas_vacias(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Descarta filas donde TODAS las columnas originales son cadena vacía
    (con dtype=str/keep_default_na=False, un campo vacío llega como "", no
    NaN). Devuelve (df_limpio, cuantas_se_descartaron)."""
    vacias = (df == "").all(axis=1)
    descartadas = int(vacias.sum())
    if descartadas:
        df = df.loc[~vacias].reset_index(drop=True)
    return df, descartadas


def _preparar_bloque(df: pd.DataFrame, source_id: str, fila_inicial: int) -> tuple[pd.DataFrame, int]:
    df, descartadas = _descartar_filas_vacias(df)
    df = df.copy()
    df.insert(0, "source_id", source_id)
    df.insert(1, "hoja_origen", "")
    df.insert(2, "fila_origen", range(fila_inicial, fila_inicial + len(df)))
    return df, descartadas


def leer_y_escribir_csv_a_parquet(
    path: Path,
    source_id: str,
    encoding: str,
    delimitador: str,
    destino_dir: Path,
) -> dict[str, Any]:
    """Lee un CSV completo (directo o por chunks si supera UMBRAL_CHUNK_BYTES)
    y escribe 02_PROCESADAS/01_ingesta/<source_id>__ingestado.parquet.

    Retorna un resumen: {'ok', 'registros', 'columnas', 'metodo', 'destino',
    'tamano_parquet_bytes', 'error'}.
    """
    destino = destino_dir / f"{source_id}__ingestado.parquet"
    assert_no_escritura_en_raw(destino)  # salvaguarda: nunca escribir en 01_BASES_RAW

    tamano_origen = path.stat().st_size
    usar_chunks = tamano_origen > UMBRAL_CHUNK_BYTES

    read_kwargs = dict(
        encoding=encoding,
        sep=delimitador,
        dtype=str,               # sin coerción de tipos en ingesta
        keep_default_na=False,   # no convertir "N/A"/"" a NaN todavía
        na_filter=False,
        engine="python" if delimitador == "\t" else "c",
    )

    try:
        if not usar_chunks:
            df = pd.read_csv(path, **read_kwargs)
            df, filas_vacias_descartadas = _preparar_bloque(df, source_id, fila_inicial=1)
            tabla = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_table(tabla, destino)
            registros = len(df)
            columnas = df.shape[1] - 3  # descontando las 3 columnas de trazabilidad
        else:
            writer = None
            fila_cursor = 1
            registros = 0
            columnas = None
            filas_vacias_descartadas = 0
            try:
                for chunk in pd.read_csv(path, chunksize=TAMANO_CHUNK_FILAS, **read_kwargs):
                    chunk, descartadas = _preparar_bloque(chunk, source_id, fila_inicial=fila_cursor)
                    fila_cursor += len(chunk)
                    registros += len(chunk)
                    filas_vacias_descartadas += descartadas
                    columnas = chunk.shape[1] - 3
                    tabla = pa.Table.from_pandas(chunk, preserve_index=False)
                    if writer is None:
                        writer = pq.ParquetWriter(destino, tabla.schema)
                    writer.write_table(tabla)
            finally:
                if writer is not None:
                    writer.close()

        return {
            "ok": True,
            "registros": registros,
            "columnas": columnas,
            "metodo": "chunked" if usar_chunks else "directo",
            "filas_vacias_descartadas": filas_vacias_descartadas,
            "destino": str(destino),
            "tamano_parquet_bytes": destino.stat().st_size if destino.exists() else 0,
            "error": None,
        }
    except Exception as e:  # noqa: BLE001 — se reporta, no se relanza (no debe tumbar el batch)
        if destino.exists():
            destino.unlink()  # no dejar un parquet a medio escribir
        return {
            "ok": False,
            "registros": 0,
            "columnas": None,
            "metodo": "chunked" if usar_chunks else "directo",
            "destino": None,
            "tamano_parquet_bytes": 0,
            "error": f"{type(e).__name__}: {e}",
        }
