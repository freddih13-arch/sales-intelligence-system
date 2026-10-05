"""
Registro de Interacciones Comerciales — Esquema y utilidades.

Define el esquema canónico del registro append-only de interacciones
comerciales: una fila = una llamada/interacción. Hereda campos del
Top N, captura resultado, aprendizaje y siguiente acción.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# Esquema canónico del registro de interacciones
ESQUEMA_REGISTRO = [
    # Identificación (heredada del Top N)
    "entidad_dedup_id",      # ID único de la entidad (ej. ENT-0000123)
    "posicion_top100",       # Posición en el ranking diversificado
    "razon_social",          # Nombre del negocio
    "fuente_top100",         # Archivo origen (ej. top100_diversificado_sintetico.csv)

    # Datos de la interacción
    "interaccion_id",        # Auto-incremental por entidad
    "fecha_registro",        # ISO date (YYYY-MM-DD)
    "canal_contacto",        # telefono, whatsapp, email, presencial, videollamada
    "resultado_contacto",    # contactado, no_contesta, ocupado, numero_errado, buzon_voz, fuera_servicio, rechaza_llamada
    "etapa_actual",          # apertura, descubrimiento_necesidades, presentacion_solucion, manejo_objeciones, cierre, seguimiento_post_llamada, cerrado_ganado, cerrado_perdido, no_calificado
    "persona_contactada_rol", # propietario_representante, gerente_administrador, encargado_compras, encargado_pagos, otro_empleado, no_informado
    "acepta_pagos_electronicos", # si, no, no_sabe, ya_tiene_proveedor
    "proveedor_actual",      # Nombre del proveedor actual (si tiene)
    "volumen_mensual",       # Valor numérico
    "unidad_volumen",        # transacciones_mes, millones_cop_mes, porcentaje_ventas_tarjeta
    "satisfaccion_proveedor", # muy_satisfecho, satisfecho, neutral, insatisfecho, muy_insatisfecho, no_aplica
    "objecion_principal",    # precio_comisiones, ya_tiene_proveedor, no_ve_necesidad, desconfianza_tecnologia, proceso_largo, requiere_aprobacion, ninguna
    "nota_libre_vendedor",   # Texto libre: aprendizaje, contexto, siguiente paso

    # Cierre
    "resultado_final",       # activado, agendado_demo, enviada_propuesta, en_evaluacion, perdido_precio, perdido_competencia, perdido_sin_interes, no_contactable, negocio_inactivo
    "motivo_perdida",        # precio_comisiones, ya_tiene_proveedor_satisfactorio, no_ve_valor_agregado, desconfianza_seguridad, proceso_onboarding_largo, requiere_aprobacion_superior, cambio_no_prioritario, no_contactable_despues_multiples_intentos, negocio_cerrado_inactivo, otro
    "proxima_accion",        # Texto libre: qué sigue y cuándo

    # Métricas heredadas (para análisis)
    "score_prioridad",       # Score numérico del prospecto
    "prioridad",             # ALTA, MEDIA, BAJA
    "enriquecimiento_legal", # EXACTO, PARCIAL, NO_CONSULTABLE, ERROR

    # Auditoría
    "fecha_creacion_registro", # Timestamp ISO del momento de creación
]

VOCABULARIOS = {
    "canal_contacto": ["telefono", "whatsapp", "email", "presencial", "videollamada"],
    "resultado_contacto": ["contactado", "no_contesta", "ocupado", "numero_errado", "buzon_voz", "fuera_servicio", "rechaza_llamada"],
    "etapa_actual": ["apertura", "descubrimiento_necesidades", "presentacion_solucion", "manejo_objeciones", "cierre", "seguimiento_post_llamada", "cerrado_ganado", "cerrado_perdido", "no_calificado"],
    "persona_contactada_rol": ["propietario_representante", "gerente_administrador", "encargado_compras", "encargado_pagos", "otro_empleado", "no_informado"],
    "acepta_pagos_electronicos": ["si", "no", "no_sabe", "ya_tiene_proveedor"],
    "satisfaccion_proveedor": ["muy_satisfecho", "satisfecho", "neutral", "insatisfecho", "muy_insatisfecho", "no_aplica"],
    "objecion_principal": ["precio_comisiones", "ya_tiene_proveedor", "no_ve_necesidad", "desconfianza_tecnologia", "proceso_largo", "requiere_aprobacion", "ninguna"],
    "resultado_final": ["activado", "agendado_demo", "enviada_propuesta", "en_evaluacion", "perdido_precio", "perdido_competencia", "perdido_sin_interes", "no_contactable", "negocio_inactivo"],
    "motivo_perdida": ["precio_comisiones", "ya_tiene_proveedor_satisfactorio", "no_ve_valor_agregado", "desconfianza_seguridad", "proceso_onboarding_largo", "requiere_aprobacion_superior", "cambio_no_prioritario", "no_contactable_despues_multiples_intentos", "negocio_cerrado_inactivo", "otro"],
    "unidad_volumen": ["transacciones_mes", "millones_cop_mes", "porcentaje_ventas_tarjeta"],
}

# Columnas heredadas del Top N (no se editan en el registro)
CAMPOS_HEREDADOS = [
    "entidad_dedup_id",
    "posicion_top100",
    "razon_social",
    "fuente_top100",
    "score_prioridad",
    "prioridad",
    "enriquecimiento_legal",
]

def validar_registro(registro: dict) -> list[str]:
    """Valida un registro contra vocabularios cerrados. Retorna lista de errores."""
    errores = []
    for campo, valor in registro.items():
        if campo in VOCABULARIOS and valor:
            if valor not in VOCABULARIOS[campo]:
                errores.append(f"{campo}: '{valor}' no es válido. Opciones: {VOCABULARIOS[campo]}")
    return errores


def crear_registro_vacio(entidad_dedup_id: str, posicion: int, razon_social: str, fuente: str, score: float, prioridad: str, enriquecimiento: str) -> dict:
    """Crea un registro base con campos heredados del Top N."""
    from datetime import date
    return {
        "entidad_dedup_id": entidad_dedup_id,
        "posicion_top100": posicion,
        "razon_social": razon_social,
        "fuente_top100": fuente,
        "score_prioridad": score,
        "prioridad": prioridad,
        "enriquecimiento_legal": enriquecimiento,
        "interaccion_id": 1,
        "fecha_registro": date.today().isoformat(),
        "fecha_creacion_registro": date.today().isoformat(),
        # Campos vacíos listos para captura
        **{k: "" for k in ESQUEMA_REGISTRO if k not in CAMPOS_HEREDADOS and k not in ["entidad_dedup_id", "posicion_top100", "razon_social", "fuente_top100", "score_prioridad", "prioridad", "enriquecimiento_legal"]},
    }


def validar_vocabulario(campo: str, valor: str) -> bool:
    """Verifica si un valor pertenece al vocabulario cerrado del campo."""
    if campo not in VOCABULARIOS:
        return True  # Campo libre
    return valor in VOCABULARIOS[campo]


def obtener_siguiente_interaccion_id(registros_existentes: list[dict], entidad_dedup_id: str) -> int:
    """Calcula el siguiente ID de interacción para una entidad."""
    max_id = 0
    for r in registros_existentes:
        if r.get("entidad_dedup_id") == entidad_dedup_id:
            max_id = max(max_id, int(r.get("interaccion_id", 0)))
    return max_id + 1