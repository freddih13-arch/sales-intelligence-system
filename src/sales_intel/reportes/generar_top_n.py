"""
Generación de listas TOP N de prospectos (requisitos 12 y 13).
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass
class FiltrosProspectos:
    """Todos los filtros son opcionales y combinables (requisito 12)."""

    ciudad: str | None = None
    departamento: str | None = None
    sector: str | None = None
    actividad_economica: str | None = None
    tamano: str | None = None
    contacto_disponible: bool | None = None
    score_minimo: float | None = None
    prioridad: str | None = None
    incluir_en_pipeline_bold: bool = False  # False = excluir por defecto (requisito 10)

    def activos(self) -> dict:
        """Solo los filtros que el usuario efectivamente pidió (no-None)."""
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None}


def generar_top_n(n: int, filtros: FiltrosProspectos, base_scored=None):
    """Filtra, ordena por score_prioridad_comercial descendente, corta a N,
    y exporta a 03_RESULTADOS/top_prospectos/top{N}_<filtros>_<fecha>.csv con
    la explicación legible de cada prospecto incluida.

    NO IMPLEMENTADO TODAVÍA — requiere pandas y que exista
    02_PROCESADAS/06_scoring/empresas_scored.parquet (es decir, requiere que
    ya se haya corrido y aprobado la fase de scoring).
    """
    raise NotImplementedError(
        "generar_top_n requiere pandas y la fase de scoring completada. "
        "Ver 04_SISTEMA/docs/GUIA_EJECUCION.md."
    )
