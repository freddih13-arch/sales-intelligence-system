"""
Motor de Decisión — Pipeline de Procesamiento Determinista.

Recibe clasificación + contexto → decide acción (send, escalate, block, approve).
NO usa LLM/ML: reglas deterministas basadas en clasificación + contexto.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from sales_intel.piloto_zernio.config import RiskLevel
from sales_intel.piloto_zernio.clasificador import ClassificationResult


@dataclass
class DecisionResult:
    action: str  # "send", "escalate", "block", "approve", "request_approval"
    draft_response: Optional[str] = None
    requires_approval: bool = False
    approval_reason: Optional[str] = None
    block_reason: Optional[str] = None
    escalation_reason: Optional[str] = None
    confidence: float = 0.0


# =============================================================================
# PLANTILLAS DE RESPUESTA (deterministas, sin LLM)
# =============================================================================

PLANTILLAS_RESPUESTA = {
    "saludo": "¡Hola! Soy el asistente de Bold. ¿En qué puedo ayudarte hoy con tu negocio?",
    "interes_comercial": "¡Excelente! Bold te ayuda a cobrar con tarjeta sin complicaciones. ¿Te gustaría una demo rápida de 15 min para ver cómo funciona?",
    "objecion_precio": "Entiendo que el costo es importante. Bold no tiene cuota de manejo y la comisión es por transacción exitosa. ¿Te gustaría ver el desglose exacto para tu volumen?",
    "ya_tiene_proveedor": "Entiendo que ya tienes proveedor. Muchos clientes nuestros venían de otro y cambiaron por la comisión por transacción (sin cuota fija) y el dinero al día siguiente. ¿Te gustaría comparar?",
    "solicita_demo": "¡Perfecto! Una demo de 15 min te muestra todo: cobro con tarjeta, link de pago, QR, y el dinero en tu cuenta al día siguiente. ¿Qué día y hora te viene bien?",
    "erp_integracion": "Para integraciones técnicas/ERP, nuestro equipo especializado te asesora mejor. Te conecto con un especialista. ¿Cuál es tu ERP actual?",
    "otp_codigo": "Por tu seguridad, ese código no debe compartirse por este medio — no lo necesito, y prefiero que ese paso lo hagas directamente en la app o con quien te esté ayudando. Le aviso a un asesor para que continúe contigo ese proceso.",
    "credenciales": "Esa contraseña la debes definir/ingresar tú mismo en la app — no puedo sugerírtela, verla ni usarla yo. Si tienes dudas con ese paso, le aviso a un asesor para que te ayude directamente.",
    "documentos_identidad": "Por seguridad, no solicito ni recibo documentos de identidad por este medio. Si el proceso lo requiere, te conecto con un asesor para que te guíe de forma segura.",
    "erp_integracion": "Para integraciones técnicas/ERP, nuestro equipo especializado te asesora mejor. Te conecto con un especialista. ¿Cuál es tu ERP actual?",
    "queja_soporte": "Lamento el inconveniente. Para darte solución rápida, te conecto con nuestro equipo de soporte especializado. ¿Me confirmas tu número de caso o el número de teléfono asociado?",
    "despedida": "¡Gracias por contactarnos! Si necesitas algo más, aquí estaremos. ¡Que tengas excelente día!",
    "desconocido": "Gracias por tu mensaje. Un asesor revisará tu consulta y te responderá pronto. ¿Hay algo más en lo que pueda ayudarte?",
    "seguridad_dura_violacion": "Por tu seguridad, ese tipo de información no debe compartirse por este medio. Un asesor te contactará para continuar de forma segura.",
}

# Respuestas de escalamiento/block
RESPUESTAS_ESCALAMIENTO = {
    "otp_codigo": "Por tu seguridad, ese código no debe compartirse por este medio — no lo necesito, y prefiero que ese paso lo hagas directamente en la app o con quien te esté ayudando. Le aviso a un asesor para que continúe contigo ese proceso.",
    "credenciales": "Esa contraseña la debes definir/ingresar tú mismo en la app — no puedo sugerírtela, verla ni usarla yo. Si tienes dudas con ese paso, le aviso a un asesor para que te ayude directamente.",
    "documentos_identidad": "Por seguridad, no solicito ni recibo documentos de identidad por este medio. Si el proceso lo requiere, te conecto con un asesor para que te guíe de forma segura.",
    "erp_integracion": "Para integraciones técnicas/ERP, nuestro equipo especializado te asesora mejor. Te conecto con un especialista. ¿Cuál es tu ERP actual?",
}

DEFAULT_RESPONSE = "Gracias por tu mensaje. Un asesor revisará tu consulta y te responderá pronto. ¿Hay algo más en lo que pueda ayudarte?"


# =============================================================================
# MOTOR DE DECISIÓN PRINCIPAL
# =============================================================================

def decidir(
    clasificacion: dict,
    opt_in: bool = True,
    en_ventana: bool = True,
    template_disponible: bool = True,
    opt_in_verificado: bool = True,
) -> dict:
    """
    Motor de decisión determinista.
    Entrada: clasificación + contexto (opt_in, ventana 24h, template).
    Salida: acción + respuesta + metadatos.
    """
    from sales_intel.piloto_zernio.config import RiskLevel

    intent = clasificacion.get("intent", "desconocido")
    risk_level = clasificacion.get("risk_level", "LOW")
    confidence = clasificacion.get("confidence", 0.0)
    requires_approval = clasificacion.get("requires_approval", False)
    escalation_reason = clasificacion.get("escalation_reason")
    entities = clasificacion.get("entities", {})

    # 1. Reglas de bloqueo duro (siempre prevalecen)
    if risk_level == RiskLevel.CRITICAL:
        return {
            "action": "block",
            "draft_response": PLANTILLAS_RESPUESTA.get("seguridad_dura_violacion"),
            "requires_approval": True,
            "block_reason": f"Regla de seguridad dura: {entities.get('razon', 'violación seguridad dura')}",
            "escalation_reason": "Regla de seguridad dura activada",
            "confidence": 1.0,
        }

    # 2. Verificaciones de compliance (opt_in, ventana 24h, template)
    if not opt_in_verificado:
        return {
            "action": "block",
            "draft_response": "Para continuar, necesitamos tu autorización para contactarte por WhatsApp. Un asesor te contactará para gestionar tu consentimiento.",
            "block_reason": "opt_in no verificado",
            "confidence": 1.0,
        }

    if not en_ventana:
        # Fuera de ventana 24h: requiere template aprobado
        # En demo, asumimos template no disponible
        return {
            "action": "block",
            "draft_response": "Tu mensaje llegó fuera del horario de atención automatizada. Un asesor te responderá en horario hábil.",
            "block_reason": "fuera_ventana_24h_sin_template",
            "confidence": 1.0,
        }

    # 3. Decisión por intent
    # El intent ya fue extraído en línea 77 desde clasificacion.get("intent", "desconocido")
    # No sobrescribir con entities.get("intent") porque entities puede no tener el intent

    # Mapeo de acción por intent
    ACCIONES_POR_INTENT = {
        "saludo": ("send", "saludo"),
        "interes_comercial": ("request_approval", "interes_comercial"),
        "objecion_precio": ("send", "objecion_precio"),
        "ya_tiene_proveedor": ("send", "ya_tiene_proveedor"),
        "solicita_demo": ("request_approval", "solicita_demo"),
        "erp_integracion": ("escalate", "erp_integracion"),
        "otp_codigo": ("block", "otp_codigo"),
        "credenciales": ("block", "credenciales"),
        "documentos_identidad": ("block", "documentos_identidad"),
        "queja_soporte": ("escalate", "queja_soporte"),
        "despedida": ("send", "despedida"),
        "interes_comercial": ("request_approval", "interes_comercial"),
        "solicita_demo": ("request_approval", "solicita_demo"),
    }

    accion, plantilla_key = ACCIONES_POR_INTENT.get(
        intent, ("send", "desconocido")
    )

    draft_response = PLANTILLAS_RESPUESTA.get(plantilla_key, DEFAULT_RESPONSE)
    requires_approval = accion in ["request_approval", "escalate"]

    return {
        "action": accion,
        "draft_response": draft_response,
        "requires_approval": requires_approval,
        "approval_reason": escalation_reason or f"Intent '{intent}' requiere aprobación humana",
        "block_reason": None,
        "escalation_reason": escalation_reason,
        "confidence": 0.9,
    }


def generar_respuesta_escalamiento(intent: str, entities: dict) -> str:
    """Genera respuesta de escalamiento/bloqueo para intents especiales."""
    return RESPUESTAS_ESCALAMIENTO.get(intent, DEFAULT_RESPONSE)


def procesar_aprobacion(
    approval_request_id: str,
    decision: str,  # "APPROVED" | "REJECTED"
    approved_by: str,
    draft_response: str,
    to_number: str,
) -> dict:
    """
    Procesa resultado de aprobación humana.
    En demo, solo registra decisión — no envía realmente.
    """
    from sales_intel.piloto_zernio.delivery import MockDeliveryAdapter

    if decision != "APPROVED":
        return {
            "success": False,
            "action": "rejected",
            "message": "Aprobación rechazada por humano — no se envía mensaje",
        }

    # En demo, usa MockDeliveryAdapter
    from sales_intel.piloto_zernio.delivery import MockDeliveryAdapter
    adapter = MockDeliveryAdapter()
    delivery = adapter.send(to_number, draft_response)

    return {
        "success": True,
        "action": "sent",
        "delivery": delivery,
        "approved_by": approved_by,
    }


def main():
    """Test rápido del motor de decisión."""
    from sales_intel.piloto_zernio.clasificador import clasificar_mensaje

    casos = [
        ("Hola, me interesa Bold", True, True, True),
        ("Mi OTP es 123456", True, True, True),
        ("Quiero demo para mi restaurante", True, True, True),
        ("Necesito integrar con SAP", True, True, True),
        ("Ya tengo proveedor", True, True, True),
    ]

    for texto, opt_in, en_ventana, template in casos:
        clasif = {"intent": "interes_comercial", "confidence": 0.8, "risk_level": "LOW", "requires_approval": True, "entities": {}}
        if "OTP" in texto or "otp" in texto.lower():
            clasif = {"intent": "otp_codigo", "confidence": 1.0, "risk_level": "CRITICAL", "requires_approval": True, "entities": {"razon": "OTP detectado"}}
        elif "SAP" in texto:
            clasif = {"intent": "erp_integracion", "confidence": 0.9, "risk_level": "HIGH", "requires_approval": True, "entities": {}}
        elif "proveedor" in texto.lower():
            clasif = {"intent": "ya_tiene_proveedor", "confidence": 0.85, "risk_level": "LOW", "requires_approval": False, "entities": {}}

        decision = decidir(clasif, True, True, True)
        print(f"Texto: {texto}")
        print(f"  Acción: {decision['action']}, Approval: {decision['requires_approval']}")
        print(f"  Respuesta: {decision['draft_response'][:80]}...")
        print()


if __name__ == "__main__":
    main()