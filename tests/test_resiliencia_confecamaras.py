"""
Pruebas de la POLÍTICA DE RESILIENCIA del cliente de Confecámaras
(`ClienteConfecamarasSocrata`) — timeout, reintentos, backoff+jitter, 429,
rate limiting propio y su interacción con la capa de negocio.

TODO con MOCKS -- ninguna prueba de este archivo hace una llamada de red
real ni espera físicamente ningún segundo: `transporte` reemplaza la
llamada HTTP por una secuencia programada de `ResultadoIntentoCrudo`, y
`dormir` reemplaza `time.sleep` por un espía que solo registra cuánto se le
pidió esperar, sin bloquear.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bold_intel.enriquecimiento_legal.capa_enriquecimiento_legal import (
    clasificar_match,
    normalizar_nit_para_consulta,
    preparar_registro_enriquecido,
)
from bold_intel.enriquecimiento_legal.cliente_confecamaras import (
    ClienteConfecamarasSocrata,
    EventoIntento,
    PoliticaResiliencia,
    RegistradorEnMemoria,
    ResultadoIntentoCrudo,
    es_cacheable,
    ttl_cache_segundos,
)


# ---------------------------------------------------------------------------
# Dobles de prueba
# ---------------------------------------------------------------------------

class TransporteSecuenciaMock:
    """Devuelve, en orden, cada resultado de una lista predefinida -- una
    llamada de más hace fallar la prueba explícitamente (en vez de fallar
    de forma confusa), para detectar reintentos no esperados."""

    def __init__(self, secuencia):
        self._secuencia = list(secuencia)
        self.llamadas = []

    def __call__(self, nit_base):
        self.llamadas.append(nit_base)
        if not self._secuencia:
            raise AssertionError("TransporteSecuenciaMock: se agotó la secuencia -- llamada de más, no esperada")
        return self._secuencia.pop(0)


class DormirEspia:
    """Registra cuánto se le pidió esperar, sin esperar de verdad."""

    def __init__(self):
        self.llamadas = []

    def __call__(self, segundos):
        self.llamadas.append(segundos)


REGISTRO_EJEMPLO = {
    "nit": "901955318", "digito_verificacion": "3",
    "razon_social": "INVERSIONES GRUPO C&D S.A.S.",
    "organizacion_juridica": "SOCIEDADES POR ACCIONES SIMPLIFICADAS SAS",
    "representante_legal": "REPRESENTANTE EJEMPLO S.A.S.",
    "num_identificacion_representante_legal": "1088296164",
    "estado_matricula": "ACTIVA", "matricula": "18228847", "camara_comercio": "PEREIRA",
}


def _cliente(secuencia, dormir=None):
    transporte = TransporteSecuenciaMock(secuencia)
    dormir = dormir if dormir is not None else DormirEspia()
    cliente = ClienteConfecamarasSocrata(transporte=transporte, dormir=dormir)
    return cliente, transporte, dormir


# ---------------------------------------------------------------------------
# A-E: error reintentable -> reintento -> éxito
# ---------------------------------------------------------------------------

def _caso_reintentable_luego_exito(codigo_http, detalle):
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=codigo_http, detalle_error=detalle),
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is True
    assert len(respuesta.registros) == 1
    assert len(transporte.llamadas) == 2
    assert len(dormir.llamadas) == 1
    assert 0.7 <= dormir.llamadas[0] <= 1.3  # backoff base 1s, jitter +-25%


def test_A_timeout_reintento_exito():
    _caso_reintentable_luego_exito(None, "Timeout: read timed out")


def test_B_503_reintento_exito():
    _caso_reintentable_luego_exito(503, "HTTPError 503")


def test_C_500_reintento_exito():
    _caso_reintentable_luego_exito(500, "HTTPError 500")


def test_D_502_reintento_exito():
    _caso_reintentable_luego_exito(502, "HTTPError 502")


def test_E_504_reintento_exito():
    _caso_reintentable_luego_exito(504, "HTTPError 504")


# ---------------------------------------------------------------------------
# F. 429 con Retry-After -- respeta la espera exacta (y el caso >60s)
# ---------------------------------------------------------------------------

def test_F_429_con_retry_after_respeta_espera():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=429, retry_after_segundos=5.0, detalle_error="429"),
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is True
    assert len(dormir.llamadas) == 1
    assert dormir.llamadas[0] == 5.0  # SIN jitter -- se respeta tal cual
    assert cliente._rate_limit_elevado is True
    assert cliente._intervalo_actual == 0.6


def test_F_429_con_retry_after_excesivo_termina_sin_mas_reintentos():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=429, retry_after_segundos=120.0, detalle_error="429"),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is False
    assert "Retry-After" in respuesta.error
    assert len(transporte.llamadas) == 1  # no se reintenta pese a quedar intentos disponibles
    assert len(dormir.llamadas) == 0


# ---------------------------------------------------------------------------
# G. 429 sin Retry-After -- backoff especial (base 2s, no 1s)
# ---------------------------------------------------------------------------

def test_G_429_sin_retry_after_backoff_especial():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=429, retry_after_segundos=None, detalle_error="429"),
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is True
    assert len(dormir.llamadas) == 1
    assert 1.4 <= dormir.llamadas[0] <= 2.6  # base 2s (no 1s), jitter +-25%
    assert cliente._rate_limit_elevado is True


# ---------------------------------------------------------------------------
# H. error de conexión -> reintentos -> ERROR_CONSULTA
# ---------------------------------------------------------------------------

def test_H_error_conexion_agota_reintentos_error_consulta():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error="Conexión interrumpida: ..."),
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error="Conexión interrumpida: ..."),
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error="Conexión interrumpida: ..."),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is False
    assert len(transporte.llamadas) == 3
    assert len(dormir.llamadas) == 2  # backoff tras el 1er y 2do fallo, no tras el 3ro (ya no se reintenta)


# ---------------------------------------------------------------------------
# I. 3 fallos consecutivos (genérico) -> ERROR_CONSULTA
# ---------------------------------------------------------------------------

def test_I_tres_fallos_consecutivos_error_consulta():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=503, detalle_error="503"),
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=503, detalle_error="503"),
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=503, detalle_error="503"),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is False
    assert len(transporte.llamadas) == 3
    resultado_match = clasificar_match(normalizar_nit_para_consulta("9019553183"), respuesta, "X")
    assert resultado_match == "ERROR_CONSULTA"  # nunca NO_MATCH ante fallo técnico


# ---------------------------------------------------------------------------
# J/K. Errores NO reintentables -> ERROR_CONSULTA sin reintentos
# ---------------------------------------------------------------------------

def test_J_http_400_error_consulta_sin_reintentos():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_NO_REINTENTABLE", codigo_http=400, detalle_error="HTTPError 400"),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is False
    assert len(transporte.llamadas) == 1
    assert len(dormir.llamadas) == 0


def test_K_http_404_error_consulta_sin_reintentos():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="ERROR_NO_REINTENTABLE", codigo_http=404, detalle_error="HTTPError 404"),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is False
    assert len(transporte.llamadas) == 1
    assert len(dormir.llamadas) == 0


# ---------------------------------------------------------------------------
# L. JSON inválido -> máximo 1 reintento (no agota los 3 intentos generales)
# ---------------------------------------------------------------------------

def test_L_json_invalido_un_reintento_luego_exito():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="JSON_INVALIDO", detalle_error="Expecting value"),
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is True
    assert len(transporte.llamadas) == 2


def test_L_json_invalido_dos_veces_error_consulta_sin_tercer_intento():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="JSON_INVALIDO", detalle_error="Expecting value"),
        ResultadoIntentoCrudo(tipo="JSON_INVALIDO", detalle_error="Expecting value"),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is False
    assert len(transporte.llamadas) == 2  # NUNCA un 3er intento, aunque la política general permite 3


# ---------------------------------------------------------------------------
# M. >1 registro -> ERROR_CONSULTA sin reintento (decisión de negocio, no técnica)
# ---------------------------------------------------------------------------

def test_M_mas_de_un_registro_no_reintenta_y_business_layer_lo_marca_error():
    cliente, transporte, dormir = _cliente([
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO, dict(REGISTRO_EJEMPLO))),
    ])
    respuesta = cliente.consultar_nit("901955318")
    assert respuesta.ok is True  # el cliente SÍ tuvo éxito técnico -- no es su decisión clasificar esto
    assert len(respuesta.registros) == 2
    assert len(transporte.llamadas) == 1  # sin reintento -- no es un error técnico

    norm = normalizar_nit_para_consulta("9019553183")
    resultado_match = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    assert resultado_match == "ERROR_CONSULTA"  # la capa de negocio lo resuelve, sin fuzzy matching ni elección arbitraria


# ---------------------------------------------------------------------------
# N/O. 0 registros -> NO_MATCH; 1 registro -> flujo normal de match
# ---------------------------------------------------------------------------

def test_N_cero_registros_es_no_match():
    cliente, transporte, dormir = _cliente([ResultadoIntentoCrudo(tipo="EXITO", registros=())])
    respuesta = cliente.consultar_nit("909999999")
    assert respuesta.ok is True
    assert len(respuesta.registros) == 0
    norm = normalizar_nit_para_consulta("9099999999")
    assert clasificar_match(norm, respuesta, "CUALQUIERA") == "NO_MATCH"


def test_O_un_registro_flujo_normal_de_match():
    cliente, transporte, dormir = _cliente([ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,))])
    respuesta = cliente.consultar_nit("901955318")
    norm = normalizar_nit_para_consulta("9019553183")
    resultado_match = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    assert resultado_match == "MATCH_CONFIRMADO"


# ---------------------------------------------------------------------------
# P. NO_MATCH nunca se produce por una excepción técnica
# ---------------------------------------------------------------------------

def test_P_no_match_nunca_por_fallo_tecnico():
    escenarios = [
        [ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error="Timeout")] * 3,
        [ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=503, detalle_error="503")] * 3,
        [ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=429, retry_after_segundos=None, detalle_error="429")] * 3,
        [ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error="DNS")] * 3,
        [ResultadoIntentoCrudo(tipo="ERROR_NO_REINTENTABLE", codigo_http=400, detalle_error="400")],
    ]
    for secuencia in escenarios:
        cliente, _, _ = _cliente(secuencia)
        respuesta = cliente.consultar_nit("901955318")
        assert respuesta.ok is False
        norm = normalizar_nit_para_consulta("9019553183")
        resultado_match = clasificar_match(norm, respuesta, "X")
        assert resultado_match == "ERROR_CONSULTA", f"no debía ser NO_MATCH: {secuencia}"
        assert resultado_match != "NO_MATCH"


# ---------------------------------------------------------------------------
# Q. El NIT original nunca cambia
# ---------------------------------------------------------------------------

def test_Q_nit_original_nunca_cambia():
    nit_original = "9019553183"
    cliente, _, _ = _cliente([ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,))])
    norm = normalizar_nit_para_consulta(nit_original)
    respuesta = cliente.consultar_nit(norm.nit_consultado)
    resultado_match = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    salida = preparar_registro_enriquecido("ENT-X", 1, nit_original, norm, respuesta, resultado_match)
    assert salida["nit"] == nit_original
    assert norm.nit_original == nit_original


# ---------------------------------------------------------------------------
# R. num_identificacion_representante_legal no aparece en el resultado comercial
# ---------------------------------------------------------------------------

def test_R_sin_identificacion_representante_legal_en_resultado_comercial():
    cliente, _, _ = _cliente([ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,))])
    assert "num_identificacion_representante_legal" in REGISTRO_EJEMPLO  # la respuesta cruda SÍ lo trae
    norm = normalizar_nit_para_consulta("9019553183")
    respuesta = cliente.consultar_nit(norm.nit_consultado)
    resultado_match = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    salida = preparar_registro_enriquecido("ENT-X", 1, "9019553183", norm, respuesta, resultado_match)
    assert "num_identificacion_representante_legal" not in salida

    # tampoco como campo del EventoIntento de log:
    registrador = RegistradorEnMemoria()
    cliente2, _, _ = _cliente([ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,))])
    cliente2._registrador = registrador
    cliente2.consultar_nit("901955318")
    assert len(registrador.eventos) == 1
    assert not hasattr(registrador.eventos[0], "num_identificacion_representante_legal")
    assert "num_identificacion_representante_legal" not in EventoIntento.__dataclass_fields__


# ---------------------------------------------------------------------------
# S. Rate limiting de 300 ms entre solicitudes normales
# ---------------------------------------------------------------------------

def test_S_rate_limiting_300ms_entre_solicitudes():
    transporte = TransporteSecuenciaMock([
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),
    ])
    dormir = DormirEspia()
    cliente = ClienteConfecamarasSocrata(transporte=transporte, dormir=dormir)

    cliente.consultar_nit("901955318")   # 1ra consulta -- sin espera previa (nada que espaciar todavía)
    assert len(dormir.llamadas) == 0

    cliente.consultar_nit("900648107")   # 2da consulta -- debe esperar ~300ms desde la anterior
    assert len(dormir.llamadas) == 1
    assert 0.25 <= dormir.llamadas[0] <= 0.35


# ---------------------------------------------------------------------------
# T. Un 429 eleva el intervalo posterior a 600 ms
# ---------------------------------------------------------------------------

def test_T_429_eleva_intervalo_a_600ms_para_el_resto_de_la_corrida():
    transporte = TransporteSecuenciaMock([
        ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", codigo_http=429, retry_after_segundos=None, detalle_error="429"),
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),  # resuelve el NIT A en el reintento
        ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,)),  # NIT B, primera y única llamada
    ])
    dormir = DormirEspia()
    cliente = ClienteConfecamarasSocrata(transporte=transporte, dormir=dormir)

    cliente.consultar_nit("901955318")  # NIT A -- dispara 429 en el 1er intento
    assert cliente._intervalo_actual == 0.6

    cliente.consultar_nit("900648107")  # NIT B -- el espaciado antes de esta llamada ya debe ser 600ms, no 300ms
    ultima_espera = dormir.llamadas[-1]
    assert 0.5 <= ultima_espera <= 0.7


# ---------------------------------------------------------------------------
# U. Idempotencia -- misma entrada, mismo resultado
# ---------------------------------------------------------------------------

def test_U_idempotencia():
    resultados = []
    for _ in range(3):
        cliente, _, _ = _cliente([ResultadoIntentoCrudo(tipo="EXITO", registros=(REGISTRO_EJEMPLO,))])
        norm = normalizar_nit_para_consulta("9019553183")
        respuesta = cliente.consultar_nit(norm.nit_consultado)
        resultado_match = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
        salida = preparar_registro_enriquecido("ENT-0128399", 1, "9019553183", norm, respuesta, resultado_match)
        resultados.append(salida)
    assert resultados[0] == resultados[1] == resultados[2]


# ---------------------------------------------------------------------------
# Caché -- interfaz preparada (TTL por resultado_match, spec §12)
# ---------------------------------------------------------------------------

def test_politica_de_cache_ttl_por_resultado():
    assert es_cacheable("MATCH_CONFIRMADO") is True
    assert es_cacheable("MATCH_CON_OBSERVACION") is True
    assert es_cacheable("NO_MATCH") is True
    assert es_cacheable("NO_CONSULTABLE") is True
    assert es_cacheable("ERROR_CONSULTA") is False  # NUNCA cacheable

    assert ttl_cache_segundos("MATCH_CONFIRMADO") == 7 * 24 * 3600
    assert ttl_cache_segundos("MATCH_CON_OBSERVACION") == 7 * 24 * 3600
    assert ttl_cache_segundos("NO_MATCH") == 72 * 3600
    assert ttl_cache_segundos("NO_CONSULTABLE") is None  # indefinido


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
