"""
Adapters de Entrega — Mock y Real (boundary).

MockDeliveryAdapter: ÚNICO adapter implementado. Simula envío sin red.
RealZernioDeliveryAdapter: Boundary — NO implementado, siempre NotImplementedError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


@dataclass
class DeliveryResult:
    """Resultado de intento de entrega."""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    simulated: bool = True
    delivery_mode: str = "mock"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class MockDeliveryAdapter:
    """
    ÚNICO adapter de entrega implementado en esta fase.
    Simula envío por WhatsApp/Zernio SIN tocar red real.
    Registra en memoria para auditoría.
    """

    def __init__(self):
        self.sent_messages: list[dict] = []
        self.delivery_mode: str = "mock"

    def send(
        self,
        to_number: str,
        text: str,
        approval_request: Any = None,
        metadata: dict | None = None,
    ) -> 'DeliveryResult':
        """Simula envío — registra en memoria, NO hace red real."""
        msg = {
            "to": to_number,
            "text": text,
            "timestamp": datetime.now().isoformat(),
            "approval_request_id": getattr(approval_request, "request_id", None) if approval_request else None,
            "metadata": metadata or {},
        }
        self.sent_messages.append(msg)

        return DeliveryResult(
            success=True,
            message_id=f"mock_{len(self.sent_messages)}",
            simulated=True,
            delivery_mode="mock",
        )

    def get_sent_messages(self) -> list[dict]:
        """Retorna copia de mensajes enviados (para auditoría)."""
        return self.sent_messages.copy()

    def clear(self) -> None:
        """Limpia historial (útil para tests)."""
        self.sent_messages.clear()


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


# =============================================================================
# FACTORY / BOUNDARY ENFORCEMENT
# =============================================================================

def get_delivery_adapter(mode: str = "mock") -> Any:
    """
    Factory que retorna el adapter apropiado.
    En producción (fase futura), mode="real" retornaría RealZernioDeliveryAdapter.
    En esta fase, SOLO retorna MockDeliveryAdapter.
    """
    if mode == "mock":
        return MockDeliveryAdapter()
    raise NotImplementedError(
        f"Modo de entrega '{mode}' no implementado. "
        "Solo 'mock' está disponible en esta fase. "
        "Para 'real' se requiere fase futura autorizada."
    )


def assert_delivery_mode_safe(mode: str) -> None:
    """Verifica que el modo de entrega sea seguro (solo mock)."""
    if mode != "mock":
        raise NotImplementedError(
            f"DELIVERY_MODE='{mode}' no implementado — solo 'mock' disponible. "
            "Cualquier otro modo requiere código nuevo en fase autorizada."
        )


# Instancia global singleton para uso en pipeline (mock)
MOCK_ADAPTER = MockDeliveryAdapter()


def get_mock_adapter() -> MockDeliveryAdapter:
    """Retorna instancia singleton del mock adapter."""
    return MOCK_ADAPTER


def send_via_real_zernio_delivery(*args, **kwargs):
    """
    Punto de entrada para envío real — SIEMPRE NotImplementedError.
    Existe como boundary explícito: nunca se llama en esta fase.
    """
    raise NotImplementedError(
        "send_via_real_zernio_delivery() no implementado en esta fase. "
        "RealZernioDeliveryAdapter no existe — requeriría fase futura autorizada. "
        "Ver config.py: REAL_DELIVERY_ENABLED y DELIVERY_MODE."
    )


# Exportaciones explícitas
__all__ = [
    "DeliveryResult",
    "MockDeliveryAdapter",
    "RealZernioDeliveryAdapter",
    "get_delivery_adapter",
    "assert_delivery_mode_safe",
    "get_mock_adapter",
    "send_via_real_zernio_delivery",
]

if __name__ == "__main__":
    # Test rápido
    adapter = MockDeliveryAdapter()
    result = adapter.send("+573001234567", "Hola, prueba mock", metadata={"test": True})
    print(f"Envío mock: {result}")
    print(f"Mensajes en cola: {len(adapter.sent_messages)}")

    # Verificar que real adapter falla
    try:
        RealZernioDeliveryAdapter()
    except NotImplementedError as e:
        print(f"✅ Real adapter bloqueado correctamente: {e}")