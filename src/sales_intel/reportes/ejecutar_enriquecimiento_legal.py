"""
Ejecutor VERSIONADO del enriquecimiento legal (Confecámaras) sobre un Top N
ya construido. Cierra el segundo gap de reproducibilidad identificado en el
análisis de arquitectura de este turno: hasta ahora, cada ejecución real del
enriquecimiento legal se hizo con un script fuera del repositorio (en
`/tmp`, nunca versionado).

NO reimplementa NINGUNA regla de negocio, resiliencia ni caché -- delega
TODO a las piezas ya aprobadas y probadas:
- `orquestador_enriquecimiento.leer_prospectos_desde_csv` / `enriquecer_prospectos`
  (normalización de NIT, matching, resolución histórica -- sin tocar nada de eso)
- `cliente_confecamaras.ClienteConfecamarasSocrata` (solo si no se inyecta un cliente)
- `escritor_enriquecimiento.escribir_enriquecimiento_comercial`

Decisiones aprobadas para esta primera versión (turno 2026-09-02):
- `cache=None` por defecto -- el ejecutor NUNCA crea una caché implícita
  (ni `CacheEnMemoria` ni ninguna otra). Si el caller quiere caché, la
  inyecta explícitamente. Una ejecución oficial con `cache=None` consulta
  Confecámaras en vivo para cada prospecto, según la política de
  resiliencia del cliente (sin caché entre prospectos con el mismo NIT).
- `registrador=None` por defecto -- se reutiliza la interfaz
  `RegistradorConsultas` ya existente en `cliente_confecamaras.py`, no se
  inventa ningún mecanismo de auditoría nuevo. Solo tiene efecto cuando
  `cliente=None`: es el único punto de la arquitectura actual que acepta un
  `registrador` (el constructor de `ClienteConfecamarasSocrata`). Si el
  caller inyecta su propio `cliente` ya construido, el registrador de ESE
  cliente es el que manda -- el parámetro `registrador` de este ejecutor no
  puede "inyectarse" retroactivamente en un cliente ya construido.
- Ningún archivo de auditoría se persiste automáticamente desde aquí -- si
  se inyecta un `registrador` (p. ej. `RegistradorEnMemoria()`), sus
  eventos quedan en memoria del objeto que el caller ya tiene; decidir si
  y cómo persistirlos es una decisión de un turno posterior, no de este.
- `ruta_entrada` acepta cualquier CSV Top N que cumpla el esquema exigido
  por `leer_prospectos_desde_csv` (`entidad_dedup_id`, `posicion_diversificada`,
  `nit`, `razon_social`) -- no se limita artificialmente al Top100.
- `n_esperado` para el escritor se deriva SIEMPRE de `len(prospectos)` leído
  del propio `ruta_entrada` -- nunca un valor fijo ni un parámetro aparte
  que el caller pueda desalinear.
"""

from __future__ import annotations

from pathlib import Path

from sales_intel.enriquecimiento_legal.cliente_confecamaras import (
    CacheConfecamaras,
    ClienteConfecamaras,
    ClienteConfecamarasSocrata,
    PoliticaResiliencia,
    RegistradorConsultas,
)
from sales_intel.enriquecimiento_legal.escritor_enriquecimiento import escribir_enriquecimiento_comercial
from sales_intel.enriquecimiento_legal.orquestador_enriquecimiento import (
    enriquecer_prospectos,
    leer_prospectos_desde_csv,
)


def ejecutar_enriquecimiento_legal(
    ruta_entrada: str | Path,
    ruta_salida: str | Path,
    cliente: ClienteConfecamaras | None = None,
    cache: CacheConfecamaras | None = None,
    politica: PoliticaResiliencia | None = None,
    registrador: RegistradorConsultas | None = None,
    overwrite: bool = False,
) -> dict:
    """Top N (CSV, cualquiera que cumpla el esquema de `leer_prospectos_desde_csv`)
    -> enriquecimiento legal real vía `enriquecer_prospectos` (sin tocar su
    lógica) -> CSV comercial vía `escribir_enriquecimiento_comercial` (sin
    tocar su validación).

    `cliente`: si se omite (`None`), se construye un `ClienteConfecamarasSocrata`
    REAL (transporte HTTP real, sin ningún mock) usando `politica` si se dio,
    o la política aprobada por defecto si no. Si se inyecta un `cliente` ya
    construido, `politica` y `registrador` se ignoran para ese cliente (ver
    docstring del módulo) -- útil para pruebas o para reutilizar un cliente
    ya configurado por el caller.

    `cache`: `None` por defecto -- NUNCA se crea una caché implícita aquí.

    `ruta_salida` es obligatorio y explícito. Si ya existe y `overwrite=False`
    (default), `escribir_enriquecimiento_comercial` falla con
    `FileExistsError` sin escribir nada.

    Devuelve `{'registros': list[dict] (uno por prospecto, mismo orden que
    la entrada), 'ruta_salida': Path, 'stats': {'n_prospectos', 'n_registros',
    'ruta_entrada', 'conteo_resultado_match'}}` -- todo derivado directamente
    de lo que ya devuelven las piezas existentes, sin ninguna métrica nueva.
    """
    ruta_entrada = Path(ruta_entrada)
    if not ruta_entrada.exists():
        raise FileNotFoundError(f"ruta_entrada no existe: {ruta_entrada}")
    if not ruta_entrada.is_file():
        raise ValueError(f"ruta_entrada no es un archivo: {ruta_entrada}")
    if ruta_salida is None:
        raise ValueError(
            "ruta_salida es obligatorio y explícito -- este ejecutor nunca elige una ruta de "
            "producción por defecto."
        )
    ruta_salida = Path(ruta_salida)

    prospectos = leer_prospectos_desde_csv(ruta_entrada)
    n_esperado = len(prospectos)
    if n_esperado == 0:
        raise ValueError(f"ruta_entrada ({ruta_entrada}) no tiene ningún prospecto -- 0 filas.")

    if cliente is None:
        kwargs_cliente = {"registrador": registrador}
        if politica is not None:
            kwargs_cliente["politica"] = politica
        cliente = ClienteConfecamarasSocrata(**kwargs_cliente)

    registros = enriquecer_prospectos(prospectos, cliente, cache=cache)

    ruta_escrita = escribir_enriquecimiento_comercial(
        registros, ruta_salida, n_esperado=n_esperado, overwrite=overwrite,
    )

    conteo_resultado_match: dict[str, int] = {}
    for r in registros:
        clave = r["resultado_match"]
        conteo_resultado_match[clave] = conteo_resultado_match.get(clave, 0) + 1

    return {
        "registros": registros,
        "ruta_salida": ruta_escrita,
        "stats": {
            "n_prospectos": n_esperado,
            "n_registros": len(registros),
            "ruta_entrada": str(ruta_entrada),
            "conteo_resultado_match": conteo_resultado_match,
        },
    }
