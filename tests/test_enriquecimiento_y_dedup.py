"""
Pruebas de las funciones puras de enriquecimiento y de generación de clave
de deduplicación. No procesan ningún archivo de 01_BASES_RAW.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sales_intel.deduplicacion.dedup_registros import generar_clave_negocio
from sales_intel.enriquecimiento.clasificador_tamano import clasificar_tamano
from sales_intel.enriquecimiento.mapeo_sectorial import obtener_sector_comercial


def test_sector_bold_por_excepcion_especifica():
    r = obtener_sector_comercial("G4773 ** Comercio al por menor de productos farmaceuticos")
    assert r["sector_bold"] == "Salud / Farmacias"
    assert r["encaje_pagos_bold"] == "alto"


def test_sector_bold_por_seccion_general():
    r = obtener_sector_comercial("I5611 ** Expendio a la mesa de comidas preparadas")
    assert r["seccion"] == "I"
    assert r["sector_bold"] == "Gastronomía y Hotelería"


def test_sector_bold_codigo_no_reconocido():
    r = obtener_sector_comercial("texto sin formato ciiu")
    assert r["sector_bold"] is None


def test_clasificar_tamano_por_etiqueta_declarada():
    r = clasificar_tamano(tamano_declarado="MICRO EMPRESA")
    assert r["tamano_empresa"] == "micro"
    assert r["nivel_confianza"] == "confirmado"


def test_clasificar_tamano_por_empleados():
    r = clasificar_tamano(num_empleados=950)
    assert r["tamano_empresa"] == "grande"
    assert r["nivel_confianza"] == "inferido"


def test_clasificar_tamano_sin_datos():
    r = clasificar_tamano()
    assert r["tamano_empresa"] == "sin_dato"


def test_clave_negocio_por_nit():
    clave, metodo = generar_clave_negocio("9.015.371.367", "GREEN ECOHOUSE SAS BIC", "BUENAVENTURA")
    assert clave == "nit:9015371367"
    assert metodo == "nit"


def test_clave_negocio_respaldo_por_razon_y_municipio():
    clave, metodo = generar_clave_negocio(None, "Tienda La Florida", "Armenia")
    assert clave == "razon_municipio:TIENDA LA FLORIDA|ARMENIA"
    assert metodo == "razon_municipio"


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
