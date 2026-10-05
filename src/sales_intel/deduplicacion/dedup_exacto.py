"""
Detección de duplicados de ARCHIVO completo (Nivel 1 de la estrategia de
duplicados, ver ARQUITECTURA.md sección E).

Puro stdlib — funciona hoy. Se apoya en los hashes ya declarados en
fuentes.yaml (calculados manualmente durante la auditoría) y puede
recalcularlos para verificar que no cambiaron.
"""

from __future__ import annotations

from collections import defaultdict

from sales_intel.ingesta.registro_fuentes import calcular_hash_archivo
from sales_intel.utils.config import listar_fuentes


def agrupar_por_duplicado_declarado() -> dict[str, list[str]]:
    """Agrupa las fuentes según el campo 'duplicado' ya declarado en
    fuentes.yaml (resultado de la auditoría manual con MD5). No recalcula
    hashes — es una lectura directa de la configuración.

    Retorna {fuente_canonica_id: [ids_duplicados_de_ella]}.
    """
    todas = listar_fuentes(excluir_duplicados=False)
    grupos: dict[str, list[str]] = defaultdict(list)
    for f in todas:
        if f.duplicado_estado == "duplicado_exacto" and f.duplicado_referencia:
            grupos[f.duplicado_referencia].append(f.id)
    return dict(grupos)


def verificar_duplicados_por_hash(fuentes_ids: list[str] | None = None) -> dict[str, str]:
    """Recalcula el hash SHA-256 real de cada fuente y devuelve
    {fuente_id: hash}, para volver a agrupar por igualdad de hash y así
    confirmar (o refutar) lo declarado en fuentes.yaml si 01_BASES_RAW
    cambiara.

    NO SE HA EJECUTADO TODAVÍA. Es segura de correr (solo lectura), pero se
    deja pendiente de invocación explícita para no procesar los 50 archivos
    sin aprobación, según lo solicitado.
    """
    todas = listar_fuentes(excluir_duplicados=False)
    if fuentes_ids is not None:
        todas = [f for f in todas if f.id in fuentes_ids]
    return {f.id: calcular_hash_archivo(f.ruta_absoluta) for f in todas if f.ruta_absoluta.exists()}
