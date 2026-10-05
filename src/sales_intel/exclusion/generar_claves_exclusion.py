"""
Extracción de la capa mínima de exclusión desde el CRM y HUBS internos de
Client (requisito 10 de la arquitectura V1).

REGLA NO NEGOCIABLE: la función `campos_permitidos_exclusion` es la ÚNICA
lista de campos que este módulo tiene permitido leer y conservar de esas
fuentes. Cualquier otro campo (correo, teléfono, dirección, nombre de
persona/asesor) se descarta en memoria y NUNCA se escribe a disco.
"""

from __future__ import annotations

# Campos que SÍ se permiten extraer del CRM interno (Detalle lead y
# oportunidades) para la capa de exclusión.
CAMPOS_PERMITIDOS_CRM = {
    "numero_documento",      # candidato a NIT — ver punto abierto #1 en DECISIONES.md
    "nombre_comercio_lead",  # respaldo si numero_documento no es confiable como NIT
    "ciudad",                # respaldo, junto con nombre_comercio_lead
}

# Campos que SÍ se permiten extraer de los archivos HUBS para la capa de
# exclusión.
CAMPOS_PERMITIDOS_HUBS = {
    "matricula",
    "identificacion",  # NIT
}

# Campos EXPLÍCITAMENTE PROHIBIDOS — nunca deben aparecer en
# claves_exclusion_bold.parquet, documentados aquí para que sea evidente en
# revisión de código si alguna vez se intentan incluir.
CAMPOS_PROHIBIDOS = {
    "user_email", "lead_email", "manager_email",       # correos (CRM)
    "numero_contacto", "direccion",                     # teléfono/dirección (CRM)
    "tipo_documento",                                    # se usa solo para VALIDAR el numero_documento, no se persiste
    "correo comercial", "telefono comercial",            # contacto (HUBS)
    "asignado a",                                        # nombre de asesor interno (HUBS)
}


def campos_permitidos_exclusion(fuente: str) -> set[str]:
    """Devuelve el conjunto de campos permitidos para una fuente interna
    ('crm' o 'hubs'). Cualquier extracción debe filtrar contra este conjunto
    antes de escribir nada a 02_PROCESADAS/05_exclusion/.
    """
    if fuente == "crm":
        return CAMPOS_PERMITIDOS_CRM
    if fuente == "hubs":
        return CAMPOS_PERMITIDOS_HUBS
    raise ValueError(f"Fuente interna desconocida: '{fuente}' (esperado 'crm' o 'hubs')")


def generar_claves_exclusion_crm(tabla_crm):
    """Extrae SOLO las llaves de exclusión del CRM interno.

    NO IMPLEMENTADO TODAVÍA — requiere pandas para leer el CSV del CRM.
    Antes de implementar, resolver el punto abierto #1 de DECISIONES.md
    (si 'numero_documento' es NIT del negocio o cédula de la persona de
    contacto) — de eso depende si se usa como llave primaria o como
    respaldo de menor confianza.
    """
    raise NotImplementedError(
        "generar_claves_exclusion_crm requiere pandas, no instalado todavía, "
        "y depende del punto abierto #1 en DECISIONES.md."
    )


def generar_claves_exclusion_hubs(tablas_hubs: list):
    """Extrae SOLO matrícula/NIT de los 4 archivos HUBS.

    NO IMPLEMENTADO TODAVÍA — requiere pandas + openpyxl.
    """
    raise NotImplementedError(
        "generar_claves_exclusion_hubs requiere pandas y openpyxl, no "
        "instalados todavía."
    )
