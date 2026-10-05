"""
Aplica el Score de Prioridad Comercial (motor_scoring.calcular_scores) sobre
dataset_preparado_scoring.parquet y escribe empresas_scored.parquet.

Alcance explícito de este módulo (turno del 2026-09-01): ÚNICAMENTE el
cálculo del score y sus columnas de trazabilidad. NO genera Top N, NO hace
análisis de distribución/sectorial/geográfico ni de sensibilidad de pesos.

dataset_preparado_scoring.parquet se trata como entrada de SOLO LECTURA —
nunca se modifica. La salida es un archivo nuevo.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from sales_intel.scoring.motor_scoring import calcular_scores
from sales_intel.utils.config import SCORING_DIR, assert_no_escritura_en_raw

ENTRADA_PARQUET = SCORING_DIR / "dataset_preparado_scoring.parquet"
SALIDA_PARQUET = SCORING_DIR / "empresas_scored.parquet"


def aplicar_score(
    entrada: "str | None" = None,
    salida: "str | None" = None,
) -> dict:
    ruta_entrada = ENTRADA_PARQUET if entrada is None else entrada
    ruta_salida = SALIDA_PARQUET if salida is None else salida
    assert_no_escritura_en_raw(ruta_salida)

    df = pd.read_parquet(ruta_entrada)
    n_entrada = len(df)

    columnas_score = calcular_scores(df)
    out = pd.concat([df, columnas_score], axis=1)
    out["fecha_calculo_score_utc"] = datetime.now(timezone.utc).isoformat()

    assert len(out) == n_entrada, "El cálculo de score no debe alterar el número de filas."

    out.to_parquet(ruta_salida, index=False)

    stats = {
        "n_entrada": n_entrada,
        "n_salida": len(out),
        "por_estado_exclusion": df["estado_exclusion"].value_counts(dropna=False).to_dict(),
        "n_scoreados": int(columnas_score["score_prioridad_comercial"].notna().sum()),
        "n_sin_score_por_universo": int(columnas_score["score_prioridad_comercial"].isna().sum()),
        "destino": str(ruta_salida),
    }
    return {"df": out, "stats": stats}


if __name__ == "__main__":
    resultado = aplicar_score()
    s = resultado["stats"]
    print(f"Entrada:  {s['n_entrada']:,}")
    print(f"Salida:   {s['n_salida']:,}")
    print(f"Por estado_exclusion: {s['por_estado_exclusion']}")
    print(f"Scoreados (score_prioridad_comercial no nulo): {s['n_scoreados']:,}")
    print(f"Sin score (fuera del universo priorizable): {s['n_sin_score_por_universo']:,}")
    print(f"Escrito en: {s['destino']}")
