"""
Orquesta la ejecución de la Capa de Diversificación
(`capa_diversificacion.construir_ranking_diversificado`) como fase de
pipeline posterior al scoring.

Lee `empresas_scored.parquet` (solo lectura — NUNCA se modifica ni se
recalcula ningún score), filtra el universo elegible exactamente como exige
`especificacion_capa_diversificacion.md` (`estado_exclusion ==
SIN_COINCIDENCIA`; `CANDIDATO_AMBIGUO` queda separado para revisión, fuera
del ranking principal; `EXCLUSION_ALTA`/`EXCLUSION_MEDIA` quedan excluidos)
y construye un Top N reutilizando `construir_ranking_diversificado` tal
cual — este módulo NO reimplementa ninguna lógica de diversificación, NO
calcula ni toca el score, y NO conoce los pesos ni la fórmula de scoring.

INTEGRACIÓN CONTROLADA (turno 2026-09-02) — DELIBERADAMENTE NO ESCRIBE
NINGÚN ARCHIVO todavía: a diferencia de las demás fases de
`04_SISTEMA/pipeline.py` (que persisten su resultado en un parquet para la
fase siguiente), esta es una integración de preparación/prueba. La
exportación de un Top N definitivo a `03_RESULTADOS/top_prospectos/` es un
paso productivo separado, pendiente de autorización explícita — no
implementado aquí a propósito.
"""

from __future__ import annotations

import pandas as pd

from sales_intel.diversificacion.capa_diversificacion import (
    ConfiguracionDiversificacion,
    construir_ranking_diversificado,
)
from sales_intel.utils.config import SCORING_DIR

ENTRADA_PARQUET = SCORING_DIR / "empresas_scored.parquet"

# Único estado que compone el universo elegible de esta capa (spec §3, §5;
# ver también capa_diversificacion.ESTADOS_UNIVERSO_VALIDOS, la misma
# fuente de verdad). CANDIDATO_AMBIGUO se calcula aparte solo para
# reportarlo en las estadísticas de universo -- nunca entra al ranking.
ESTADOS_ELEGIBLES = {"SIN_COINCIDENCIA"}
ESTADO_AMBIGUO = "CANDIDATO_AMBIGUO"


def ejecutar_diversificacion(
    n: int,
    entrada: "str | None" = None,
    config: ConfiguracionDiversificacion | None = None,
) -> dict:
    """Lee `empresas_scored.parquet` (o `entrada`, para pruebas — siempre
    solo lectura), filtra al universo elegible (`SIN_COINCIDENCIA`) y
    construye un Top `n` diversificado reutilizando
    `construir_ranking_diversificado` con la configuración aprobada por
    defecto (M=22, taxonomía V2, desempate F, W, pisos de calidad —
    `ConfiguracionDiversificacion()` si `config` no se especifica).

    Devuelve el mismo contrato que `construir_ranking_diversificado`
    (`{'top_n', 'stats', 'config'}`), con una clave adicional
    `stats['universo']` con el desglose por `estado_exclusion`. NO escribe
    ningún archivo — ver docstring del módulo.
    """
    ruta_entrada = ENTRADA_PARQUET if entrada is None else entrada
    df = pd.read_parquet(ruta_entrada)
    n_total = len(df)

    universo = df[df["estado_exclusion"].isin(ESTADOS_ELEGIBLES)].copy()
    candidato_ambiguo = df[df["estado_exclusion"] == ESTADO_AMBIGUO]
    excluidos = df[~df["estado_exclusion"].isin(ESTADOS_ELEGIBLES | {ESTADO_AMBIGUO})]

    resultado = construir_ranking_diversificado(universo, n, config=config)

    resultado["stats"]["universo"] = {
        "n_total_dataset": n_total,
        "n_elegibles": len(universo),
        "n_candidato_ambiguo": len(candidato_ambiguo),
        "n_excluidos": len(excluidos),
        "entrada": str(ruta_entrada),
    }
    return resultado


if __name__ == "__main__":
    import sys

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    resultado = ejecutar_diversificacion(n)
    s = resultado["stats"]
    u = s["universo"]
    print(f"Universo total: {u['n_total_dataset']:,}")
    print(f"Elegibles (SIN_COINCIDENCIA): {u['n_elegibles']:,}")
    print(f"Candidato ambiguo (fuera del ranking): {u['n_candidato_ambiguo']:,}")
    print(f"Excluidos: {u['n_excluidos']:,}")
    print(f"\nTop {n} construido (M={resultado['config'].m_suavizado}):")
    print(f"  n_final: {s['n_final']}")
    print(f"  Reemplazos exitosos: {s['n_reemplazos']}")
    print(f"  Protegidos (sin reemplazo válido): {s['n_proteccion_calidad']}")
    print(f"  Diferidos por tope duro: {s['n_diferidos_tope_duro']}")
    print(f"  Recuperados en Fase 2: {s['n_recuperados_fase2']}")
    print("\n[sales_intel] Este comando NO escribe ningún archivo -- resultado "
          "solo en memoria. La exportación a 03_RESULTADOS/top_prospectos es "
          "un paso productivo separado, pendiente de autorización explícita.")
