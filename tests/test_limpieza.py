"""
Pruebas de las funciones puras de normalizacion/limpieza.py.

No tocan 01_BASES_RAW ni ningún archivo del proyecto — usan solo strings de
ejemplo. Se pueden correr en cualquier momento sin instalar dependencias
adicionales (pytest incluido, ver requirements.txt).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bold_intel.normalizacion.limpieza import (
    es_valor_nulo_declarado,
    normalizar_email,
    normalizar_nit,
    normalizar_telefono,
    normalizar_texto,
)


def test_normalizar_texto_quita_tildes_y_colapsa_espacios():
    assert normalizar_texto("  Cámara de Comercio   de Pereira  ") == "CAMARA DE COMERCIO DE PEREIRA"


def test_normalizar_texto_reconoce_nulos_declarados():
    assert normalizar_texto("N/A") is None
    assert normalizar_texto("No reporta") is None
    assert normalizar_texto("No aplica") is None
    assert normalizar_texto("") is None


def test_normalizar_nit_deja_solo_digitos():
    assert normalizar_nit("8.160.024.518") == "8160024518"
    assert normalizar_nit("9015371367") == "9015371367"
    assert normalizar_nit(None) is None


def test_normalizar_telefono():
    assert normalizar_telefono("310-611-6510") == "3106116510"
    assert normalizar_telefono("N/A") is None


def test_normalizar_email():
    assert normalizar_email("  Contador@Empresa.COM  ") == "contador@empresa.com"
    assert normalizar_email("no reporta") is None
    assert normalizar_email("sin-arroba") is None


def test_es_valor_nulo_declarado():
    assert es_valor_nulo_declarado("No reportado") is True
    assert es_valor_nulo_declarado("PEREIRA") is False
    assert es_valor_nulo_declarado(None) is True


if __name__ == "__main__":
    # Permite correr `python test_limpieza.py` sin pytest instalado.
    fallos = 0
    for nombre, funcion in list(globals().items()):
        if nombre.startswith("test_") and callable(funcion):
            try:
                funcion()
                print(f"OK   {nombre}")
            except AssertionError:
                fallos += 1
                print(f"FAIL {nombre}")
    raise SystemExit(fallos)
