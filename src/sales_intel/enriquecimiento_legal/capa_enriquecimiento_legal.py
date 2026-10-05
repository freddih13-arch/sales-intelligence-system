"""
Lógica de negocio pura de la Capa de Enriquecimiento Legal.

Sin I/O, sin HTTP, sin pandas — cada función es determinística y testeable
de forma aislada, sin red (ver `tests/test_enriquecimiento_legal.py`).
Consume una `RespuestaConfecamaras` ya obtenida (ver `cliente_confecamaras.py`
para la interfaz de consulta, deliberadamente separada de este módulo).

Implementa las 5 funciones de la especificación aprobada:
1. normalizar_nit_para_consulta
2. normalizar_razon_social_para_comparacion
3. comparar_razones_sociales
4. clasificar_match
5. preparar_registro_enriquecido

Más `resolver_registro_por_estado_vigente` (spec "Regla de resolución por
unicidad de estado vigente", 2026-09-02): resolución determinista de
múltiples registros por NIT, validada por simulación antes de
implementarse — ver su docstring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sales_intel.normalizacion.limpieza import normalizar_nit, normalizar_texto

# ---------------------------------------------------------------------------
# 1. NIT: NIT original -> validación -> separación base/DV -> [consulta,
#    fuera de este módulo] -> validación del resultado -> conservación de
#    ambos valores. NUNCA se modifica el NIT original.
# ---------------------------------------------------------------------------

# Rango de longitud aceptado para la BASE+DV concatenados, tras dejar solo
# dígitos: 6 dígitos de base (cédulas antiguas cortas) + 1 DV = 7, hasta 11
# dígitos de base + 1 DV = 12. Margen amplio y documentado, no un límite
# oficial inventado — cualquier valor fuera de este rango se considera
# NO_CONSULTABLE en vez de arriesgar una consulta con una base mal cortada.
_LONGITUD_MINIMA_NIT = 7
_LONGITUD_MAXIMA_NIT = 12

# Algoritmo oficial DIAN de dígito de verificación (módulo 11), pesos para
# una base rellenada a 15 dígitos por la izquierda.
_PESOS_DV_DIAN = [71, 67, 59, 53, 47, 43, 41, 37, 29, 23, 19, 17, 13, 7, 3]


def _calcular_digito_verificacion(base: str) -> str:
    """DV oficial DIAN para una base de NIT sin DV. Se usa ÚNICAMENTE para
    contrastar contra el DV declarado en nuestro dato — nunca para generar
    ni corregir ningún NIT."""
    n = base.zfill(15)
    total = sum(int(d) * p for d, p in zip(n, _PESOS_DV_DIAN))
    resto = total % 11
    return str(resto if resto in (0, 1) else 11 - resto)


@dataclass(frozen=True)
class ResultadoNormalizacionNit:
    nit_original: str | None                       # tal cual se recibió, SIN TOCAR
    nit_consultado: str | None                      # base sin DV; None si no consultable
    digito_verificacion_original: str | None
    digito_verificacion_calculado: str | None
    dv_coincide: bool | None                        # None si no fue posible calcular
    consultable: bool


def normalizar_nit_para_consulta(nit_original: str | None) -> ResultadoNormalizacionNit:
    """NIT original -> validación de formato -> separación base/DV.

    NUNCA modifica ni descarta `nit_original` — se conserva tal cual en el
    resultado, para que quien llame nunca pierda la referencia del dato
    fuente exacto, incluso si resulta NO_CONSULTABLE.
    """
    limpio = normalizar_nit(nit_original)  # reutiliza normalizacion.limpieza: solo dígitos
    if not limpio or not (_LONGITUD_MINIMA_NIT <= len(limpio) <= _LONGITUD_MAXIMA_NIT):
        return ResultadoNormalizacionNit(
            nit_original=nit_original, nit_consultado=None,
            digito_verificacion_original=None, digito_verificacion_calculado=None,
            dv_coincide=None, consultable=False,
        )
    base, dv_declarado = limpio[:-1], limpio[-1]
    dv_calculado = _calcular_digito_verificacion(base)
    return ResultadoNormalizacionNit(
        nit_original=nit_original, nit_consultado=base,
        digito_verificacion_original=dv_declarado, digito_verificacion_calculado=dv_calculado,
        dv_coincide=(dv_declarado == dv_calculado), consultable=True,
    )


# ---------------------------------------------------------------------------
# 2-3. Razón social: normalización SOLO para comparar (nunca reemplaza el
#      nombre original) y comparación determinística compatible/discrepante.
# ---------------------------------------------------------------------------

# Sufijos de ESTADO anexados al nombre en la fuente propia (caso ya
# observado empíricamente: "... S.A.S EN LIQUIDACION") — no son parte de la
# identidad de la empresa, son información que pertenece a `estado_matricula`.
_SUFIJOS_ESTADO_ANEXADOS = [
    "EN LIQUIDACION JUDICIAL", "EN LIQUIDACION", "EN REESTRUCTURACION",
    "EN REORGANIZACION", "EN CONCORDATO",
]

# Equivalencias de sufijo societario — se prueban en este orden (más largo
# primero) para no dejar residuos ("S.A.S" no debe quedar leído como "S.A" + "S").
_EQUIVALENCIAS_SOCIETARIAS = [
    (re.compile(r"\bS\.?\s*A\.?\s*S\.?\s*$"), "SAS"),
    (re.compile(r"\bLTDA\.?\s*$"), "LTDA"),
    (re.compile(r"\bE\.?\s*U\.?\s*$"), "EU"),
    (re.compile(r"\bS\.?\s*A\.?\s*$"), "SA"),
]

_PUNTUACION = re.compile(r"[.,;:'\"()]")
_ESPACIOS_MULTIPLES = re.compile(r"\s+")


@dataclass(frozen=True)
class ResultadoNormalizacionNombre:
    nombre_original: str | None
    nombre_normalizado: str | None   # SOLO para comparar — nunca se guarda como reemplazo
    sufijo_estado_detectado: str | None


def normalizar_razon_social_para_comparacion(nombre: str | None) -> ResultadoNormalizacionNombre:
    """Mayúsculas, sin tildes, sin puntuación, espacios colapsados,
    equivalencias societarias, separación de sufijos de estado anexados.
    Nunca modifica `nombre` — el resultado normalizado es exclusivamente
    para `comparar_razones_sociales`."""
    texto = normalizar_texto(nombre)  # reutiliza normalizacion.limpieza
    if texto is None:
        return ResultadoNormalizacionNombre(nombre, None, None)

    sufijo_estado_detectado = None
    for sufijo in _SUFIJOS_ESTADO_ANEXADOS:
        if texto.endswith(sufijo):
            texto = texto[: -len(sufijo)].strip()
            sufijo_estado_detectado = sufijo
            break

    for patron, canonico in _EQUIVALENCIAS_SOCIETARIAS:
        reemplazado = patron.sub(canonico, texto)
        if reemplazado != texto:
            texto = reemplazado
            break

    texto = _PUNTUACION.sub(" ", texto)
    texto = _ESPACIOS_MULTIPLES.sub(" ", texto).strip()
    return ResultadoNormalizacionNombre(nombre, texto or None, sufijo_estado_detectado)


@dataclass(frozen=True)
class ResultadoComparacionNombres:
    original: str | None
    externa: str | None
    original_normalizado: str | None
    externa_normalizado: str | None
    clasificacion: str  # "compatible" | "discrepante"


def comparar_razones_sociales(original: str | None, externa: str | None) -> ResultadoComparacionNombres:
    """Clasificación determinística compatible/discrepante — SIN fuzzy
    matching (sin distancia de edición, sin similitud estadística). Dos
    nombres normalizados son "compatible" si son iguales o si uno está
    contenido en el otro (cubre variantes/abreviaturas ya normalizadas);
    cualquier otro caso es "discrepante"."""
    norm_original = normalizar_razon_social_para_comparacion(original)
    norm_externa = normalizar_razon_social_para_comparacion(externa)
    a, b = norm_original.nombre_normalizado, norm_externa.nombre_normalizado
    if not a or not b:
        clasificacion = "discrepante"
    elif a == b or a in b or b in a:
        clasificacion = "compatible"
    else:
        clasificacion = "discrepante"
    return ResultadoComparacionNombres(original, externa, a, b, clasificacion)


# ---------------------------------------------------------------------------
# 4. Taxonomía de match
# ---------------------------------------------------------------------------

RESULTADOS_MATCH = (
    "MATCH_CONFIRMADO", "MATCH_CON_OBSERVACION", "NO_MATCH",
    "NO_CONSULTABLE", "ERROR_CONSULTA", "MATCH_RESUELTO_HISTORICO",
)


# ---------------------------------------------------------------------------
# 4b. Resolución determinista de múltiples registros por estado vigente.
#
# Spec "Regla de resolución por unicidad de estado vigente" (turno
# 2026-09-02) -- validada por SIMULACIÓN en memoria sobre los 18 casos
# ERROR_CONSULTA reales del Top100 antes de implementarse aquí: resuelve
# exactamente 13/18 (7,14,15,26,35,37,39,49,52,60,84,89,98) y deja 5/18 sin
# resolver (17,25,33,74,83), tal cual se esperaba.
# ---------------------------------------------------------------------------

# Comparación EXACTA (nunca substring, nunca fuzzy) contra estos dos
# conjuntos cerrados. Un estado_matricula que no esté en NINGUNO de los dos
# hace que la regla no se aplique -- conservador ante estados no
# contemplados: nunca se adivina si un estado desconocido es "vigente" o
# "histórico".
ESTADOS_VIGENTES_RESOLUCION_HISTORICA = frozenset({
    "ACTIVA",
    "MATRÍCULA NUEVA, CONSTITUCIÓN POR TRASLADO",
})
ESTADOS_HISTORICOS_RESOLUCION_HISTORICA = frozenset({
    "CANCELADA",
    "MATRÍCULA CANCELADA POR TRASLADO DE DOMICILIO",
})


@dataclass(frozen=True)
class ResolucionHistorica:
    """Traza completa de si la regla se aplicó (o no) sobre N registros --
    para auditoría interna, NO para el dataset comercial de 12 columnas
    (`CAMPOS_COMERCIALES` no cambia). `registro_seleccionado` y
    `registros_descartados` quedan disponibles aquí para que un futuro paso
    de logging/auditoría los persista si se decide conectarlo -- esta
    función no escribe nada por sí misma, igual que el resto de este
    módulo (sin I/O)."""
    aplica: bool
    n_registros_totales: int
    registro_seleccionado: dict | None
    registros_descartados: tuple[dict, ...]


def resolver_registro_por_estado_vigente(registros: tuple[dict, ...]) -> ResolucionHistorica:
    """Regla determinista aprobada e implementada tras simulación previa
    (spec 2026-09-02). Se aplica ÚNICAMENTE si, de los N registros
    devueltos para un mismo NIT:

    1. Existe EXACTAMENTE 1 registro con `estado_matricula` en
       `ESTADOS_VIGENTES_RESOLUCION_HISTORICA`.
    2. TODOS los demás (N-1, cualquiera que sea N) tienen `estado_matricula`
       en `ESTADOS_HISTORICOS_RESOLUCION_HISTORICA`.
    3. Ningún registro tiene un `estado_matricula` fuera de esos dos
       conjuntos cerrados.

    Deliberadamente NO usa `representante_legal` para decidir nada (una
    diferencia de representante entre registros nunca bloquea ni activa la
    regla), NO interpreta semánticamente `razon_social` (p. ej. "EN
    LIQUIDACIÓN" no tiene ningún efecto aquí), NO usa ninguna fecha (no
    viene en los datos) y NUNCA combina campos de más de un registro: si la
    regla aplica, `registro_seleccionado` es UN registro completo, tal cual
    llegó de la fuente."""
    n = len(registros)
    estados = [r.get("estado_matricula") for r in registros]

    fuera_de_conjuntos = any(
        e not in ESTADOS_VIGENTES_RESOLUCION_HISTORICA and e not in ESTADOS_HISTORICOS_RESOLUCION_HISTORICA
        for e in estados
    )
    vigentes = [r for r in registros if r.get("estado_matricula") in ESTADOS_VIGENTES_RESOLUCION_HISTORICA]
    historicos = tuple(r for r in registros if r.get("estado_matricula") in ESTADOS_HISTORICOS_RESOLUCION_HISTORICA)

    aplica = (not fuera_de_conjuntos) and len(vigentes) == 1 and len(historicos) == n - 1

    return ResolucionHistorica(
        aplica=aplica,
        n_registros_totales=n,
        registro_seleccionado=vigentes[0] if aplica else None,
        registros_descartados=historicos if aplica else (),
    )


def clasificar_match(
    normalizacion_nit: ResultadoNormalizacionNit,
    respuesta,  # RespuestaConfecamaras — no se importa el tipo para no acoplar este módulo al cliente
    razon_social_original: str | None,
) -> str:
    """Aplica exactamente las reglas aprobadas (spec §8):

    - NO_CONSULTABLE: el NIT propio no era válido — nunca se llegó a consultar.
    - ERROR_CONSULTA: falló la consulta técnica, o la respuesta trajo más
      de 1 registro para un NIT (respuesta inesperada — RUES es 1 NIT = 1
      registro) Y `resolver_registro_por_estado_vigente` tampoco pudo
      resolverlo de forma determinista.
    - NO_MATCH: la consulta funcionó pero no hay ningún registro.
    - MATCH_CONFIRMADO: NIT exacto (mismo DV que el declarado) Y razón
      social compatible.
    - MATCH_CON_OBSERVACION: hay un registro para ese NIT, pero el DV
      externo no coincide con el declarado, o la razón social es discrepante
      — nunca se asume que es la misma empresa sin más.
    - MATCH_RESUELTO_HISTORICO: la respuesta trajo más de 1 registro, pero
      `resolver_registro_por_estado_vigente` encontró exactamente 1 con
      estado vigente y el resto con estado histórico (spec 2026-09-02) —
      ver ese docstring para las condiciones exactas.
    """
    if not normalizacion_nit.consultable:
        return "NO_CONSULTABLE"
    if not respuesta.ok:
        return "ERROR_CONSULTA"
    if len(respuesta.registros) == 0:
        return "NO_MATCH"
    if len(respuesta.registros) > 1:
        if resolver_registro_por_estado_vigente(respuesta.registros).aplica:
            return "MATCH_RESUELTO_HISTORICO"
        return "ERROR_CONSULTA"

    registro = respuesta.registros[0]
    comparacion = comparar_razones_sociales(razon_social_original, registro.get("razon_social"))
    dv_externo = registro.get("digito_verificacion")
    dv_coincide_con_externo = dv_externo == normalizacion_nit.digito_verificacion_original

    if comparacion.clasificacion == "compatible" and dv_coincide_con_externo:
        return "MATCH_CONFIRMADO"
    return "MATCH_CON_OBSERVACION"


# ---------------------------------------------------------------------------
# 5. Registro comercial enriquecido — SOLO los campos aprobados.
# ---------------------------------------------------------------------------

CAMPOS_COMERCIALES = (
    "entidad_dedup_id", "posicion_diversificada", "nit", "nit_confecamaras",
    "digito_verificacion", "razon_social_confecamaras", "representante_legal",
    "estado_matricula", "matricula", "camara_comercio", "resultado_match",
    "nit_consultado",
)

_ORGANIZACION_PERSONA_NATURAL = "PERSONA NATURAL"


def _resolver_representante_legal(registro: dict) -> str:
    """Distingue explícitamente los 3 casos de la especificación §7 —
    nunca infiere un nombre que no venga literal en la respuesta."""
    if registro.get("organizacion_juridica") == _ORGANIZACION_PERSONA_NATURAL:
        return "no aplica"
    valor = registro.get("representante_legal")
    if not valor or not str(valor).strip():
        return "no informado por la fuente"
    return valor


def preparar_registro_enriquecido(
    entidad_dedup_id: str,
    posicion_diversificada: int,
    nit_original: str | None,
    normalizacion_nit: ResultadoNormalizacionNit,
    respuesta,  # RespuestaConfecamaras
    resultado_match: str,
) -> dict:
    """Produce ÚNICAMENTE los campos comerciales aprobados (`CAMPOS_COMERCIALES`)
    — `num_identificacion_representante_legal` NUNCA aparece aquí (spec
    revisada). `nit` es siempre `nit_original`, sin ninguna transformación:
    esta función nunca sobrescribe el dato propio con el externo.

    Para `MATCH_RESUELTO_HISTORICO` (spec 2026-09-02), el registro del que
    se extraen los campos es EXCLUSIVAMENTE el que
    `resolver_registro_por_estado_vigente` identificó como vigente — nunca
    `respuesta.registros[0]` a secas, que podría ser el histórico si el
    vigente llegó en otra posición. Recalcular aquí (en vez de recibir el
    registro ya elegido) mantiene esta función pura y consistente con
    `clasificar_match`, que aplicó la misma regla determinista para decidir
    el resultado."""
    if resultado_match == "MATCH_RESUELTO_HISTORICO":
        registro = resolver_registro_por_estado_vigente(respuesta.registros).registro_seleccionado or {}
    else:
        hay_un_registro = resultado_match not in ("NO_MATCH", "NO_CONSULTABLE", "ERROR_CONSULTA")
        registro = respuesta.registros[0] if (hay_un_registro and respuesta.registros) else {}

    salida = {
        "entidad_dedup_id": entidad_dedup_id,
        "posicion_diversificada": posicion_diversificada,
        "nit": nit_original,
        "nit_confecamaras": registro.get("nit"),
        "digito_verificacion": registro.get("digito_verificacion"),
        "razon_social_confecamaras": registro.get("razon_social"),
        "representante_legal": _resolver_representante_legal(registro) if registro else None,
        "estado_matricula": registro.get("estado_matricula"),
        "matricula": registro.get("matricula"),
        "camara_comercio": registro.get("camara_comercio"),
        "resultado_match": resultado_match,
        "nit_consultado": normalizacion_nit.nit_consultado,
    }
    assert set(salida.keys()) == set(CAMPOS_COMERCIALES), "el registro debe tener exactamente los campos aprobados"
    assert "num_identificacion_representante_legal" not in salida
    return salida
