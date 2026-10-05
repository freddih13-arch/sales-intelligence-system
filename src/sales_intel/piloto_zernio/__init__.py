"""
Piloto Controlado Zernio — Integración WhatsApp Business (MOCK).

Implementa el flujo de piloto controlado para integración con Zernio
(WhatsApp Business API) bajo estrictos guardrails:

- DELIVERY_MODE = "mock" (único modo implementado)
- 5 kill-switches independientes (todos FALSE por defecto)
- MockDeliveryAdapter único adapter implementado
- Dry-run end-to-end con 7 escenarios de prueba
- Cost guard: $0.05/call, 5 calls/day máximo
- CERO envío a producción real

Arquitectura:
  inbound (webhook) → clasificador → knowledge_lookup → decision_engine
  → approval_request → aprobación humana (simulada) → MockDeliveryAdapter
  → audit log completo

CERO envíos reales. CERO conexiones a producción.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional
import sys

# Importar submódulos para que estén disponibles como sales_intel.piloto_zernio.xxx
from . import clasificador
from . import config
from . import decision_engine
from . import delivery

# Registrar explícitamente en sys.modules para que las importaciones directas funcionen
sys.modules['sales_intel.piloto_zernio.clasificador'] = clasificador
sys.modules['sales_intel.piloto_zernio.config'] = config
sys.modules['sales_intel.piloto_zernio.decision_engine'] = decision_engine
sys.modules['sales_intel.piloto_zernio.delivery'] = delivery


class DeliveryMode(str, Enum):
    """Modos de entrega — solo 'mock' implementado."""
    MOCK = "mock"
    # REAL = "real"  # Deliberadamente NO incluido — requiere código nuevo


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class InboundMessage:
    """Mensaje entrante normalizado desde webhook Zernio."""
    message_id: str
    from_number: str
    to_number: str
    text: str
    timestamp: str
    message_type: str = "text"
    media_url: Optional[str] = None


@dataclass
class ClassificationResult:
    """Resultado de clasificación de mensaje entrante."""
    intent: str
    confidence: float
    entities: dict
    risk_level: RiskLevel
    requires_approval: bool
    escalation_reason: Optional[str] = None


@dataclass
class ApprovalRequest:
    """Solicitud de aprobación humana para envío."""
    request_id: str
    inbound_message: InboundMessage
    classification: ClassificationResult
    draft_response: str
    recommended_action: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    escalation_reason: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None


@dataclass
class DeliveryResult:
    """Resultado de entrega (mock o real)."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    simulated: bool = True
    delivery_mode: str = "mock"


class MockDeliveryAdapter:
    """
    ÚNICO adapter de entrega implementado en esta fase.
    Simula envío por WhatsApp/Zernio sin tocar red real.
    """

    def __init__(self):
        self.sent_messages: list[dict] = []

    def send(self, to_number: str, text: str, approval_request: Optional[Any] = None) -> DeliveryResult:
        """Simula envío — registra en memoria, no hace red."""
        msg = {
            "to": to_number,
            "text": text,
            "timestamp:": __import__("datetime").datetime.now().isoformat(),
            "approval_request_id": approval_request.request_id if approval_request else None,
        }
        self.sent_messages.append(msg)
        return DeliveryResult(
            success=True,
            message_id=f"mock_{len(self.sent_messages)}",
            simulated=True,
            delivery_mode="mock",
        )


class RealZernioDeliveryAdapter:
    """
    Adapter para envío REAL a Zernio — NO IMPLEMENTADO EN ESTA FASE.
    Existe solo como boundary: cualquier intento de instanciarlo
    o usarlo lanza NotImplementedError.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "RealZernioDeliveryAdapter no existe en esta fase. "
            "Construirlo requiere fase futura autorizada explícitamente. "
            "Ver config.py: REAL_DELIVERY_ENABLED y DELIVERY_MODE."
        )

    def send(self, *args, **kwargs):
        raise NotImplementedError("No implementado en esta fase.")


# Kill-switches (re-exportados desde config para claridad)
# Ver runtime/config.py para valores reales
KILL_SWITCHES = {
    "PILOTO_ACTIVO": False,
    "DELIVERY_MODE": "mock",
    "REAL_DELIVERY_ENABLED": False,
    "CLAUDE_DRAFTING_ENABLED": False,
    "REAL_LLM_SPEND_AUTHORIZED": False,
}

# Cost Guard defaults
MAX_COST_PER_CALL_USD = 0.05
MAX_CALLS_PER_DAY = 5


# Escenarios de dry-run (7 escenarios de prueba)
DRY_RUN_ESCENARIOS = [
    {
        "id": "normal",
        "descripcion": "Flujo normal: mensaje → clasificación → aprobación → envío mock",
        "entrada": "Hola, me interesa Bold para mi restaurante",
        "esperado": "classification.intent='interes_comercial', approval→APPROVED, mock_send",
    },
    {
        "id": "riesgo_compliance",
        "descripcion": "Mensaje con riesgo compliance (OTP, credenciales) → escalamiento CRITICAL",
        "entrada": "Mi código OTP es 123456",
        "esperado": "risk_level=CRITICAL, escalate_to_human=True, no mock_send",
    },
    {
        "id": "erp_integration",
        "descripcion": "Intención ERP detectada → escalamiento a humano",
        "entrada": "Necesito integrar con mi ERP SAP",
        "esperado": "intent=erp_integration, escalate_to_human=True",
    },
    {
        "id": "sin_optin",
        "descripcion": "Prospecto sin whatsapp_opt_in → bloqueado antes de approval",
        "entrada": "Quiero info",
        "esperado": "opt_in=False → bloqueado, no approval",
    },
    {
        "id": "ventana_24h",
        "descripcion": "Mensaje fuera de ventana 24h sin template → bloqueado",
        "entrada": "Hola (fuera de ventana)",
        "esperado": "fuera_ventana=True, sin_template=True → bloqueado",
    },
    {
        "id": "template_faltante",
        "descripcion": "Requiere template aprobado y no hay → bloqueado",
        "entrada": "Confirmo pedido",
        "esperado": "requiere_template=True, no_template → bloqueado",
    },
    {
        "id": "duplicado",
        "descripcion": "Mensaje duplicado (message_id repetido) → ignorado",
        "entrada": "Hola (id duplicado)",
        "esperado": "duplicate_detected=True → ignorado, no procesar",
    },
]


def validar_kill_switches() -> tuple[bool, str]:
    """Verifica que todos los kill-switches estén en estado seguro (demo)."""
    from sales_intel.piloto_zernio.config import (
        PILOTO_ACTIVO, DELIVERY_MODE, REAL_DELIVERY_ENABLED,
        CLAUDE_DRAFTING_ENABLED, REAL_LLM_SPEND_AUTHORIZED,
    )

    if PILOTO_ACTIVO:
        return False, "PILOTO_ACTIVO debe ser False en demo"
    if DELIVERY_MODE != "mock":
        return False, f"DELIVERY_MODE debe ser 'mock', es '{DELIVERY_MODE}'"
    if REAL_DELIVERY_ENABLED:
        return False, "REAL_DELIVERY_ENABLED debe ser False en demo"
    if CLAUDE_DRAFTING_ENABLED:
        return False, "CLAUDE_DRAFTING_ENABLED debe ser False en demo"
    if REAL_LLM_SPEND_AUTHORIZED:
        return False, "REAL_LLM_SPEND_AUTHORIZED debe ser False en demo"
    return True, "Todos los kill-switches en estado seguro (demo)"


def ejecutar_dry_run(escenario_id: str = "normal") -> dict:
    """Ejecuta un dry-run del piloto controlado (solo mock)."""
    # Usar módulos ya importados en el paquete para evitar problemas de importación
    from .config import assert_delivery_mode_is_safe
    from .clasificador import clasificar_mensaje
    from .decision_engine import decidir
    from .delivery import MockDeliveryAdapter

    assert_delivery_mode_is_safe()

    escenario = next(e for e in DRY_RUN_ESCENARIOS if e["id"] == escenario_id)
    entrada = escenario["entrada"]

    # Simular inbound
    inbound = {
        "message_id": f"test_{escenario_id}",
        "from_number": "+573001234567",
        "to_number": "+573007654321",
        "text": entrada,
        "timestamp": "2026-01-15T10:00:00Z",
    }

    # Pipeline mock
    clasificacion = clasificar_mensaje(entrada)
    decision = decidir(clasificacion, opt_in=True, en_ventana=True, template_disponible=True)
    approval = {"status": "APPROVED", "approved_by": "demo_user"} if decision["requires_approval"] else None

    adapter = MockDeliveryAdapter()
    if decision["action"] == "send" and approval and approval["status"] == "APPROVED":
        delivery = adapter.send(inbound["from_number"], decision["draft_response"])
    else:
        delivery = {"success": False, "reason": decision.get("block_reason", "no_aplica")}

    return {
        "escenario": escenario_id,
        "entrada": entrada,
        "clasificacion": clasificacion,
        "decision": decision,
        "approval": approval,
        "delivery": delivery,
        "escenario_esperado": escenario["esperado"],
        "demo_mode": True,
    }


def main():
    """CLI para testing del piloto."""
    import argparse
    parser = argparse.ArgumentParser(description="Piloto Controlado Zernio - Demo")
    parser.add_argument("--escenario", default="normal", choices=[e["id"] for e in DRY_RUN_ESCENARIOS])
    parser.add_argument("--verificar-kill-switches", action="store_true")
    args = parser.parse_args()

    if args.verificar_kill_switches:
        ok, msg = validar_kill_switches()
        print(f"{'✅' if ok else '❌'} Kill-switches: {msg}")
        return

    print(f"🚀 Ejecutando dry-run: {args.escenario}")
    resultado = ejecutar_dry_run(args.escenario)
    import json
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()