"""Configuración estándar de logging para todos los módulos del pipeline."""

from __future__ import annotations

import logging
import sys


def configurar_logging(nivel: int = logging.INFO) -> logging.Logger:
    """Configura y retorna el logger raíz 'sales_intel' con salida a consola.

    No escribe a ningún archivo por defecto (evita crear artefactos no
    solicitados). Cada módulo debe obtener su logger con:
        logger = logging.getLogger(f"sales_intel.{__name__}")
    """
    logger = logging.getLogger("sales_intel")
    if logger.handlers:
        return logger  # ya configurado, evita duplicar handlers

    logger.setLevel(nivel)
    handler = logging.StreamHandler(stream=sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
