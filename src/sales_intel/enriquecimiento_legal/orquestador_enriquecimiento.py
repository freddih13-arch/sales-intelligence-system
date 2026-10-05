"""
Orquestación del enriquecimiento legal de un Top N ya construido (score +
diversificación), usando el cliente resiliente de Confecámaras.

Reutiliza sin duplicar:
- `capa_enriquecimiento_legal.py`: `normalizar_nit_para_consulta`,
  `clasificar_match`, `preparar_registro_enriquecido` (lógica de negocio
  pura, ya aprobada).
- `cliente_confecamaras.py`: `ClienteConfecamaras` (protocolo, cualquier
  cliente que lo cumpla), `CacheConfecamaras`/`EntradaCache`/`es_cacheable`/
  `ttl_cache_segundos` (interfaz de caché ya definida).

Este módulo NO reimplementa ninguna política de reintentos, backoff, rate
limiting ni caché — todo eso ya vive en el cliente inyectado
(`ClienteConfecamarasSocrata`) y en la interfaz de caché ya definida. La
orquestación solo decide, POR PROSPECTO: si hay NIT consultable, si hay un
resultado en caché reutilizable, y si no, delega la consulta al cliente —
después convierte el resultado a la estructura comercial ya aprobada.

REGLA NO NEGOCIABLE, igual que en `capa_enriquecimiento_legal.py` y
`capa_diversificacion.py`: este módulo NUNCA calcula ni modifica el score,
la posición, el sector, el municipio ni `entidad_dedup_id` de ningún
prospecto. No agrega ni elimina prospectos del Top N de entrada — produce
exactamente una fila de salida por cada fila de entrada, en el mismo orden.

ESTADO ACTUAL: solo orquestación EN MEMORIA. `enriquecer_top_n_desde_csv`
lee el CSV del Top N en modo estrictamente solo lectura y devuelve la
lista de registros comerciales enriquecidos — NO escribe ningún archivo de
salida todavía (eso es un paso posterior, no autorizado en este turno). No
está conectado a `pipeline.py`.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable

from sales_intel.enriquecimiento_legal.capa_enriquecimiento_legal import (
    clasificar_match,
    normalizar_nit_para_consulta,
    preparar_registro_enriquecido,
)
from sales_intel.enriquecimiento_legal.cliente_confecamaras import (
    CacheConfecamaras,
    ClienteConfecamaras,
    EntradaCache,
    RespuestaConfecamaras,
    es_cacheable,
    ttl_cache_segundos,
)

# Columnas mínimas que la orquestación necesita leer del Top N de entrada.
# Deliberadamente NO se leen ni se tocan las demás columnas del CSV (score,
# sector, municipio, trazabilidad de diversificación, etc.) -- no son
# responsabilidad de este módulo.
CAMPOS_ENTRADA_REQUERIDOS = ("entidad_dedup_id", "posicion_diversificada", "nit", "razon_social")

# Placeholder para clasificar_match()/preparar_registro_enriquecido() en el
# caso NO_CONSULTABLE -- clasificar_match ya retorna "NO_CONSULTABLE" sin
# siquiera inspeccionar `respuesta` cuando el NIT no es consultable (ver
# capa_enriquecimiento_legal.py), así que este valor nunca se usa de verdad;
# existe solo para satisfacer la firma de ambas funciones sin duplicar lógica.
_RESPUESTA_NO_APLICABLE = RespuestaConfecamaras(ok=False, registros=())


def enriquecer_prospectos(
    prospectos: Iterable[dict],
    cliente: ClienteConfecamaras,
    cache: CacheConfecamaras | None = None,
    ahora: Callable[[], float] = time.monotonic,
) -> list[dict]:
    """Enriquece una lista de prospectos (cada uno, como mínimo, con
    `entidad_dedup_id`, `posicion_diversificada`, `nit`, `razon_social`)
    usando `cliente` (cualquier objeto que cumpla `ClienteConfecamaras` --
    típicamente `ClienteConfecamarasSocrata`, con su propia política de
    reintentos ya configurada) y, opcionalmente, una caché.

    Determinística e idempotente: la misma entrada, el mismo cliente
    (mismas respuestas) y la misma caché (o ninguna) producen exactamente
    la misma salida, en el mismo orden -- una fila de salida por cada fila
    de entrada, ni una más ni una menos.

    NIT es la ÚNICA llave de consulta -- nunca se busca por razón social,
    nunca se hace fuzzy matching, nunca se elige un registro "parecido".
    """
    resultados: list[dict] = []

    for prospecto in prospectos:
        entidad_dedup_id = prospecto["entidad_dedup_id"]
        posicion_diversificada = prospecto["posicion_diversificada"]
        nit_original = prospecto.get("nit")
        razon_social_original = prospecto.get("razon_social")

        normalizacion = normalizar_nit_para_consulta(nit_original)

        if not normalizacion.consultable:
            # Nunca se llega a tocar el cliente ni la caché -- no hay nada
            # que consultar (spec: "si no tiene NIT consultable ->
            # resultado_match = NO_CONSULTABLE").
            resultado_match = clasificar_match(normalizacion, _RESPUESTA_NO_APLICABLE, razon_social_original)
            registro = preparar_registro_enriquecido(
                entidad_dedup_id, posicion_diversificada, nit_original,
                normalizacion, _RESPUESTA_NO_APLICABLE, resultado_match,
            )
            resultados.append(registro)
            continue

        clave_cache = normalizacion.nit_consultado
        respuesta: RespuestaConfecamaras | None = None

        if cache is not None:
            entrada_cacheada = cache.obtener(clave_cache)
            if entrada_cacheada is not None:
                respuesta = entrada_cacheada.respuesta

        if respuesta is None:
            respuesta = cliente.consultar_nit(normalizacion.nit_consultado)

        resultado_match = clasificar_match(normalizacion, respuesta, razon_social_original)

        if cache is not None and es_cacheable(resultado_match):
            cache.guardar(
                clave_cache,
                EntradaCache(
                    respuesta=respuesta,
                    resultado_match=resultado_match,
                    guardado_en=ahora(),
                    ttl_segundos=ttl_cache_segundos(resultado_match),
                ),
            )
            # ERROR_CONSULTA nunca llega aquí -- es_cacheable() lo excluye
            # explícitamente (spec §12: un fallo técnico no es información
            # válida sobre la empresa, no se guarda).

        registro = preparar_registro_enriquecido(
            entidad_dedup_id, posicion_diversificada, nit_original,
            normalizacion, respuesta, resultado_match,
        )
        resultados.append(registro)

    return resultados


def leer_prospectos_desde_csv(ruta_csv) -> list[dict]:
    """Lee el Top N (CSV) en modo ESTRICTAMENTE SOLO LECTURA y devuelve la
    lista de prospectos en la forma mínima que necesita
    `enriquecer_prospectos`. Nunca escribe ni modifica el archivo de
    entrada; no toca ninguna otra columna del CSV (score, sector,
    municipio, trazabilidad de diversificación quedan intactos y ni
    siquiera se cargan más allá de lo necesario)."""
    import pandas as pd  # import local: mantiene enriquecer_prospectos() sin dependencia de pandas

    df = pd.read_csv(ruta_csv, dtype={"nit": str})
    faltantes = [c for c in CAMPOS_ENTRADA_REQUERIDOS if c not in df.columns]
    if faltantes:
        raise ValueError(f"El CSV de entrada no tiene las columnas requeridas: {faltantes}")
    return df[list(CAMPOS_ENTRADA_REQUERIDOS)].to_dict("records")


def enriquecer_top_n_desde_csv(
    ruta_csv,
    cliente: ClienteConfecamaras,
    cache: CacheConfecamaras | None = None,
    ahora: Callable[[], float] = time.monotonic,
) -> list[dict]:
    """Punto de entrada de archivo: Top N (CSV) -> orquestador -> cliente
    resiliente -> lista de registros comerciales enriquecidos, EN MEMORIA.

    NO escribe ningún archivo de salida -- devuelve la lista para que un
    paso posterior (no implementado aquí) decida cómo y cuándo persistirla,
    igual que `ejecutar_diversificacion()` nunca escribe el Top N que
    calcula. El CSV de entrada se abre únicamente con `pandas.read_csv`
    (lectura) -- en ningún punto de este módulo se llama a `to_csv`/
    `to_parquet`/`.write(`.
    """
    prospectos = leer_prospectos_desde_csv(ruta_csv)
    return enriquecer_prospectos(prospectos, cliente, cache=cache, ahora=ahora)
