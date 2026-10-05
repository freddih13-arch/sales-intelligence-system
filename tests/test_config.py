"""
Pruebas de carga de configuración para DEMO PÚBLICA.
Verifican que los 4 YAML de config/ tengan estructura válida y consistente.
NO requieren archivos reales en 01_BASES_RAW — usan templates.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sales_intel.utils.config import (
    RAW_DIR,
    cargar_fuentes,
    cargar_mapeo_ciiu_sector,
    cargar_mapeo_columnas,
    cargar_scoring_variables,
    listar_fuentes,
)


def test_fuentes_yaml_estructura_valida():
    """Verifica que fuentes.yaml tenga estructura correcta (aunque sea template)."""
    data = cargar_fuentes()
    assert "metadata" in data
    assert "fuentes" in data
    assert isinstance(data["fuentes"], list)
    assert len(data["fuentes"]) > 0  # al menos entradas de ejemplo
    # Verificar campos obligatorios en cada fuente
    for f in data["fuentes"]:
        assert "id" in f
        assert "archivo" in f
        assert "formato" in f
        assert "categoria" in f


def test_fuentes_yaml_no_valida_archivos_reales():
    """En demo, NO verificamos existencia de archivos (son templates)."""
    # Este test pasa si no lanza excepción — solo verifica que la carga funciona
    data = cargar_fuentes()
    assert data["metadata"]["version"].startswith("v1-")


def test_listar_fuentes_funciona():
    """Verifica que listar_fuentes() funciona sin error."""
    todas = listar_fuentes(excluir_duplicados=False)
    sin_duplicados = listar_fuentes(excluir_duplicados=True)
    assert len(sin_duplicados) <= len(todas)
    assert len(todas) > 0


def test_mapeo_ciiu_sector_tiene_todas_las_secciones():
    data = cargar_mapeo_ciiu_sector()
    letras_esperadas = set("ABCDEFGHIJKLMNOPQRSTU")
    letras_presentes = {k for k in data["secciones"] if len(k) == 1}
    assert letras_esperadas.issubset(letras_presentes)
    # Verificar que hay excepciones de ejemplo
    assert "excepciones_codigo_especifico" in data
    assert "G4773" in data["excepciones_codigo_especifico"]


def test_mapeo_columnas_sin_conflictos():
    """Ningún sinónimo normalizado debe apuntar a dos campos canónicos distintos."""
    from sales_intel.normalizacion.mapeo_columnas import construir_diccionario_columna_a_canonico
    construir_diccionario_columna_a_canonico()  # lanza ValueError si hay conflicto


def test_scoring_variables_pesos_definidos_y_suman_100():
    """Verifica que la arquitectura de scoring tenga pesos definidos y sumen 1.00."""
    data = cargar_scoring_variables()
    assert data["metadata"]["pesos_definidos"] is True
    dims = data["dimensiones"]
    assert dims["fit_comercial"]["peso"] == 0.40
    assert dims["escala_potencial"]["peso"] == 0.35
    assert dims["contactabilidad"]["peso"] == 0.25
    assert dims["calidad_confianza"]["peso"] == 0.0
    assert dims["calidad_confianza"]["entra_al_score"] is False
    suma = (
        dims["fit_comercial"]["peso"]
        + dims["escala_potencial"]["peso"]
        + dims["contactabilidad"]["peso"]
    )
    assert abs(suma - 1.00) < 1e-9
    # Verificar estructura completa
    assert "fit_comercial" in dims
    assert "escala_potencial" in dims
    assert "contactabilidad" in dims
    assert "calidad_confianza" in dims
    assert "formula_cobertura" in data
    assert "nivel_confianza_score" in data


def test_scoring_variables_advertencia_alcance():
    """Verifica que la advertencia de 'no es predicción de TPV' esté presente."""
    data = cargar_scoring_variables()
    assert data["metadata"]["nombre_score_prohibido"] == "predicción de TPV"
    assert "no una predicción" in data["metadata"]["advertencia"].lower()


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
            except Exception as e:
                fallos += 1
                print(f"ERROR {nombre}: {e}")
    raise SystemExit(fallos)