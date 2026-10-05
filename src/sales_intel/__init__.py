"""
SALES_INTELLIGENCE — sales_intel

Sistema de inteligencia de prospección comercial para Client.

ESTADO: esqueleto de infraestructura inicial (2026-09-01). Ningún módulo de
este paquete ha sido ejecutado todavía sobre las bases reales de
01_BASES_RAW. Ver 04_SISTEMA/docs/ARQUITECTURA.md y GUIA_EJECUCION.md antes
de invocar cualquier función de procesamiento.

Principio no negociable: ningún módulo de este paquete escribe, mueve,
renombra ni elimina nada dentro de 01_BASES_RAW. Esa carpeta es solo lectura.
"""

__version__ = "0.1.0-skeleton"

# Importar subpaquetes para que estén disponibles
from . import piloto_zernio
