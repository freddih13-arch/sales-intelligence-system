"""
Capa de Diversificación posterior al Score de Prioridad Comercial.

IMPORTANTE: este paquete NUNCA calcula ni modifica ningún score. Solo
reordena/selecciona, a partir de `score_prioridad_comercial` ya calculado
(ver `sales_intel.scoring`), qué entidades componen un Top N, reduciendo
concentración excesiva de sector y de geografía mediante un mecanismo
"soft" (zona de tolerancia -> zona soft con ventana de reemplazo -> tope
duro como red de seguridad).

Especificación aprobada: `03_RESULTADOS/especificacion_capa_diversificacion.md`.
Este es un PROTOTIPO (ver `prototipo_diversificacion.py`) — no está conectado
al pipeline oficial (`pipeline.py`) ni a `cmd_scorear`.
"""
