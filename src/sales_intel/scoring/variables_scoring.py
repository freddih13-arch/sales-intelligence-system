"""
Carga de la configuración FINAL Y APROBADA del Score de Prioridad Comercial
desde config/scoring_variables.yaml (estructura `dimensiones` con pesos
40/35/25/0, escala de fit sectorial, ordinal de tamaño y fórmula de
cobertura). Puro stdlib+yaml — no depende de pandas.

Reemplaza la versión de fase de diseño (que exponía `variables` con
`peso_provisional: null`); esa lista queda archivada en el propio YAML bajo
`variables_borrador_v1_superadas`, solo por trazabilidad histórica.
"""

from __future__ import annotations

from sales_intel.utils.config import cargar_scoring_variables

NOMBRE_SCORE = "Score de Prioridad Comercial"
NOMBRE_PROHIBIDO = "predicción de TPV"

PESO_FIT = "fit_comercial"
PESO_ESCALA = "escala_potencial"
PESO_CONTACTO = "contactabilidad"


def pesos_definidos() -> bool:
    """True solo si config/scoring_variables.yaml declara
    metadata.pesos_definidos: true Y los 3 pesos activos suman 1.00. Es la
    salvaguarda que motor_scoring.py usa antes de calcular cualquier score."""
    config = cargar_scoring_variables()
    if not config["metadata"].get("pesos_definidos", False):
        return False
    dims = config["dimensiones"]
    suma = dims[PESO_FIT]["peso"] + dims[PESO_ESCALA]["peso"] + dims[PESO_CONTACTO]["peso"]
    return abs(suma - 1.0) < 1e-9


def obtener_pesos() -> dict[str, float]:
    """{'fit_comercial': 0.40, 'escala_potencial': 0.35, 'contactabilidad': 0.25}"""
    dims = cargar_scoring_variables()["dimensiones"]
    return {
        PESO_FIT: dims[PESO_FIT]["peso"],
        PESO_ESCALA: dims[PESO_ESCALA]["peso"],
        PESO_CONTACTO: dims[PESO_CONTACTO]["peso"],
    }


def obtener_escala_fit() -> dict:
    """{'sectores_estrategicos': {...}, 'encaje_generico': {...}}"""
    return cargar_scoring_variables()["dimensiones"][PESO_FIT]["escala_valores"]


def obtener_ordinal_tamano() -> dict[str, float]:
    """{'micro': 0.25, 'pequena': 0.50, 'mediana': 0.75, 'grande': 1.00}"""
    return cargar_scoring_variables()["dimensiones"][PESO_ESCALA]["ordinal_tamano_empresa"]


def obtener_valores_contactabilidad() -> dict[str, float]:
    """{'telefono_y_email': 1.00, 'solo_uno': 0.60, 'ninguno': 0.00}"""
    return cargar_scoring_variables()["dimensiones"][PESO_CONTACTO]["valores"]


def obtener_constantes_cobertura() -> dict:
    """Constantes textuales de la fórmula de cobertura (documentales; las
    constantes numéricas 0.70/0.30/3 están fijadas en motor_scoring.py junto
    a la implementación, por ser parte indisociable de la fórmula acordada)."""
    return cargar_scoring_variables()["formula_cobertura"]
