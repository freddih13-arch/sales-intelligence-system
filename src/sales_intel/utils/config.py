"""
Rutas del proyecto y carga de archivos de configuración YAML.

Este módulo SOLO define rutas y lee configuración — no toca datos de
01_BASES_RAW ni escribe nada. Es seguro de importar y de ejecutar en
cualquier momento.

Dependencias: únicamente PyYAML (ya disponible en el entorno) y stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------

# 04_SISTEMA/src/sales_intel/utils/config.py -> subir 4 niveles hasta la raíz
# del proyecto (SALES_INTELLIGENCE/).
# En la demo pública, la estructura es plana: config/ está en la raíz del repo.
_THIS_FILE = Path(__file__).resolve()

# Detectar si estamos en la estructura original (SALES_INTELLIGENCE/04_SISTEMA/...)
# o en la demo pública (client-sales-intelligence-public/).
# En la demo: .../src/sales_intel/utils/config.py -> parents[3] = repo root (tiene config/)
# En original: .../src/sales_intel/utils/config.py -> parents[4] = repo root (tiene 04_SISTEMA/)
if (_THIS_FILE.parents[3] / "config").exists():
    # Estructura demo: .../src/sales_intel/utils/config.py -> parents[3] = repo root
    PROJECT_ROOT = _THIS_FILE.parents[3]
    CONFIG_DIR = PROJECT_ROOT / "config"
    RAW_DIR = PROJECT_ROOT / "01_BASES_RAW"
    PROCESADAS_DIR = PROJECT_ROOT / "02_PROCESADAS"
    RESULTADOS_DIR = PROJECT_ROOT / "03_RESULTADOS"
    SISTEMA_DIR = PROJECT_ROOT
    DOCS_DIR = PROJECT_ROOT / "docs"
elif (_THIS_FILE.parents[4] / "04_SISTEMA" / "config").exists():
    # Estructura original
    PROJECT_ROOT = _THIS_FILE.parents[4]
    RAW_DIR = PROJECT_ROOT / "01_BASES_RAW"
    PROCESADAS_DIR = PROJECT_ROOT / "02_PROCESADAS"
    RESULTADOS_DIR = PROJECT_ROOT / "03_RESULTADOS"
    SISTEMA_DIR = PROJECT_ROOT / "04_SISTEMA"
    CONFIG_DIR = SISTEMA_DIR / "config"
    DOCS_DIR = SISTEMA_DIR / "docs"
else:
    # Fallback: asumir estructura demo
    PROJECT_ROOT = _THIS_FILE.parents[3]
    CONFIG_DIR = PROJECT_ROOT / "config"
    RAW_DIR = PROJECT_ROOT / "01_BASES_RAW"
    PROCESADAS_DIR = PROJECT_ROOT / "02_PROCESADAS"
    RESULTADOS_DIR = PROJECT_ROOT / "03_RESULTADOS"
    SISTEMA_DIR = PROJECT_ROOT
    DOCS_DIR = PROJECT_ROOT / "docs"

# Subcarpetas de 02_PROCESADAS, una por fase del pipeline.
CATALOGO_DIR = PROCESADAS_DIR / "00_catalogo"
INGESTA_DIR = PROCESADAS_DIR / "01_ingesta"
NORMALIZADO_DIR = PROCESADAS_DIR / "02_normalizado"
DEDUPLICADO_DIR = PROCESADAS_DIR / "03_deduplicado"
ENRIQUECIDO_DIR = PROCESADAS_DIR / "04_enriquecido"
EXCLUSION_DIR = PROCESADAS_DIR / "05_exclusion"
SCORING_DIR = PROCESADAS_DIR / "06_scoring"

REPORTES_DIR = RESULTADOS_DIR / "reportes"
TOP_PROSPECTOS_DIR = RESULTADOS_DIR / "top_prospectos"

FUENTES_YAML = CONFIG_DIR / "fuentes.yaml"
MAPEO_COLUMNAS_YAML = CONFIG_DIR / "mapeo_columnas.yaml"
MAPEO_CIIU_SECTOR_YAML = CONFIG_DIR / "mapeo_ciiu_sector.yaml"
SCORING_VARIABLES_YAML = CONFIG_DIR / "scoring_variables.yaml"


def assert_no_escritura_en_raw(path: Path) -> None:
    """Lanza un error si `path` cae dentro de 01_BASES_RAW.

    Se debe llamar antes de CUALQUIER apertura de archivo en modo escritura
    en todo el pipeline, como salvaguarda adicional a "abrir siempre en modo
    lectura" sobre esa carpeta.
    """
    resolved = Path(path).resolve()
    if RAW_DIR in resolved.parents or resolved == RAW_DIR:
        raise PermissionError(
            f"Operación bloqueada: '{resolved}' está dentro de 01_BASES_RAW, "
            "que es exclusivamente de solo lectura en este sistema."
        )


# ---------------------------------------------------------------------------
# Carga de configuración
# ---------------------------------------------------------------------------

def _cargar_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cargar_fuentes() -> dict[str, Any]:
    """Carga y retorna el contenido completo de config/fuentes.yaml."""
    return _cargar_yaml(FUENTES_YAML)


def cargar_mapeo_columnas() -> dict[str, Any]:
    """Carga y retorna el contenido completo de config/mapeo_columnas.yaml."""
    return _cargar_yaml(MAPEO_COLUMNAS_YAML)


def cargar_mapeo_ciiu_sector() -> dict[str, Any]:
    """Carga y retorna el contenido completo de config/mapeo_ciiu_sector.yaml."""
    return _cargar_yaml(MAPEO_CIIU_SECTOR_YAML)


def cargar_scoring_variables() -> dict[str, Any]:
    """Carga y retorna el contenido completo de config/scoring_variables.yaml."""
    return _cargar_yaml(SCORING_VARIABLES_YAML)


@dataclass(frozen=True)
class FuenteInfo:
    """Representación tipada de una entrada de fuentes.yaml."""

    id: str
    archivo: str
    formato: str
    encoding: str | None
    delimitador: str | None
    tamano_bytes: int
    registros_aprox: int
    columnas_n: int
    categoria: str
    nivel_confianza_fuente: str
    duplicado_estado: str
    duplicado_referencia: str | None

    @property
    def ruta_absoluta(self) -> Path:
        """Ruta absoluta de solo lectura hacia el archivo en 01_BASES_RAW."""
        return RAW_DIR / self.archivo


def listar_fuentes(
    categoria: str | None = None,
    excluir_duplicados: bool = True,
) -> list[FuenteInfo]:
    """Devuelve las fuentes declaradas en fuentes.yaml, opcionalmente filtradas.

    Args:
        categoria: si se da, solo devuelve fuentes con esa categoría
            (ej. "general_regional", "sectorial", "interno_bold_crm").
        excluir_duplicados: si True (default), omite las fuentes marcadas con
            duplicado.estado == "duplicado_exacto" que además tienen una
            "referencia" (es decir, no son la copia canónica).
    """
    data = cargar_fuentes()
    resultado: list[FuenteInfo] = []
    for f in data["fuentes"]:
        dup = f.get("duplicado", {}) or {}
        if excluir_duplicados and dup.get("estado") == "duplicado_exacto" and dup.get("referencia"):
            continue
        if categoria is not None and f.get("categoria") != categoria:
            continue
        resultado.append(
            FuenteInfo(
                id=f["id"],
                archivo=f["archivo"],
                formato=f["formato"],
                encoding=f.get("encoding"),
                delimitador=f.get("delimitador"),
                tamano_bytes=f.get("tamano_bytes") or 0,
                registros_aprox=f.get("registros_aprox") or 0,
                columnas_n=f.get("columnas_n") or 0,
                categoria=f.get("categoria", ""),
                nivel_confianza_fuente=f.get("nivel_confianza_fuente", ""),
                duplicado_estado=dup.get("estado", "unico"),
                duplicado_referencia=dup.get("referencia"),
            )
        )
    return resultado
