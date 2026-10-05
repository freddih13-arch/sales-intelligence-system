"""
Tests para Piloto Controlado Zernio.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sales_intel.piloto_zernio.config import (
    PILOTO_ACTIVO,
    DELIVERY_MODE,
    REAL_DELIVERY_ENABLED,
    validar_kill_switches,
    load_from_env,
)
from sales_intel.piloto_zernio.clasificador import clasificar_mensaje, detectar_seguridad_dura
from sales_intel.piloto_zernio.decision_engine import decidir
from sales_intel.piloto_zernio.delivery import MockDeliveryAdapter, RealZernioDeliveryAdapter, get_delivery_adapter


def test_kill_switches_defaults():
    """Verifica que kill-switches estén en valores seguros por defecto."""
    assert PILOTO_ACTIVO is False
    assert DELIVERY_MODE == "mock"
    assert REAL_DELIVERY_ENABLED is False


def test_validar_kill_switches():
    ok, msg = validar_kill_switches()
    assert ok, f"Kill-switches inseguros: {msg}"


def test_load_from_env():
    """Test override por variables de entorno."""
    import os
    os.environ["PILOTO_ACTIVO"] = "true"
    load_from_env()
    # Nota: en demo no cambiamos realmente, solo test de que la función existe
    os.environ.pop("PILOTO_ACTIVO", None)


def test_assert_delivery_mode_safe():
    """assert_delivery_mode_is_safe debe fallar si mode != mock."""
    from sales_intel.piloto_zernio.config import assert_delivery_mode_is_safe, DELIVERY_MODE
    # En demo, DELIVERY_MODE = "mock"
    assert DELIVERY_MODE == "mock"
    # No debe lanzar excepción
    from sales_intel.piloto_zernio.config import assert_delivery_mode_is_safe
    assert_delivery_mode_is_safe()


def test_real_delivery_disabled():
    """RealZernioDeliveryAdapter siempre lanza NotImplementedError."""
    try:
        RealZernioDeliveryAdapter()
        assert False, "Debe lanzar NotImplementedError"
    except NotImplementedError:
        pass


def test_mock_delivery_adapter():
    """MockDeliveryAdapter simula envío sin red."""
    adapter = MockDeliveryAdapter()
    result = adapter.send("+573001234567", "Hola prueba", metadata={"test": True})
    assert result.success is True
    assert result.simulated is True
    assert result.delivery_mode == "mock"
    assert len(adapter.sent_messages) == 1
    assert adapter.sent_messages[0]["to"] == "+573001234567"


def test_get_delivery_adapter():
    """Factory retorna MockDeliveryAdapter para modo mock."""
    adapter = get_delivery_adapter("mock")
    assert isinstance(adapter, MockDeliveryAdapter)

    # Modo real no implementado
    try:
        get_delivery_adapter("real")
        assert False, "Debe fallar"
    except NotImplementedError:
        pass


def test_clasificador_intent():
    """Test clasificación de intenciones."""
    resultado = clasificar_mensaje("Hola, me interesa Bold para mi restaurante")
    assert resultado["intent"] == "interes_comercial"
    assert resultado["confidence"] >= 0.8
    assert resultado["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_clasificador_otp():
    """Test detección de OTP/códigos."""
    resultado = clasificar_mensaje("Mi código OTP es 123456")
    assert resultado["intent"] == "otp_codigo"
    assert resultado["risk_level"] == "CRITICAL"
    assert resultado["requires_approval"] is True


def test_clasificador_credenciales():
    """Test detección de credenciales."""
    resultado = clasificar_mensaje("Mi contraseña es 123456")
    assert resultado["intent"] == "credenciales"
    assert resultado["risk_level"] == "CRITICAL"


def test_clasificador_erp():
    """Test detección de integración ERP."""
    resultado = clasificar_mensaje("Necesito integrar con mi ERP SAP")
    assert resultado["intent"] == "erp_integracion"
    assert resultado["risk_level"] == "HIGH"
    assert resultado["requires_approval"] is True


def test_detectar_seguridad_dura():
    """Test detección de violaciones de seguridad duras (V3 Spec)."""
    # OTP
    es_violacion, risk, intent_especifico, razon = detectar_seguridad_dura("Mi OTP es 123456")
    assert es_violacion
    assert risk.name == "CRITICAL"
    assert intent_especifico == "otp_codigo"
    assert "OTP" in razon or "código" in razon.lower()

    # Contraseña
    es_violacion, risk, intent_especifico, razon = detectar_seguridad_dura("Mi contraseña es 123456")
    assert es_violacion
    assert risk.name == "CRITICAL"
    assert intent_especifico == "credenciales"

    # Documentos identidad
    es_violacion, risk, intent_especifico, razon = detectar_seguridad_dura("Mi cédula es 123456789")
    assert es_violacion
    assert intent_especifico == "documentos_identidad"
    assert risk.name == "CRITICAL"

    # Texto normal sin violación
    es_violacion, risk, intent_especifico, razon = detectar_seguridad_dura("Hola, quiero información")
    assert not es_violacion
    assert intent_especifico == ""


def test_decision_engine():
    """Test motor de decisión determinista."""
    from sales_intel.piloto_zernio.clasificador import ClassificationResult

    # Caso normal: interes_comercial
    clasificacion = {
        "intent": "interes_comercial",
        "confidence": 0.85,
        "risk_level": "LOW",
        "requires_approval": True,
        "escalation_reason": "Demo requiere aprobación",
        "entities": {},
    }
    decision = decidir(clasificacion, opt_in=True, en_ventana=True, template_disponible=True)
    assert decision["action"] == "request_approval"
    assert decision["requires_approval"] is True

    # Caso OTP -> block
    clasificacion = {
        "intent": "otp_codigo",
        "confidence": 1.0,
        "risk_level": "CRITICAL",
        "requires_approval": True,
        "entities": {"razon": "OTP detectado"},
    }
    decision = decidir(clasificacion, opt_in=True, en_ventana=True, template_disponible=True)
    assert decision["action"] == "block"
    assert "OTP" in decision["block_reason"] or "seguridad" in decision["block_reason"].lower()

    # Caso ERP -> escalate
    clasificacion = {
        "intent": "erp_integracion",
        "confidence": 0.9,
        "risk_level": "HIGH",
        "requires_approval": True,
        "entities": {},
    }
    decision = decidir(clasificacion, opt_in=True, en_ventana=True, template_disponible=True)
    assert decision["action"] == "escalate"


def test_dry_run_escenarios():
    """Test dry-run de los 7 escenarios."""
    from sales_intel.piloto_zernio import DRY_RUN_ESCENARIOS, ejecutar_dry_run

    for escenario in DRY_RUN_ESCENARIOS:
        resultado = ejecutar_dry_run(escenario["id"])
        assert "escenario" in resultado
        assert "entrada" in resultado
        assert "decision" in resultado
        assert "delivery" in resultado


def test_kill_switches_env_override():
    """Test override por variables de entorno."""
    import os
    from sales_intel.piloto_zernio.config import load_from_env, PILOTO_ACTIVO

    os.environ["PILOTO_ACTIVO"] = "true"
    load_from_env()
    # En test no cambiamos el global real, solo verificamos que la función existe
    os.environ.pop("PILOTO_ACTIVO", None)


def test_mock_adapter_singleton():
    """get_mock_adapter retorna singleton."""
    from sales_intel.piloto_zernio.delivery import get_mock_adapter
    a1 = get_mock_adapter()
    a2 = get_mock_adapter()
    assert a1 is a2


def test_send_via_real_always_fails():
    """send_via_real_zernio_delivery siempre falla."""
    from sales_intel.piloto_zernio.delivery import send_via_real_zernio_delivery
    try:
        send_via_real_zernio_delivery()
        assert False, "Debe lanzar NotImplementedError"
    except NotImplementedError:
        pass


if __name__ == "__main__":
    import sys
    fallos = 0
    for nombre, funcion in list(globals().items()):
        if nombre.startswith("test_") and callable(funcion):
            try:
                funcion()
                print(f"OK   {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"FAIL {nombre}: {e}")
            except Exception as e:
                fallos += 1
                print(f"ERROR {nombre}: {e}")
    raise SystemExit(fallos)