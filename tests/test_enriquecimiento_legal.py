"""
Pruebas de la Capa de Enriquecimiento Legal — ÚNICAMENTE con respuestas
MOCK (`ClienteConfecamarasMock` en este archivo). Ninguna prueba de este
archivo hace una llamada de red real ni consulta ningún NIT real del Top
100 — todos los NIT/registros usados son sintéticos o, cuando reproducen
un caso ya observado en la validación comercial previa, se reescriben aquí
como datos de prueba fijos (no se vuelve a consultar la API).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sales_intel.enriquecimiento_legal.capa_enriquecimiento_legal import (
    CAMPOS_COMERCIALES,
    RESULTADOS_MATCH,
    clasificar_match,
    comparar_razones_sociales,
    normalizar_nit_para_consulta,
    normalizar_razon_social_para_comparacion,
    preparar_registro_enriquecido,
    resolver_registro_por_estado_vigente,
)
from sales_intel.enriquecimiento_legal.cliente_confecamaras import RespuestaConfecamaras


class ClienteConfecamarasMock:
    """Cumple el mismo contrato que `ClienteConfecamarasSocrata`
    (`consultar_nit(nit_base) -> RespuestaConfecamaras`) sin ninguna
    llamada de red — las respuestas se precargan explícitamente por caso."""

    def __init__(self, respuestas: dict):
        self._respuestas = respuestas

    def consultar_nit(self, nit_base: str) -> RespuestaConfecamaras:
        if nit_base not in self._respuestas:
            return RespuestaConfecamaras(ok=True, registros=())
        return self._respuestas[nit_base]


def _registro_persona_juridica(**overrides) -> dict:
    base = {
        "nit": "901955318",
        "digito_verificacion": "3",
        "razon_social": "INVERSIONES GRUPO C&D S.A.S.",
        "organizacion_juridica": "SOCIEDADES POR ACCIONES SIMPLIFICADAS SAS",
        "representante_legal": "REPRESENTANTE EJEMPLO S.A.S.",
        "num_identificacion_representante_legal": "1088296164",
        "estado_matricula": "ACTIVA",
        "matricula": "18228847",
        "camara_comercio": "PEREIRA",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# A. NIT válido + DV correcto + ACTIVA + razón social compatible -> MATCH_CONFIRMADO
# ---------------------------------------------------------------------------

def test_A_match_confirmado_activa():
    nit_original = "9019553183"
    norm = normalizar_nit_para_consulta(nit_original)
    assert norm.consultable
    assert norm.nit_consultado == "901955318"
    assert norm.dv_coincide is True

    registro = _registro_persona_juridica()
    cliente = ClienteConfecamarasMock({"901955318": RespuestaConfecamaras(ok=True, registros=(registro,))})
    respuesta = cliente.consultar_nit(norm.nit_consultado)

    resultado = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    assert resultado == "MATCH_CONFIRMADO"

    salida = preparar_registro_enriquecido("ENT-0128399", 1, nit_original, norm, respuesta, resultado)
    assert salida["resultado_match"] == "MATCH_CONFIRMADO"
    assert salida["estado_matricula"] == "ACTIVA"
    assert salida["nit"] == nit_original


# ---------------------------------------------------------------------------
# B. NIT válido + CANCELADA + razón social compatible -> MATCH_CONFIRMADO,
#    y el estado queda CANCELADA (no filtra, no oculta).
# ---------------------------------------------------------------------------

def test_B_match_confirmado_cancelada_no_se_filtra():
    nit_original = "9006481076"
    norm = normalizar_nit_para_consulta(nit_original)
    registro = _registro_persona_juridica(
        nit="900648107", digito_verificacion="6",
        razon_social="IPS LABORATORIO Y OPTICA BERRIO S.A.S",
        representante_legal="GUTIERREZ LEON DANNA VALENTINA",
        estado_matricula="CANCELADA", matricula="50805", camara_comercio="MAGDALENA MEDIO",
    )
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))

    resultado = clasificar_match(norm, respuesta, "IPS LABORATORIO Y OPTICA BERRIO S.A.S EN LIQUIDACION")
    assert resultado == "MATCH_CONFIRMADO"

    salida = preparar_registro_enriquecido("ENT-0085165", 16, nit_original, norm, respuesta, resultado)
    assert salida["estado_matricula"] == "CANCELADA"
    assert salida["resultado_match"] == "MATCH_CONFIRMADO"  # CANCELADA no degrada el match


# ---------------------------------------------------------------------------
# C. Razón social con "EN LIQUIDACION" pero mismo núcleo -> MATCH_CONFIRMADO
# ---------------------------------------------------------------------------

def test_C_sufijo_en_liquidacion_no_produce_discrepancia():
    comparacion = comparar_razones_sociales(
        "IPS LABORATORIO Y OPTICA BERRIO S.A.S EN LIQUIDACION",
        "IPS LABORATORIO Y OPTICA BERRIO S.A.S",
    )
    assert comparacion.clasificacion == "compatible"

    norm_original = normalizar_razon_social_para_comparacion(
        "IPS LABORATORIO Y OPTICA BERRIO S.A.S EN LIQUIDACION"
    )
    assert norm_original.sufijo_estado_detectado == "EN LIQUIDACION"
    assert "LIQUIDACION" not in (norm_original.nombre_normalizado or "")


# ---------------------------------------------------------------------------
# D. Razón social claramente diferente -> MATCH_CON_OBSERVACION
# ---------------------------------------------------------------------------

def test_D_razon_social_distinta_produce_observacion():
    nit_original = "9000399996"
    norm = normalizar_nit_para_consulta(nit_original)
    registro = _registro_persona_juridica(
        nit="900039999", digito_verificacion="6",
        razon_social="COMERCIALIZADORA DISTINTA DEL PACIFICO SAS",
        estado_matricula="ACTIVA",
    )
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))

    resultado = clasificar_match(norm, respuesta, "BERLLANO S.A")
    assert resultado == "MATCH_CON_OBSERVACION"

    comparacion = comparar_razones_sociales("BERLLANO S.A", "COMERCIALIZADORA DISTINTA DEL PACIFICO SAS")
    assert comparacion.clasificacion == "discrepante"


# ---------------------------------------------------------------------------
# E. NIT válido + cero resultados -> NO_MATCH
# ---------------------------------------------------------------------------

def test_E_cero_resultados_es_no_match():
    norm = normalizar_nit_para_consulta("9099999999")
    respuesta = RespuestaConfecamaras(ok=True, registros=())
    resultado = clasificar_match(norm, respuesta, "CUALQUIER RAZON SOCIAL")
    assert resultado == "NO_MATCH"

    salida = preparar_registro_enriquecido("ENT-TEST", 99, "9099999999", norm, respuesta, resultado)
    assert salida["resultado_match"] == "NO_MATCH"
    assert salida["razon_social_confecamaras"] is None
    assert salida["nit"] == "9099999999"  # el original permanece, aunque no hubo match


# ---------------------------------------------------------------------------
# F. NIT vacío/inválido -> NO_CONSULTABLE
# ---------------------------------------------------------------------------

def test_F_nit_vacio_o_invalido_es_no_consultable():
    for nit_invalido in (None, "", "ABC", "12", "1" * 20):
        norm = normalizar_nit_para_consulta(nit_invalido)
        assert not norm.consultable, f"'{nit_invalido}' no debía ser consultable"
        assert norm.nit_consultado is None
        # no debe intentarse ninguna consulta: clasificar_match corta antes de mirar `respuesta`
        resultado = clasificar_match(norm, RespuestaConfecamaras(ok=False, registros=(), error="no debería usarse"), "X")
        assert resultado == "NO_CONSULTABLE"

    salida = preparar_registro_enriquecido("ENT-SINNIT", 40, None, normalizar_nit_para_consulta(None),
                                            RespuestaConfecamaras(ok=True, registros=()), "NO_CONSULTABLE")
    assert salida["nit"] is None
    assert salida["resultado_match"] == "NO_CONSULTABLE"


# ---------------------------------------------------------------------------
# G. Error HTTP/timeout simulado -> ERROR_CONSULTA
# ---------------------------------------------------------------------------

def test_G_error_tecnico_es_error_consulta():
    norm = normalizar_nit_para_consulta("9019553183")
    respuesta_timeout = RespuestaConfecamaras(ok=False, registros=(), error="TimeoutError: timed out")
    assert clasificar_match(norm, respuesta_timeout, "X") == "ERROR_CONSULTA"

    respuesta_http = RespuestaConfecamaras(ok=False, registros=(), error="URLError: 503 Service Unavailable")
    assert clasificar_match(norm, respuesta_http, "X") == "ERROR_CONSULTA"


# ---------------------------------------------------------------------------
# H. Persona natural -> representante_legal = "no aplica"
# ---------------------------------------------------------------------------

def test_H_persona_natural_representante_no_aplica():
    # NIT real de 11 dígitos (base 10 + DV) ya verificado en la validación
    # comercial previa (posición 46 del Top 100) -- no se vuelve a consultar
    # aquí, se reutiliza como dato de prueba fijo.
    nit_original = "10072206214"
    norm = normalizar_nit_para_consulta(nit_original)
    assert norm.nit_consultado == "1007220621"
    registro = {
        "nit": "1007220621", "digito_verificacion": "4",
        "razon_social": "CASTAÑEDA AGUIRRE LUIS DAVID",
        "organizacion_juridica": "PERSONA NATURAL",
        "estado_matricula": "ACTIVA", "matricula": "18227241", "camara_comercio": "PEREIRA",
        # nota: una persona natural no trae representante_legal en la fuente
    }
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))
    resultado = clasificar_match(norm, respuesta, "CASTAÑEDA AGUIRRE LUIS DAVID")
    assert resultado == "MATCH_CONFIRMADO"

    salida = preparar_registro_enriquecido("ENT-0125200", 46, nit_original, norm, respuesta, resultado)
    assert salida["representante_legal"] == "no aplica"


# ---------------------------------------------------------------------------
# I. Persona jurídica sin representante legal informado -> "no informado por la fuente"
# ---------------------------------------------------------------------------

def test_I_persona_juridica_sin_representante_legal():
    norm = normalizar_nit_para_consulta("9000399996")
    registro = _registro_persona_juridica(
        nit="900039999", digito_verificacion="6", razon_social="BERLLANO S.A",
        representante_legal=None,  # ausente en la respuesta
    )
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))
    resultado = clasificar_match(norm, respuesta, "BERLLANO S.A")
    assert resultado == "MATCH_CONFIRMADO"

    salida = preparar_registro_enriquecido("ENT-0084685", 24, "9000399996", norm, respuesta, resultado)
    assert salida["representante_legal"] == "no informado por la fuente"

    # también vacío ("") debe tratarse igual que ausente
    registro_vacio = _registro_persona_juridica(representante_legal="")
    salida_vacio = preparar_registro_enriquecido(
        "ENT-X", 1, "9019553183", norm, RespuestaConfecamaras(ok=True, registros=(registro_vacio,)), "MATCH_CONFIRMADO"
    )
    assert salida_vacio["representante_legal"] == "no informado por la fuente"


# ---------------------------------------------------------------------------
# J. DV externo diferente al original -> MATCH_CON_OBSERVACION
# ---------------------------------------------------------------------------

def test_J_dv_externo_distinto_produce_observacion():
    nit_original = "9019553183"  # DV declarado = "3"
    norm = normalizar_nit_para_consulta(nit_original)
    registro = _registro_persona_juridica(digito_verificacion="9")  # DV externo distinto
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))

    # misma razon social (compatible) pero DV externo no coincide
    resultado = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    assert resultado == "MATCH_CON_OBSERVACION"


# ---------------------------------------------------------------------------
# K. Más de un registro devuelto -> ERROR_CONSULTA
# ---------------------------------------------------------------------------

def test_K_mas_de_un_registro_es_error_consulta():
    norm = normalizar_nit_para_consulta("9019553183")
    respuesta = RespuestaConfecamaras(ok=True, registros=(_registro_persona_juridica(), _registro_persona_juridica()))
    resultado = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    assert resultado == "ERROR_CONSULTA"


# ---------------------------------------------------------------------------
# L. El NIT original nunca se sobrescribe
# ---------------------------------------------------------------------------

def test_L_nit_original_nunca_se_sobrescribe():
    nit_original = "9019553183"
    norm = normalizar_nit_para_consulta(nit_original)
    assert norm.nit_original == nit_original  # sin tocar, ni limpiar

    registro = _registro_persona_juridica(nit="901955318", digito_verificacion="9")  # DV externo distinto a proposito
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))
    resultado = clasificar_match(norm, respuesta, "OTRA COSA COMPLETAMENTE DISTINTA")

    salida = preparar_registro_enriquecido("ENT-X", 1, nit_original, norm, respuesta, resultado)
    assert salida["nit"] == nit_original  # el campo comercial "nit" es SIEMPRE el original
    assert salida["nit"] != salida["nit_confecamaras"] or nit_original == registro["nit"]
    assert salida["nit_consultado"] == "901955318"  # el derivado, en un campo aparte


# ---------------------------------------------------------------------------
# M. num_identificacion_representante_legal NO aparece en el dataset comercial
# ---------------------------------------------------------------------------

def test_M_no_incluye_identificacion_representante_legal():
    norm = normalizar_nit_para_consulta("9019553183")
    registro = _registro_persona_juridica()  # SÍ trae num_identificacion_representante_legal
    assert "num_identificacion_representante_legal" in registro  # confirma que la respuesta cruda sí lo trae

    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))
    resultado = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
    salida = preparar_registro_enriquecido("ENT-0128399", 1, "9019553183", norm, respuesta, resultado)

    assert "num_identificacion_representante_legal" not in salida
    assert set(salida.keys()) == set(CAMPOS_COMERCIALES)


# ---------------------------------------------------------------------------
# N. Idempotencia de la transformación
# ---------------------------------------------------------------------------

def test_N_idempotencia():
    nit_original = "9019553183"
    registro = _registro_persona_juridica()
    respuesta = RespuestaConfecamaras(ok=True, registros=(registro,))

    resultados = []
    for _ in range(3):
        norm = normalizar_nit_para_consulta(nit_original)
        resultado_match = clasificar_match(norm, respuesta, "INVERSIONES GRUPO C&D S.A.S.")
        salida = preparar_registro_enriquecido("ENT-0128399", 1, nit_original, norm, respuesta, resultado_match)
        resultados.append(salida)

    assert resultados[0] == resultados[1] == resultados[2]


# ---------------------------------------------------------------------------
# O. Resolución determinista de múltiples registros por estado vigente
#    (spec "Regla de resolución por unicidad de estado vigente",
#    2026-09-02) -- todos los NIT/registros de esta sección son sintéticos,
#    salvo cuando se indica explícitamente que reproducen un caso ya
#    auditado (posición X del Top100) como dato de prueba fijo, sin volver
#    a consultar la API.
# ---------------------------------------------------------------------------

def _reg_estado(estado, **overrides):
    """Registro mínimo con el `estado_matricula` dado -- solo para probar
    `resolver_registro_por_estado_vigente`/`clasificar_match`, no reutiliza
    `_registro_persona_juridica` porque estas pruebas necesitan controlar
    `estado_matricula` como variable principal."""
    base = {
        "nit": "901234567", "digito_verificacion": "1",
        "razon_social": "EMPRESA DE PRUEBA SAS",
        "organizacion_juridica": "SOCIEDADES POR ACCIONES SIMPLIFICADAS SAS",
        "representante_legal": "PEREZ GOMEZ JUAN CARLOS",
        "estado_matricula": estado,
        "matricula": "1", "camara_comercio": "PEREIRA",
    }
    base.update(overrides)
    return base


def test_O1_dos_registros_cancelada_y_activa_resuelve():
    # Reproduce el patrón real de la posición 7 del Top100 (auditoría
    # 2026-09-02): 1 CANCELADA + 1 ACTIVA, misma identidad.
    norm = normalizar_nit_para_consulta("9019553183")
    r_historico = _reg_estado("CANCELADA", matricula="18185134")
    r_vigente = _reg_estado("ACTIVA", matricula="18231195")
    respuesta = RespuestaConfecamaras(ok=True, registros=(r_historico, r_vigente))

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "MATCH_RESUELTO_HISTORICO"

    salida = preparar_registro_enriquecido("ENT-O1", 7, "9019553183", norm, respuesta, resultado)
    assert salida["resultado_match"] == "MATCH_RESUELTO_HISTORICO"
    assert salida["estado_matricula"] == "ACTIVA"
    assert salida["matricula"] == "18231195"  # del vigente, NUNCA del histórico
    assert set(salida.keys()) == set(CAMPOS_COMERCIALES)
    assert "num_identificacion_representante_legal" not in salida


def test_O2_dos_registros_traslado_resuelve():
    # Reproduce el patrón real de la posición 37 (JANG GROUP S.A.S.).
    norm = normalizar_nit_para_consulta("9019553183")
    r_historico = _reg_estado("MATRÍCULA CANCELADA POR TRASLADO DE DOMICILIO", matricula="855291", camara_comercio="BARRANQUILLA")
    r_vigente = _reg_estado("MATRÍCULA NUEVA, CONSTITUCIÓN POR TRASLADO", matricula="18228004", camara_comercio="PEREIRA")
    respuesta = RespuestaConfecamaras(ok=True, registros=(r_historico, r_vigente))

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "MATCH_RESUELTO_HISTORICO"

    salida = preparar_registro_enriquecido("ENT-O2", 37, "9019553183", norm, respuesta, resultado)
    assert salida["estado_matricula"] == "MATRÍCULA NUEVA, CONSTITUCIÓN POR TRASLADO"
    assert salida["camara_comercio"] == "PEREIRA"  # del vigente, no de la cámara de origen


def test_O3_tres_registros_dos_historicos_uno_vigente_resuelve():
    # Reproduce el patrón real de la posición 35 (3 registros).
    norm = normalizar_nit_para_consulta("9019553183")
    r1 = _reg_estado("CANCELADA", matricula="59306")
    r2 = _reg_estado("MATRÍCULA CANCELADA POR TRASLADO DE DOMICILIO", matricula="67184")
    r3 = _reg_estado("MATRÍCULA NUEVA, CONSTITUCIÓN POR TRASLADO", matricula="140277", camara_comercio="ORIENTE ANTIOQUENO")
    respuesta = RespuestaConfecamaras(ok=True, registros=(r1, r2, r3))

    resolucion = resolver_registro_por_estado_vigente(respuesta.registros)
    assert resolucion.aplica is True
    assert resolucion.n_registros_totales == 3
    assert resolucion.registro_seleccionado == r3
    assert sorted(resolucion.registros_descartados, key=lambda r: r["matricula"]) == sorted([r1, r2], key=lambda r: r["matricula"])  # traza de AMBOS descartados

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "MATCH_RESUELTO_HISTORICO"
    salida = preparar_registro_enriquecido("ENT-O3", 35, "9019553183", norm, respuesta, resultado)
    assert salida["matricula"] == "140277"


def test_O4_dos_historicos_sin_vigente_error_consulta():
    # Reproduce el patrón real de las posiciones 17/25/74/83: ningún
    # registro vigente -> no hay señal objetiva de cuál preferir.
    norm = normalizar_nit_para_consulta("9019553183")
    r1 = _reg_estado("CANCELADA", matricula="1")
    r2 = _reg_estado("CANCELADA", matricula="2")
    respuesta = RespuestaConfecamaras(ok=True, registros=(r1, r2))

    resolucion = resolver_registro_por_estado_vigente(respuesta.registros)
    assert resolucion.aplica is False
    assert resolucion.registro_seleccionado is None
    assert resolucion.registros_descartados == ()

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "ERROR_CONSULTA"  # NO se eligió ningún registro
    salida = preparar_registro_enriquecido("ENT-O4", 17, "9019553183", norm, respuesta, resultado)
    assert salida["estado_matricula"] is None  # sin registro elegido, campos vacíos como cualquier ERROR_CONSULTA


def test_O5_dos_vigentes_error_consulta():
    # Reproduce el patrón real de la posición 33 (traslado sin ningún
    # vigente sería otro caso -- este es el caso "2 vigentes" explícito
    # pedido, no observado en el Top100 real pero cubierto por la regla).
    norm = normalizar_nit_para_consulta("9019553183")
    r1 = _reg_estado("ACTIVA", matricula="1")
    r2 = _reg_estado("MATRÍCULA NUEVA, CONSTITUCIÓN POR TRASLADO", matricula="2")
    respuesta = RespuestaConfecamaras(ok=True, registros=(r1, r2))

    resolucion = resolver_registro_por_estado_vigente(respuesta.registros)
    assert resolucion.aplica is False  # 2 vigentes -- ambigüedad real, nunca se elige arbitrariamente

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "ERROR_CONSULTA"


def test_O6_estado_desconocido_error_consulta():
    # Un estado fuera de los dos conjuntos cerrados -- incluso acompañado
    # de un vigente inequívoco -- nunca se interpreta ni se adivina.
    norm = normalizar_nit_para_consulta("9019553183")
    r_vigente = _reg_estado("ACTIVA", matricula="1")
    r_desconocido = _reg_estado("SUSPENDIDA POR ORDEN JUDICIAL", matricula="2")  # estado no contemplado
    respuesta = RespuestaConfecamaras(ok=True, registros=(r_vigente, r_desconocido))

    resolucion = resolver_registro_por_estado_vigente(respuesta.registros)
    assert resolucion.aplica is False

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "ERROR_CONSULTA"


def test_O7_representante_legal_diferente_no_bloquea():
    # spec: representante_legal NUNCA decide si la regla se aplica.
    norm = normalizar_nit_para_consulta("9019553183")
    r_historico = _reg_estado("CANCELADA", matricula="1", representante_legal="OROZCO PEREZ SIRLEY YOLIMA")
    r_vigente = _reg_estado("ACTIVA", matricula="2", representante_legal="BOTERO FLOREZ CARLOS MARIO")
    respuesta = RespuestaConfecamaras(ok=True, registros=(r_historico, r_vigente))

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "MATCH_RESUELTO_HISTORICO"  # la diferencia de representante NO bloqueó la regla

    salida = preparar_registro_enriquecido("ENT-O7", 33, "9019553183", norm, respuesta, resultado)
    assert salida["representante_legal"] == "BOTERO FLOREZ CARLOS MARIO"  # el del vigente, sin fusionar con el histórico


def test_O8_en_liquidacion_en_razon_social_no_bloquea():
    # spec: "EN LIQUIDACIÓN" en la razón social del registro vigente NUNCA
    # se interpreta semánticamente -- reproduce el patrón real de las
    # posiciones 15 y 39.
    norm = normalizar_nit_para_consulta("9019553183")
    r_historico = _reg_estado("MATRÍCULA CANCELADA POR TRASLADO DE DOMICILIO", matricula="1", razon_social="RETRO ACOPLES Y MANGUERAS S.A.S")
    r_vigente = _reg_estado(
        "MATRÍCULA NUEVA, CONSTITUCIÓN POR TRASLADO", matricula="2",
        razon_social="RETRO ACOPLES Y MANGUERAS S.A.S EN LIQUIDACIÓN",
    )
    respuesta = RespuestaConfecamaras(ok=True, registros=(r_historico, r_vigente))

    resultado = clasificar_match(norm, respuesta, "X")
    assert resultado == "MATCH_RESUELTO_HISTORICO"  # "EN LIQUIDACIÓN" no bloqueó nada

    salida = preparar_registro_enriquecido("ENT-O8", 15, "9019553183", norm, respuesta, resultado)
    assert salida["razon_social_confecamaras"] == "RETRO ACOPLES Y MANGUERAS S.A.S EN LIQUIDACIÓN"


def test_O9_resultados_match_incluye_la_nueva_taxonomia():
    assert "MATCH_RESUELTO_HISTORICO" in RESULTADOS_MATCH
    assert len(RESULTADOS_MATCH) == 6


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
