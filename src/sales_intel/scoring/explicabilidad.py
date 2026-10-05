"""
Generación de la explicación legible de un Score de Prioridad Comercial
(requisito 14: cada prospecto debe poder explicar por qué recibió su
puntuación).

Puro stdlib. Este módulo formatea un desglose ya calculado — no calcula el
score en sí (eso es responsabilidad de motor_scoring.py). Se puede usar y
probar hoy con datos de ejemplo, sin depender de que el scoring real exista.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContribucionVariable:
    """Una línea del desglose: qué variable, qué valor tenía el registro,
    y cuánto aportó al score final."""

    variable_id: str
    variable_nombre: str
    valor_observado: str
    contribucion: float
    nivel_confianza: str


def generar_explicacion_texto(
    prioridad: str,
    score_total: float,
    contribuciones: list[ContribucionVariable],
) -> str:
    """Genera un texto legible tipo:

    'Prioridad ALTA (82/100) — Sector Gastronomía (alto encaje, +25), 8
    empleados (pequeña empresa, +15), matrícula activa desde 2019 (+10),
    contacto completo (email+teléfono, +10), no aparece en pipeline Client.'

    Ordena las contribuciones de mayor a menor para que las señales más
    determinantes aparezcan primero. Incluye siempre el recordatorio de que
    es un índice de priorización, no una predicción financiera, en
    `generar_explicacion_estructurada` (ver más abajo) para que quede en el
    dato, no solo en la documentación.
    """
    ordenadas = sorted(contribuciones, key=lambda c: c.contribucion, reverse=True)
    partes = [f"{c.variable_nombre} ({c.valor_observado}, {c.contribucion:+.0f})" for c in ordenadas]
    return f"Prioridad {prioridad.upper()} ({score_total:.0f}/100) — " + "; ".join(partes) + "."


def generar_explicacion_estructurada(
    prioridad: str,
    score_total: float,
    contribuciones: list[ContribucionVariable],
) -> dict:
    """Versión estructurada (para guardar en score_explicacion, columna JSON
    de la base maestra) equivalente al texto de generar_explicacion_texto."""
    return {
        "prioridad": prioridad,
        "score_total": score_total,
        "advertencia": (
            "Índice de priorización relativa basado en señales/proxies. "
            "NO es una predicción de TPV, facturación ni ingresos."
        ),
        "contribuciones": [
            {
                "variable_id": c.variable_id,
                "variable_nombre": c.variable_nombre,
                "valor_observado": c.valor_observado,
                "contribucion": c.contribucion,
                "nivel_confianza": c.nivel_confianza,
            }
            for c in sorted(contribuciones, key=lambda c: c.contribucion, reverse=True)
        ],
    }
