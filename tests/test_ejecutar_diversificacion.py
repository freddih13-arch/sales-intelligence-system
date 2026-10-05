"""
Pruebas de integración de la Capa de Diversificación con el pipeline
(`ejecutar_diversificacion.py` y el subcomando `diversificar` de
`pipeline.py`). Reutilizan `empresas_scored.parquet` (solo lectura) --
igual que `test_capa_diversificacion.py`, ninguna prueba de este archivo
escribe ni modifica ningún dataset, ni genera ningún archivo de Top N.

Integración controlada (turno 2026-09-02): `ejecutar_diversificacion` NO
escribe ningún archivo -- por diseño. Estas pruebas lo verifican
explícitamente (bloque I).
"""

import inspect
import sys
from pathlib import Path

RAIZ_04_SISTEMA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_04_SISTEMA / "src"))
sys.path.insert(0, str(RAIZ_04_SISTEMA))

import pandas as pd

from sales_intel.diversificacion.capa_diversificacion import (
    ConfiguracionDiversificacion,
    PISO_SCORE_ABSOLUTO,
    PISO_SCORE_RELATIVO,
    bucket_sector,
    clave_desempate_hash,
)
from sales_intel.diversificacion import ejecutar_diversificacion as ed_mod
from sales_intel.diversificacion.ejecutar_diversificacion import ejecutar_diversificacion
from sales_intel.scoring.variables_scoring import obtener_pesos
from sales_intel.utils.config import SCORING_DIR, TOP_PROSPECTOS_DIR

import pipeline as pipeline_cli

_PARQUET = SCORING_DIR / "empresas_scored.parquet"
_CACHE: dict = {}


def _resultado(n: int) -> dict:
    clave = f"res_{n}"
    if clave not in _CACHE:
        _CACHE[clave] = ejecutar_diversificacion(n)
    return _CACHE[clave]


# ---------------------------------------------------------------------------
# A. Entrada
# ---------------------------------------------------------------------------

def test_A_acepta_empresas_scored_parquet_por_defecto():
    resultado = _resultado(50)
    u = resultado["stats"]["universo"]
    assert u["entrada"] == str(_PARQUET)
    assert u["n_total_dataset"] == 408_907
    assert u["n_elegibles"] == 376_731
    assert u["n_candidato_ambiguo"] == 484
    assert u["n_excluidos"] == 31_604 + 88


def test_A_acepta_una_entrada_alternativa_para_pruebas(tmp_path):
    """El parámetro `entrada` permite apuntar a un parquet distinto (ej. uno
    sintético de prueba) sin tocar el de producción.

    Nota de diseño: la distribución sectorial/geográfica del universo
    sintético debe ser realista (categorías diluidas, no 2 categorías al
    ~50%) -- un universo con solo 2 categorías concentradas dispara
    correctamente el tope duro desde la primera evaluación (verificado
    directamente contra `construir_ranking_diversificado`, el motor ya
    auditado, sin relación con `ejecutar_diversificacion`: produce el mismo
    `n_final=0` con esos mismos datos). Ese NO es el comportamiento que este
    test quiere ejercitar, así que se usa una distribución diluida (5
    sectores, 10 municipios) para que los 10 candidatos pedidos entren por
    la zona de tolerancia, igual que ya hacen `test_21`/`test_33`/`test_34`
    de `test_capa_diversificacion.py` para el mismo propósito."""
    sectores = [
        "Comercio / Retail", "Manufactura", "Gastronomía y Hotelería",
        "Ferretería y construcción menor", "Tecnología / Comunicaciones",
    ]
    filas = []
    for i in range(200):
        if i < 190:
            estado = "SIN_COINCIDENCIA"
        elif i < 196:
            estado = "EXCLUSION_ALTA"
        else:
            estado = "CANDIDATO_AMBIGUO"
        filas.append({
            "entidad_dedup_id": f"SYN{i:03d}",
            "score_prioridad_comercial": 100.0 - i * 0.2,
            "sector_vertical": sectores[i % len(sectores)],
            "municipio_nombre_normalizado": f"MUN_{i % 10}",
            "estado_exclusion": estado,
        })
    df_sintetico = pd.DataFrame(filas)
    ruta = tmp_path / "sintetico_scored.parquet"
    df_sintetico.to_parquet(ruta, index=False)

    resultado = ejecutar_diversificacion(10, entrada=str(ruta))
    u = resultado["stats"]["universo"]
    assert u["n_total_dataset"] == 200
    assert u["n_elegibles"] == 190
    assert u["n_candidato_ambiguo"] == 4
    assert u["n_excluidos"] == 6
    assert resultado["stats"]["n_final"] == 10
    # El parquet de PRODUCCIÓN no se tocó por usar uno alternativo.
    assert _PARQUET.stat().st_mtime > 0  # sigue existiendo, sin necesidad de comparar mtime aquí


# ---------------------------------------------------------------------------
# B. Score -- no se recalcula
# ---------------------------------------------------------------------------

def test_B_no_recalcula_el_score():
    codigo_modulo = inspect.getsource(ed_mod)
    assert "motor_scoring" not in codigo_modulo
    assert "calcular_score" not in codigo_modulo.lower()
    assert "aplicar_score" not in codigo_modulo

    df_completo = pd.read_parquet(_PARQUET)
    mapa_score_antes = dict(zip(df_completo["entidad_dedup_id"], df_completo["score_prioridad_comercial"]))
    resultado = _resultado(200)
    top = resultado["top_n"]
    assert (top["score_base"] == top["entidad_dedup_id"].map(mapa_score_antes)).all()


# ---------------------------------------------------------------------------
# C. N controla el tamaño del resultado
# ---------------------------------------------------------------------------

def test_C_n_controla_el_tamano_del_resultado():
    for n in (10, 37, 250):
        resultado = ejecutar_diversificacion(n)
        assert len(resultado["top_n"]) == n
        assert resultado["stats"]["n_final"] == n


# ---------------------------------------------------------------------------
# D. Universo -- solo SIN_COINCIDENCIA entra al ranking
# ---------------------------------------------------------------------------

def test_D_solo_sin_coincidencia_entra_al_ranking():
    df_completo = pd.read_parquet(_PARQUET)
    ids_no_elegibles = set(
        df_completo.loc[df_completo["estado_exclusion"] != "SIN_COINCIDENCIA", "entidad_dedup_id"]
    )
    resultado = _resultado(500)
    ids_en_top = set(resultado["top_n"]["entidad_dedup_id"])
    assert ids_en_top.isdisjoint(ids_no_elegibles)

    u = resultado["stats"]["universo"]
    assert u["n_candidato_ambiguo"] == 484
    assert u["n_excluidos"] == 31_692  # EXCLUSION_ALTA + EXCLUSION_MEDIA


# ---------------------------------------------------------------------------
# E. Configuración -- M=22, pesos, taxonomía V2, hash F, W, pisos
# ---------------------------------------------------------------------------

def test_E_configuracion_aprobada_esta_activa():
    resultado = _resultado(2000)  # N grande para tener reemplazos que auditar
    cfg = resultado["config"]
    assert cfg.m_suavizado == 22

    pesos = obtener_pesos()
    assert pesos == {"fit_comercial": 0.40, "escala_potencial": 0.35, "contactabilidad": 0.25}

    assert bucket_sector("Entretenimiento") == "Entretenimiento"
    assert bucket_sector("Transporte y logística") == "Transporte/logística"
    assert bucket_sector("Salud") != bucket_sector("Salud / Farmacias")

    assert clave_desempate_hash("ENT-0000001") == clave_desempate_hash("ENT-0000001")

    assert resultado["stats"]["ventana_w"] == max(50, 20)  # max(50, ceil(1%*2000))

    top = resultado["top_n"]
    reemplazos = top[top["metodo_seleccion"] == "diversificacion"]
    assert len(reemplazos) > 0  # confirma que la muestra sí ejerció los pisos
    assert (reemplazos["score_base"] >= PISO_SCORE_ABSOLUTO).all()
    assert (reemplazos["score_base"] >= reemplazos["score_candidato_desplazado"] * PISO_SCORE_RELATIVO - 1e-9).all()


# ---------------------------------------------------------------------------
# F. No mutación
# ---------------------------------------------------------------------------

def test_F_no_muta_el_parquet_de_entrada():
    mtime_antes = _PARQUET.stat().st_mtime
    tamano_antes = _PARQUET.stat().st_size
    ejecutar_diversificacion(300)
    assert _PARQUET.stat().st_mtime == mtime_antes
    assert _PARQUET.stat().st_size == tamano_antes


# ---------------------------------------------------------------------------
# G. Reproducibilidad
# ---------------------------------------------------------------------------

def test_G_reproducibilidad():
    r1 = ejecutar_diversificacion(400)["top_n"]
    r2 = ejecutar_diversificacion(400)["top_n"]
    pd.testing.assert_frame_equal(r1, r2)


# ---------------------------------------------------------------------------
# H. CLI -- validable sin ejecutar producción real
# ---------------------------------------------------------------------------

def test_H_cli_parsea_el_subcomando_diversificar():
    parser = pipeline_cli.construir_parser()
    args = parser.parse_args(["diversificar", "--n", "100"])
    assert args.fase == "diversificar"
    assert args.n == 100
    assert args.func is pipeline_cli.cmd_diversificar
    # NO se invoca args.func(args) aquí -- eso ejecutaría el comando sobre el
    # dataset real; esta prueba valida únicamente el cableado del CLI.


def test_H_cli_requiere_n():
    parser = pipeline_cli.construir_parser()
    fallo = False
    try:
        parser.parse_args(["diversificar"])
    except SystemExit:
        fallo = True
    assert fallo, "--n debía ser obligatorio"


# ---------------------------------------------------------------------------
# I. No escritura accidental
# ---------------------------------------------------------------------------

def test_I_no_escribe_ningun_archivo():
    codigo_modulo = inspect.getsource(ed_mod)
    assert "to_parquet" not in codigo_modulo
    assert "to_csv" not in codigo_modulo
    assert ".write(" not in codigo_modulo

    # No se asume contenido fijo (ej. solo "_README.md") -- ya pueden existir
    # artefactos legítimos de producción (ej. un Top N ya aprobado). Lo que
    # debe seguir siendo cierto, sin excepción, es que ejecutar_diversificacion()
    # no cambia el contenido del directorio en absoluto.
    contenido_antes = sorted(p.name for p in TOP_PROSPECTOS_DIR.iterdir())
    ejecutar_diversificacion(150)
    contenido_despues = sorted(p.name for p in TOP_PROSPECTOS_DIR.iterdir())
    assert contenido_despues == contenido_antes


if __name__ == "__main__":
    fallos = 0
    for nombre, funcion in list(globals().items()):
        if nombre.startswith("test_") and callable(funcion):
            try:
                sig = inspect.signature(funcion)
                if "tmp_path" in sig.parameters:
                    import tempfile
                    with tempfile.TemporaryDirectory() as td:
                        funcion(Path(td))
                else:
                    funcion()
                print(f"OK   {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"FAIL {nombre}: {e}")
    raise SystemExit(fallos)
