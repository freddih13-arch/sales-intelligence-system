"""
Pruebas del escritor del artefacto de salida
(`escritor_enriquecimiento.escribir_enriquecimiento_comercial`) — TODO con
datos sintéticos en memoria, sin ninguna llamada de red y sin tocar ningún
archivo fuente del proyecto (Top100, parquet de scoring, RAW, pipeline.py,
YAMLs). Cada test que escribe algo lo hace en un directorio temporal
(`tmp_path`), nunca en 03_RESULTADOS/.
"""

import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from bold_intel.enriquecimiento_legal.capa_enriquecimiento_legal import CAMPOS_COMERCIALES
from bold_intel.enriquecimiento_legal.escritor_enriquecimiento import (
    ErrorValidacionEnriquecimiento,
    escribir_enriquecimiento_comercial,
)
from bold_intel.utils.config import RAW_DIR, SCORING_DIR, SISTEMA_DIR, TOP_PROSPECTOS_DIR

RUTA_TOP100_REAL = TOP_PROSPECTOS_DIR / "top100_diversificado_20260902.csv"
RUTA_PARQUET_SCORING = SCORING_DIR / "empresas_scored.parquet"
RUTA_PIPELINE = SISTEMA_DIR / "pipeline.py"


def _registro(entidad_dedup_id, posicion, resultado_match="MATCH_CONFIRMADO", **overrides):
    base = {
        "entidad_dedup_id": entidad_dedup_id,
        "posicion_diversificada": posicion,
        "nit": "9019553183",
        "nit_confecamaras": "901955318",
        "digito_verificacion": "3",
        "razon_social_confecamaras": "INVERSIONES GRUPO C&D S.A.S.",
        "representante_legal": "REPRESENTANTE EJEMPLO S.A.S.",
        "estado_matricula": "ACTIVA",
        "matricula": "18228847",
        "camara_comercio": "PEREIRA",
        "resultado_match": resultado_match,
        "nit_consultado": "901955318",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A. Escribe correctamente registros válidos
# ---------------------------------------------------------------------------

def test_A_escribe_correctamente_registros_validos(tmp_path):
    registros = [_registro("ENT-1", 1), _registro("ENT-2", 2)]
    destino = tmp_path / "salida.csv"

    ruta = escribir_enriquecimiento_comercial(registros, destino, n_esperado=2)

    assert ruta == destino
    assert destino.exists()
    with open(destino, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == 2
    assert filas[0]["entidad_dedup_id"] == "ENT-1"
    assert filas[1]["entidad_dedup_id"] == "ENT-2"


# ---------------------------------------------------------------------------
# B. Conserva exactamente las 12 columnas y su orden
# ---------------------------------------------------------------------------

def test_B_conserva_las_12_columnas_y_su_orden(tmp_path):
    registros = [_registro("ENT-1", 1)]
    destino = tmp_path / "salida.csv"
    escribir_enriquecimiento_comercial(registros, destino, n_esperado=1)

    with open(destino, newline="", encoding="utf-8") as f:
        encabezado = next(csv.reader(f))
    assert encabezado == list(CAMPOS_COMERCIALES)
    assert len(encabezado) == 12


# ---------------------------------------------------------------------------
# C. Rechaza num_identificacion_representante_legal
# ---------------------------------------------------------------------------

def test_C_rechaza_num_identificacion_representante_legal(tmp_path):
    registros = [_registro("ENT-1", 1, num_identificacion_representante_legal="1088296164")]
    destino = tmp_path / "salida.csv"

    with pytest.raises(ErrorValidacionEnriquecimiento, match="num_identificacion_representante_legal"):
        escribir_enriquecimiento_comercial(registros, destino, n_esperado=1)
    assert not destino.exists()


# ---------------------------------------------------------------------------
# D. Rechaza entidades duplicadas
# ---------------------------------------------------------------------------

def test_D_rechaza_entidades_duplicadas(tmp_path):
    registros = [_registro("ENT-1", 1), _registro("ENT-1", 2)]
    destino = tmp_path / "salida.csv"

    with pytest.raises(ErrorValidacionEnriquecimiento, match="duplicad"):
        escribir_enriquecimiento_comercial(registros, destino, n_esperado=2)
    assert not destino.exists()


# ---------------------------------------------------------------------------
# E. Rechaza posiciones duplicadas
# ---------------------------------------------------------------------------

def test_E_rechaza_posiciones_duplicadas(tmp_path):
    registros = [_registro("ENT-1", 1), _registro("ENT-2", 1)]
    destino = tmp_path / "salida.csv"

    with pytest.raises(ErrorValidacionEnriquecimiento, match="posicion_diversificada duplicada"):
        escribir_enriquecimiento_comercial(registros, destino, n_esperado=2)
    assert not destino.exists()


# ---------------------------------------------------------------------------
# F. Rechaza estados fuera de la taxonomía aprobada
# ---------------------------------------------------------------------------

def test_F_rechaza_estados_fuera_de_taxonomia(tmp_path):
    registros = [_registro("ENT-1", 1, resultado_match="MATCH_PARCIAL")]
    destino = tmp_path / "salida.csv"

    with pytest.raises(ErrorValidacionEnriquecimiento, match="taxonomía aprobada"):
        escribir_enriquecimiento_comercial(registros, destino, n_esperado=1)
    assert not destino.exists()


# ---------------------------------------------------------------------------
# G. Rechaza columnas faltantes
# ---------------------------------------------------------------------------

def test_G_rechaza_columnas_faltantes(tmp_path):
    registro_incompleto = _registro("ENT-1", 1)
    del registro_incompleto["matricula"]
    destino = tmp_path / "salida.csv"

    with pytest.raises(ErrorValidacionEnriquecimiento, match="faltan columnas"):
        escribir_enriquecimiento_comercial([registro_incompleto], destino, n_esperado=1)
    assert not destino.exists()


# ---------------------------------------------------------------------------
# H. No sobrescribe un archivo existente silenciosamente
# ---------------------------------------------------------------------------

def test_H_no_sobrescribe_silenciosamente(tmp_path):
    destino = tmp_path / "salida.csv"
    escribir_enriquecimiento_comercial([_registro("ENT-1", 1)], destino, n_esperado=1)
    contenido_original = destino.read_bytes()

    with pytest.raises(FileExistsError):
        escribir_enriquecimiento_comercial([_registro("ENT-2", 1)], destino, n_esperado=1)

    assert destino.read_bytes() == contenido_original  # intacto tras el intento fallido

    # overwrite=True explícito sí permite reemplazar
    ruta = escribir_enriquecimiento_comercial([_registro("ENT-2", 1)], destino, n_esperado=1, overwrite=True)
    with open(ruta, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert filas[0]["entidad_dedup_id"] == "ENT-2"


# ---------------------------------------------------------------------------
# I. Escritura determinista
# ---------------------------------------------------------------------------

def test_I_escritura_determinista(tmp_path):
    registros = [_registro(f"ENT-{i}", i) for i in range(1, 11)]

    destino1 = tmp_path / "salida1.csv"
    destino2 = tmp_path / "salida2.csv"
    escribir_enriquecimiento_comercial(registros, destino1, n_esperado=10)
    escribir_enriquecimiento_comercial(registros, destino2, n_esperado=10)

    hash1 = hashlib.sha256(destino1.read_bytes()).hexdigest()
    hash2 = hashlib.sha256(destino2.read_bytes()).hexdigest()
    assert hash1 == hash2


# ---------------------------------------------------------------------------
# J. Exactamente una fila de salida por registro de entrada
# ---------------------------------------------------------------------------

def test_J_una_fila_por_registro_de_entrada(tmp_path):
    registros = [_registro(f"ENT-{i}", i) for i in range(1, 6)]
    destino = tmp_path / "salida.csv"
    escribir_enriquecimiento_comercial(registros, destino, n_esperado=5)

    with open(destino, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == len(registros)

    # además, si n_esperado no coincide con len(registros), se rechaza --
    # es la misma invariante vista desde el otro lado.
    with pytest.raises(ErrorValidacionEnriquecimiento, match="Se esperaban exactamente"):
        escribir_enriquecimiento_comercial(registros, tmp_path / "otra.csv", n_esperado=6)


# ---------------------------------------------------------------------------
# K. No modifica ningún archivo fuente
# ---------------------------------------------------------------------------

def test_K_no_modifica_ningun_archivo_fuente(tmp_path):
    archivos_fuente = [RUTA_TOP100_REAL, RUTA_PARQUET_SCORING, RUTA_PIPELINE]
    hashes_antes = {ruta: hashlib.sha256(ruta.read_bytes()).hexdigest() for ruta in archivos_fuente}

    registros = [_registro("ENT-1", 1)]
    escribir_enriquecimiento_comercial(registros, tmp_path / "salida.csv", n_esperado=1)

    for ruta in archivos_fuente:
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() == hashes_antes[ruta], f"{ruta} fue modificado"

    # además, ni siquiera se PUEDE escribir dentro de 01_BASES_RAW
    with pytest.raises(PermissionError):
        escribir_enriquecimiento_comercial(registros, RAW_DIR / "no_deberia_existir.csv", n_esperado=1)
    assert not (RAW_DIR / "no_deberia_existir.csv").exists()


# ---------------------------------------------------------------------------
# L. Un registro NO_CONSULTABLE puede escribirse correctamente
# ---------------------------------------------------------------------------

def test_L_no_consultable_se_escribe_correctamente(tmp_path):
    # posicion=1 aquí porque n_esperado=1 (único registro de este test) --
    # el valor real de la posición (p. ej. 40, como en el Top100 real) no es
    # lo que se está probando; ver test_integracion_top100_real_sin_tocar_el_archivo
    # en test_orquestador_enriquecimiento.py para la posición real observada.
    registro = _registro(
        "ENT-0376562", 1, resultado_match="NO_CONSULTABLE",
        nit=None, nit_confecamaras=None, digito_verificacion=None,
        razon_social_confecamaras=None, representante_legal=None,
        estado_matricula=None, matricula=None, camara_comercio=None,
        nit_consultado=None,
    )
    destino = tmp_path / "salida.csv"

    escribir_enriquecimiento_comercial([registro], destino, n_esperado=1)

    with open(destino, newline="", encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert filas[0]["resultado_match"] == "NO_CONSULTABLE"
    assert filas[0]["entidad_dedup_id"] == "ENT-0376562"
    assert filas[0]["nit"] == ""  # None se escribe como celda vacía


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
