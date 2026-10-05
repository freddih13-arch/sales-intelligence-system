"""
Capa de Enriquecimiento Legal — módulo posterior e independiente a la
selección comercial (score + diversificación).

IMPORTANTE: este paquete NUNCA calcula ni modifica ningún score, ninguna
posición, ningún sector, ningún municipio ni ningún estado de exclusión.
Tampoco agrega ni elimina prospectos de un Top N ya construido — es
estrictamente informativo, corre DESPUÉS de un Top N ya aprobado y produce
un artefacto separado, nunca sobrescribe el Top N ni `empresas_scored.parquet`.

Fuente externa: dataset nacional de Confecámaras (RUES), API pública
Socrata `c82u-588k` (datos.gov.co).

Especificación conceptual aprobada: turno "Especificación del enriquecimiento
legal" (2026-09-02), con la revisión que excluye
`num_identificacion_representante_legal` del dataset comercial.

Distinto del paquete `sales_intel.enriquecimiento` ya existente (que cubre
sector Client / tamaño / nivel de confianza, Fase 4 del pipeline principal) —
sin relación entre ambos, nombres deliberadamente distintos para no confundirlos.

ESTADO ACTUAL (turno de implementación base): solo infraestructura —
`capa_enriquecimiento_legal.py` (lógica pura, sin I/O) y
`cliente_confecamaras.py` (interfaz de cliente desacoplada; el cliente real
de Socrata está definido pero NO se ejecuta todavía). No existe todavía un
módulo de orquestación (`ejecutar_*`) ni conexión a `pipeline.py` — eso es
un paso posterior, no autorizado en este turno.
"""
