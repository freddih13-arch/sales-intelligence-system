#!/usr/bin/env python3
"""
Generador de Cockpit Comercial para Demo Pública.

Crea un archivo Excel/Calc interactivo (.xlsx) que funciona como
cabina de llamada: datos precargados, playbook, captura ultrarrápida,
clasificación automática, export a CSV.

Versión demo: genera cockpit con datos 100% sintéticos.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


# =============================================================================
# PALETA DE COLORES (semántica, no decorativa)
# =============================================================================
COLORS = {
    "sistema": "D6E4F0",      # Azul claro: dato del sistema (no editable)
    "alerta": "FCE4EC",       # Rojo claro: alerta / validación
    "paso_actual": "FFF9C4",  # Amarillo: paso actual / por confirmar
    "confirmado": "C8E6C9",   # Verde: confirmado en llamada
    "captura": "FFFFFF",      # Blanco con borde: campo de captura
    "header": "1B5E20",       # Verde oscuro: encabezados
    "subheader": "2E7D32",    # Verde medio: sub-encabezados
    "borde": "90A4AE",        # Gris azulado: bordes
}

FILLS = {k: PatternFill(start_color=v, end_color=v, fill_type="solid") for k, v in COLORS.items()}
THIN_SIDE = Side(style="thin", color=COLORS["borde"])
BORDER_THIN = Border(
    left=THIN_SIDE,
    right=THIN_SIDE,
    top=THIN_SIDE,
    bottom=THIN_SIDE,
)

FONT_HEADER = Font(name="Calibri", bold=True, size=12, color="FFFFFF")
FONT_SUBHEADER = Font(name="Calibri", bold=True, size=11, color=COLORS["header"])
FONT_NORMAL = Font(name="Calibri", size=10)
FONT_BOLD = Font(name="Calibri", bold=True, size=10, color=COLORS["header"])
ALIGN_CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
ALIGN_TOP = Alignment(horizontal="left", vertical="top", wrap_text=True)

PROTECTED = Protection(locked=True)
UNPROTECTED = Protection(locked=False)


# =============================================================================
# VOCABULARIOS CERRADOS (listas desplegables)
# =============================================================================
VOCABULARIOS = {
    "resultado_contacto": [
        "contactado",
        "no_contesta",
        "ocupado",
        "numero_errado",
        "buzon_voz",
        "fuera_servicio",
        "rechaza_llamada",
    ],
    "persona_contactada_rol": [
        "propietario_representante",
        "gerente_administrador",
        "encargado_compras",
        "encargado_pagos",
        "otro_empleado",
        "no_informado",
    ],
    "etapa_actual": [
        "apertura",
        "descubrimiento_necesidades",
        "presentacion_solucion",
        "manejo_objeciones",
        "cierre",
        "seguimiento_post_llamada",
        "cerrado_ganado",
        "cerrado_perdido",
        "no_calificado",
    ],
    "acepta_pagos_electronicos": [
        "si",
        "no",
        "no_sabe",
        "ya_tiene_proveedor",
    ],
    "satisfaccion_proveedor": [
        "muy_satisfecho",
        "satisfecho",
        "neutral",
        "insatisfecho",
        "muy_insatisfecho",
        "no_aplica",
    ],
    "objecion_principal": [
        "precio_comisiones",
        "ya_tiene_proveedor",
        "no_ve_necesidad",
        "desconfianza_tecnologia",
        "proceso_largo",
        "requiere_aprobacion",
        "ninguna",
    ],
    "resultado_final": [
        "activado",
        "agendado_demo",
        "enviada_propuesta",
        "en_evaluacion",
        "perdido_precio",
        "perdido_competencia",
        "perdido_sin_interes",
        "no_contactable",
        "negocio_inactivo",
    ],
    "motivo_perdida": [
        "precio_comisiones",
        "ya_tiene_proveedor_satisfactorio",
        "no_ve_valor_agregado",
        "desconfianza_seguridad",
        "proceso_onboarding_largo",
        "requiere_aprobacion_superior",
        "cambio_no_prioritario",
        "no_contactable_despues_multiples_intentos",
        "negocio_cerrado_inactivo",
        "otro",
    ],
    "unidad_volumen": [
        "transacciones_mes",
        "millones_cop_mes",
        "porcentaje_ventas_tarjeta",
    ],
    "canal_contacto": [
        "telefono",
        "whatsapp",
        "email",
        "presencial",
        "videollamada",
    ],
    "prioridad_clasificacion": [
        "ALTA",
        "MEDIA",
        "BAJA",
    ],
}

# =============================================================================
# DATOS SINTÉTICOS DE EJEMPLO (para demo)
# =============================================================================
def generar_prospectos_sinteticos(n: int = 10) -> list[dict[str, Any]]:
    """Genera prospectos sintéticos realistas para el cockpit demo."""
    import random

    random.seed(42)

    sectores = [
        "Gastronomía y Hotelería",
        "Ferretería y construcción menor",
        "Salud",
        "Salud / Farmacias",
        "Educación",
        "Comercio / Retail",
        "Manufactura",
        "Servicios profesionales",
        "Transporte y logística",
        "Entretenimiento",
    ]

    ciudades = [
        ("BOGOTA", "CUNDINAMARCA"),
        ("MEDELLIN", "ANTIOQUIA"),
        ("CALI", "VALLE DEL CAUCA"),
        ("BARRANQUILLA", "ATLANTICO"),
        ("CARTAGENA", "BOLIVAR"),
        ("PEREIRA", "RISARALDA"),
        ("MANIZALES", "CALDAS"),
        ("ARMENIA", "QUINDIO"),
        ("IBAGUE", "TOLIMA"),
        ("BUCARAMANGA", "SANTANDER"),
    ]

    sufijos = ["S.A.S.", "S.A.", "LTDA.", "E.U."]
    prefijos_nombre = [
        "COMERCIAL", "DISTRIBUIDORA", "ALMACEN", "FERRETERIA", "FARMACIA",
        "RESTAURANTE", "HOTEL", "CLINICA", "COLEGIO", "CONSTRUCTORA",
        "TRANSPORTES", "TECNOLOGIA", "SERVICIOS", "CONSULTORIA",
    ]

    prospectos = []
    for i in range(n):
        sector = random.choice(sectores)
        ciudad, depto = random.choice(ciudades)
        prefijo = random.choice(prefijos_nombre)
        sufijo = random.choice(sufijos)
        nombre = f"{prefijo} {ciudad} {sufijo}"

        # Score sintético coherente con sector
        base_score = {
            "Gastronomía y Hotelería": random.randint(75, 95),
            "Ferretería y construcción menor": random.randint(70, 90),
            "Salud": random.randint(70, 90),
            "Salud / Farmacias": random.randint(70, 90),
            "Educación": random.randint(65, 85),
            "Comercio / Retail": random.randint(55, 80),
            "Manufactura": random.randint(45, 70),
            "Servicios profesionales": random.randint(40, 65),
            "Transporte y logística": random.randint(40, 65),
            "Entretenimiento": random.randint(35, 60),
        }[sector]

        prospectos.append({
            "posicion_ranking": i + 1,
            "entidad_dedup_id": f"ENT-{i+1:07d}",
            "nit": f"{random.randint(800000000, 999999999)}",
            "razon_social": nombre,
            "sector_vertical": sector,
            "encaje_pagos": "alto" if sector in ["Gastronomía y Hotelería", "Ferretería y construcción menor", "Salud", "Salud / Farmacias", "Educación"] else "medio",
            "municipio_comercial": ciudad,
            "departamento": depto,
            "direccion_comercial": f"CR {random.randint(1,100)} #{random.randint(1,99)}-{random.randint(1,99)}",
            "telefono_comercial_1": f"601{random.randint(2000000, 9999999)}",
            "telefono_comercial_2": f"3{random.randint(100000000, 999999999)}" if random.random() > 0.5 else "",
            "email_comercial": f"contacto@{prefijo.lower()}{ciudad.lower()}.com" if random.random() > 0.3 else "",
            "tamano_empresa": random.choice(["micro", "pequena", "mediana", "grande"]),
            "num_empleados": random.randint(1, 200),
            "ultimo_ano_renovado": str(random.randint(2020, 2024)),
            "score_prioridad_comercial": round(base_score + random.uniform(-5, 5), 1),
            "prioridad": "ALTA" if base_score >= 70 else ("MEDIA" if base_score >= 45 else "BAJA"),
            "contactabilidad": "telefono_y_email" if random.random() > 0.3 else ("solo_uno" if random.random() > 0.5 else "ninguno"),
            "nivel_confianza_score": random.choice(["Alta", "Media", "Baja"]),
            "enriquecimiento_legal": random.choice(["EXACTO", "PARCIAL", "NO_CONSULTABLE"]),
        })
    return prospectos


# =============================================================================
# GENERADOR DE COCKPIT EXCEL
# =============================================================================
def crear_hoja_cockpit(wb: Workbook, prospectos: list[dict]) -> None:
    """Crea la hoja principal COCKPIT con un prospecto seleccionable."""
    ws = wb.active
    ws.title = "COCKPIT"
    ws.sheet_properties.tabColor = "1B5E20"

    # Configuración de columnas (anchos optimizados para visualización)
    anchos = {
        "A": 3, "B": 18, "C": 35, "D": 18, "E": 18, "F": 15,
        "G": 15, "H": 15, "I": 15, "J": 18, "K": 18,
        "L": 18, "M": 18, "N": 18, "O": 18, "P": 18,
        "Q": 18, "R": 18, "S": 18, "T": 18, "U": 18,
        "V": 18, "W": 18, "X": 18, "Y": 18, "Z": 18,
        "AA": 18, "AB": 18, "AC": 18, "AD": 18, "AE": 18,
        "AF": 18, "AG": 18, "AH": 18, "AI": 18, "AJ": 18,
    }
    for col, w in anchos.items():
        ws.column_dimensions[col].width = w

    # ========== SECCIÓN 1: SELECTOR DE PROSPECTO (Fila 1-3) ==========
    # Celda C4 = selector de prospecto (desplegable)
    ws.merge_cells("B1:D1")
    cell = ws["B1"]
    cell.value = "🎯 BOLD CALLING COCKPIT — DEMO SINTÉTICA"
    cell.font = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
    cell.fill = FILLS["header"]
    cell.alignment = ALIGN_CENTER
    cell.border = BORDER_THIN
    for col in ["C", "D"]:
        ws[f"{col}1"].fill = FILLS["header"]
        ws[f"{col}1"].border = BORDER_THIN

    ws.merge_cells("B2:D2")
    cell = ws["B2"]
    cell.value = "Seleccione prospecto →"
    cell.font = FONT_SUBHEADER
    cell.alignment = ALIGN_CENTER
    cell.fill = FILLS["sistema"]
    cell.border = BORDER_THIN
    for col in ["C", "D"]:
        ws[f"{col}2"].fill = FILLS["sistema"]
        ws[f"{col}2"].border = BORDER_THIN

    # Selector en C3
    opciones = [f"{p['posicion_ranking']:03d} - {p['razon_social'][:40]}" for p in prospectos]
    dv = DataValidation(type="list", formula1=f'"{",".join(opciones)}"', allow_blank=True)
    dv.prompt = "Seleccione un prospecto del Top N"
    dv.error = "Seleccione una opción válida"
    ws.add_data_validation(dv)
    ws["C3"] = opciones[0]
    dv.add(ws["C3"])
    ws["C3"].fill = FILLS["paso_actual"]
    ws["C3"].font = FONT_BOLD
    ws["C3"].alignment = ALIGN_CENTER
    ws["C3"].border = BORDER_THIN

    # Labels para selector
    ws["B3"] = "PROSPECTO:"
    ws["B3"].font = FONT_NORMAL
    ws["B3"].alignment = ALIGN_LEFT
    ws["B3"].fill = FILLS["sistema"]
    ws["B3"].border = BORDER_THIN
    ws["D3"] = f"Total: {len(prospectos)} prospectos"
    ws["D3"].font = Font(name="Calibri", italic=True, size=9, color="666666")
    ws["D3"].alignment = ALIGN_LEFT
    ws["D3"].fill = FILLS["sistema"]
    ws["D3"].border = BORDER_THIN

    # ========== SECCIÓN 2: IDENTIFICACIÓN DEL PROSPECTO (Filas 5-18) ==========
    row = 5
    _escribir_seccion(ws, row, "🏢 IDENTIFICACIÓN DEL PROSPECTO", "sistema")
    row += 1

    campos_identificacion = [
        ("Posición en Ranking", "posicion_ranking", "sistema"),
        ("ID Entidad", "entidad_dedup_id", "sistema"),
        ("NIT", "nit", "sistema"),
        ("Razón Social", "razon_social", "sistema"),
        ("Sector Vertical", "sector_vertical", "sistema"),
        ("Encaje Pagos", "encaje_pagos", "sistema"),
        ("Municipio", "municipio_comercial", "sistema"),
        ("Departamento", "departamento", "sistema"),
        ("Dirección", "direccion_comercial", "sistema"),
        ("Teléfono 1", "telefono_comercial_1", "sistema"),
        ("Teléfono 2", "telefono_comercial_2", "sistema"),
        ("Email", "email_comercial", "sistema"),
    ]

    for label, key, tipo in campos_identificacion:
        _escribir_campo(ws, row, label, key, tipo)
        row += 1

    # ========== SECCIÓN 3: ALERTAS (Fila 19) ==========
    row += 1
    _escribir_seccion(ws, row, "🔔 ALERTAS", "alerta")
    row += 1
    _escribir_campo(ws, row, "Alerta Legal", "enriquecimiento_legal", "alerta", 
                    nota="EXACTO=sin alerta | PARCIAL=revisar | NO_CONSULTABLE=sin validar")
    row += 1
    _escribir_campo(ws, row, "Confianza Score", "nivel_confianza_score", "sistema")
    row += 1

    # ========== SECCIÓN 4: SCORE Y PRIORIZACIÓN (Filas 22-28) ==========
    _escribir_seccion(ws, row, "📊 SCORE Y PRIORIZACIÓN", "sistema")
    row += 1

    campos_score = [
        ("Score Prioridad", "score_prioridad_comercial", "sistema"),
        ("Prioridad Comercial", "prioridad", "sistema"),
        ("Fit Comercial (40%)", "sector_vertical", "sistema"),
        ("Escala/Potencial (35%)", "tamano_empresa", "sistema"),
        ("Contactabilidad (25%)", "contactabilidad", "sistema"),
        ("Nivel Confianza", "nivel_confianza_score", "sistema"),
    ]

    for label, key, tipo in campos_score:
        _escribir_campo(ws, row, label, key, tipo)
        row += 1

    # ========== SECCIÓN 5: PASO ACTUAL Y PLAYBOOK (Filas 30-45) ==========
    _escribir_seccion(ws, row, "👉 PASO ACTUAL — PLAYBOOK HORECA", "paso_actual")
    row += 1

    # Paso actual (editable, amarillo)
    _escribir_campo(ws, row, "Paso Actual", "etapa_actual", "paso_actual", 
                    opciones=VOCABULARIOS["etapa_actual"])
    row += 1

    # Apertura literal (sistema, no editable)
    _escribir_campo(ws, row, "Apertura Literal", "apertura_literal", "sistema",
                    valor="Buenos días, hablo con [NOMBRE] de [RAZON_SOCIAL]? "
                          "Soy [TU NOMBRE] de Bold. Llamo porque vemos que "
                          "su negocio en [SECTOR] en [CIUDAD] podría "
                          "optimizar sus cobros con tarjeta. ¿Tiene 2 min?")
    row += 1

    # Preguntas de descubrimiento (captura ultrarrápida)
    preguntas = [
        ("¿Acepta pagos electrónicos?", "acepta_pagos_electronicos", VOCABULARIOS["acepta_pagos_electronicos"]),
        ("¿Con qué proveedor actual?", "proveedor_actual", None),
        ("¿Volumen mensual aprox?", "volumen_mensual", None),
        ("Unidad de volumen", "unidad_volumen", VOCABULARIOS["unidad_volumen"]),
        ("Satisfacción proveedor actual", "satisfaccion_proveedor", VOCABULARIOS["satisfaccion_proveedor"]),
        ("Objeción principal", "objecion_principal", VOCABULARIOS["objecion_principal"]),
        ("Persona contactada / Rol", "persona_contactada_rol", VOCABULARIOS["persona_contactada_rol"]),
    ]

    for label, key, opciones in preguntas:
        _escribir_campo(ws, row, label, key, "captura", opciones=opciones)
        row += 1

    # ========== SECCIÓN 6: CLASIFICACIÓN AUTOMÁTICA (Fila 47) ==========
    _escribir_seccion(ws, row, "📊 CLASIFICACIÓN AUTOMÁTICA", "sistema")
    row += 1
    _escribir_campo(ws, row, "Prioridad Comercial", "prioridad_clasificacion", "sistema",
                    opciones=VOCABULARIOS["prioridad_clasificacion"])
    row += 1

    # ========== SECCIÓN 7: CIERRE Y APRENDIZAJE (Filas 49-55) ==========
    _escribir_seccion(ws, row, "🧠 APRENDIZAJE / NOTA LIBRE", "captura")
    row += 1
    _escribir_campo(ws, row, "Nota del Vendedor", "nota_libre_vendedor", "captura",
                    es_textarea=True)
    row += 2

    _escribir_seccion(ws, row, "✅ RESULTADO FINAL", "captura")
    row += 1
    _escribir_campo(ws, row, "Resultado Final", "resultado_final", "captura",
                    opciones=VOCABULARIOS["resultado_final"])
    row += 1
    _escribir_campo(ws, row, "Motivo (si perdido)", "motivo_perdida", "captura",
                    opciones=VOCABULARIOS["motivo_perdida"])
    row += 1
    _escribir_campo(ws, row, "Próxima Acción / Fecha", "proxima_accion", "captura")
    row += 1

    # ========== SECCIÓN 8: EXPORTAR A REGISTRO (Fila 57) ==========
    _escribir_seccion(ws, row, "📤 EXPORTAR A REGISTRO DE INTERACCIONES", "sistema")
    row += 1
    ws.merge_cells(f"B{row}:H{row}")
    ws[f"B{row}"] = "1. Complete todos los campos de captura (amarillos) → 2. Copie fila de EXPORTAR_CSV → 3. Pegue en registro_interacciones_comerciales.csv (Pegado especial → Solo valores)"
    ws[f"B{row}"].font = Font(name="Calibri", italic=True, size=9, color="666666")
    ws[f"B{row}"].alignment = ALIGN_LEFT
    ws[f"B{row}"].fill = FILLS["sistema"]
    ws[f"B{row}"].border = BORDER_THIN

    # Proteger hoja (excepto celdas de captura)
    ws.protection.sheet = True
    ws.protection.password = "demo"  # Solo para demo, no seguridad real


def _escribir_seccion(ws, row: int, titulo: str, tipo_color: str) -> None:
    """Escribe un encabezado de sección con color semántico."""
    ws.merge_cells(f"B{row}:H{row}")
    cell = ws[f"B{row}"]
    cell.value = titulo
    cell.font = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
    cell.fill = FILLS[tipo_color]
    cell.alignment = ALIGN_CENTER
    cell.border = BORDER_THIN
    for col in ["C", "D", "E", "F", "G", "H"]:
        ws[f"{col}{row}"].fill = FILLS[tipo_color]
        ws[f"{col}{row}"].border = BORDER_THIN


def _escribir_campo(
    ws,
    row: int,
    label: str,
    key: str,
    tipo: str,
    opciones: list[str] | None = None,
    valor: str | None = None,
    nota: str | None = None,
    es_textarea: bool = False,
) -> None:
    """Escribe un campo label + valor con semántica visual según tipo."""
    # Columna B = Label
    ws[f"B{row}"] = label
    ws[f"B{row}"].font = FONT_NORMAL
    ws[f"B{row}"].alignment = ALIGN_LEFT
    ws[f"B{row}"].fill = FILLS["sistema"]
    ws[f"B{row}"].border = BORDER_THIN

    # Columna C = Valor (principal)
    cell_valor = ws[f"C{row}"]
    if valor is not None:
        cell_valor.value = valor
    else:
        cell_valor.value = f"{{{{{key}}}}}"  # Placeholder para fórmula VLOOKUP/INDEX-MATCH

    # Estilo según tipo
    if tipo == "sistema":
        cell_valor.fill = FILLS["sistema"]
        cell_valor.protection = PROTECTED
        cell_valor.font = FONT_NORMAL
    elif tipo == "alerta":
        cell_valor.fill = FILLS["alerta"]
        cell_valor.protection = PROTECTED
        cell_valor.font = FONT_BOLD
    elif tipo == "paso_actual":
        cell_valor.fill = FILLS["paso_actual"]
        cell_valor.protection = UNPROTECTED
        cell_valor.font = FONT_BOLD
    elif tipo == "captura":
        cell_valor.fill = FILLS["captura"]
        cell_valor.protection = UNPROTECTED
        cell_valor.font = FONT_NORMAL
    else:
        cell_valor.fill = FILLS["sistema"]
        cell_valor.protection = PROTECTED
        cell_valor.font = FONT_NORMAL

    cell_valor.alignment = ALIGN_CENTER if not es_textarea else ALIGN_TOP
    cell_valor.border = BORDER_THIN

    # Validación de datos (desplegable) si hay opciones
    if opciones:
        dv = DataValidation(type="list", formula1=f'"{",".join(opciones)}"', allow_blank=True)
        cell_valor.parent.add_data_validation(dv)
        dv.add(cell_valor)

    # Columna D = Nota/ayuda (opcional)
    if nota:
        ws[f"D{row}"] = nota
        ws[f"D{row}"].font = Font(name="Calibri", italic=True, size=8, color="888888")
        ws[f"D{row}"].alignment = ALIGN_LEFT
        ws[f"D{row}"].fill = FILLS["sistema"]
        ws[f"D{row}"].border = BORDER_THIN

    # Columnas E-H = reservadas para fórmulas VLOOKUP/INDEX-MATCH que traen datos del prospecto seleccionado
    for col in ["E", "F", "G", "H"]:
        ws[f"{col}{row}"].fill = FILLS["sistema"]
        ws[f"{col}{row}"].border = BORDER_THIN
        ws[f"{col}{row}"].protection = PROTECTED


def crear_hoja_datos_fuente(wb: Workbook, prospectos: list[dict]) -> None:
    """Crea hoja oculta DATOS_FUENTE con todos los prospectos para VLOOKUP."""
    ws = wb.create_sheet("DATOS_FUENTE")
    ws.sheet_state = "hidden"

    # Headers
    headers = list(prospectos[0].keys())
    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = FONT_HEADER
        cell.fill = FILLS["header"]
        cell.alignment = ALIGN_CENTER
        cell.border = BORDER_THIN

    # Data
    for row_idx, p in enumerate(prospectos, 2):
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=p.get(header, ""))
            cell.font = FONT_NORMAL
            cell.border = BORDER_THIN
            if row_idx % 2 == 0:
                cell.fill = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")

    # Ajustar anchos
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 18


def crear_hoja_listas(wb: Workbook) -> None:
    """Crea hoja oculta LISTAS con vocabularios para validaciones."""
    ws = wb.create_sheet("LISTAS")
    ws.sheet_state = "hidden"

    row = 1
    for nombre, valores in VOCABULARIOS.items():
        ws.cell(row=row, column=1, value=nombre).font = FONT_SUBHEADER
        ws.cell(row=row, column=1).fill = FILLS["subheader"] if "subheader" in FILLS else FILLS["header"]
        ws.cell(row=row, column=1).border = BORDER_THIN
        row += 1
        for v in valores:
            ws.cell(row=row, column=1, value=v).font = FONT_NORMAL
            ws.cell(row=row, column=1).border = BORDER_THIN
            row += 1
        row += 1  # espacio entre listas


def crear_hoja_exportar_csv(wb: Workbook, prospectos: list[dict]) -> None:
    """Crea hoja EXPORTAR_CSV con fila lista para copiar al registro."""
    ws = wb.create_sheet("EXPORTAR_CSV")

    # Headers del registro de interacciones
    headers_registro = [
        "interaccion_id", "fecha_registro", "entidad_dedup_id", "posicion_top100",
        "razon_social", "fuente_top100", "resultado_contacto", "etapa_actual",
        "persona_contactada_rol", "acepta_pagos_electronicos", "proveedor_actual",
        "volumen_mensual", "unidad_volumen", "satisfaccion_proveedor",
        "objecion_principal", "nota_libre_vendedor", "resultado_final",
        "motivo_perdida", "proxima_accion", "canal_contacto",
        "score_prioridad", "prioridad", "enriquecimiento_legal",
    ]

    for col_idx, header in enumerate(headers_registro, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = FONT_HEADER
        cell.fill = FILLS["header"]
        cell.alignment = ALIGN_CENTER
        cell.border = BORDER_THIN

    # Fila 2 = plantilla con fórmulas que referencian COCKPIT y DATOS_FUENTE
    # En demo, ponemos valores de ejemplo del primer prospecto
    p = prospectos[0]
    valores_ejemplo = [
        1, date.today().isoformat(), p["entidad_dedup_id"], p["posicion_ranking"],
        p["razon_social"], "top100_diversificado_sintetico.csv", "contactado",
        "apertura", "propietario_representante", "si", "Proveedor Actual S.A.S.",
        "500", "transacciones_mes", "satisfecho", "precio_comisiones",
        "Cliente interesado en demo la próxima semana", "agendado_demo",
        "", "Enviar propuesta por email - 2026-01-15", "telefono",
        p["score_prioridad_comercial"], p["prioridad"], "EXACTO",
    ]

    for col_idx, val in enumerate(valores_ejemplo, 1):
        cell = ws.cell(row=2, column=col_idx, value=val)
        cell.font = FONT_NORMAL
        cell.border = BORDER_THIN
        cell.fill = FILLS["captura"]
        cell.protection = UNPROTECTED

    # Ajustar anchos
    for col_idx in range(1, len(headers_registro) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 22

    ws.protection.sheet = True
    ws.protection.password = "demo"


def generar_cockpit_demo(
    salida: str = "demo_data/cockpit_demo.xlsx",
    n_prospectos: int = 10,
) -> str:
    """Genera el archivo de cockpit demo completo."""
    prospectos = generar_prospectos_sinteticos(n_prospectos)

    wb = Workbook()

    # Hoja 1: COCKPIT (principal)
    crear_hoja_cockpit(wb, prospectos)

    # Hoja 2: DATOS_FUENTE (oculta)
    crear_hoja_datos_fuente(wb, prospectos)

    # Hoja 3: LISTAS (oculta, vocabularios)
    crear_hoja_listas(wb)

    # Hoja 4: EXPORTAR_CSV (para copiar a registro)
    crear_hoja_exportar_csv(wb, prospectos)

    # Guardar
    salida_path = Path(salida)
    salida_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(salida_path)

    return str(salida_path)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Genera Cockpit Comercial Demo")
    parser.add_argument("--n", type=int, default=10, help="Número de prospectos sintéticos")
    parser.add_argument("--output", default="demo_data/cockpit_demo.xlsx", help="Ruta de salida")
    args = parser.parse_args()

    salida = generar_cockpit_demo(args.output, args.n)
    print(f"✅ Cockpit demo generado: {salida}")
    print(f"   Prospectos: {args.n}")
    print(f"   Abra con LibreOffice Calc o Excel")
    print(f"   Hoja COCKPIT: selección en C3, capture en amarillos, exporte desde EXPORTAR_CSV")


if __name__ == "__main__":
    main()