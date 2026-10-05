"""
Prototipo aislado de la Capa de Diversificación — NO conectado al pipeline
oficial (`pipeline.py`), NO conectado a `cmd_scorear`, NO escribe ningún
dataset. Lee `empresas_scored.parquet` (solo lectura), ejecuta
`construir_ranking_diversificado` para varios tamaños de Top N y genera el
reporte comparativo `03_RESULTADOS/prototipo_capa_diversificacion.md`.

Ejecutar: `python -m sales_intel.diversificacion.prototipo_diversificacion`
(con el .venv del proyecto activo).
"""

from __future__ import annotations

import pandas as pd

from sales_intel.diversificacion.capa_diversificacion import (
    ConfiguracionDiversificacion,
    construir_ranking_diversificado,
)
from sales_intel.utils.config import RESULTADOS_DIR, SCORING_DIR

ENTRADA_PARQUET = SCORING_DIR / "empresas_scored.parquet"
SALIDA_REPORTE = RESULTADOS_DIR / "prototipo_capa_diversificacion.md"

TOPS = [100, 500, 1000, 5000]

# Estas dos categorías se citan por NOMBRE únicamente aquí, en el script de
# REPORTE — nunca dentro de capa_diversificacion.py (que es 100% genérico).
# Se citan porque son las que motivaron el diagnóstico previo, no porque el
# mecanismo las trate distinto de cualquier otro sector/municipio.
SECTOR_DE_INTERES = "HORECA"
MUNICIPIO_DE_INTERES = "PEREIRA"


def _cargar_universo() -> pd.DataFrame:
    df = pd.read_parquet(ENTRADA_PARQUET)
    universo = df[df["estado_exclusion"] == "SIN_COINCIDENCIA"].copy()
    return universo


def _ranking_puro(universo: pd.DataFrame, n: int) -> pd.DataFrame:
    return universo.sort_values(
        ["score_prioridad_comercial", "entidad_dedup_id"], ascending=[False, True], kind="mergesort"
    ).head(n)


def _mapa_posicion_ranking_puro(universo: pd.DataFrame) -> dict:
    """entidad_dedup_id -> posición (1-indexada) en el ranking puro completo
    del universo (mismo criterio de orden/desempate que capa_diversificacion)."""
    ordenado = universo.sort_values(
        ["score_prioridad_comercial", "entidad_dedup_id"], ascending=[False, True], kind="mergesort"
    ).reset_index(drop=True)
    return dict(zip(ordenado["entidad_dedup_id"], ordenado.index + 1))


def ejecutar_prototipo() -> dict:
    universo = _cargar_universo()
    assert len(universo) == 376_731, f"universo SIN_COINCIDENCIA inesperado: {len(universo)}"
    posicion_puro_por_id = _mapa_posicion_ranking_puro(universo)

    resultados_por_n = {}
    for n in TOPS:
        puro = _ranking_puro(universo, n)
        salida = construir_ranking_diversificado(universo, n)
        div = salida["top_n"]
        stats = salida["stats"]

        from sales_intel.diversificacion.capa_diversificacion import bucket_sector, categoria_municipio

        sector_puro = puro["sector_vertical"].apply(bucket_sector)
        sector_div = div["sector"]
        muni_puro = puro["municipio_nombre_normalizado"].apply(categoria_municipio)
        muni_div = div["municipio"]

        resultados_por_n[n] = {
            "puro_df": puro,
            "div_df": div,
            "stats": stats,
            "sector_puro_counts": sector_puro.value_counts(),
            "sector_div_counts": sector_div.value_counts(),
            "muni_puro_counts": muni_puro.value_counts(),
            "muni_div_counts": muni_div.value_counts(),
            "score_puro": puro["score_prioridad_comercial"],
            "score_div": div["score_base"],
        }

    return {"universo": universo, "resultados": resultados_por_n, "posicion_puro_por_id": posicion_puro_por_id}


def _fmt_pct(n, total):
    return f"{n} ({n/total*100:.1f}%)" if total else f"{n} (0.0%)"


def generar_reporte(resultado: dict) -> str:
    universo = resultado["universo"]
    resultados = resultado["resultados"]
    posicion_puro_por_id = resultado["posicion_puro_por_id"]

    lineas = []
    lineas.append("# Prototipo de la Capa de Diversificación — resultados de ejecución")
    lineas.append("**Fecha:** 2026-09-01")
    lineas.append(
        "**Estado:** PROTOTIPO AISLADO. No conectado a `pipeline.py` ni a `cmd_scorear`. "
        "No se generó ningún ranking comercial definitivo. No se modificó "
        "`score_prioridad_comercial` ni ningún dataset."
    )
    lineas.append("")
    lineas.append(
        "**Recordatorio de alcance:** el mecanismo implementado es exactamente el "
        "descrito en `03_RESULTADOS/especificacion_capa_diversificacion.md`, sobre "
        "`empresas_scored.parquet` (solo lectura), filtrado a "
        "`estado_exclusion == SIN_COINCIDENCIA` (376,731 entidades). "
        "`CANDIDATO_AMBIGUO` y las `EXCLUSION_*` quedan fuera del universo, igual "
        "que en el score."
    )
    lineas.append("")
    lineas.append("## 1. Configuración utilizada")
    cfg = ConfiguracionDiversificacion()
    lineas.append("")
    lineas.append("| Parámetro | Valor |")
    lineas.append("|---|---|")
    lineas.append(f"| k (multiplicador de sobrerrepresentación) | {cfg.k} |")
    lineas.append(f"| margen a tope_duro | +{cfg.margen_tope_duro:.0%} |")
    lineas.append(f"| Sector — piso/techo activación, techo tope_duro | {cfg.params_sector['piso_activacion']:.0%} / {cfg.params_sector['techo_activacion']:.0%} / {cfg.params_sector['techo_tope_duro']:.0%} |")
    lineas.append(f"| Municipio — piso/techo activación, techo tope_duro | {cfg.params_municipio['piso_activacion']:.0%} / {cfg.params_municipio['techo_activacion']:.0%} / {cfg.params_municipio['techo_tope_duro']:.0%} |")
    lineas.append(f"| Piso de calidad absoluto | score ≥ {cfg.piso_score_absoluto:.0f} |")
    lineas.append(f"| Piso de calidad relativo | score ≥ {cfg.piso_score_relativo:.0%} del candidato desplazado |")
    lineas.append(f"| Ventana de búsqueda W | max({cfg.ventana_minima}, {cfg.ventana_fraccion_n:.0%} de N) |")
    lineas.append("")

    for n in TOPS:
        r = resultados[n]
        s = r["stats"]
        act_sector = s["umbrales_sector"].get(SECTOR_DE_INTERES)
        act_muni = s["umbrales_municipio"].get(MUNICIPIO_DE_INTERES)

        lineas.append(f"## Top {n}")
        lineas.append("")
        lineas.append("### Configuración derivada para este N")
        lineas.append(f"- Ventana W = {s['ventana_w']}")
        if act_sector:
            lineas.append(f"- Umbral/tope duro calculado para sector '{SECTOR_DE_INTERES}': activación={act_sector[0]:.1%}, tope_duro={act_sector[1]:.1%} (participación base p_x={s['p_sector'].get(SECTOR_DE_INTERES,0):.2%})")
        if act_muni:
            lineas.append(f"- Umbral/tope duro calculado para municipio '{MUNICIPIO_DE_INTERES}': activación={act_muni[0]:.1%}, tope_duro={act_muni[1]:.1%} (participación base p_x={s['p_municipio'].get(MUNICIPIO_DE_INTERES,0):.2%})")
        lineas.append("")

        lineas.append("### Candidatos evaluados y reemplazos")
        lineas.append(f"- Candidatos evaluados en Fase 1: {s['n_evaluados_fase1']:,}")
        lineas.append(f"- Reemplazos ejecutados (diversificación exitosa): {s['n_reemplazos']:,}")
        n_tolerancia = n - s["n_reemplazos"] - s["n_proteccion_calidad"] - s["n_recuperados_fase2"]
        pct_intervenidas = (s["n_reemplazos"] + s["n_proteccion_calidad"] + s["n_recuperados_fase2"]) / s["n_final"] * 100 if s["n_final"] else 0
        lineas.append(f"- Admitidos por zona de tolerancia (sin intervención): {n_tolerancia:,} ({n_tolerancia/s['n_final']*100:.1f}%)")
        lineas.append(f"- % de posiciones intervenidas en total: {pct_intervenidas:.1f}%")
        lineas.append(f"- Candidatos que dispararon el umbral pero SIN reemplazo elegible (protección de calidad, se conservó el original): {s['n_proteccion_calidad']:,}")
        lineas.append(f"- Candidatos diferidos por tope duro: {s['n_diferidos_tope_duro']:,}")
        lineas.append(f"- Recuperados en Fase 2 (cierre): {s['n_recuperados_fase2']:,}")
        lineas.append(f"- Diferidos que nunca volvieron a entrar: {s['n_diferidos_nunca_recuperados']:,}")
        lineas.append(f"- Tamaño final del Top {n}: {s['n_final']:,} {'✅ (=N)' if s['n_final']==n else '⚠️ (<N, universo insuficiente)'}")
        lineas.append("")

        lineas.append("### Distribución de métodos de selección")
        metodo_counts = r["div_df"]["metodo_seleccion"].value_counts()
        lineas.append("")
        lineas.append("| Método | Cantidad | % |")
        lineas.append("|---|---:|---:|")
        for metodo, cnt in metodo_counts.items():
            lineas.append(f"| {metodo} | {cnt} | {cnt/len(r['div_df'])*100:.1f}% |")
        lineas.append("")

        lineas.append("### Composición sectorial — antes (puro) / después (diversificado)")
        lineas.append("")
        lineas.append("| Sector | Puro | Diversificado |")
        lineas.append("|---|---:|---:|")
        todos_sectores = sorted(set(r["sector_puro_counts"].index) | set(r["sector_div_counts"].index))
        for sec in todos_sectores:
            p = int(r["sector_puro_counts"].get(sec, 0))
            d = int(r["sector_div_counts"].get(sec, 0))
            lineas.append(f"| {sec} | {p} ({p/n*100:.1f}%) | {d} ({d/n*100:.1f}%) |")
        n_horeca_puro = int(r["sector_puro_counts"].get(SECTOR_DE_INTERES, 0))
        n_horeca_div = int(r["sector_div_counts"].get(SECTOR_DE_INTERES, 0))
        lineas.append("")
        lineas.append(f"**{SECTOR_DE_INTERES} antes/después: {n_horeca_puro} ({n_horeca_puro/n*100:.1f}%) → {n_horeca_div} ({n_horeca_div/n*100:.1f}%)**")
        lineas.append("")

        lineas.append("### Composición geográfica — antes (puro) / después (diversificado), top municipios")
        lineas.append("")
        lineas.append("| Municipio | Puro | Diversificado |")
        lineas.append("|---|---:|---:|")
        top_munis = sorted(set(r["muni_puro_counts"].head(8).index) | set(r["muni_div_counts"].head(8).index))
        for mu in top_munis:
            p = int(r["muni_puro_counts"].get(mu, 0))
            d = int(r["muni_div_counts"].get(mu, 0))
            lineas.append(f"| {mu} | {p} ({p/n*100:.1f}%) | {d} ({d/n*100:.1f}%) |")
        n_pereira_puro = int(r["muni_puro_counts"].get(MUNICIPIO_DE_INTERES, 0))
        n_pereira_div = int(r["muni_div_counts"].get(MUNICIPIO_DE_INTERES, 0))
        lineas.append("")
        lineas.append(f"**{MUNICIPIO_DE_INTERES} antes/después: {n_pereira_puro} ({n_pereira_puro/n*100:.1f}%) → {n_pereira_div} ({n_pereira_div/n*100:.1f}%)**")
        lineas.append("")

        sp, sd = r["score_puro"], r["score_div"]
        media_puro, media_div = sp.mean(), sd.mean()
        mediana_puro, mediana_div = sp.median(), sd.median()
        min_puro, min_div = sp.min(), sd.min()
        perdida_pct = (media_puro - media_div) / media_puro * 100 if media_puro else 0

        lineas.append("### Score — antes (puro) / después (diversificado)")
        lineas.append("")
        lineas.append("| Estadístico | Puro | Diversificado |")
        lineas.append("|---|---:|---:|")
        lineas.append(f"| Media | {media_puro:.3f} | {media_div:.3f} |")
        lineas.append(f"| Mediana | {mediana_puro:.3f} | {mediana_div:.3f} |")
        lineas.append(f"| Mínimo | {min_puro:.3f} | {min_div:.3f} |")
        lineas.append("")
        lineas.append(f"**Pérdida de score medio: −{media_puro-media_div:.3f} absoluto (−{perdida_pct:.2f}%)**")
        lineas.append("")

        lineas.append("### Ejemplos agregados (sin datos personales)")
        # Nota: el mismo W=50 y calentamiento=20 aplican para todos los N de
        # esta corrida (1% de N no supera 50 salvo para N>5,000), así que el
        # inicio del recorrido de Fase 1 es idéntico entre tamaños de Top N
        # -- se muestrean ejemplos repartidos (inicio/medio/fin de los
        # reemplazos de este Top N) para no repetir siempre los mismos.
        candidatos_div = r["div_df"][r["div_df"]["metodo_seleccion"] == "diversificacion"]
        if len(candidatos_div):
            posiciones_muestra = sorted(set([0, len(candidatos_div) // 2, len(candidatos_div) - 1]))
            ejemplos = candidatos_div.iloc[posiciones_muestra]
        else:
            ejemplos = candidatos_div
        if len(ejemplos):
            for _, ej in ejemplos.iterrows():
                pos_desplazado = posicion_puro_por_id.get(ej["candidato_desplazado"], "?")
                lineas.append(
                    f"- Posición final #{ej['posicion_ranking_diversificado']} (sector={ej['sector']}, "
                    f"municipio={ej['municipio']}): reemplazó al candidato que ocupaba la posición "
                    f"#{pos_desplazado} del ranking puro. Score propio {ej['score_base']:.2f} vs. "
                    f"desplazado {ej['score_candidato_desplazado']:.2f} (diferencia {ej['diferencia_score']:.2f}). "
                    f"Motivo: {ej['motivo_diversificacion']}"
                )
        else:
            lineas.append("- No hubo reemplazos exitosos en este Top N.")
        lineas.append("")
        lineas.append("---")
        lineas.append("")

    return "\n".join(lineas)


if __name__ == "__main__":
    resultado = ejecutar_prototipo()
    reporte = generar_reporte(resultado)
    SALIDA_REPORTE.write_text(reporte, encoding="utf-8")
    print(f"Reporte escrito en: {SALIDA_REPORTE}")
    for n in TOPS:
        s = resultado["resultados"][n]["stats"]
        print(f"Top {n}: final={s['n_final']} reemplazos={s['n_reemplazos']} proteccion_calidad={s['n_proteccion_calidad']}")
