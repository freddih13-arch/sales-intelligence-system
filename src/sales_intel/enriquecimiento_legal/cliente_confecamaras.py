"""
Cliente resiliente para consultar el dataset nacional de Confecámaras
(RUES) vía la API pública Socrata, dataset `c82u-588k` (datos.gov.co).

Implementa la política de resiliencia aprobada (turno "Política de
resiliencia — Confecámaras", 2026-09-02): timeout, reintentos con backoff
exponencial + jitter, manejo específico de HTTP 429 (con/sin Retry-After),
rate limiting propio (300ms / 600ms tras un 429), y una interfaz de caché
preparada (sin conectar automáticamente al flujo de consulta).

Separación deliberada (ya establecida en el módulo base): la lógica de
negocio (`capa_enriquecimiento_legal.py`) nunca importa `urllib` ni conoce
HTTP — solo conoce `RespuestaConfecamaras`. Todo lo de este archivo (la
política de reintentos, el rate limiting, la caché) es transporte e
infraestructura, no cambia esa separación ni el contrato ya usado por
`capa_enriquecimiento_legal.py`.

Para pruebas sin red: el constructor de `ClienteConfecamarasSocrata`
acepta `transporte` (reemplaza la llamada HTTP real por una función/mock
que devuelve `ResultadoIntentoCrudo`) y `dormir` (reemplaza `time.sleep`
por cualquier función — un espía que no bloquee de verdad) — ver
`tests/test_resiliencia_confecamaras.py`.
"""

from __future__ import annotations

import http.client
import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

DATASET_ID_CONFECAMARAS = "c82u-588k"
BASE_URL_DATOS_GOV_CO = f"https://www.datos.gov.co/resource/{DATASET_ID_CONFECAMARAS}.json"

# Campos exactamente necesarios (spec §3) — nunca "select *". Se incluye
# `organizacion_juridica` (distinguir persona natural/jurídica, spec §7) y,
# deliberadamente, `num_identificacion_representante_legal`: puede llegar
# en la respuesta cruda (útil solo para un eventual log de auditoría) pero
# `preparar_registro_enriquecido` en `capa_enriquecimiento_legal.py` NUNCA
# lo promueve al dataset comercial, y `EventoIntento` (este archivo) NUNCA
# lo incluye como campo estructurado del log.
CAMPOS_SOLICITADOS = (
    "nit", "digito_verificacion", "razon_social", "organizacion_juridica",
    "representante_legal", "num_identificacion_representante_legal",
    "estado_matricula", "matricula", "camara_comercio",
)


@dataclass(frozen=True)
class RespuestaConfecamaras:
    """Resultado desacoplado de CUALQUIER cliente (mock o real). La lógica
    de negocio solo conoce esta forma — nunca el transporte HTTP ni la
    política de reintentos."""

    ok: bool                     # False solo tras agotar la política de reintentos (o error no reintentable)
    registros: tuple[dict, ...]  # 0, 1, o (excepcionalmente) >1 registros crudos
    error: str | None = None     # descripción del último error técnico, si ok=False


class ClienteConfecamaras(Protocol):
    """Contrato que debe cumplir cualquier cliente (mock o real) — la única
    superficie que conoce `capa_enriquecimiento_legal.py`."""

    def consultar_nit(self, nit_base: str) -> RespuestaConfecamaras: ...


# ---------------------------------------------------------------------------
# Política de resiliencia — parámetros aprobados
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PoliticaResiliencia:
    timeout_segundos: float = 10.0
    max_intentos: int = 3                       # 1 original + 2 reintentos
    backoff_base_segundos: float = 1.0           # 1s tras el 1er fallo, 2s tras el 2do (x2 exponencial)
    backoff_maximo_segundos: float = 10.0
    jitter_fraccion: float = 0.25                # ±25%
    intervalo_minimo_segundos: float = 0.3       # rate limiting propio, normal
    intervalo_elevado_segundos: float = 0.6      # rate limiting propio, tras cualquier 429
    retry_after_maximo_segundos: float = 60.0    # techo de seguridad para Retry-After
    codigos_reintentables: frozenset[int] = field(default_factory=lambda: frozenset({429, 500, 502, 503, 504}))
    codigos_no_reintentables: frozenset[int] = field(default_factory=lambda: frozenset({400, 401, 403, 404}))


# ---------------------------------------------------------------------------
# Resultado de UN intento crudo (una sola llamada HTTP) — lo que produce el
# "transporte", mockeable en pruebas sin tocar la política de reintentos.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultadoIntentoCrudo:
    tipo: str  # "EXITO" | "ERROR_REINTENTABLE" | "ERROR_NO_REINTENTABLE" | "JSON_INVALIDO"
    registros: tuple[dict, ...] = ()
    codigo_http: int | None = None
    retry_after_segundos: float | None = None
    detalle_error: str | None = None


# ---------------------------------------------------------------------------
# Logging / auditoría — interfaz preparada (spec §14). Sin infraestructura
# de persistencia: solo la forma del evento y un registrador en memoria de
# referencia. NUNCA incluye num_identificacion_representante_legal (no es
# un campo de este evento en absoluto -- ver docstring del módulo).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EventoIntento:
    nit_consultado: str
    numero_intento: int
    timestamp_utc: str
    resultado_http: int | None
    error_tecnico: str | None
    tiempo_respuesta_segundos: float
    resultado_final: str | None          # None en intentos intermedios; poblado solo en el evento que cierra la consulta
    hubo_retry_after: bool
    rate_limiting_global_activado: bool  # estado de la BANDERA al momento de este evento (pudo activarse en este mismo intento)


class RegistradorConsultas(Protocol):
    def registrar(self, evento: EventoIntento) -> None: ...


class RegistradorNulo:
    """Referencia por defecto — no hace nada. El proyecto no tiene todavía
    infraestructura de logging estructurado; esta interfaz queda lista para
    conectarse a una futura (archivo, base de datos, etc.) sin tocar
    `ClienteConfecamarasSocrata`."""

    def registrar(self, evento: EventoIntento) -> None:
        return None


class RegistradorEnMemoria:
    """Referencia mínima para pruebas/depuración — acumula los eventos en
    una lista del propio proceso, sin persistencia."""

    def __init__(self) -> None:
        self.eventos: list[EventoIntento] = []

    def registrar(self, evento: EventoIntento) -> None:
        self.eventos.append(evento)


# ---------------------------------------------------------------------------
# Caché — interfaz preparada (spec §12). Deliberadamente NO conectada al
# flujo de `consultar_nit`: una futura orquestación decide cuándo consultar
# la caché antes de llamar, y cuándo guardar el resultado después, usando
# `es_cacheable`/`ttl_cache_segundos` para decidir el TTL según
# `resultado_match`. Mantiene la política simple en esta fase (spec: "no
# introducir complejidad innecesaria").
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EntradaCache:
    respuesta: RespuestaConfecamaras
    resultado_match: str
    guardado_en: float             # time.monotonic() en el momento de guardar
    ttl_segundos: float | None     # None = no expira (caso NO_CONSULTABLE)


class CacheConfecamaras(Protocol):
    def obtener(self, clave: str) -> EntradaCache | None: ...
    def guardar(self, clave: str, entrada: EntradaCache) -> None: ...


class CacheEnMemoria:
    """Referencia mínima — proceso local, sin persistencia entre
    ejecuciones. Suficiente para esta fase (no se requiere una
    arquitectura de caché mayor todavía); una futura orquestación podría
    sustituirla por algo persistente sin cambiar el contrato `CacheConfecamaras`."""

    def __init__(self, ahora: Callable[[], float] = time.monotonic) -> None:
        self._datos: dict[str, EntradaCache] = {}
        self._ahora = ahora

    def obtener(self, clave: str) -> EntradaCache | None:
        entrada = self._datos.get(clave)
        if entrada is None:
            return None
        if entrada.ttl_segundos is not None and (self._ahora() - entrada.guardado_en) > entrada.ttl_segundos:
            del self._datos[clave]
            return None
        return entrada

    def guardar(self, clave: str, entrada: EntradaCache) -> None:
        self._datos[clave] = entrada


# TTL por resultado_match (spec §12). "ERROR_CONSULTA" deliberadamente
# ausente de este diccionario -- NO es cacheable, ver `es_cacheable`.
_TTL_SEGUNDOS_POR_RESULTADO = {
    "MATCH_CONFIRMADO": 7 * 24 * 3600,
    "MATCH_CON_OBSERVACION": 7 * 24 * 3600,
    "NO_MATCH": 72 * 3600,
    "NO_CONSULTABLE": None,  # indefinido, hasta que cambie el NIT propio
}


def es_cacheable(resultado_match: str) -> bool:
    """ERROR_CONSULTA es la única taxonomía NO cacheable (spec §12) — un
    fallo técnico no es información válida sobre la empresa."""
    return resultado_match in _TTL_SEGUNDOS_POR_RESULTADO


def ttl_cache_segundos(resultado_match: str) -> float | None:
    """TTL en segundos, o None si no expira. Llamar solo si
    `es_cacheable(resultado_match)` es True."""
    if resultado_match not in _TTL_SEGUNDOS_POR_RESULTADO:
        raise ValueError(f"{resultado_match!r} no es cacheable -- verificar con es_cacheable() antes de llamar")
    return _TTL_SEGUNDOS_POR_RESULTADO[resultado_match]


# ---------------------------------------------------------------------------
# Clasificación de excepciones del transporte real -> ResultadoIntentoCrudo
# ---------------------------------------------------------------------------

def _clasificar_excepcion(exc: Exception, politica: PoliticaResiliencia) -> ResultadoIntentoCrudo:
    if isinstance(exc, urllib.error.HTTPError):
        codigo = exc.code
        retry_after = None
        if codigo == 429:
            valor = exc.headers.get("Retry-After") if exc.headers else None
            if valor is not None:
                try:
                    retry_after = float(valor)
                except ValueError:
                    retry_after = None
        if codigo in politica.codigos_reintentables:
            return ResultadoIntentoCrudo(
                tipo="ERROR_REINTENTABLE", codigo_http=codigo,
                retry_after_segundos=retry_after, detalle_error=f"HTTPError {codigo}",
            )
        # codigo en codigos_no_reintentables, o cualquier codigo no
        # contemplado explícitamente -- conservador: no reintentable.
        return ResultadoIntentoCrudo(tipo="ERROR_NO_REINTENTABLE", codigo_http=codigo, detalle_error=f"HTTPError {codigo}")

    if isinstance(exc, TimeoutError):
        return ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error=f"Timeout: {exc}")

    if isinstance(exc, urllib.error.URLError):
        razon = exc.reason
        if isinstance(razon, socket.gaierror):
            return ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error=f"DNS: {razon}")
        if isinstance(razon, TimeoutError):
            return ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error=f"Timeout: {razon}")
        return ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error=f"URLError: {razon}")

    if isinstance(exc, (ConnectionError, http.client.RemoteDisconnected)):
        return ResultadoIntentoCrudo(tipo="ERROR_REINTENTABLE", detalle_error=f"Conexión interrumpida: {exc}")

    if isinstance(exc, json.JSONDecodeError):
        return ResultadoIntentoCrudo(tipo="JSON_INVALIDO", detalle_error=str(exc))

    # Excepción no contemplada explícitamente: conservador -> no reintentable
    # (evita reintentos indefinidos ante algo desconocido).
    return ResultadoIntentoCrudo(tipo="ERROR_NO_REINTENTABLE", detalle_error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Cliente real
# ---------------------------------------------------------------------------

class ClienteConfecamarasSocrata:
    """Cliente REAL con política de resiliencia — timeout, reintentos con
    backoff+jitter, manejo de 429 (con/sin Retry-After), rate limiting
    propio (300ms / 600ms tras un 429). Solo stdlib (`urllib`, `json`) — no
    agrega ninguna dependencia nueva al proyecto.

    `transporte` y `dormir` son inyectables para pruebas sin red y sin
    esperas reales — ver `tests/test_resiliencia_confecamaras.py`. Si no se
    especifican, se usa la llamada HTTP real y `time.sleep`.
    """

    def __init__(
        self,
        base_url: str = BASE_URL_DATOS_GOV_CO,
        app_token: str | None = None,
        politica: PoliticaResiliencia = PoliticaResiliencia(),
        transporte: Callable[[str], ResultadoIntentoCrudo] | None = None,
        dormir: Callable[[float], None] = time.sleep,
        registrador: RegistradorConsultas | None = None,
    ):
        self._base_url = base_url
        self._app_token = app_token
        self._politica = politica
        self._transporte = transporte if transporte is not None else self._intento_crudo_http
        self._dormir = dormir
        self._registrador = registrador if registrador is not None else RegistradorNulo()

        # Estado mutable del rate limiting propio -- vive mientras viva esta
        # instancia ("el resto de la corrida", spec §7/§9).
        self._ultima_solicitud_ts: float | None = None
        self._intervalo_actual = politica.intervalo_minimo_segundos
        self._rate_limit_elevado = False

    # -- transporte real (una sola llamada HTTP, sin reintentos aquí) ------

    def _intento_crudo_http(self, nit_base: str) -> ResultadoIntentoCrudo:
        """NO SE INVOCA salvo que se use el cliente real sin `transporte`
        inyectado. Filtro exacto `nit=<nit_base>`; sin `$q` de texto libre."""
        params = {"nit": nit_base, "$select": ",".join(CAMPOS_SOLICITADOS)}
        url = f"{self._base_url}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        if self._app_token:
            headers["X-App-Token"] = self._app_token
        try:
            peticion = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(peticion, timeout=self._politica.timeout_segundos) as resp:
                cuerpo = json.loads(resp.read().decode("utf-8"))
            if not isinstance(cuerpo, list):
                return ResultadoIntentoCrudo(tipo="JSON_INVALIDO", detalle_error="la respuesta no es una lista JSON")
            return ResultadoIntentoCrudo(tipo="EXITO", registros=tuple(cuerpo))
        except Exception as exc:  # clasificado exhaustivamente arriba
            return _clasificar_excepcion(exc, self._politica)

    # -- espera unificada: rate limiting propio Y backoff, sin duplicar ----
    # (si hace falta esperar por backoff, ese tiempo ya cubre de sobra el
    # intervalo mínimo de espaciado -- se toma el máximo, nunca se suman).

    def _esperar(self, espera_minima_adicional: float) -> None:
        espera_por_intervalo = 0.0
        if self._ultima_solicitud_ts is not None:
            transcurrido = time.monotonic() - self._ultima_solicitud_ts
            espera_por_intervalo = max(0.0, self._intervalo_actual - transcurrido)
        espera_total = max(espera_por_intervalo, espera_minima_adicional)
        if espera_total > 0:
            self._dormir(espera_total)
        self._ultima_solicitud_ts = time.monotonic()

    def _con_jitter(self, base: float) -> float:
        factor = 1 + random.uniform(-self._politica.jitter_fraccion, self._politica.jitter_fraccion)
        return max(0.0, min(base * factor, self._politica.backoff_maximo_segundos))

    def _espera_backoff(self, numero_intento_fallido: int) -> float:
        """1s tras el 1er fallo, 2s tras el 2do (exponencial x2), con jitter."""
        base = self._politica.backoff_base_segundos * (2 ** (numero_intento_fallido - 1))
        base = min(base, self._politica.backoff_maximo_segundos)
        return self._con_jitter(base)

    def _espera_para_429(self, crudo: ResultadoIntentoCrudo) -> float | None:
        """None significa "no esperar más -- terminar ya como ERROR_CONSULTA"
        (Retry-After excede el máximo permitido)."""
        if crudo.retry_after_segundos is not None:
            if crudo.retry_after_segundos > self._politica.retry_after_maximo_segundos:
                return None
            return crudo.retry_after_segundos  # se respeta tal cual, SIN jitter -- instrucción explícita del servidor
        base = 2.0  # backoff especial para 429 sin Retry-After (spec §7)
        return self._con_jitter(min(base, self._politica.backoff_maximo_segundos))

    def _activar_rate_limit_elevado(self) -> None:
        if self._intervalo_actual < self._politica.intervalo_elevado_segundos:
            self._intervalo_actual = self._politica.intervalo_elevado_segundos
        self._rate_limit_elevado = True

    def _registrar(
        self, nit_base: str, numero_intento: int, crudo: ResultadoIntentoCrudo,
        duracion: float, resultado_final: str | None, hubo_429: bool,
    ) -> None:
        evento = EventoIntento(
            nit_consultado=nit_base,
            numero_intento=numero_intento,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            resultado_http=crudo.codigo_http,
            error_tecnico=crudo.detalle_error,
            tiempo_respuesta_segundos=duracion,
            resultado_final=resultado_final,
            hubo_retry_after=bool(hubo_429 and crudo.retry_after_segundos is not None),
            rate_limiting_global_activado=self._rate_limit_elevado,
        )
        self._registrador.registrar(evento)

    # -- orquestación de reintentos -----------------------------------------

    def consultar_nit(self, nit_base: str) -> RespuestaConfecamaras:
        """NIT base (sin DV) -> RespuestaConfecamaras, aplicando la política
        de resiliencia completa. NUNCA declara NO_MATCH por una excepción
        técnica -- ok=False siempre que no se obtuvo una respuesta HTTP 200
        con JSON válido en forma de lista."""
        intentos_json_invalido = 0
        ultimo_error = "reintentos agotados"
        espera_pendiente = 0.0

        for numero_intento in range(1, self._politica.max_intentos + 1):
            self._esperar(espera_pendiente)
            espera_pendiente = 0.0

            t0 = time.monotonic()
            crudo = self._transporte(nit_base)
            duracion = time.monotonic() - t0

            hubo_429 = crudo.codigo_http == 429
            if hubo_429:
                self._activar_rate_limit_elevado()

            if crudo.tipo == "EXITO":
                self._registrar(nit_base, numero_intento, crudo, duracion, "EXITO", hubo_429)
                return RespuestaConfecamaras(ok=True, registros=crudo.registros)

            if crudo.tipo == "ERROR_NO_REINTENTABLE":
                self._registrar(nit_base, numero_intento, crudo, duracion, "ERROR_CONSULTA", hubo_429)
                return RespuestaConfecamaras(ok=False, registros=(), error=crudo.detalle_error)

            if crudo.tipo == "JSON_INVALIDO":
                intentos_json_invalido += 1
                ultimo_error = crudo.detalle_error
                # Regla especial (spec §5): como mucho 1 reintento para JSON
                # inválido, sin importar cuántos intentos generales queden.
                if intentos_json_invalido >= 2 or numero_intento >= self._politica.max_intentos:
                    self._registrar(nit_base, numero_intento, crudo, duracion, "ERROR_CONSULTA", hubo_429)
                    return RespuestaConfecamaras(ok=False, registros=(), error=crudo.detalle_error)
                self._registrar(nit_base, numero_intento, crudo, duracion, None, hubo_429)
                espera_pendiente = self._espera_backoff(numero_intento)
                continue

            # ERROR_REINTENTABLE (timeout, conexión, DNS, interrumpida, 429, 5xx)
            ultimo_error = crudo.detalle_error
            if numero_intento >= self._politica.max_intentos:
                self._registrar(nit_base, numero_intento, crudo, duracion, "ERROR_CONSULTA", hubo_429)
                return RespuestaConfecamaras(ok=False, registros=(), error=ultimo_error)

            if hubo_429:
                espera = self._espera_para_429(crudo)
                if espera is None:
                    self._registrar(nit_base, numero_intento, crudo, duracion, "ERROR_CONSULTA", hubo_429)
                    return RespuestaConfecamaras(
                        ok=False, registros=(),
                        error="Retry-After excede el máximo permitido (60s) -- se detiene sin más reintentos",
                    )
            else:
                espera = self._espera_backoff(numero_intento)

            self._registrar(nit_base, numero_intento, crudo, duracion, None, hubo_429)
            espera_pendiente = espera

        return RespuestaConfecamaras(ok=False, registros=(), error=ultimo_error)
