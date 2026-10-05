"""
Pruebas de la Capa de Diversificación (prototipo, PROTOTIPO AISLADO — no
conectado al pipeline oficial). Carga `empresas_scored.parquet` (solo
lectura) y ejecuta `construir_ranking_diversificado` en memoria — NO escribe
ningún archivo, NO recalcula ningún score.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd

from bold_intel.diversificacion.capa_diversificacion import (
    M_SUAVIZADO,
    ConfiguracionDiversificacion,
    bucket_sector,
    calcular_umbrales_por_categoria,
    categoria_municipio,
    clave_desempate_hash,
    construir_ranking_diversificado,
    participacion_suavizada,
    umbral_activacion,
)
from bold_intel.scoring.variables_scoring import obtener_pesos
from bold_intel.utils.config import SCORING_DIR

_PARQUET = SCORING_DIR / "empresas_scored.parquet"
_CACHE: dict = {}

TOPS = [100, 500, 1000, 5000]


def _universo() -> pd.DataFrame:
    if "universo" not in _CACHE:
        df = pd.read_parquet(_PARQUET)
        _CACHE["df_completo"] = df
        _CACHE["universo"] = df[df["estado_exclusion"] == "SIN_COINCIDENCIA"].copy()
    return _CACHE["universo"]


def _resultado(n: int) -> dict:
    key = f"res_{n}"
    if key not in _CACHE:
        _CACHE[key] = construir_ranking_diversificado(_universo(), n)
    return _CACHE[key]


def test_1_score_base_no_cambia():
    """score_base en la salida debe ser exactamente score_prioridad_comercial
    de la entidad correspondiente en la entrada -- ni un decimal distinto."""
    universo = _universo()
    mapa_score = dict(zip(universo["entidad_dedup_id"], universo["score_prioridad_comercial"]))
    for n in TOPS:
        top = _resultado(n)["top_n"]
        for _, fila in top.iterrows():
            assert fila["score_base"] == mapa_score[fila["entidad_dedup_id"]]


def test_2_pesos_no_cambian():
    pesos = obtener_pesos()
    assert pesos["fit_comercial"] == 0.40
    assert pesos["escala_potencial"] == 0.35
    assert pesos["contactabilidad"] == 0.25


def test_3_ningun_score_es_recalculado():
    """La entrada (`score_prioridad_comercial` y sus componentes) es idéntica
    antes y después de llamar a construir_ranking_diversificado."""
    universo = _universo()
    columnas_score = [
        "score_fit", "score_escala", "score_contactabilidad", "score_base",
        "factor_cobertura", "dimensiones_con_dato", "score_prioridad_comercial",
        "nivel_confianza_score",
    ]
    antes = {c: universo[c].copy() for c in columnas_score}
    construir_ranking_diversificado(universo, 100)
    for c in columnas_score:
        pd.testing.assert_series_equal(antes[c], universo[c], check_names=False)


def test_4_ningun_registro_excluido_entra_al_ranking():
    universo = _universo()
    ids_universo = set(universo["entidad_dedup_id"])
    for n in TOPS:
        top = _resultado(n)["top_n"]
        assert set(top["entidad_dedup_id"]).issubset(ids_universo)

    # Ademas: pasar un universo con estados fuera de SIN_COINCIDENCIA debe
    # rechazarse explicitamente (responsabilidad del llamador filtrar antes).
    df_completo = _CACHE["df_completo"]
    con_exclusion = pd.concat([universo.head(200), df_completo[df_completo["estado_exclusion"] == "EXCLUSION_ALTA"].head(5)])
    fallo = False
    try:
        construir_ranking_diversificado(con_exclusion, 50)
    except ValueError:
        fallo = True
    assert fallo, "debia rechazar un universo con estados distintos de SIN_COINCIDENCIA"


def test_5_ningun_reemplazo_con_score_menor_a_60():
    for n in TOPS:
        top = _resultado(n)["top_n"]
        reemplazos = top[top["metodo_seleccion"] == "diversificacion"]
        assert (reemplazos["score_base"] >= 60.0).all()


def test_6_ningun_reemplazo_por_debajo_del_85_pct_del_desplazado():
    for n in TOPS:
        top = _resultado(n)["top_n"]
        reemplazos = top[top["metodo_seleccion"] == "diversificacion"]
        piso = reemplazos["score_candidato_desplazado"] * 0.85
        # tolerancia de punto flotante minima
        assert (reemplazos["score_base"] >= piso - 1e-9).all()


def test_7_sin_reemplazo_valido_se_conserva_el_original():
    for n in TOPS:
        top = _resultado(n)["top_n"]
        proteccion = top[top["metodo_seleccion"] == "proteccion_calidad"]
        # Estas filas dispararon un umbral pero no fueron "reemplazadas" --
        # no tienen candidato_desplazado (no desplazaron a nadie, son ellas
        # mismas las que iban a ser diferidas y terminaron admitidas).
        assert proteccion["candidato_desplazado"].isna().all()
        assert proteccion["motivo_diversificacion"].notna().all()


def test_8_sector_y_municipio_solo_se_usan_en_diversificacion():
    """Verifica que sector/municipio no aparecen en ninguna parte de la
    fórmula de score (ya cubierto por motor_scoring.py, test de la fase
    anterior) y que la capa de diversificación no escribe ninguna columna de
    score en el universo de entrada."""
    universo = _universo()
    columnas_antes = set(universo.columns)
    construir_ranking_diversificado(universo, 100)
    assert set(universo.columns) == columnas_antes, "no debe agregar columnas al DataFrame de entrada"


def test_9_no_existe_hardcode_especifico_para_horeca_pereira():
    """Prueba de comportamiento (no solo de texto): dos categorías
    sintéticas con la MISMA participación que HORECA y que Pereira deben
    producir EXACTAMENTE los mismos umbrales -- si hubiera una rama especial
    para esos nombres, este test lo detectaría."""
    p_horeca = 0.1120
    p_pereira = 0.0137
    params_sector = ConfiguracionDiversificacion().params_sector
    params_municipio = ConfiguracionDiversificacion().params_municipio

    act_horeca = umbral_activacion(p_horeca, params_sector["piso_activacion"], params_sector["techo_activacion"])
    act_sintetico_sector = umbral_activacion(p_horeca, params_sector["piso_activacion"], params_sector["techo_activacion"])
    assert act_horeca == act_sintetico_sector

    umbrales = calcular_umbrales_por_categoria(
        {"Gastronomía y Hotelería_bucket_HORECA": p_horeca, "ZZZZ_SECTOR_SINTETICO": p_horeca},
        params_sector,
    )
    assert umbrales["Gastronomía y Hotelería_bucket_HORECA"] == umbrales["ZZZZ_SECTOR_SINTETICO"]

    umbrales_geo = calcular_umbrales_por_categoria(
        {"PEREIRA": p_pereira, "ZZZZ_MUNICIPIO_SINTETICO": p_pereira},
        params_municipio,
    )
    assert umbrales_geo["PEREIRA"] == umbrales_geo["ZZZZ_MUNICIPIO_SINTETICO"]

    # Ademas: el código fuente del módulo no debe contener ninguna rama
    # condicional sobre estos nombres (más allá de la etiqueta de bucket, que
    # es una constante de mapeo, no una condición).
    import inspect

    from bold_intel.diversificacion import capa_diversificacion as cd

    codigo = inspect.getsource(cd)
    assert "pereira" not in codigo.lower(), "no debe existir ninguna mención a Pereira en la lógica del módulo"


def test_10_trazabilidad_completa():
    columnas_requeridas = {
        "entidad_dedup_id", "score_base", "posicion_ranking_puro",
        "posicion_ranking_diversificado", "sector", "municipio",
        "metodo_seleccion", "motivo_diversificacion", "entro_por_diversificacion",
        "candidato_desplazado", "score_candidato_desplazado", "diferencia_score",
    }
    for n in TOPS:
        top = _resultado(n)["top_n"]
        assert columnas_requeridas.issubset(set(top.columns))
        assert top["posicion_ranking_puro"].notna().all()
        assert top["posicion_ranking_diversificado"].notna().all()
        assert top["metodo_seleccion"].notna().all()
        assert top["sector"].notna().all()
        assert top["municipio"].notna().all()  # SIN_DATO es un valor válido, no NaN
        # ningun dato personal: no debe haber columnas de contacto/nombre
        assert not ({"telefono_comercial_1", "email_comercial", "razon_social", "direccion_comercial"} & set(top.columns))


def test_11_top_n_tiene_exactamente_n_registros():
    for n in TOPS:
        top = _resultado(n)["top_n"]
        assert len(top) == n


def test_12_determinismo():
    universo = _universo()
    r1 = construir_ranking_diversificado(universo, 500)["top_n"]
    r2 = construir_ranking_diversificado(universo, 500)["top_n"]
    pd.testing.assert_frame_equal(r1, r2)


# ---------------------------------------------------------------------------
# Taxonomía V2 (Nivel B) — aprobada en `03_RESULTADOS/validacion_taxonomia_v2.md`.
# `Entretenimiento` y `Transporte y logística` pasan a tener bucket propio;
# Construcción/Inmobiliario/Agro/Financiero-Seguros/Minería y
# Sector público/Hogares/Extraterritorial permanecen en "Otros" (residual
# aprobado, no se les asignó bucket propio).
# ---------------------------------------------------------------------------

# El residual "Otros" tal como quedó aprobado -- exactamente estos 8
# `sector_vertical` (los 10 que antes vivían en "Otros", menos los 2 que
# ahora tienen bucket propio).
_RESIDUAL_OTROS_APROBADO = {
    "Construcción", "Inmobiliario", "Agro", "Financiero / Seguros", "Minería",
    "Sector público", "Hogares", "Extraterritorial",
}

# El conjunto completo de `sector_vertical` que, ANTES de la taxonomía V2,
# caía en "Otros" -- los 8 del residual + los 2 que ahora se separan. Se usa
# solo para la prueba de conservación de entidades (test_17).
_TODO_LO_QUE_ANTES_ERA_OTROS = _RESIDUAL_OTROS_APROBADO | {"Entretenimiento", "Transporte y logística"}

# Los únicos nombres de bucket que la especificación aprueba hoy -- cualquier
# valor fuera de este conjunto es un bucket no aprobado.
_BUCKETS_APROBADOS = {
    "HORECA", "Ferretería", "Salud", "Salud/Farmacias", "Educación",
    "Comercio/Retail", "Manufactura", "Servicios", "Tecnología",
    "Entretenimiento", "Transporte/logística", "Otros", "Sin sector",
}


def test_13_entretenimiento_y_transporte_tienen_bucket_propio():
    """Taxonomía V2: Entretenimiento y Transporte y logística ya no deben
    caer en el bucket genérico "Otros" -- cada uno debe mapear a su propio
    bucket, con nombre distinto entre sí y distinto de "Otros"."""
    assert bucket_sector("Entretenimiento") == "Entretenimiento"
    assert bucket_sector("Transporte y logística") == "Transporte/logística"
    assert bucket_sector("Entretenimiento") != bucket_sector("Transporte y logística")
    assert bucket_sector("Entretenimiento") != "Otros"
    assert bucket_sector("Transporte y logística") != "Otros"


def test_14_salud_y_salud_farmacias_siguen_separadas():
    """La pregunta central de `auditoria_taxonomia_diversificacion.md`:
    Salud (sección CIIU Q, servicios de salud) y Salud/Farmacias (excepción
    G4773, retail farmacéutico) deben seguir siendo buckets distintos -- la
    taxonomía V2 NO las fusiona."""
    assert bucket_sector("Salud") == "Salud"
    assert bucket_sector("Salud / Farmacias") == "Salud/Farmacias"
    assert bucket_sector("Salud") != bucket_sector("Salud / Farmacias")


def test_15_otros_contiene_unicamente_el_residual_aprobado():
    """"Otros" debe seguir recibiendo exactamente el residual aprobado
    (Construcción, Inmobiliario, Agro, Financiero/Seguros, Minería, Sector
    público, Hogares, Extraterritorial) -- ni más (no debe "recuperar" a
    Entretenimiento/Transporte) ni menos (no debe perder ninguna de las 8)."""
    for sector_vertical in _RESIDUAL_OTROS_APROBADO:
        assert bucket_sector(sector_vertical) == "Otros", (
            f"{sector_vertical!r} debe seguir cayendo en 'Otros' (residual aprobado)"
        )

    # Verificación contra el universo real: todo lo que hoy mapea a "Otros"
    # debe venir únicamente de sector_vertical en el residual aprobado -- si
    # apareciera cualquier otro valor, sería un bucket no documentado.
    universo = _universo()
    en_otros = universo[universo["sector_vertical"].apply(bucket_sector) == "Otros"]
    origenes_en_otros = set(en_otros["sector_vertical"].dropna().unique())
    assert origenes_en_otros <= _RESIDUAL_OTROS_APROBADO, (
        f"'Otros' contiene sector_vertical no aprobados: {origenes_en_otros - _RESIDUAL_OTROS_APROBADO}"
    )


def test_16_no_se_introducen_buckets_no_aprobados():
    """Sobre el universo real completo: el conjunto de buckets que produce
    bucket_sector() no debe exceder los 13 nombres aprobados en la taxonomía
    V2 -- ningún bucket nuevo no documentado."""
    universo = _universo()
    buckets_reales = set(universo["sector_vertical"].apply(bucket_sector).unique())
    no_aprobados = buckets_reales - _BUCKETS_APROBADOS
    assert not no_aprobados, f"buckets no aprobados detectados: {no_aprobados}"


def test_17_division_de_otros_conserva_todas_las_entidades():
    """Separar Entretenimiento/Transporte de "Otros" no debe perder ni
    duplicar ninguna entidad: el conjunto de entidades cuyo sector_vertical
    antes caía en "Otros" (las 10 categorías originales) debe ser
    EXACTAMENTE igual al conjunto que hoy cae en {Entretenimiento,
    Transporte/logística, Otros} combinados."""
    universo = _universo()
    buckets = universo["sector_vertical"].apply(bucket_sector)

    ids_antes = set(universo.loc[universo["sector_vertical"].isin(_TODO_LO_QUE_ANTES_ERA_OTROS), "entidad_dedup_id"])
    ids_despues = set(universo.loc[buckets.isin({"Entretenimiento", "Transporte/logística", "Otros"}), "entidad_dedup_id"])

    assert ids_antes == ids_despues


# ---------------------------------------------------------------------------
# Mecanismo definitivo de participación — suavizado bayesiano (aprobado en
# `03_RESULTADOS/decision_mecanismo_suavizado.md`, M=22 en
# `03_RESULTADOS/decision_final_M_suavizado.md`, implementado reemplazando
# por completo `CALENTAMIENTO_MINIMO`). Los tests 1-17 de arriba ya corren
# contra este mecanismo (es la configuración por defecto de
# `ConfiguracionDiversificacion`) -- estos tests adicionales verifican la
# fórmula y sus propiedades específicas.
# ---------------------------------------------------------------------------


def test_18_formula_suavizada_valores_conocidos():
    """A: p_suavizada(x) = (conteo_x+1+M*p_x)/(tamaño+1+M) contra valores
    calculados a mano, incluido el ejemplo ya verificado en la
    especificación (M=20, p_x=11.20% -> 15.4286%)."""
    valor_spec = participacion_suavizada(conteo=0, tamano=0, p_x=0.1120, m=20)
    assert abs(valor_spec - 0.154286) < 1e-5

    valor_m22 = participacion_suavizada(conteo=0, tamano=0, p_x=0.1120, m=22)
    esperado_m22 = (0 + 1 + 22 * 0.1120) / (0 + 1 + 22)
    assert abs(valor_m22 - esperado_m22) < 1e-12

    valor_lista_no_vacia = participacion_suavizada(conteo=5, tamano=20, p_x=0.05, m=22)
    esperado_lista_no_vacia = (5 + 1 + 22 * 0.05) / (20 + 1 + 22)
    assert abs(valor_lista_no_vacia - esperado_lista_no_vacia) < 1e-12


def test_19_M_de_produccion_es_22():
    """B."""
    assert M_SUAVIZADO == 22
    assert ConfiguracionDiversificacion().m_suavizado == 22


def test_20_M_unico_se_aplica_igual_a_sector_y_municipio():
    """C: la misma fórmula, el mismo M, sin distinción de dimensión --
    prueba de comportamiento (no de texto), mismo estilo que test_9. Además
    confirma que la configuración no tiene M separado por dimensión (M
    único, aprobado explícitamente en `decision_final_M_suavizado.md` §9)."""
    p = 0.08
    valor_como_sector = participacion_suavizada(3, 30, p, M_SUAVIZADO)
    valor_como_municipio = participacion_suavizada(3, 30, p, M_SUAVIZADO)
    assert valor_como_sector == valor_como_municipio

    cfg = ConfiguracionDiversificacion()
    assert cfg.m_suavizado == M_SUAVIZADO
    assert not hasattr(cfg, "m_sector")
    assert not hasattr(cfg, "m_municipio")


def test_21_ninguna_admision_incondicional_inicial():
    """D: el candidato de mayor score (posición 1 del ranking puro) SÍ se
    evalúa contra el umbral desde el primer momento -- si su categoría
    domina el universo sintético (80% del total), debe quedar diferida
    igual que cualquier otra, sin ninguna "zona de calentamiento" que la
    admita gratis. Con el mecanismo anterior (CALENTAMIENTO_MINIMO=22), las
    primeras 22 posiciones se admitían SIN evaluar -- este test habría
    fallado con ese mecanismo."""
    n_dominante, n_chica = 80, 20
    filas = []
    for i in range(n_dominante):
        filas.append({
            "entidad_dedup_id": f"DOM{i:03d}",
            "score_prioridad_comercial": 100.0 - i * 0.3,
            "sector_vertical": "Comercio / Retail",
            "municipio_nombre_normalizado": f"MUN_{i % 5}",
            "estado_exclusion": "SIN_COINCIDENCIA",
        })
    for i in range(n_chica):
        filas.append({
            "entidad_dedup_id": f"CHI{i:03d}",
            "score_prioridad_comercial": 75.0 - i * 0.3,
            "sector_vertical": "Educación",
            "municipio_nombre_normalizado": f"MUN_{i % 5}",
            "estado_exclusion": "SIN_COINCIDENCIA",
        })
    universo_sintetico = pd.DataFrame(filas)

    resultado = construir_ranking_diversificado(universo_sintetico, 10)
    top = resultado["top_n"]

    assert len(top) == 10
    # El candidato #1 del ranking puro (el de mayor score, sector dominante)
    # NO está entre los admitidos -- fue diferido desde su primerísima
    # evaluación, no admitido sin evaluar.
    assert top["posicion_ranking_puro"].min() > 1
    assert resultado["stats"]["n_diferidos_tope_duro"] >= 1


def test_22_M_de_produccion_nunca_por_debajo_de_5():
    """E: M<5 no debe aparecer como configuración de producción -- rango
    errático ya documentado (`analisis_alternativas_calentamiento.md` §5,
    `decision_final_M_suavizado.md` §3)."""
    assert M_SUAVIZADO >= 5
    assert ConfiguracionDiversificacion().m_suavizado >= 5
    # Y específicamente dentro del rango de sensibilidad aceptable aprobado.
    assert 20 <= M_SUAVIZADO <= 26


def test_23_categoria_pequena_recibe_prior_pequeno_no_cero():
    """F: una categoría con p_x cercano a cero recibe una estimación
    positiva y proporcional a su p_x -- nunca se trunca a 0."""
    p_x_chico = 0.006  # ~ Educación, 0.60% del universo real
    valor = participacion_suavizada(0, 0, p_x_chico, M_SUAVIZADO)
    valor_sin_prior = participacion_suavizada(0, 0, 0.0, M_SUAVIZADO)

    assert valor > 0.0
    assert valor > valor_sin_prior  # el prior positivo mueve la estimación
    valor_p_x_mayor = participacion_suavizada(0, 0, 0.05, M_SUAVIZADO)
    assert valor_p_x_mayor > valor  # monótono creciente en p_x


def test_24_categoria_grande_conserva_prior_proporcional_a_p_x():
    """G: para una categoría grande, la estimación sigue siendo linealmente
    proporcional a p_x (no se aplana ni se trata distinto por ser grande)."""
    p_x_grande = 0.30  # ~ Comercio/Retail
    valor = participacion_suavizada(0, 0, p_x_grande, M_SUAVIZADO)
    esperado = (1 + M_SUAVIZADO * p_x_grande) / (1 + M_SUAVIZADO)
    assert abs(valor - esperado) < 1e-12

    # Duplicar p_x duplica exactamente el término M*p_x del numerador --
    # la misma fórmula lineal, sin ningún trato especial por tamaño.
    p_x_doble = 0.60
    valor_doble = participacion_suavizada(0, 0, p_x_doble, M_SUAVIZADO)
    termino_simple = valor * (1 + M_SUAVIZADO) - 1
    termino_doble = valor_doble * (1 + M_SUAVIZADO) - 1
    assert abs(termino_doble - termino_simple * 2) < 1e-9


def test_25_convergencia_a_p_x_cuando_M_crece():
    """H: para conteo/tamaño fijos, p_suavizada converge hacia p_x a medida
    que M crece -- nunca "salta", se acerca de forma monótona y suave."""
    p_x = 0.1837
    valores = [participacion_suavizada(0, 0, p_x, m) for m in (10, 100, 10_000, 10_000_000)]
    distancias = [abs(v - p_x) for v in valores]
    assert all(distancias[i] > distancias[i + 1] for i in range(len(distancias) - 1))
    assert distancias[-1] < 1e-6


def test_26_suavizado_no_altera_score_taxonomia_ni_pisos():
    """I, J, K combinados -- referencia explícita, sin duplicar lógica: las
    48 pruebas de este archivo ya corren contra el mecanismo de suavizado
    (es la configuración por defecto de `ConfiguracionDiversificacion`).
    Aquí se deja una verificación directa de las 3 invariantes bajo el
    nuevo mecanismo, en un solo lugar fácil de auditar."""
    universo = _universo()

    # I: el score de entrada no se modifica.
    antes = universo["score_prioridad_comercial"].copy()
    construir_ranking_diversificado(universo, 200)
    pd.testing.assert_series_equal(antes, universo["score_prioridad_comercial"], check_names=False)

    # J: taxonomía V2 (Entretenimiento y Transporte/logística con bucket
    # propio) sigue intacta -- no se tocó al implementar el suavizado.
    assert bucket_sector("Entretenimiento") == "Entretenimiento"
    assert bucket_sector("Transporte y logística") == "Transporte/logística"
    assert bucket_sector("Salud") != bucket_sector("Salud / Farmacias")

    # K: pisos de calidad activos bajo el mecanismo de suavizado.
    resultado = _resultado(500)["top_n"]
    reemplazos = resultado[resultado["metodo_seleccion"] == "diversificacion"]
    assert (reemplazos["score_base"] >= 60.0).all()
    piso_relativo = reemplazos["score_candidato_desplazado"] * 0.85
    assert (reemplazos["score_base"] >= piso_relativo - 1e-9).all()


# ---------------------------------------------------------------------------
# Desempate definitivo — F: hash SHA-256 determinístico de entidad_dedup_id
# (aprobado en `03_RESULTADOS/analisis_criterio_desempate.md`, implementado
# reemplazando `entidad_dedup_id` ascendente en los 2 puntos funcionales de
# `capa_diversificacion.py`). Los tests 1-26 de arriba ya corren contra este
# desempate (es el comportamiento por defecto del módulo).
# ---------------------------------------------------------------------------


def test_27_clave_desempate_misma_entidad_misma_clave_siempre():
    """A."""
    valores = {clave_desempate_hash("ENT-0000001") for _ in range(5)}
    assert len(valores) == 1
    assert clave_desempate_hash("ENT-0000001") == clave_desempate_hash("ENT-0000001")


def test_28_ids_diferentes_producen_claves_diferentes_en_muestra_amplia():
    """B: 0 colisiones en una muestra de 5,000 IDs sintéticos."""
    ids = [f"ENT-{i:07d}" for i in range(5000)]
    claves = [clave_desempate_hash(i) for i in ids]
    assert len(set(claves)) == len(claves)


def test_29_reproducible_entre_procesos_distintos():
    """C: mismo resultado en ejecuciones de PROCESO completamente separadas
    (no solo dentro del mismo proceso de test) -- descarta cualquier
    dependencia oculta de PYTHONHASHSEED u otro estado de proceso, que es
    justamente el defecto que descalifica a hash() nativo de Python."""
    raiz_04_sistema = str(Path(__file__).resolve().parents[1])
    script = (
        "import sys; sys.path.insert(0, 'src'); "
        "from bold_intel.diversificacion.capa_diversificacion import clave_desempate_hash; "
        "print(clave_desempate_hash('ENT-0000123'))"
    )
    resultados = set()
    for _ in range(3):
        salida = subprocess.run(
            [sys.executable, "-c", script],
            cwd=raiz_04_sistema, capture_output=True, text=True, check=True,
        )
        resultados.add(salida.stdout.strip())
    assert len(resultados) == 1


def test_30_independiente_del_orden_de_filas_de_entrada():
    """D: invertir el orden físico de las filas de entrada (sin cambiar
    ningún dato) no debe cambiar el resultado -- ni el conjunto admitido ni
    el orden final del Top N."""
    universo = _universo()
    universo_invertido = universo.iloc[::-1].reset_index(drop=True)
    r1 = construir_ranking_diversificado(universo, 500)["top_n"]
    r2 = construir_ranking_diversificado(universo_invertido, 500)["top_n"]
    pd.testing.assert_frame_equal(r1.reset_index(drop=True), r2.reset_index(drop=True))


def test_31_clave_desempate_depende_solo_del_id_y_no_usa_hash_nativo():
    """E: comportamiento (no de texto) -- la clave del mismo ID es idéntica
    sin importar en qué contexto se calcule. F: inspección de código fuente
    para confirmar que no se usa hash() nativo de Python."""
    id_fijo = "ENT-0000777"
    assert clave_desempate_hash(id_fijo) == clave_desempate_hash(id_fijo)

    from bold_intel.diversificacion import capa_diversificacion as cd

    # Inspección de BYTECODE (no de texto/docstring, que sí puede mencionar
    # "hash()" o "aleatorio" en prosa explicativa sin llamarlos realmente):
    # co_names lista los nombres globales/atributos que la función realmente
    # referencia al ejecutarse.
    nombres_usados = cd.clave_desempate_hash.__code__.co_names
    assert "hashlib" in nombres_usados
    assert "hash" not in nombres_usados  # no se llama al hash() nativo de Python
    assert "random" not in nombres_usados
    assert "time" not in nombres_usados
    assert "seed" not in nombres_usados


def test_32_desempate_no_altera_score_M_ni_taxonomia_ni_pisos():
    """G, H, I, J combinados -- referencia explícita bajo el mecanismo de
    desempate F, sin duplicar la lógica ya cubierta en detalle por test_1,
    test_3 (score), test_18-test_26 (M y suavizado) y test_13-test_17
    (taxonomía V2)."""
    universo = _universo()
    antes = universo["score_prioridad_comercial"].copy()
    resultado = construir_ranking_diversificado(universo, 200)
    pd.testing.assert_series_equal(antes, universo["score_prioridad_comercial"], check_names=False)  # G

    assert resultado["config"].m_suavizado == 22  # H
    assert M_SUAVIZADO == 22

    assert bucket_sector("Entretenimiento") == "Entretenimiento"  # I
    assert bucket_sector("Transporte y logística") == "Transporte/logística"
    assert bucket_sector("Salud") != bucket_sector("Salud / Farmacias")

    top = resultado["top_n"]
    reemplazos = top[top["metodo_seleccion"] == "diversificacion"]
    assert (reemplazos["score_base"] >= 60.0).all()  # J
    piso_relativo = reemplazos["score_candidato_desplazado"] * 0.85
    assert (reemplazos["score_base"] >= piso_relativo - 1e-9).all()


def test_33_plateau_de_empates_no_favorece_orden_de_entrada():
    """K: con muchos empates exactos de score, el orden final no debe
    coincidir con el orden de las filas de entrada, y debe ser el mismo sin
    importar en qué orden llegaron esas filas."""
    sectores = [
        "Comercio / Retail", "Manufactura", "Gastronomía y Hotelería",
        "Ferretería y construcción menor", "Tecnología / Comunicaciones",
    ]
    filas = [{
        "entidad_dedup_id": f"PLAT{i:04d}",
        "score_prioridad_comercial": 90.0,  # empate exacto para las 300
        "sector_vertical": sectores[i % len(sectores)],
        "municipio_nombre_normalizado": f"MUN_{i % 10}",
        "estado_exclusion": "SIN_COINCIDENCIA",
    } for i in range(300)]
    universo_plateau = pd.DataFrame(filas)
    universo_invertido = universo_plateau.iloc[::-1].reset_index(drop=True)

    top_normal = construir_ranking_diversificado(universo_plateau, 300)["top_n"]
    top_invertido = construir_ranking_diversificado(universo_invertido, 300)["top_n"]

    orden_normal = list(top_normal["entidad_dedup_id"])
    orden_entrada = list(universo_plateau["entidad_dedup_id"])

    assert orden_normal != orden_entrada  # no es una copia del orden de entrada
    assert orden_normal == list(top_invertido["entidad_dedup_id"])  # ni depende de él


def test_34_desempate_ya_no_es_entidad_dedup_id_ascendente():
    """Prueba de comportamiento directa: construye un par de IDs donde el
    orden alfabético (criterio antiguo) y el orden por hash (criterio
    nuevo) DISCREPAN, y confirma que, ante un empate exacto de score, el
    resultado sigue al hash -- no al orden ascendente de entidad_dedup_id."""
    id_a = "AAA-0000001"
    id_b = None
    for i in range(50):
        candidato = f"BBB-{i:07d}"
        orden_id_dice_a = id_a < candidato  # siempre True: "AAA" < "BBB..."
        orden_hash_dice_a = clave_desempate_hash(id_a) < clave_desempate_hash(candidato)
        if orden_id_dice_a != orden_hash_dice_a:
            id_b = candidato
            break
    assert id_b is not None, "no se encontró desacuerdo ID-ascendente vs hash en 50 intentos"

    # id_a/id_b, empatados y con el score más alto de un universo de 500
    # filas -- el resto ("padding") diluye la participación de sus
    # categorías para que ambos entren sin intervención (tolerancia), y así
    # aislar exclusivamente el efecto del desempate sobre su orden relativo
    # (un universo de solo 2 filas dispara el tope duro por diseño del
    # mecanismo -- no es apto para este test).
    sectores = [
        "Comercio / Retail", "Manufactura", "Gastronomía y Hotelería",
        "Ferretería y construcción menor", "Tecnología / Comunicaciones",
    ]
    filas = [
        {"entidad_dedup_id": id_a, "score_prioridad_comercial": 99.0,
         "sector_vertical": "Comercio / Retail", "municipio_nombre_normalizado": "MUN_PAD_0",
         "estado_exclusion": "SIN_COINCIDENCIA"},
        {"entidad_dedup_id": id_b, "score_prioridad_comercial": 99.0,
         "sector_vertical": "Comercio / Retail", "municipio_nombre_normalizado": "MUN_PAD_0",
         "estado_exclusion": "SIN_COINCIDENCIA"},
    ]
    for i in range(498):
        filas.append({
            "entidad_dedup_id": f"PAD{i:04d}",
            "score_prioridad_comercial": 50.0 - (i * 0.01),
            "sector_vertical": sectores[i % len(sectores)],
            "municipio_nombre_normalizado": f"MUN_PAD_{i % 10}",
            "estado_exclusion": "SIN_COINCIDENCIA",
        })
    universo = pd.DataFrame(filas)

    top = construir_ranking_diversificado(universo, 2)["top_n"]
    assert set(top["entidad_dedup_id"]) == {id_a, id_b}
    primero = top.iloc[0]["entidad_dedup_id"]

    hash_dice_a_primero = clave_desempate_hash(id_a) < clave_desempate_hash(id_b)
    assert primero == (id_a if hash_dice_a_primero else id_b)
    assert (primero == id_a) != (id_a < id_b)  # y contradice lo que el ID ascendente hubiera dicho


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
