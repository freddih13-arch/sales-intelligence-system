"""
Pruebas del Score de Prioridad Comercial (arquitectura aprobada 2026-09-01).

Carga dataset_preparado_scoring.parquet (solo lectura) y ejecuta
motor_scoring.calcular_scores() en memoria — NO escribe ningún archivo.
Cubre exactamente las 11 validaciones pedidas al aprobar la implementación.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from sales_intel.scoring.motor_scoring import ESTADOS_SCOREABLES, calcular_scores
from sales_intel.scoring.variables_scoring import obtener_pesos
from sales_intel.utils.config import SCORING_DIR

_PARQUET = SCORING_DIR / "dataset_preparado_scoring.parquet"
_CACHE: dict = {}


def _cargar() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Carga y calcula una sola vez por proceso (dataset de 408,907 filas)."""
    if not _CACHE:
        df = pd.read_parquet(_PARQUET)
        out = calcular_scores(df)
        full = pd.concat([df, out], axis=1)
        scoreable = df["estado_exclusion"].isin(ESTADOS_SCOREABLES)
        _CACHE["df"] = df
        _CACHE["out"] = out
        _CACHE["full"] = full
        _CACHE["scoreable"] = scoreable
    return _CACHE["df"], _CACHE["out"], _CACHE["scoreable"]


def test_1_scores_dentro_de_0_100():
    _, out, _ = _cargar()
    sp = out["score_prioridad_comercial"].dropna()
    assert sp.between(0, 100).all()


def test_2_sin_nan_inesperados_dentro_del_universo_scoreable():
    """score_prioridad_comercial debe ser NaN EXACTAMENTE en las filas fuera
    de {SIN_COINCIDENCIA, CANDIDATO_AMBIGUO} — nunca dentro del universo
    scoreable (contactabilidad garantiza al menos 1 dimensión disponible)."""
    _, out, scoreable = _cargar()
    sp = out["score_prioridad_comercial"]
    assert (sp.isna() == ~scoreable).all()


def test_3_pesos_exactos_40_35_25():
    pesos = obtener_pesos()
    assert pesos["fit_comercial"] == 0.40
    assert pesos["escala_potencial"] == 0.35
    assert pesos["contactabilidad"] == 0.25

    _, _, scoreable = _cargar()
    full = _CACHE["full"]
    fila = full[scoreable & full["score_fit"].notna() & full["score_escala"].notna()].iloc[0]
    esperado = 100 * (
        0.40 * fila["score_fit"] + 0.35 * fila["score_escala"] + 0.25 * fila["score_contactabilidad"]
    )
    assert abs(esperado - fila["score_base"]) < 1e-6


def test_4_calidad_no_altera_el_score():
    """Dos entidades con las mismas 3 dimensiones ponderadas pero distinto
    nivel_confianza_score deben tener EXACTAMENTE el mismo score."""
    _, _, scoreable = _cargar()
    full = _CACHE["full"]
    sub = full[scoreable].dropna(subset=["score_fit", "score_escala"])
    grupos = sub.groupby(["score_fit", "score_escala", "score_contactabilidad"])
    encontrado_grupo_con_variedad = False
    for _, grupo in grupos:
        if grupo["nivel_confianza_score"].nunique() > 1:
            encontrado_grupo_con_variedad = True
            assert grupo["score_prioridad_comercial"].nunique() == 1
    assert encontrado_grupo_con_variedad, "no se encontró un grupo de control con variedad de confianza"


def test_5_geografia_no_altera_el_score():
    """El código fuente del motor no debe referenciar ninguna columna
    geográfica en absoluto."""
    import inspect

    from sales_intel.scoring import motor_scoring as ms

    codigo = inspect.getsource(ms)
    assert "municipio" not in codigo
    assert "departamento" not in codigo


def test_6_contactabilidad_exacta_0_060_1():
    _, out, _ = _cargar()
    valores = set(out["score_contactabilidad"].dropna().unique())
    assert valores <= {0.0, 0.6, 1.0}
    assert valores == {0.0, 0.6, 1.0}, "se esperaban los 3 valores presentes en el dataset real"


def test_7_dimensiones_faltantes_no_reciben_0_automaticamente():
    _, _, scoreable = _cargar()
    full = _CACHE["full"]
    fila = full[scoreable & full["score_fit"].notna() & full["score_escala"].isna()].iloc[0]
    renormalizado = 100 * (0.40 * fila["score_fit"] + 0.25 * fila["score_contactabilidad"]) / (0.40 + 0.25)
    como_si_fuera_cero = 100 * (0.40 * fila["score_fit"] + 0.35 * 0 + 0.25 * fila["score_contactabilidad"])
    assert abs(fila["score_base"] - renormalizado) < 1e-6
    assert abs(fila["score_base"] - como_si_fuera_cero) > 1e-6


def test_8_factor_cobertura_entre_070_y_100():
    _, out, _ = _cargar()
    fc = out["factor_cobertura"].dropna()
    assert fc.between(0.70, 1.00).all()


def test_9_no_se_eliminaron_entidades():
    df, _, _ = _cargar()
    assert len(df) == 408_907


def test_10_dimensiones_con_dato_coincide_con_disponibilidad_real():
    _cargar()
    full = _CACHE["full"]
    esperado = (
        full["score_fit"].notna().astype(int)
        + full["score_escala"].notna().astype(int)
        + full["score_contactabilidad"].notna().astype(int)
    )
    comparables = full["dimensiones_con_dato"].notna()
    assert (full.loc[comparables, "dimensiones_con_dato"] == esperado[comparables]).all()


def test_11_universo_priorizable_y_candidato_ambiguo_coinciden_con_lo_esperado():
    df, _, scoreable = _cargar()
    conteo = df["estado_exclusion"].value_counts()
    assert conteo["SIN_COINCIDENCIA"] == 376_731
    assert conteo["CANDIDATO_AMBIGUO"] == 484
    assert scoreable.sum() == 376_731 + 484


if __name__ == "__main__":
    fallos = 0
    for nombre, funcion in list(globals().items()):
        if nombre.startswith("test_") and callable(funcion):
            try:
                funcion()
                print(f"OK   {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"FAIL {nombre}: {e}")
    raise SystemExit(fallos)
