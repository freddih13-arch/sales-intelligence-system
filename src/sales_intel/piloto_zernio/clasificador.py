"""
Clasificador de Mensajes Entrantes — Motor de Decisión Determinista.

Clasifica mensajes entrantes de WhatsApp/Zernio usando reglas
deterministas (keywords, patrones, heurísticas). NO usa ML/LLM.

Reglas de seguridad duras (V3 Spec):
- OTP/códigos → escalamiento CRITICAL
- Contraseñas/credenciales → escalamiento
- Documentos identidad/PII → escalamiento
- ERP/integración técnica → escalamiento
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from sales_intel.piloto_zernio.config import RiskLevel


@dataclass
class ClassificationResult:
    intent: str
    confidence: float
    entities: dict
    risk_level: RiskLevel
    requires_approval: bool
    escalation_reason: Optional[str] = None


# =============================================================================
# PATRONES DE CLASIFICACIÓN (keywords deterministas)
# =============================================================================

PATRONES_INTENCION = {
    "interes_comercial": {
        "keywords": ["interesado", "quiero información", "me interesa", "cómo funciona", "precios", "costos", "comisiones", "demo", "prueba"],
        "confidence": 0.95,
    },
    "saludo": {
        "keywords": ["hola", "buenos días", "buenas tardes", "buenas", "qué tal", "saludos"],
        "confidence": 0.9,
    },
    "objecion_precio": {
        "keywords": ["muy caro", "caro", "costoso", "comisión alta", "comisión muy alta", "no tengo presupuesto"],
        "confidence": 0.8,
    },
    "ya_tiene_proveedor": {
        "keywords": ["ya tengo", "ya uso", "trabajo con", "mi proveedor", "ya tengo pos", "ya tengo datáfono"],
        "confidence": 0.85,
    },
    "solicita_demo": {
        "keywords": ["demo", "demostración", "quiero ver", "me pueden mostrar", "prueba gratis"],
        "confidence": 0.9,
    },
    "erp_integracion": {
        "keywords": ["erp", "sap", "oracle", "integración", "api", "conectar con", "sistema contable", "facturación electrónica"],
        "confidence": 0.9,
    },
    "otp_codigo": {
        "keywords": ["otp", "código", "código de verificación", "código sms", "pin", "clave", "autenticación", "verificación"],
        "confidence": 0.95,
    },
    "credenciales": {
        "keywords": ["contraseña", "password", "clave", "usuario y clave", "login", "acceso"],
        "confidence": 0.95,
    },
    "documentos_identidad": {
        "keywords": ["cédula", "cedula", "documento", "identidad", "foto de cédula", "cc", "pasaporte"],
        "confidence": 0.95,
    },
    "queja_soporte": {
        "keywords": ["problema", "error", "no funciona", "falla", "queja", "reclamo", "soporte técnico"],
        "confidence": 0.8,
    },
    "despedida": {
        "keywords": ["gracias", "adiós", "hasta luego", "nos vemos", "chau", "bye"],
        "confidence": 0.9,
    },
}


# =============================================================================
# REGLAS DE SEGURIDAD DURAS (V3 Spec) — SIEMPRE prevalecen
# =============================================================================

def detectar_seguridad_dura(texto: str) -> tuple[bool, RiskLevel, str, str]:
    """
    Detecta violaciones de reglas de seguridad duras (V3 Spec).
    Retorna (es_violación, risk_level, intent_específico, razón).
    intent_específico puede ser: "otp_codigo", "credenciales", "documentos_identidad", o "" si no hay violación.
    """
    texto_lower = texto.lower()

    # 1. OTP / Códigos de verificación
    for kw in ["otp", "código de verificación", "código sms", "código de verificación", "pin", "código de autenticación"]:
        if kw in texto_lower:
            return True, RiskLevel.CRITICAL, "otp_codigo", "OTP/código de verificación detectado — nunca procesar"

    # 2. Contraseñas / credenciales
    for kw in ["contraseña", "password", "clave de acceso", "usuario y clave", "credencial"]:
        if kw in texto_lower:
            return True, RiskLevel.CRITICAL, "credenciales", "Credencial detectada — nunca procesar ni almacenar"

    # 3. Documentos de identidad / PII
    for kw in ["cédula", "cedula", "foto de cédula", "foto de cedula", "documento de identidad", "pasaporte"]:
        if kw in texto_lower:
            return True, RiskLevel.CRITICAL, "documentos_identidad", "Documento de identidad detectado — nunca procesar"

    # 3b. Número de documento de tercero
    if "número de documento" in texto_lower and "tercero" in texto_lower:
        return True, RiskLevel.CRITICAL, "documentos_identidad", "Documento de tercero detectado — KYC requerido"

    return False, RiskLevel.LOW, "", ""


# =============================================================================
# CLASIFICADOR PRINCIPAL
# =============================================================================

def clasificar_mensaje(texto: str) -> dict:
    """
    Clasifica un mensaje entrante usando reglas deterministas.
    Retorna dict compatible con ClassificationResult.
    """
    from sales_intel.piloto_zernio.config import RiskLevel

    texto_lower = texto.lower().strip()

    # 1. Reglas de seguridad duras (siempre primero)
    es_violacion, risk_level, intent_especifico, razon = detectar_seguridad_dura(texto)
    if es_violacion:
        return {
            "intent": intent_especifico,
            "confidence": 1.0,
            "entities": {"razon": razon, "texto_original": texto[:100]},
            "risk_level": risk_level,
            "requires_approval": True,
            "escalation_reason": razon,
        }

    # 2. Clasificación por intenciones (keyword matching)
    mejor_intent = "desconocido"
    mejor_confidence = 0.0
    mejor_entities = {}

    for intent, config in PATRONES_INTENCION.items():
        for kw in config["keywords"]:
            if kw in texto_lower:
                if config["confidence"] > mejor_confidence:
                    mejor_confidence = config["confidence"]
                    mejor_intent = intent
                    mejor_entities = {"keyword_match": kw}

    # 3. Determinar risk_level y requires_approval según intent
    risk_level = RiskLevel.LOW
    requires_approval = False
    escalation_reason = None

    if mejor_intent in ["erp_integracion"]:
        risk_level = RiskLevel.HIGH
        requires_approval = True
        escalation_reason = "Integración técnica/ERP requiere escalamiento a humano"
    elif mejor_intent in ["otp_codigo", "credenciales", "documentos_identidad"]:
        risk_level = RiskLevel.CRITICAL
        requires_approval = True
        escalation_reason = "Regla de seguridad dura: nunca procesar automáticamente"
    elif mejor_intent in ["objecion_precio", "ya_tiene_proveedor"]:
        risk_level = RiskLevel.MEDIUM
        requires_approval = False  # El agente puede manejar objeciones estándar
    elif mejor_intent in ["solicita_demo", "interes_comercial"]:
        risk_level = RiskLevel.LOW
        requires_approval = True  # Demo requiere aprobación humana
        escalation_reason = "Demo requiere aprobación humana antes de agendar"
    elif mejor_intent in ["queja_soporte"]:
        risk_level = RiskLevel.MEDIUM
        requires_approval = True
        escalation_reason = "Queja/soporte requiere escalamiento a humano"

    return {
        "intent": mejor_intent,
        "confidence": round(mejor_confidence, 2),
        "entities": mejor_entities,
        "risk_level": risk_level,
        "requires_approval": requires_approval,
        "escalation_reason": escalation_reason,
    }


# =============================================================================
# EXTRACCIÓN DE ENTIDADES (heurísticas simples)
# =============================================================================

def extraer_entidades(texto: str) -> dict:
    """Extrae entidades simples usando regex heurísticos."""
    import re

    entidades = {}

    # Teléfonos colombianos
    telefonos = re.findall(r'(?:\+57|57)?\s?3\d{9}|\d{7,10}', texto)
    if telefonos:
        entidades["telefonos"] = telefonos

    # Emails
    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', texto)
    if emails:
        entidades["emails"] = emails

    # Montos (COP)
    montos = re.findall(r'\$?\s?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?\s?(?:COP|pesos|cop)?', texto, re.IGNORECASE)
    if montos:
        entidades["montos"] = montos

    return entidades


def clasificar_y_extraer(texto: str) -> dict:
    """Pipeline completo: clasificar + extraer entidades."""
    resultado = clasificar_mensaje(texto)
    entidades_extra = extraer_entidades(texto)
    if entidades_extra:
        resultado["entities"] = {**resultado["entities"], **entidades_extra}
    return resultado


if __name__ == "__main__":
    # Test rápido
    casos_test = [
        "Hola, me interesa Bold para mi restaurante",
        "Mi código OTP es 123456",
        "Ya tengo proveedor, uso MercadoPago",
        "Necesito integrar con mi ERP SAP",
        "Mi contraseña es 123456",
        "Quiero una demo para mi ferretería",
        "Mi cédula es 1234567890",
    ]

    for caso in casos_test:
        resultado = clasificar_y_extraer(caso)
        print(f"Entrada: {caso}")
        print(f"  Intent: {resultado['intent']} ({resultado['confidence']})")
        print(f"  Risk: {resultado['risk_level']}, Approval: {resultado['requires_approval']}")
        if resultado.get("escalation_reason"):
            print(f"  Escalation: {resultado['escalation_reason']}")
        print()