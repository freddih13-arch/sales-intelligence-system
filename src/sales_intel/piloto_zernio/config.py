"""
config.py — Kill-switches de seguridad para el Piloto Controlado Zernio.

Tres barreras INDEPENDIENTES, TODAS deben estar "abiertas" para que
exista CUALQUIER posibilidad de envío real (que en esta fase NUNCA existe,
porque ni DELIVERY_MODE soporta otra cosa que "mock" ni existe todavía
ningún RealZernioDeliveryAdapter).

1. PILOTO_ACTIVO (bool) — por defecto False. Si es False, el pipeline
   completo se detiene antes de aprobar/entregar nada.

2. DELIVERY_MODE (str) — por defecto "mock". El único valor implementado
   en todo runtime/ es "mock". Cualquier otro valor (incluido "real")
   hace que delivery.py levante NotImplementedError — nunca ejecuta una
   llamada real a Zernio.

3. REAL_DELIVERY_ENABLED (bool) — por defecto False. Barrera adicional
   e independiente, pensada para una fase futura en la que SÍ exista un
   RealZernioDeliveryAdapter: incluso si alguien la activa,
   delivery.send_via_real_zernio_delivery() levanta NotImplementedError.

4. CLAUDE_DRAFTING_ENABLED (bool) — por defecto False. Kill switch
   propio para la redacción con Claude real, independiente de los
   anteriores. Por defecto False: el pipeline usa el draft_response
   fijo del motor (decision_engine) — el comportamiento de fases
   anteriores no cambia para nadie que no active esto explícitamente.

5. REAL_LLM_SPEND_AUTHORIZED (bool) — por defecto False. Autorización
   FINANCIERA, separada a propósito de CLAUDE_DRAFTING_ENABLED.
   CLAUDE_DRAFTING_ENABLED responde "¿el sistema PUEDE intentar usar
   Claude para redactar?" — es una decisión de producto/comportamiento.
   REAL_LLM_SPEND_AUTHORIZED responde "¿el usuario autorizó explícitamente
   GASTAR DINERO REAL hoy?" — es una decisión financiera, deliberadamente
   distinta. Activar la primera NUNCA activa la segunda. Ambas deben ser
   True para que una llamada real pueda proceder.

Límites de Cost Guard (techos persistentes en código, no solo env vars):
- MAX_COST_PER_CALL_USD = 0.05
- MAX_CALLS_PER_DAY = 5

Estos valores viven en memoria de proceso por defecto; load_from_env()
permite sobreescribirlos vía variables de entorno para pruebas locales,
sin nunca requerir ninguna credencial real.
"""

from __future__ import annotations

import os
from typing import Optional
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# =============================================================================
# KILL-SWITCHES (valores por defecto SEGUROS para demo)
# =============================================================================

PILOTO_ACTIVO: bool = False
DELIVERY_MODE: str = "mock"
REAL_DELIVERY_ENABLED: bool = False
CLAUDE_DRAFTING_ENABLED: bool = False
REAL_LLM_SPEND_AUTHORIZED: bool = False

# Cost Guard — techos persistentes en código
MAX_COST_PER_CALL_USD: float = 0.05
MAX_CALLS_PER_DAY: int = 5

_VALID_DELIVERY_MODES = {"mock"}  # "real" deliberadamente NO incluido


def load_from_env() -> None:
    """Permite overridear los flags vía variables de entorno, solo
    para pruebas locales. Nunca lee ni requiere ninguna credencial real.
    """
    global PILOTO_ACTIVO, DELIVERY_MODE, REAL_DELIVERY_ENABLED, CLAUDE_DRAFTING_ENABLED
    global REAL_LLM_SPEND_AUTHORIZED, MAX_COST_PER_CALL_USD, MAX_CALLS_PER_DAY

    env_activo = os.environ.get("PILOTO_ACTIVO")
    if env_activo is not None:
        PILOTO_ACTIVO = env_activo.strip().lower() == "true"

    env_mode = os.environ.get("DELIVERY_MODE")
    if env_mode is not None:
        DELIVERY_MODE = env_mode.strip().lower()

    env_real = os.environ.get("REAL_DELIVERY_ENABLED")
    if env_real is not None:
        REAL_DELIVERY_ENABLED = env_real.strip().lower() == "true"

    env_claude = os.environ.get("CLAUDE_DRAFTING_ENABLED")
    if env_claude is not None:
        CLAUDE_DRAFTING_ENABLED = env_claude.strip().lower() == "true"

    env_spend = os.environ.get("REAL_LLM_SPEND_AUTHORIZED")
    if env_spend is not None:
        REAL_LLM_SPEND_AUTHORIZED = env_spend.strip().lower() == "true"

    env_max_cost = os.environ.get("MAX_COST_PER_CALL_USD")
    if env_max_cost is not None:
        MAX_COST_PER_CALL_USD = float(env_max_cost.strip())

    env_max_calls = os.environ.get("MAX_CALLS_PER_DAY")
    if env_max_calls is not None:
        MAX_CALLS_PER_DAY = int(env_max_calls.strip())


def assert_delivery_mode_is_safe() -> None:
    """Se llama SIEMPRE antes de cualquier intento de entrega. Si alguna
    vez DELIVERY_MODE fuera distinto de 'mock' (nunca debería serlo en
    esta fase), esto detiene la ejecución en vez de permitir un envío
    real accidental.
    """
    if DELIVERY_MODE not in _VALID_DELIVERY_MODES:
        raise NotImplementedError(
            f"DELIVERY_MODE={DELIVERY_MODE!r} no está implementado en esta "
            f"fase — el único modo real es 'mock'. Esto NUNCA debe "
            f"interpretarse como 'activa el modo real' sin escribir código "
            f"nuevo explícito en una fase posterior."
        )


def assert_real_delivery_is_disabled() -> None:
    """Barrera de 'no autonomía'. Se llama desde
    delivery.send_via_real_zernio_delivery(). SIEMPRE levanta
    NotImplementedError en esta fase, con o sin REAL_DELIVERY_ENABLED,
    porque no existe ningún RealZernioDeliveryAdapter todavía (prohibido
    construirlo en esta fase). El mensaje distingue los dos casos solo
    para que el log/la excepción sea clara sobre POR QUÉ se bloquea.
    """
    if REAL_DELIVERY_ENABLED:
        raise NotImplementedError(
            "REAL_DELIVERY_ENABLED=true, pero RealZernioDeliveryAdapter no "
            "existe en esta fase. Activar este flag nunca habilita un envío "
            "real por sí solo; se requeriría escribir código nuevo explícito "
            "en una fase futura autorizada, exactamente igual que DELIVERY_MODE."
        )
    raise NotImplementedError(
        "REAL_DELIVERY_ENABLED=false (valor por defecto) — ningún envío "
        "real a Zernio es posible en esta fase, incluso con "
        "PILOTO_ACTIVO=true."
    )


def validar_kill_switches() -> tuple[bool, str]:
    """Verifica que todos los kill-switches estén en estado seguro (demo)."""
    if PILOTO_ACTIVO:
        return False, "PILOTO_ACTIVO debe ser False en demo"
    if DELIVERY_MODE != "mock":
        return False, f"DELIVERY_MODE debe ser 'mock', es '{DELIVERY_MODE}'"
    if REAL_DELIVERY_ENABLED:
        return False, "REAL_DELIVERY_ENABLED debe ser False en demo"
    return True, "Todos los kill-switches en estado seguro (demo)"


# Cargar overrides de entorno al importar (solo para pruebas locales)
load_from_env()