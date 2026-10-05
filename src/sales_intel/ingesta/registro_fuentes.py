"""
Catálogo técnico de fuentes: hash, tamaño, fecha de carga.

`calcular_hash_archivo` y `verificar_integridad_fuente` funcionan hoy (solo
stdlib) y son de solo LECTURA sobre 01_BASES_RAW — nunca escriben ahí.
`registrar_catalogo` sí escribe (a 02_PROCESADAS/00_catalogo/), por lo que
incluye la salvaguarda `assert_no_escritura_en_raw`.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sales_intel.utils.config import (
    CATALOGO_DIR,
    RAW_DIR,
    assert_no_escritura_en_raw,
    listar_fuentes,
)


def calcular_hash_archivo(path: Path, algoritmo: str = "sha256", bloque: int = 8 * 1024 * 1024) -> str:
    """Calcula el hash de un archivo leyéndolo por bloques (seguro para el
    archivo nacional de 1.4 GB, no requiere cargarlo completo en memoria).
    Operación de solo lectura.
    """
    h = hashlib.new(algoritmo)
    with open(path, "rb") as f:
        while chunk := f.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def verificar_integridad_fuente(fuente_id: str) -> dict:
    """Verifica que un archivo declarado en fuentes.yaml exista y reporta su
    tamaño y hash actuales, SIN modificarlo. Útil para detectar si
    01_BASES_RAW cambió respecto a lo que asume el catálogo.
    """
    fuentes = {f.id: f for f in listar_fuentes(excluir_duplicados=False)}
    if fuente_id not in fuentes:
        raise KeyError(f"'{fuente_id}' no está declarado en fuentes.yaml")

    info = fuentes[fuente_id]
    ruta = info.ruta_absoluta
    if not ruta.exists():
        return {"id": fuente_id, "existe": False, "ruta": str(ruta)}

    return {
        "id": fuente_id,
        "existe": True,
        "ruta": str(ruta),
        "tamano_bytes": ruta.stat().st_size,
        "hash_sha256": calcular_hash_archivo(ruta),
        "verificado_en": datetime.now(timezone.utc).isoformat(),
    }


def registrar_catalogo(fuentes_ids: list[str] | None = None) -> Path:
    """Genera 02_PROCESADAS/00_catalogo/fuentes_registradas.csv a partir del
    catálogo declarativo (fuentes.yaml) + verificación real contra disco.

    NO SE HA EJECUTADO TODAVÍA. Queda implementada y lista para correr en la
    fase de ingesta, cuando se apruebe. No requiere pandas (usa csv de
    stdlib), por lo que podría ejecutarse hoy mismo si se decide avanzar.
    """
    destino = CATALOGO_DIR / "fuentes_registradas.csv"
    assert_no_escritura_en_raw(destino)  # nunca debería apuntar a 01_BASES_RAW

    fuentes = listar_fuentes(excluir_duplicados=False)
    if fuentes_ids is not None:
        fuentes = [f for f in fuentes if f.id in fuentes_ids]

    CATALOGO_DIR.mkdir(parents=True, exist_ok=True)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["source_id", "archivo", "formato", "existe", "tamano_bytes", "hash_sha256", "verificado_en"]
        )
        for fuente in fuentes:
            verif = verificar_integridad_fuente(fuente.id)
            writer.writerow(
                [
                    fuente.id,
                    fuente.archivo,
                    fuente.formato,
                    verif["existe"],
                    verif.get("tamano_bytes", ""),
                    verif.get("hash_sha256", ""),
                    verif.get("verificado_en", ""),
                ]
            )
    return destino


if __name__ == "__main__":
    print(
        "Este módulo no se ejecuta automáticamente. "
        "Invocar registrar_catalogo() explícitamente desde pipeline.py "
        "cuando se apruebe la fase de ingesta."
    )
