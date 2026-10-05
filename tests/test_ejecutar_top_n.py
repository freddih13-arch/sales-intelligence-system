"""
Pruebas del ejecutor versionado del Top N comercial
(`reportes.ejecutar_top_n.ejecutar_top_n`) — TODO con snapshots `scored`
sintéticos en `tmp_path`, sin tocar `empresas_scored.parquet` real, sin
HTTP, sin modificar `capa_diversificacion.py`/`ejecutar_diversificacion.py`.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import pytest

from sales_intel.reportes.ejecutar_top_n import (
    CAMPOS_TOP_N_COMERCIAL,
    ErrorValidacionTopN,
    _validar_estado_exclusion,
    _validar_esquema_final,
    _validar_todos_coinciden,
    ejecutar_top_n,
)
from sales_intel.utils.config import RAW_DIR

# ---------------------------------------------------------------------------
# Fixture: snapshot `scored` sintético -- 5 filas SIN_COINCIDENCIA, cada una
# con sector/municipio distinto (evita cualquier intervención de
# diversificación, mantiene los tests centrados en join/esquema/validación,
# que es lo que prueba este módulo -- la lógica de diversificación en sí ya
# está cubierta por test_capa_diversificacion.py), más 1 EXCLUSION_ALTA y 1
# CANDIDATO_AMBIGUO para confirmar que ejecutar_diversificacion() los filtra
# antes de que este módulo los vea.
# ---------------------------------------------------------------------------

# 5 sectores REALES de la taxonomía V2 (`capa_diversificacion._SECTOR_BUCKETS`),
# uno por bucket distinto -- así cada fila cae en un bucket propio (p_x=0.2
# cada uno) y ninguna participación se acerca al umbral. Usar nombres de
# sector inventados haría que TODO caiga en el bucket residual "Otros" con
# p_x=1.0, y con eso ningún candidato es admisible nunca (tope duro de
# sector=0.55) -- no es un caso de prueba útil para este módulo, que no
# prueba la taxonomía en sí (ya cubierta en test_capa_diversificacion.py).
_SECTORES_REALES = [
    "Gastronomía y Hotelería", "Ferretería y construcción menor",
    "Salud", "Educación", "Comercio / Retail",
]


def _fila(i, estado="SIN_COINCIDENCIA", **overrides):
    base = {
        "entidad_dedup_id": f"ENT-{i}",
        "score_prioridad_comercial": 90.0 - i,
        "sector_vertical": _SECTORES_REALES[(i - 1) % len(_SECTORES_REALES)],
        "municipio_nombre_normalizado": f"Municipio{i}",
        "estado_exclusion": estado,
        "razon_social": f"EMPRESA {i} SAS",
        "nit": f"90000000{i}",
        "direccion_comercial": f"CALLE {i} # 1-{i}",
        "telefono_comercial_1": f"300000000{i}",
        "telefono_comercial_2": None,
        "telefono_comercial_3": None,
        "email_comercial": f"contacto{i}@empresa{i}.co",
        "representante_legal": f"REPRESENTANTE {i}",
    }
    base.update(overrides)
    return base


def _construir_scored_sintetico(tmp_path, filas=None) -> Path:
    if filas is None:
        filas = (
            [_fila(i) for i in range(1, 6)]  # 5 elegibles
            + [_fila(6, estado="EXCLUSION_ALTA")]
            + [_fila(7, estado="CANDIDATO_AMBIGUO")]
        )
    df = pd.DataFrame(filas)
    ruta = tmp_path / "empresas_scored_sintetico.parquet"
    df.to_parquet(ruta, index=False)
    return ruta


# ---------------------------------------------------------------------------
# A. Join correcto por entidad_dedup_id
# ---------------------------------------------------------------------------

def test_A_join_correcto_por_entidad_dedup_id(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    salida = tmp_path / "top3.csv"

    resultado = ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida)
    df = resultado["top_n_comercial"]

    assert len(df) == 3
    for _, fila in df.iterrows():
        i = fila["entidad_dedup_id"].split("-")[1]
        assert fila["razon_social"] == f"EMPRESA {i} SAS"
        assert fila["nit"] == f"90000000{i}"
        assert fila["direccion_comercial"] == f"CALLE {i} # 1-{i}"
        assert fila["email_comercial"] == f"contacto{i}@empresa{i}.co"
        assert fila["representante_legal"] == f"REPRESENTANTE {i}"
        assert fila["sector_vertical"] == _SECTORES_REALES[(int(i) - 1) % len(_SECTORES_REALES)]
    # Los 2 no elegibles (EXCLUSION_ALTA, CANDIDATO_AMBIGUO) nunca aparecen
    assert "ENT-6" not in df["entidad_dedup_id"].values
    assert "ENT-7" not in df["entidad_dedup_id"].values


# ---------------------------------------------------------------------------
# B. Detección de IDs duplicados en el snapshot scored
# ---------------------------------------------------------------------------

def test_B_ids_duplicados_en_scored_falla(tmp_path):
    filas = [_fila(i) for i in range(1, 6)]
    filas.append(_fila(1))  # ENT-1 duplicado
    ruta_scored = _construir_scored_sintetico(tmp_path, filas=filas)
    salida = tmp_path / "top3.csv"

    with pytest.raises(ErrorValidacionTopN, match="no es único"):
        ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida)
    assert not salida.exists()


# ---------------------------------------------------------------------------
# C. Validación de posiciones
# ---------------------------------------------------------------------------

def test_C_validacion_de_posiciones():
    columnas = list(CAMPOS_TOP_N_COMERCIAL)

    def _df(posiciones):
        data = {c: [None] * len(posiciones) for c in columnas}
        data["entidad_dedup_id"] = [f"ENT-{i}" for i in range(len(posiciones))]  # únicos, independientes de la posición
        data["posicion_diversificada"] = posiciones
        # campos de cobertura estructural no nulos -- esta prueba valida
        # posiciones, no cobertura (esa la cubre la propia suite end-to-end).
        for campo in ("razon_social", "nit", "sector_vertical", "score_prioridad_comercial"):
            data[campo] = [f"valor-{i}" for i in range(len(posiciones))]
        return pd.DataFrame(data)[columnas]

    with pytest.raises(ErrorValidacionTopN, match="no cubre exactamente"):
        _validar_esquema_final(_df([1, 2, 2]), n=3)  # duplicada, hueco en 3

    with pytest.raises(ErrorValidacionTopN, match="no cubre exactamente"):
        _validar_esquema_final(_df([1, 2, 4]), n=3)  # hueco en 3, sobra 4

    _validar_esquema_final(_df([1, 2, 3]), n=3)  # válido -- no lanza


# ---------------------------------------------------------------------------
# D. Validación de estados de exclusión
# ---------------------------------------------------------------------------

def test_D_validacion_estado_exclusion():
    valido = pd.DataFrame({"entidad_dedup_id": ["A", "B"], "estado_exclusion": ["SIN_COINCIDENCIA", "SIN_COINCIDENCIA"]})
    _validar_estado_exclusion(valido)  # no lanza

    invalido = pd.DataFrame({"entidad_dedup_id": ["A", "B"], "estado_exclusion": ["SIN_COINCIDENCIA", "EXCLUSION_ALTA"]})
    with pytest.raises(ErrorValidacionTopN, match="estado_exclusion distinto"):
        _validar_estado_exclusion(invalido)


# ---------------------------------------------------------------------------
# E. Rechazo de IDs sin correspondencia
# ---------------------------------------------------------------------------

def test_E_rechazo_ids_sin_correspondencia():
    valido = pd.DataFrame({"entidad_dedup_id": ["A", "B"], "_merge": ["both", "both"]})
    _validar_todos_coinciden(valido)  # no lanza

    invalido = pd.DataFrame({"entidad_dedup_id": ["A", "B"], "_merge": ["both", "left_only"]})
    with pytest.raises(ErrorValidacionTopN, match="no tienen correspondencia"):
        _validar_todos_coinciden(invalido)


# ---------------------------------------------------------------------------
# F. Protección contra overwrite
# ---------------------------------------------------------------------------

def test_F_proteccion_overwrite(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    salida = tmp_path / "top3.csv"

    ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida)
    contenido_original = salida.read_bytes()

    with pytest.raises(FileExistsError):
        ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida)
    assert salida.read_bytes() == contenido_original  # intacto tras el intento fallido

    # overwrite=True explícito sí permite reemplazar
    resultado = ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida, overwrite=True)
    assert resultado["ruta_salida"] == salida


# ---------------------------------------------------------------------------
# G. Determinismo
# ---------------------------------------------------------------------------

def test_G_determinismo(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    salida1 = tmp_path / "top3_a.csv"
    salida2 = tmp_path / "top3_b.csv"

    ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida1)
    ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida2)

    hash1 = hashlib.sha256(salida1.read_bytes()).hexdigest()
    hash2 = hashlib.sha256(salida2.read_bytes()).hexdigest()
    assert hash1 == hash2


# ---------------------------------------------------------------------------
# H. Esquema final exacto
# ---------------------------------------------------------------------------

def test_H_esquema_final_exacto(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    salida = tmp_path / "top3.csv"

    resultado = ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida)
    assert list(resultado["top_n_comercial"].columns) == list(CAMPOS_TOP_N_COMERCIAL)
    assert len(CAMPOS_TOP_N_COMERCIAL) == 20

    with open(salida, newline="", encoding="utf-8") as f:
        encabezado = f.readline().strip().split(",")
    assert encabezado == list(CAMPOS_TOP_N_COMERCIAL)


# ---------------------------------------------------------------------------
# I. Validaciones de entrada básicas
# ---------------------------------------------------------------------------

def test_I_n_no_entero_positivo_falla(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    for n_invalido in (0, -1, 2.5, "3", True):
        with pytest.raises(ValueError):
            ejecutar_top_n(n_invalido, entrada=str(ruta_scored), ruta_salida=tmp_path / "x.csv")


def test_I_ruta_salida_obligatoria(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    with pytest.raises(ValueError, match="ruta_salida"):
        ejecutar_top_n(3, entrada=str(ruta_scored))


def test_I_columnas_faltantes_en_scored_falla(tmp_path):
    filas = [{"entidad_dedup_id": f"ENT-{i}", "score_prioridad_comercial": 90.0 - i,
              "sector_vertical": f"S{i}", "municipio_nombre_normalizado": f"M{i}",
              "estado_exclusion": "SIN_COINCIDENCIA"} for i in range(1, 6)]
    ruta_scored = _construir_scored_sintetico(tmp_path, filas=filas)  # sin razon_social/nit/etc.
    with pytest.raises(ErrorValidacionTopN, match="Faltan columnas"):
        ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=tmp_path / "x.csv")


def test_I_no_escribe_dentro_de_raw(tmp_path):
    ruta_scored = _construir_scored_sintetico(tmp_path)
    with pytest.raises(PermissionError):
        ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=RAW_DIR / "no_deberia_existir.csv")
    assert not (RAW_DIR / "no_deberia_existir.csv").exists()


# ---------------------------------------------------------------------------
# Helpers para los 4 gaps de cobertura cerrados en este turno (revisión
# estática previa) -- construyen un `top_n` FALSO (con la misma forma de 12
# columnas que produce realmente `construir_ranking_diversificado`) y
# parchean `ejecutar_diversificacion` tal como quedó importado dentro de
# `reportes.ejecutar_top_n` (no se toca ese módulo en absoluto -- solo se
# sustituye la función que `ejecutar_top_n()` llama, vía `monkeypatch`).
# Esto es lo que permite escribir pruebas que SÍ fallarían si se rompiera el
# comportamiento defensivo del ejecutor (orden explícito, sourcing del
# score), algo que los datos "naturales" de `_construir_scored_sintetico`
# nunca podrían detectar por sí solos -- ver justificación en cada prueba.
# ---------------------------------------------------------------------------

def _construir_top_n_falso(entidades_posiciones, score_base_valor=None):
    """`entidades_posiciones`: lista de (entidad_dedup_id, posicion) EN EL
    ORDEN FÍSICO que deben tener las filas del DataFrame resultante --
    permite construir un `top_n` cuyo orden de filas NO coincide con el
    orden ascendente de posición, algo que `construir_ranking_diversificado`
    nunca produciría en la práctica (siempre devuelve las filas ya en orden
    ascendente), pero que sirve para probar que `ejecutar_top_n()` no
    DEPENDE de esa garantía externa sin más -- reordena explícitamente él
    mismo."""
    filas = []
    for entidad_id, posicion in entidades_posiciones:
        filas.append({
            "entidad_dedup_id": entidad_id,
            "score_base": score_base_valor if score_base_valor is not None else float(100 - posicion),
            "posicion_ranking_puro": posicion,
            "sector": "HORECA",
            "municipio": "MunicipioX",
            "metodo_seleccion": "tolerancia",
            "motivo_diversificacion": None,
            "entro_por_diversificacion": False,
            "candidato_desplazado": None,
            "score_candidato_desplazado": None,
            "diferencia_score": None,
            "posicion_ranking_diversificado": posicion,
        })
    return pd.DataFrame(filas)


def _parchear_ejecutar_diversificacion(monkeypatch, top_n_falso, ruta_scored):
    """Sustituye, SOLO para el test que lo invoque, la función
    `ejecutar_diversificacion` tal como la ve `reportes.ejecutar_top_n`
    (import ya resuelto) -- no modifica `diversificacion/ejecutar_diversificacion.py`
    ni ningún otro archivo, y pytest deshace el parche automáticamente al
    terminar el test."""

    def _fake(n, entrada=None, config=None):
        return {
            "top_n": top_n_falso,
            "stats": {"universo": {"entrada": str(ruta_scored)}},
            "config": config,
        }

    monkeypatch.setattr("bold_intel.reportes.ejecutar_top_n.ejecutar_diversificacion", _fake)


# ---------------------------------------------------------------------------
# J. Default de entrada (entrada=None usa empresas_scored.parquet)
# ---------------------------------------------------------------------------

def test_J_usa_empresas_scored_parquet_por_defecto(tmp_path, monkeypatch):
    """Gap 1 de la revisión estática: ningún test anterior invocaba
    `entrada=None`. Se redirige el DEFAULT de `ejecutar_diversificacion`
    (`ENTRADA_PARQUET`, un atributo de módulo) hacia el parquet sintético --
    nunca se toca ni se lee el `empresas_scored.parquet` real. Si
    `ejecutar_top_n()` no reutilizara la ruta que `ejecutar_diversificacion`
    reporta (sino que, por ejemplo, recalculara su propio default o leyera
    otra cosa), el join fallaría con "sin correspondencia" -- los IDs
    sintéticos (ENT-1..) no existen en ningún otro sitio."""
    ruta_scored = _construir_scored_sintetico(tmp_path)
    monkeypatch.setattr(
        "bold_intel.diversificacion.ejecutar_diversificacion.ENTRADA_PARQUET", ruta_scored
    )
    salida = tmp_path / "top3.csv"

    resultado = ejecutar_top_n(3, entrada=None, ruta_salida=salida)

    assert resultado["stats"]["universo"]["entrada"] == str(ruta_scored)
    df = resultado["top_n_comercial"]
    assert len(df) == 3
    assert set(df["entidad_dedup_id"]) <= {"ENT-1", "ENT-2", "ENT-3", "ENT-4", "ENT-5"}


# ---------------------------------------------------------------------------
# K. Orden de posiciones ascendente tras el join
# ---------------------------------------------------------------------------

def test_K_orden_de_posiciones_ascendente_tras_el_join(tmp_path, monkeypatch):
    """Gap 2: con datos "naturales" (`_construir_scored_sintetico`), `top_n`
    ya sale ordenado ascendente de `construir_ranking_diversificado`, y
    `pd.merge(how="left")` preserva el orden del frame izquierdo -- por lo
    que ninguna prueba con esos datos detectaría si se elimina el
    `.sort_values("posicion_diversificada")` del ejecutor (se verificó
    empíricamente). Aquí se parchea `ejecutar_diversificacion` para que
    devuelva un `top_n` con las filas en orden FÍSICO invertido (3, 2, 1) --
    si el ejecutor no reordenara explícitamente, el resultado saldría en
    ese mismo orden invertido y esta prueba fallaría."""
    ruta_scored = _construir_scored_sintetico(tmp_path)
    top_n_falso = _construir_top_n_falso([("ENT-3", 3), ("ENT-2", 2), ("ENT-1", 1)])
    _parchear_ejecutar_diversificacion(monkeypatch, top_n_falso, ruta_scored)
    salida = tmp_path / "top3.csv"

    resultado = ejecutar_top_n(3, entrada="ignorado-por-el-parche", ruta_salida=salida)
    df = resultado["top_n_comercial"]

    assert list(df["posicion_diversificada"]) == [1, 2, 3]
    assert list(df["entidad_dedup_id"]) == ["ENT-1", "ENT-2", "ENT-3"]


# ---------------------------------------------------------------------------
# L. score_prioridad_comercial viene del join, nunca de score_base
# ---------------------------------------------------------------------------

def test_L_score_prioridad_comercial_viene_del_join_no_de_score_base(tmp_path, monkeypatch):
    """Gap 3: en el flujo real, `score_base` y `score_prioridad_comercial`
    son matemáticamente idénticos (ambos derivan de la misma columna del
    mismo snapshot), así que comparar valores con datos "naturales" no
    distinguiría un error que usara `score_base` por accidente. Aquí se
    parchea `ejecutar_diversificacion` para que su `top_n` traiga un
    `score_base` DELIBERADAMENTE distinto (-999.0) al
    `score_prioridad_comercial` real del snapshot scored -- si el ejecutor
    tomara el score de `score_base` en vez de hacer el join, esta prueba lo
    detectaría inmediatamente."""
    ruta_scored = _construir_scored_sintetico(tmp_path)  # ENT-1..5, score_prioridad_comercial = 90.0 - i
    top_n_falso = _construir_top_n_falso(
        [("ENT-1", 1), ("ENT-2", 2), ("ENT-3", 3)], score_base_valor=-999.0
    )
    _parchear_ejecutar_diversificacion(monkeypatch, top_n_falso, ruta_scored)
    salida = tmp_path / "top3.csv"

    resultado = ejecutar_top_n(3, entrada="ignorado-por-el-parche", ruta_salida=salida)
    df = resultado["top_n_comercial"].set_index("entidad_dedup_id")

    assert "score_prioridad_comercial" in df.columns
    assert "score_base" not in df.columns
    for i in (1, 2, 3):
        valor = df.loc[f"ENT-{i}", "score_prioridad_comercial"]
        assert valor == 90.0 - i, f"ENT-{i}: se esperaba {90.0 - i} (del snapshot scored), salió {valor}"
        assert valor != -999.0  # nunca el score_base falso


# ---------------------------------------------------------------------------
# M. Integridad del snapshot scored (sintético, nunca el real)
# ---------------------------------------------------------------------------

def test_M_no_modifica_el_snapshot_scored_sintetico(tmp_path):
    """Gap 4: SHA-256 del parquet SINTÉTICO antes/después de ejecutar
    `ejecutar_top_n()` -- nunca se usa `empresas_scored.parquet` real."""
    ruta_scored = _construir_scored_sintetico(tmp_path)
    hash_antes = hashlib.sha256(ruta_scored.read_bytes()).hexdigest()

    salida = tmp_path / "top3.csv"
    ejecutar_top_n(3, entrada=str(ruta_scored), ruta_salida=salida)

    hash_despues = hashlib.sha256(ruta_scored.read_bytes()).hexdigest()
    assert hash_antes == hash_despues


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
