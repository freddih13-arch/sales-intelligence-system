"""
Pruebas de la ORQUESTACIÓN del enriquecimiento legal
(`orquestador_enriquecimiento.py`) — TODO con clientes/cachés FAKE, sin
ninguna llamada de red. Incluye una prueba de integración de extremo a
extremo sobre el Top 100 REAL (`top100_diversificado_20260902.csv`), leído
en modo estrictamente solo lectura -- se verifica explícitamente que el
archivo no cambia.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from sales_intel.enriquecimiento_legal.capa_enriquecimiento_legal import CAMPOS_COMERCIALES
from sales_intel.enriquecimiento_legal.cliente_confecamaras import CacheEnMemoria, RespuestaConfecamaras
from sales_intel.enriquecimiento_legal.orquestador_enriquecimiento import (
    enriquecer_prospectos,
    enriquecer_top_n_desde_csv,
    leer_prospectos_desde_csv,
)
from sales_intel.utils.config import TOP_PROSPECTOS_DIR

RUTA_TOP100_REAL = TOP_PROSPECTOS_DIR / "top100_diversificado_20260902.csv"

REGISTRO_ACTIVO = {
    "nit": "901955318", "digito_verificacion": "3",
    "razon_social": "INVERSIONES GRUPO C&D S.A.S.",
    "organizacion_juridica": "SOCIEDADES POR ACCIONES SIMPLIFICADAS SAS",
    "representante_legal": "REPRESENTANTE EJEMPLO S.A.S.",
    "num_identificacion_representante_legal": "1088296164",
    "estado_matricula": "ACTIVA", "matricula": "18228847", "camara_comercio": "PEREIRA",
}


class ClienteFake:
    """Responde con una tabla fija de resultados por NIT base -- una
    consulta a un NIT no programado hace fallar la prueba explícitamente
    (detecta consultas inesperadas, en vez de fallar de forma confusa)."""

    def __init__(self, respuestas: dict):
        self._respuestas = respuestas
        self.llamadas = []

    def consultar_nit(self, nit_base):
        self.llamadas.append(nit_base)
        if nit_base not in self._respuestas:
            raise AssertionError(f"ClienteFake: consulta inesperada para NIT base {nit_base!r}")
        return self._respuestas[nit_base]


class ClienteGenericoFake:
    """Responde EXITO/ACTIVA para CUALQUIER NIT consultado -- usado solo
    para la prueba de integración de extremo a extremo sobre el Top 100
    real, donde programar una respuesta por cada uno de los ~98 NIT reales
    sería impráctico e innecesario para lo que esa prueba verifica."""

    def __init__(self):
        self.llamadas = []

    def consultar_nit(self, nit_base):
        self.llamadas.append(nit_base)
        registro = dict(REGISTRO_ACTIVO, nit=nit_base, digito_verificacion="0")
        return RespuestaConfecamaras(ok=True, registros=(registro,))


def _prospecto(entidad_dedup_id, posicion, nit, razon_social):
    return {
        "entidad_dedup_id": entidad_dedup_id,
        "posicion_diversificada": posicion,
        "nit": nit,
        "razon_social": razon_social,
    }


# ---------------------------------------------------------------------------
# A-E: los 5 resultados de match posibles, a nivel de orquestación
# ---------------------------------------------------------------------------

def test_A_nit_valido_match_confirmado():
    prospectos = [_prospecto("ENT-0128399", 1, "9019553183", "INVERSIONES GRUPO C&D S.A.S.")]
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert len(salida) == 1
    assert salida[0]["resultado_match"] == "MATCH_CONFIRMADO"
    assert salida[0]["nit"] == "9019553183"  # el original, sin tocar


def test_B_nit_valido_match_con_observacion():
    registro_distinto = dict(REGISTRO_ACTIVO, razon_social="COMERCIALIZADORA COMPLETAMENTE DISTINTA SAS")
    prospectos = [_prospecto("ENT-0084685", 24, "9000399996", "BERLLANO S.A")]
    cliente = ClienteFake({"900039999": RespuestaConfecamaras(ok=True, registros=(registro_distinto,))})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert salida[0]["resultado_match"] == "MATCH_CON_OBSERVACION"


def test_C_nit_valido_no_match():
    prospectos = [_prospecto("ENT-X", 99, "9099999999", "CUALQUIERA")]
    cliente = ClienteFake({"909999999": RespuestaConfecamaras(ok=True, registros=())})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert salida[0]["resultado_match"] == "NO_MATCH"


def test_D_nit_ausente_no_consultable():
    prospectos = [_prospecto("ENT-0376562", 40, None, "TRUJILLO JORDAN DERLY JANETH")]
    cliente = ClienteFake({})  # no debe llamarse -- cualquier llamada hace fallar la prueba
    salida = enriquecer_prospectos(prospectos, cliente)
    assert salida[0]["resultado_match"] == "NO_CONSULTABLE"
    assert len(cliente.llamadas) == 0


def test_E_error_tecnico_final_error_consulta():
    prospectos = [_prospecto("ENT-X", 1, "9019553183", "X")]
    # ok=False representa el resultado YA final del cliente resiliente
    # (reintentos agotados) -- el orquestador no repite ni interpreta esto.
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=False, registros=(), error="timeout tras reintentos")})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert salida[0]["resultado_match"] == "ERROR_CONSULTA"


# ---------------------------------------------------------------------------
# F. Uso de la caché
# ---------------------------------------------------------------------------

def test_F_uso_de_cache_evita_segunda_consulta():
    prospecto = _prospecto("ENT-0128399", 1, "9019553183", "INVERSIONES GRUPO C&D S.A.S.")
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    cache = CacheEnMemoria(ahora=lambda: 1000.0)

    salida1 = enriquecer_prospectos([prospecto], cliente, cache=cache, ahora=lambda: 1000.0)
    salida2 = enriquecer_prospectos([prospecto], cliente, cache=cache, ahora=lambda: 1000.0)

    assert len(cliente.llamadas) == 1  # la 2da vino de la caché, no del cliente
    assert salida1 == salida2


def test_F_error_consulta_no_se_cachea():
    prospecto = _prospecto("ENT-X", 1, "9019553183", "X")
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=False, registros=(), error="fallo")})
    cache = CacheEnMemoria(ahora=lambda: 1000.0)

    enriquecer_prospectos([prospecto], cliente, cache=cache, ahora=lambda: 1000.0)
    enriquecer_prospectos([prospecto], cliente, cache=cache, ahora=lambda: 1000.0)

    assert len(cliente.llamadas) == 2  # NUNCA se cachea ERROR_CONSULTA -- se reintenta la corrida siguiente


# ---------------------------------------------------------------------------
# G. No se modifica el Top 100 de entrada
# ---------------------------------------------------------------------------

def test_G_no_modifica_el_diccionario_de_entrada():
    prospecto = _prospecto("ENT-0128399", 1, "9019553183", "INVERSIONES GRUPO C&D S.A.S.")
    copia_antes = dict(prospecto)
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    enriquecer_prospectos([prospecto], cliente)
    assert prospecto == copia_antes


def test_G_no_modifica_el_archivo_csv_real():
    antes = hashlib.sha256(RUTA_TOP100_REAL.read_bytes()).hexdigest()
    leer_prospectos_desde_csv(RUTA_TOP100_REAL)
    despues = hashlib.sha256(RUTA_TOP100_REAL.read_bytes()).hexdigest()
    assert antes == despues


# ---------------------------------------------------------------------------
# H. Exactamente una fila de salida por prospecto
# ---------------------------------------------------------------------------

def test_H_una_fila_de_salida_por_prospecto():
    prospectos = [
        _prospecto("A", 1, "9019553183", "X"),
        _prospecto("B", 2, None, "Y"),
        _prospecto("C", 3, "9000399996", "Z"),
    ]
    cliente = ClienteFake({
        "901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,)),
        "900039999": RespuestaConfecamaras(ok=True, registros=()),
    })
    salida = enriquecer_prospectos(prospectos, cliente)
    assert len(salida) == 3


# ---------------------------------------------------------------------------
# I. Conservación exacta de entidad_dedup_id y posicion_diversificada
# ---------------------------------------------------------------------------

def test_I_conserva_entidad_dedup_id_y_posicion():
    prospectos = [_prospecto("ENT-0128399", 1, "9019553183", "X")]
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert salida[0]["entidad_dedup_id"] == "ENT-0128399"
    assert salida[0]["posicion_diversificada"] == 1


# ---------------------------------------------------------------------------
# J. num_identificacion_representante_legal no aparece en la salida
# ---------------------------------------------------------------------------

def test_J_sin_identificacion_representante_legal():
    assert "num_identificacion_representante_legal" in REGISTRO_ACTIVO  # confirma que la fuente cruda sí lo trae
    prospectos = [_prospecto("ENT-X", 1, "9019553183", "X")]
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert "num_identificacion_representante_legal" not in salida[0]
    assert set(salida[0].keys()) == set(CAMPOS_COMERCIALES)  # exactamente los 12 campos aprobados


# ---------------------------------------------------------------------------
# K/L. No se generan ni se eliminan prospectos
# ---------------------------------------------------------------------------

def test_K_L_no_genera_ni_elimina_prospectos():
    prospectos = [_prospecto(f"ENT-{i}", i, "9019553183", "X") for i in range(5)]
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    salida = enriquecer_prospectos(prospectos, cliente)
    assert {p["entidad_dedup_id"] for p in prospectos} == {r["entidad_dedup_id"] for r in salida}
    assert len(salida) == len(prospectos)


# ---------------------------------------------------------------------------
# M. Orden de salida reproducible
# ---------------------------------------------------------------------------

def test_M_orden_de_salida_reproducible():
    prospectos = [_prospecto(f"ENT-{i}", i, "9019553183", "X") for i in range(5)]
    orden_entrada = [p["entidad_dedup_id"] for p in prospectos]

    cliente1 = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    cliente2 = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    salida1 = enriquecer_prospectos(prospectos, cliente1)
    salida2 = enriquecer_prospectos(prospectos, cliente2)

    assert [r["entidad_dedup_id"] for r in salida1] == orden_entrada
    assert [r["entidad_dedup_id"] for r in salida2] == orden_entrada


# ---------------------------------------------------------------------------
# N. Delega los reintentos al cliente -- sin política paralela
# ---------------------------------------------------------------------------

def test_N_delega_reintentos_sin_politica_paralela():
    prospectos = [_prospecto("ENT-X", 1, "9019553183", "X")]
    # El cliente ya representa un resultado FINAL (como lo entregaría
    # ClienteConfecamarasSocrata tras agotar su propia política) -- si el
    # orquestador implementara una segunda política, llamaría más de una vez.
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=False, registros=(), error="final tras reintentos del cliente")})
    enriquecer_prospectos(prospectos, cliente)
    assert len(cliente.llamadas) == 1


# ---------------------------------------------------------------------------
# Integración de extremo a extremo sobre el Top 100 REAL (solo lectura)
# ---------------------------------------------------------------------------

def test_integracion_top100_real_sin_tocar_el_archivo():
    antes = hashlib.sha256(RUTA_TOP100_REAL.read_bytes()).hexdigest()

    cliente = ClienteGenericoFake()
    salida = enriquecer_top_n_desde_csv(RUTA_TOP100_REAL, cliente)

    despues = hashlib.sha256(RUTA_TOP100_REAL.read_bytes()).hexdigest()
    assert antes == despues, "el Top 100 real no debe modificarse"

    assert len(salida) == 100
    ids_csv = set(pd.read_csv(RUTA_TOP100_REAL)["entidad_dedup_id"])
    ids_salida = {r["entidad_dedup_id"] for r in salida}
    assert ids_csv == ids_salida

    no_consultables = [r for r in salida if r["resultado_match"] == "NO_CONSULTABLE"]
    assert len(no_consultables) == 2  # posiciones 40 y 41, ya identificadas en la auditoría comercial previa
    assert len(cliente.llamadas) == 98  # 100 - 2 sin NIT, ni una consulta de más


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
