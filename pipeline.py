#!/usr/bin/env python3
"""
Orquestador CLI del pipeline SALES_INTELLIGENCE V1.

ESTADO ACTUAL: esqueleto. Ninguna fase se ejecuta encadenada automáticamente
— cada subcomando es independiente y debe invocarse explícitamente. La
mayoría de las fases todavía dependen de paquetes no instalados (pandas,
openpyxl, pyarrow, rapidfuzz — ver requirements.txt) y responden con un
mensaje claro en vez de fallar con una traza críptica.

Uso previsto (cuando se apruebe pasar a ejecución):
    python pipeline.py ingesta --solo-pequenas
    python pipeline.py normalizar
    python pipeline.py deduplicar
    python pipeline.py enriquecer
    python pipeline.py excluir
    python pipeline.py scorear
    python pipeline.py diversificar --n 100   # integración controlada: no escribe archivo
    python pipeline.py reportar --top 25 --sector "Gastronomía y Hotelería"

Ningún subcomando abre nunca un archivo de 01_BASES_RAW en modo escritura.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permite ejecutar `python pipeline.py ...` sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

_DEPENDENCIAS_FALTANTES = {
    "ingesta": ["pandas", "openpyxl"],
    "normalizar": ["pandas", "unidecode"],
    "deduplicar": ["pandas", "rapidfuzz"],
    "enriquecer": ["pandas"],
    "excluir": ["pandas"],
    "scorear": ["pandas"],
    "diversificar": ["pandas"],
    "reportar": ["pandas"],
}


def _reportar_fase_no_disponible(fase: str) -> int:
    faltan = ", ".join(_DEPENDENCIAS_FALTANTES.get(fase, []))
    print(
        f"[sales_intel] La fase '{fase}' todavía no está implementada / requiere "
        f"instalar: {faltan}.\n"
        f"Ver 04_SISTEMA/docs/GUIA_EJECUCION.md antes de continuar."
    )
    return 1


def cmd_catalogo(args: argparse.Namespace) -> int:
    """Único subcomando que ya funciona hoy (solo stdlib + PyYAML): muestra
    el catálogo declarado en fuentes.yaml. NO calcula hashes por defecto
    (sería leer los 50 archivos, incluido el de 1.4 GB) — usar --con-hash
    explícitamente y con criterio si se necesita verificar integridad.
    """
    from sales_intel.utils.config import listar_fuentes

    fuentes = listar_fuentes(excluir_duplicados=not args.incluir_duplicados)
    print(f"{'ID':<45} {'CATEGORIA':<25} {'REGISTROS':>10}  ARCHIVO")
    for f in fuentes:
        print(f"{f.id:<45} {f.categoria:<25} {f.registros_aprox:>10,}  {f.archivo}")
    print(f"\nTotal fuentes listadas: {len(fuentes)}")
    return 0


def cmd_ingesta(args: argparse.Namespace) -> int:
    if args.solo_nacional:
        print("[sales_intel] La ingesta del archivo nacional (1.4GB) no está implementada "
              "todavía a propósito — ver 04_SISTEMA/docs/DECISIONES.md.")
        return 1
    if not args.solo_pequenas:
        print("[sales_intel] Especifica --solo-pequenas explícitamente (no hay un modo "
              "'ingerir todo' en V1 — el archivo nacional se trata siempre aparte).")
        return 1

    try:
        from sales_intel.ingesta.ejecutar_ingesta import ejecutar_ingesta_pequenas
    except ImportError as e:
        print(f"[sales_intel] Falta una dependencia para la ingesta: {e}")
        return _reportar_fase_no_disponible("ingesta")

    resultado = ejecutar_ingesta_pequenas()
    resumen = resultado["resumen"]
    print("\n=== RESUMEN INGESTA (fuentes pequeñas/medianas) ===")
    for k, v in resumen.items():
        print(f"{k}: {v}")
    print(f"Catálogo actualizado en: {resultado['catalogo']}")
    return 0 if resumen["errores"] == 0 else 1


def cmd_normalizar(args: argparse.Namespace) -> int:
    try:
        from sales_intel.normalizacion.ejecutar_normalizacion import ejecutar_normalizacion
    except ImportError as e:
        print(f"[sales_intel] Falta una dependencia para la normalización: {e}")
        return _reportar_fase_no_disponible("normalizar")

    resultado = ejecutar_normalizacion()
    print(f"\nFuentes normalizadas: {len(resultado['fuentes_normalizadas'])}")
    print(f"Fuentes internas excluidas (CRM/HUBS): {len(resultado['fuentes_internas_excluidas'])}")
    print(f"Registros combinados: {len(resultado['combinado']):,}")
    print(f"Parquet: {resultado['destino_parquet']}")
    print(f"Reporte de calidad: {resultado['destino_reporte']}")
    return 0


def cmd_deduplicar(args: argparse.Namespace) -> int:
    try:
        from sales_intel.deduplicacion.ejecutar_deduplicacion import ejecutar_deduplicacion
    except ImportError as e:
        print(f"[sales_intel] Falta una dependencia para la deduplicación: {e}")
        return _reportar_fase_no_disponible("deduplicar")

    resultado = ejecutar_deduplicacion()
    s = resultado["stats"]
    print(f"\nRegistros de entrada: {s['registros_entrada']:,}")
    print(f"Entidades de salida:  {s['registros_salida']:,}")
    print(f"Grupos por NIT: {s['n_grupos_nit']:,} ({s['n_registros_nit']:,} registros)")
    print(f"Grupos por matrícula+cámara: {s['n_grupos_matricula']:,} ({s['n_registros_matricula']:,} registros)")
    print(f"Candidatos razón_social+municipio: {s['n_grupos_rs_mun']:,} ({s['n_registros_rs_mun']:,} registros)")
    print(f"Candidatos fuzzy: {s['n_grupos_fuzzy']:,} ({s['n_registros_fuzzy']:,} registros)")
    print(f"Maestro: {resultado['destino_maestro']}")
    print(f"Grupos:  {resultado['destino_grupos']}")
    return 0


def cmd_enriquecer(args: argparse.Namespace) -> int:
    return _reportar_fase_no_disponible("enriquecer")


def cmd_excluir(args: argparse.Namespace) -> int:
    try:
        from sales_intel.exclusion.ejecutar_exclusion import ejecutar_exclusion
    except ImportError as e:
        print(f"[sales_intel] Falta una dependencia para la exclusión: {e}")
        return _reportar_fase_no_disponible("excluir")

    resultado = ejecutar_exclusion()
    print(f"\nEntidades de entrada: {resultado['n_entrada']:,}")
    print(resultado["maestro"]["estado_exclusion"].value_counts())
    print(f"Maestro: {resultado['destino_maestro']}")
    print(f"Matches: {resultado['destino_matches']}")
    return 0


def cmd_scorear(args: argparse.Namespace) -> int:
    try:
        from sales_intel.scoring.aplicar_score import aplicar_score
        from sales_intel.scoring.motor_scoring import PesosNoDefinidosError
    except ImportError as e:
        print(f"[sales_intel] Falta una dependencia para el scoring: {e}")
        return _reportar_fase_no_disponible("scorear")

    try:
        resultado = aplicar_score()
    except PesosNoDefinidosError as e:
        print(f"[sales_intel] {e}")
        return 1

    s = resultado["stats"]
    print(f"\nEntrada:  {s['n_entrada']:,}")
    print(f"Salida:   {s['n_salida']:,}")
    print(f"Scoreados (score_prioridad_comercial no nulo): {s['n_scoreados']:,}")
    print(f"Sin score (fuera del universo priorizable): {s['n_sin_score_por_universo']:,}")
    print(f"Parquet: {s['destino']}")
    return 0


def cmd_diversificar(args: argparse.Namespace) -> int:
    """Fase posterior al scoring: Top N diversificado (M=22, taxonomía V2,
    desempate F) reutilizando `capa_diversificacion.construir_ranking_diversificado`
    a través de `ejecutar_diversificacion`. INTEGRACIÓN CONTROLADA: no
    escribe ningún archivo -- el resultado queda solo en memoria de este
    proceso. Exportar un Top N definitivo a `03_RESULTADOS/top_prospectos/`
    es un paso productivo separado, todavía no autorizado."""
    try:
        from sales_intel.diversificacion.ejecutar_diversificacion import ejecutar_diversificacion
    except ImportError as e:
        print(f"[sales_intel] Falta una dependencia para la diversificación: {e}")
        return _reportar_fase_no_disponible("diversificar")

    resultado = ejecutar_diversificacion(args.n)
    s = resultado["stats"]
    u = s["universo"]
    print(f"\nUniverso total: {u['n_total_dataset']:,}")
    print(f"Elegibles (SIN_COINCIDENCIA): {u['n_elegibles']:,}")
    print(f"Candidato ambiguo (fuera del ranking): {u['n_candidato_ambiguo']:,}")
    print(f"Excluidos: {u['n_excluidos']:,}")
    print(f"\nTop {args.n} construido (M={resultado['config'].m_suavizado}):")
    print(f"  n_final: {s['n_final']}")
    print(f"  Reemplazos exitosos: {s['n_reemplazos']}")
    print(f"  Protegidos (sin reemplazo válido): {s['n_proteccion_calidad']}")
    print(f"  Diferidos por tope duro: {s['n_diferidos_tope_duro']}")
    print(f"  Recuperados en Fase 2: {s['n_recuperados_fase2']}")
    print(
        "\n[sales_intel] NOTA: este comando NO escribe ningún archivo todavía -- "
        "resultado solo en memoria. La exportación a 03_RESULTADOS/top_prospectos "
        "es un paso productivo separado, pendiente de autorización explícita."
    )
    return 0


def cmd_reportar(args: argparse.Namespace) -> int:
    return _reportar_fase_no_disponible("reportar")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Orquestador del pipeline SALES_INTELLIGENCE V1 (esqueleto).",
    )
    sub = parser.add_subparsers(dest="fase", required=True)

    p_cat = sub.add_parser("catalogo", help="Muestra el catálogo de fuentes.yaml (funciona hoy).")
    p_cat.add_argument("--incluir-duplicados", action="store_true", help="Incluye copias marcadas como duplicado_exacto.")
    p_cat.set_defaults(func=cmd_catalogo)

    p_ing = sub.add_parser("ingesta", help="Fase 1: lectura de fuentes crudas.")
    p_ing.add_argument("--solo-pequenas", action="store_true", help="Excluye el archivo nacional de 1.4GB.")
    p_ing.add_argument("--solo-nacional", action="store_true", help="Procesa únicamente el archivo nacional de 1.4GB.")
    p_ing.set_defaults(func=cmd_ingesta)

    sub.add_parser("normalizar", help="Fase 2: unificación de esquema de columnas.").set_defaults(func=cmd_normalizar)
    sub.add_parser("deduplicar", help="Fase 3: base maestra deduplicada.").set_defaults(func=cmd_deduplicar)
    sub.add_parser("enriquecer", help="Fase 4: sector Client, tamaño, confianza.").set_defaults(func=cmd_enriquecer)
    sub.add_parser("excluir", help="Fase 5: flag de pipeline interno Client.").set_defaults(func=cmd_excluir)
    sub.add_parser("scorear", help="Fase 6: Score de Prioridad Comercial.").set_defaults(func=cmd_scorear)

    p_div = sub.add_parser(
        "diversificar",
        help="Fase posterior al scoring: Top N diversificado (M=22, taxonomía V2, desempate F). "
             "Integración controlada: NO escribe ningún archivo todavía.",
    )
    p_div.add_argument("--n", type=int, required=True, help="Tamaño del Top N a construir (ej. 100, 500, 1000, 5000).")
    p_div.set_defaults(func=cmd_diversificar)

    p_rep = sub.add_parser("reportar", help="Fase 7: reportes y TOP N.")
    p_rep.add_argument("--top", type=int, default=25, choices=[10, 25, 50, 100])
    p_rep.add_argument("--ciudad")
    p_rep.add_argument("--departamento")
    p_rep.add_argument("--sector")
    p_rep.add_argument("--actividad-economica")
    p_rep.add_argument("--tamano")
    p_rep.add_argument("--contacto-disponible", action="store_true")
    p_rep.add_argument("--score-minimo", type=float)
    p_rep.add_argument("--prioridad", choices=["Alta", "Media", "Baja"])
    p_rep.set_defaults(func=cmd_reportar)

    return parser


def main() -> int:
    parser = construir_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
