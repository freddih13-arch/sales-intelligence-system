#!/usr/bin/env python3
"""
Generador de dataset sintético para demo público de SALES_INTELLIGENCE.

Crea 500-1000 entidades ficticias con campos realistas pero SIN datos reales:
- NITs aleatorios válidos (formato colombiano 9-10 dígitos, sin placeholders)
- Razones sociales genéricas ("Comercial [Sector] [Ciudad] S.A.S.")
- Sectores distribuidos según taxonomía V2
- Municipios colombianos reales
- Contactabilidad variada
- Scores calculados por el motor real
- Diversificación aplicada

Uso:
    python scripts/generate_synthetic.py [--n 1000] [--output demo_data/empresas_sinteticas.parquet]
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd

# Permite importar el motor de scoring real
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sales_intel.scoring.motor_scoring import calcular_scores
from sales_intel.scoring.variables_scoring import obtener_pesos, NOMBRE_SCORE
from sales_intel.diversificacion.capa_diversificacion import (
    construir_ranking_diversificado,
    ConfiguracionDiversificacion,
    M_SUAVIZADO,
)


# ============================================================================
# DATOS BASE PARA GENERACIÓN SINTÉTICA
# ============================================================================

# Municipios colombianos reales (muestra representativa)
MUNICIPIOS_COLOMBIA = [
    ("BOGOTA", "CUNDINAMARCA"),
    ("MEDELLIN", "ANTIOQUIA"),
    ("CALI", "VALLE DEL CAUCA"),
    ("BARRANQUILLA", "ATLANTICO"),
    ("CARTAGENA", "BOLIVAR"),
    ("BUCARAMANGA", "SANTANDER"),
    ("PEREIRA", "RISARALDA"),
    ("MANIZALES", "CALDAS"),
    ("ARMENIA", "QUINDIO"),
    ("IBAGUE", "TOLIMA"),
    ("CUCUTA", "NORTE DE SANTANDER"),
    ("VILLAVICENCIO", "META"),
    ("PASTO", "NARINO"),
    ("MONTERIA", "CORDOBA"),
    ("NEIVA", "HUILA"),
    ("SANTA MARTA", "MAGDALENA"),
    ("VALLEDUPAR", "CESAR"),
    ("POPAYAN", "CAUCA"),
    ("TUNJA", "BOYACA"),
    ("FLORENCIA", "CAQUETA"),
    ("YOPAL", "CASANARE"),
    ("RIOHACHA", "LA GUAJIRA"),
    ("MOCOA", "PUTUMAYO"),
    ("PUERTO CARRENO", "VAUPES"),
    ("PUERTO INIRIDA", "GUAINIA"),
    ("MITU", "VAUPES"),
    ("LETICIA", "AMAZONAS"),
    ("SINCELEJO", "SUCRE"),
    ("SANTA ROSA DE CABAL", "RISARALDA"),
    ("DOSQUEBRADAS", "RISARALDA"),
    ("LA VIRGINIA", "RISARALDA"),
    ("MARSELLA", "RISARALDA"),
    ("QUINCHIA", "RISARALDA"),
    ("BELEN DE UMBRIA", "RISARALDA"),
    ("APARTADO", "ANTIOQUIA"),
    ("ITAGUI", "ANTIOQUIA"),
    ("ENVIGADO", "ANTIOQUIA"),
    ("BELLO", "ANTIOQUIA"),
    ("COPACABANA", "ANTIOQUIA"),
    ("GIRON", "SANTANDER"),
    ("FLORIDABLANCA", "SANTANDER"),
    ("PIEDECUESTA", "SANTANDER"),
    ("PALMIRA", "VALLE DEL CAUCA"),
    ("BUENAVENTURA", "VALLE DEL CAUCA"),
    ("TULUA", "VALLE DEL CAUCA"),
    ("CALIMA", "VALLE DEL CAUCA"),
    ("YUMBO", "VALLE DEL CAUCA"),
    ("JAMUNDI", "VALLE DEL CAUCA"),
    ("SOACHA", "CUNDINAMARCA"),
    ("CHIA", "CUNDINAMARCA"),
    ("FUNZA", "CUNDINAMARCA"),
    ("MOSQUERA", "CUNDINAMARCA"),
    ("MADRID", "CUNDINAMARCA"),
    ("FACATATIVA", "CUNDINAMARCA"),
    ("ZIPAQUIRA", "CUNDINAMARCA"),
]

# Sectores según taxonomía V2 (bucket_sector en capa_diversificacion.py)
SECTORES_V2 = [
    "Gastronomía y Hotelería",
    "Ferretería y construcción menor",
    "Salud",
    "Salud / Farmacias",
    "Educación",
    "Comercio / Retail",
    "Manufactura",
    "Otros servicios",
    "Servicios profesionales",
    "Servicios de apoyo empresarial",
    "Servicios públicos",
    "Tecnología / Comunicaciones",
    "Entretenimiento",
    "Transporte y logística",
]

# Mapeo sector -> encaje_pagos (para scoring)
SECTOR_ENCAJE = {
    "Gastronomía y Hotelería": "alto",
    "Ferretería y construcción menor": "alto",
    "Salud": "alto",
    "Salud / Farmacias": "alto",
    "Educación": "medio",  # encaje_generico medio=0.60, pero sector_estrategico=0.92
    "Comercio / Retail": "alto",
    "Manufactura": "medio",
    "Otros servicios": "medio",
    "Servicios profesionales": "medio",
    "Servicios de apoyo empresarial": "medio",
    "Servicios públicos": "no_aplica",
    "Tecnología / Comunicaciones": "medio",
    "Entretenimiento": "alto",
    "Transporte y logística": "medio",
}

# Tipos de organización
TIPOS_ORG = ["S.A.S.", "S.A.", "LTDA.", "PERSONA NATURAL", "ESAL"]

# Tamaños de empresa
TAMANOS_EMPRESA = ["micro", "pequena", "mediana", "grande"]
TAMANO_PROBS = [0.45, 0.35, 0.15, 0.05]  # distribución realista

# Prefijos para NITs (formato colombiano típico)
NIT_PREFIXES = ["8", "9", "80", "81", "82", "83", "84", "85", "86", "87", "88", "89", "90"]

# Sufijos comunes para razones sociales
SUFIJOS_EMPRESA = [
    "S.A.S.", "S.A.", "LTDA.", "E.U.", "Y CIA.", "E HIJOS", "HERMANOS", "Y ASOCIADOS"
]

# Palabras base para nombres genéricos
PALABRAS_NOMBRE = [
    "COMERCIAL", "DISTRIBUIDORA", "IMPORTADORA", "EXPORTADORA", "ALMACEN",
    "FERRETERIA", "FARMACIA", "DROGUERIA", "SUPERMERCADO", "MINIMERCADO",
    "RESTAURANTE", "CAFETERIA", "PANADERIA", "HELADERIA", "CHURRERIA",
    "HOTEL", "HOSTAL", "POSADA", "ALOJAMIENTO", "GLAMPING",
    "CLINICA", "CONSULTORIO", "LABORATORIO", "OPTICA", "ORTOPEDIA",
    "COLEGIO", "INSTITUTO", "ACADEMIA", "CENTRO EDUCATIVO", "JARDIN INFANTIL",
    "CONSTRUCTORA", "INMOBILIARIA", "ARQUITECTOS", "INGENIERIA",
    "TRANSPORTES", "LOGISTICA", "ALMACENES", "BODEGAS", "MUDANZAS",
    "TECNOLOGIA", "SISTEMAS", "SOFTWARE", "INFORMATICA", "REDES",
    "SERVICIOS", "MANTENIMIENTO", "LIMPIEZA", "SEGURIDAD", "VIGILANCIA",
    "CONTABILIDAD", "ASESORIA", "CONSULTORIA", "AUDITORIA", "JURIDICA",
    "MARKETING", "PUBLICIDAD", "DISEÑO", "COMUNICACIONES", "MEDIOS",
    "TEXTILES", "CALZADO", "ROPA", "MODA", "ACCESORIOS", "JOYERIA",
    "AUTOPARTES", "REPUESTOS", "TALLER", "MECANICA", "NEUMATICOS",
    "FERRETERIA", "MATERIALES", "ACEROS", "HERRAMIENTAS", "PINTURAS",
    "AGROPECUARIA", "GANADERA", "AGRICOLA", "VETERINARIA", "INSUMOS",
    "TURISMO", "VIAJES", "TOURS", "GUIAS", "AGENCIA",
    "EVENTOS", "ESPECTACULOS", "ENTRETENIMIENTO", "RECREACION", "DEPORTES",
    "ALIMENTOS", "BEBIDAS", "CARNICERIA", "PANADERIA", "LACTEOS", "FRUTAS",
    "VIVEROS", "FLORERIA", "SEMILLAS", "ABONOS", "MAQUINARIA",
]


# ============================================================================
# FUNCIONES DE GENERACIÓN
# ============================================================================

def generar_nit_valido() -> str:
    """Genera un NIT colombiano válido (9-10 dígitos, sin placeholders)."""
    prefix = random.choice(NIT_PREFIXES)
    # NIT colombiano típico: 9-10 dígitos
    longitud = random.choice([9, 10])
    resto = longitud - len(prefix)
    digitos = ''.join(str(random.randint(0, 9)) for _ in range(resto))
    return prefix + digitos


def generar_razon_social(sector: str, municipio: str) -> str:
    """Genera una razón social genérica pero realista."""
    palabras_sector = {
        "Gastronomía y Hotelería": ["RESTAURANTE", "CAFETERIA", "HOTEL", "HOSTAL", "ALOJAMIENTO", "GLAMPING", "PANADERIA", "HELADERIA"],
        "Ferretería y construcción menor": ["FERRETERIA", "MATERIALES", "ACEROS", "HERRAMIENTAS", "PINTURAS", "CONSTRUCTORA"],
        "Salud": ["CLINICA", "CONSULTORIO", "LABORATORIO", "OPTICA", "ORTOPEDIA", "VETERINARIA"],
        "Salud / Farmacias": ["FARMACIA", "DROGUERIA", "BOTICA", "FARMACIA"],
        "Educación": ["COLEGIO", "INSTITUTO", "ACADEMIA", "CENTRO EDUCATIVO", "JARDIN INFANTIL"],
        "Comercio / Retail": ["ALMACEN", "SUPERMERCADO", "MINIMERCADO", "DISTRIBUIDORA", "IMPORTADORA", "TEXTILES", "CALZADO", "ROPA"],
        "Manufactura": ["FABRICA", "INDUSTRIA", "MAQUILA", "PRODUCCION", "MANUFACTURA"],
        "Otros servicios": ["SERVICIOS", "MANTENIMIENTO", "LIMPIEZA", "SEGURIDAD", "VIGILANCIA"],
        "Servicios profesionales": ["CONTABILIDAD", "ASESORIA", "CONSULTORIA", "AUDITORIA", "JURIDICA", "ARQUITECTOS", "INGENIERIA"],
        "Servicios de apoyo empresarial": ["LOGISTICA", "ALMACENES", "BODEGAS", "MUDANZAS", "TRANSPORTES"],
        "Servicios públicos": ["ACUEDUCTO", "ENERGIA", "GAS", "ASEO", "TELECOMUNICACIONES"],
        "Tecnología / Comunicaciones": ["TECNOLOGIA", "SISTEMAS", "SOFTWARE", "INFORMATICA", "REDES", "TELECOMUNICACIONES"],
        "Entretenimiento": ["EVENTOS", "ESPECTACULOS", "ENTRETENIMIENTO", "RECREACION", "DEPORTES", "BAR", "DISCOTECA"],
        "Transporte y logística": ["TRANSPORTES", "LOGISTICA", "MUDANZAS", "CARGA", "PAQUETERIA"],
    }.get(sector, ["COMERCIAL", "DISTRIBUIDORA", "EMPRESA", "NEGOCIO"])

    base = random.choice(palabras_sector)
    sufijo = random.choice(SUFIJOS_EMPRESA)
    ciudad = municipio.split()[0]  # primera palabra del municipio
    return f"{base} {ciudad.upper()} {sufijo}"


def generar_direccion(municipio: str) -> str:
    """Genera una dirección comercial genérica."""
    tipos_via = ["CR", "CL", "AV", "TV", "DG", "AN"]
    tipo = random.choice(tipos_via)
    num1 = random.randint(1, 200)
    num2 = random.randint(1, 99)
    num3 = random.randint(1, 99)
    barrio = random.choice(["CENTRO", "NORTE", "SUR", "ORIENTE", "OCCIDENTE", "LAURELES", "EL POBLADO", "CHAPINERO", "USAQUEN", "SUBA"])
    return f"{tipo} {num1} #{num2}-{num3} BR {barrio} {municipio}"


def generar_telefono() -> str | None:
    """Genera un teléfono comercial colombiano o None."""
    if random.random() < 0.7:  # 70% tiene teléfono
        prefijo = random.choice(["601", "602", "604", "605", "606", "607", "608", "300", "301", "302", "304", "305", "310", "311", "312", "313", "314", "315", "316", "317", "318", "319", "320", "321", "322", "323"])
        numero = ''.join(str(random.randint(0, 9)) for _ in range(7))
        return f"{prefijo}{numero}"
    return None


def generar_email(razon_social: str) -> str | None:
    """Genera un email comercial genérico o None."""
    if random.random() < 0.5:  # 50% tiene email
        # Limpiar razón social para email
        base = ''.join(c.lower() for c in razon_social if c.isalnum() or c == ' ')[:30]
        base = base.replace(' ', '')
        dominios = ["gmail.com", "hotmail.com", "yahoo.com", "outlook.com", "empresa.com", "negocio.co"]
        return f"{base}@{random.choice(dominios)}"
    return None


def generar_ciiu_para_sector(sector: str) -> str:
    """Genera un código CIIU coherente con el sector."""
    mapeo = {
        "Gastronomía y Hotelería": ["I5610", "I5621", "I5629", "I5630", "I5510", "I5520"],
        "Ferretería y construcción menor": ["G4752", "G4663", "G4662", "G4741"],
        "Salud": ["Q8610", "Q8620", "Q8690", "Q8710", "Q8720"],
        "Salud / Farmacias": ["G4773", "G4772"],
        "Educación": ["P8510", "P8521", "P8522", "P8530", "P8541", "P8542"],
        "Comercio / Retail": ["G4711", "G4719", "G4721", "G4722", "G4730", "G4741", "G4751", "G4759", "G4761", "G4762", "G4763", "G4764", "G4771", "G4772", "G4773", "G4774", "G4775", "G4776", "G4777", "G4778", "G4779", "G4781", "G4782", "G4789", "G4791", "G4799"],
        "Manufactura": ["C1010", "C1020", "C1030", "C1040", "C1050", "C1061", "C1062", "C1071", "C1072", "C1073", "C1074", "C1075", "C1079"],
        "Otros servicios": ["S9601", "S9602", "S9603", "S9609"],
        "Servicios profesionales": ["M6910", "M6920", "M7010", "M7020", "M7110", "M7120", "M7210", "M7220", "M7310", "M7320"],
        "Servicios de apoyo empresarial": ["N7710", "N7720", "N7730", "N7740", "N7810", "N7820", "N7830", "N7910", "N7920", "N8010", "N8020", "N8030", "N8110", "N8121", "N8122", "N8129", "N8130"],
        "Servicios públicos": ["D3510", "D3520", "D3530", "D3600", "D3700", "D3811", "D3812", "D3821", "D3822", "D3830"],
        "Tecnología / Comunicaciones": ["J6110", "J6120", "J6130", "J6190", "J6201", "J6202", "J6203", "J6209", "J6311", "J6312"],
        "Entretenimiento": ["R9000", "R9101", "R9102", "R9103", "R9200", "R9311", "R9312", "R9313", "R9321", "R9329"],
        "Transporte y logística": ["H4911", "H4912", "H4921", "H4922", "H4923", "H5011", "H5012", "H5021", "H5022", "H5110", "H5120", "H5210", "H5221", "H5222", "H5223", "H5224", "H5229", "H5310", "H5320"],
    }
    codigos = mapeo.get(sector, ["G4711"])
    return random.choice(codigos)


def generar_num_empleados(tamano: str) -> int | None:
    """Genera número de empleados coherente con tamaño."""
    rangos = {
        "micro": (1, 10),
        "pequena": (11, 50),
        "mediana": (51, 200),
        "grande": (201, 1000),
    }
    lo, hi = rangos.get(tamano, (1, 10))
    if random.random() < 0.85:  # 85% tiene dato
        return random.randint(lo, hi)
    return None


def generar_ultimo_ano_renovado() -> str | None:
    """Genera último año renovado (2015-2026)."""
    if random.random() < 0.8:  # 80% tiene dato
        return str(random.randint(2015, 2026))
    return None


def generar_activo_total(tamano: str) -> int | None:
    """Genera activo total coherente con tamaño (en COP millones)."""
    rangos = {
        "micro": (10, 500),
        "pequena": (500, 5000),
        "mediana": (5000, 50000),
        "grande": (50000, 500000),
    }
    lo, hi = rangos.get(tamano, (10, 500))
    if random.random() < 0.3:  # 30% tiene dato financiero
        return random.randint(lo, hi) * 1_000_000
    return None


def generar_entidad_sintetica(idx: int) -> dict:
    """Genera una entidad sintética completa."""
    municipio, departamento = random.choice(MUNICIPIOS_COLOMBIA)
    sector = random.choice(SECTORES_V2)
    encaje = SECTOR_ENCAJE[sector]
    tamano = random.choices(TAMANOS_EMPRESA, weights=TAMANO_PROBS)[0]
    tipo_org = random.choice(TIPOS_ORG)

    # Identificadores
    nit = generar_nit_valido()
    # Matrícula: 6-8 dígitos, a veces con formato
    matricula = str(random.randint(100000, 99999999))

    # Datos principales
    razon_social = generar_razon_social(sector, municipio)
    direccion = generar_direccion(municipio)
    telefono_1 = generar_telefono()
    telefono_2 = generar_telefono() if random.random() < 0.3 else None
    telefono_3 = generar_telefono() if random.random() < 0.1 else None
    email = generar_email(razon_social)

    # CIIU
    ciiu_1 = generar_ciiu_para_sector(sector)
    ciiu_2 = generar_ciiu_para_sector(sector) if random.random() < 0.4 else None
    ciiu_3 = generar_ciiu_para_sector(sector) if random.random() < 0.2 else None
    ciiu_4 = generar_ciiu_para_sector(sector) if random.random() < 0.1 else None

    # Empleados y vigencia
    num_empleados = generar_num_empleados(tamano)
    ultimo_ano_renovado = generar_ultimo_ano_renovado()
    activo_total = generar_activo_total(tamano)

    # Fechas (como strings, sin parsear - igual que en el original)
    fecha_matricula = f"{random.randint(1990, 2020)}{random.randint(1,12):02d}{random.randint(1,28):02d}"
    fecha_renovacion = f"{random.randint(2020, 2026)}{random.randint(1,12):02d}{random.randint(1,28):02d}"
    fecha_constitucion = f"{random.randint(1990, 2020)}{random.randint(1,12):02d}{random.randint(1,28):02d}"

    # CIIU descripciones
    actividad_descripcion = sector  # simplificado

    # Campos de trazabilidad (simulados)
    source_id = f"fuente_ejemplo_{random.randint(1, 10):02d}"
    fuente_archivo = f"{source_id}.csv"
    hoja_origen = "Hoja1"
    fila_origen = idx + 1

    # Entidad dedup ID (simulado como si ya pasó deduplicación)
    entidad_dedup_id = f"ENT-{idx+1:07d}"

    # Estado de exclusión - mayoría SIN_COINCIDENCIA, algunos CANDIDATO_AMBIGUO
    if random.random() < 0.99:
        estado_exclusion = "SIN_COINCIDENCIA"
    else:
        estado_exclusion = "CANDIDATO_AMBIGUO"

    # Confianza deduplicación (para nivel_confianza_score)
    confianza_dedup = random.choices(
        [None, "alta", "media_alta"],
        weights=[0.87, 0.08, 0.05]
    )[0]

    # Campos en conflicto (simulado)
    if confianza_dedup and random.random() < 0.1:
        campos_en_conflicto = "fecha_matricula;num_empleados"
    else:
        campos_en_conflicto = ""

    # Flag DANE ambiguo
    flag_codigo_dane_ambiguo = random.random() < 0.05

    return {
        "nit": nit,
        "matricula": matricula,
        "matricula_establecimiento": None,
        "razon_social": razon_social,
        "tipo_organizacion": tipo_org,
        "estado_matricula": "MA",
        "fecha_matricula": fecha_matricula,
        "fecha_renovacion": fecha_renovacion,
        "ultimo_ano_renovado": ultimo_ano_renovado,
        "fecha_constitucion": fecha_constitucion,
        "direccion_comercial": direccion,
        "barrio_comercial": None,
        "municipio_comercial": municipio,
        "departamento": departamento,
        "telefono_comercial_1": telefono_1,
        "telefono_comercial_2": telefono_2,
        "telefono_comercial_3": telefono_3,
        "email_comercial": email,
        "ciiu_1": ciiu_1,
        "ciiu_2": ciiu_2,
        "ciiu_3": ciiu_3,
        "ciiu_4": ciiu_4,
        "actividad_descripcion": actividad_descripcion,
        "tamano_empresa": tamano.upper(),
        "num_empleados": num_empleados,
        "activo_total": activo_total,
        "representante_legal": None,
        "grupo_niif": None,
        "bic": None,
        "categoria_matricula": None,
        # Campos calculados/enriquecidos
        "entidad_dedup_id": entidad_dedup_id,
        "source_id": source_id,
        "fuente_archivo": fuente_archivo,
        "hoja_origen": hoja_origen,
        "fila_origen": fila_origen,
        "estado_exclusion": estado_exclusion,
        "sector_vertical": sector,
        "encaje_pagos_declarado": encaje,
        "municipio_nombre_normalizado": municipio,
        "confianza_deduplicacion": confianza_dedup,
        "campos_en_conflicto": campos_en_conflicto,
        "flag_codigo_dane_ambiguo": flag_codigo_dane_ambiguo,
    }


def generar_dataset_sintetico(n: int = 1000) -> pd.DataFrame:
    """Genera DataFrame con n entidades sintéticas."""
    print(f"Generando {n} entidades sintéticas...")
    entidades = [generar_entidad_sintetica(i) for i in range(n)]
    df = pd.DataFrame(entidades)
    print(f"Generado DataFrame: {len(df)} filas, {len(df.columns)} columnas")
    return df


def calcular_scores_sinteticos(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica el motor de scoring real al dataset sintético."""
    print("Calculando Score de Prioridad Comercial con motor real...")
    scores = calcular_scores(df)
    out = pd.concat([df, scores], axis=1)
    out["fecha_calculo_score_utc"] = date.today().isoformat()
    print(f"Scores calculados. Rango: {out['score_prioridad_comercial'].min():.2f} - {out['score_prioridad_comercial'].max():.2f}")
    return out


def diversificar_top_n(df: pd.DataFrame, n: int = 100) -> pd.DataFrame:
    """Aplica la capa de diversificación real al Top N."""
    print(f"Construyendo Top {n} diversificado con motor real (M={M_SUAVIZADO})...")
    # Filtrar solo universo scoreable: solo SIN_COINCIDENCIA (el módulo exige esto)
    scoreable = df["estado_exclusion"] == "SIN_COINCIDENCIA"
    universo = df[scoreable].copy()

    config = ConfiguracionDiversificacion()
    resultado = construir_ranking_diversificado(universo, n, config=config)
    top_n = resultado["top_n"]
    stats = resultado["stats"]

    print(f"Top {n} construido: {stats['n_final']} admitidos")
    print(f"  Reemplazos por diversificación: {stats['n_reemplazos']}")
    print(f"  Protección calidad: {stats['n_proteccion_calidad']}")
    print(f"  Diferidos tope duro: {stats['n_diferidos_tope_duro']}")
    print(f"  Recuperados Fase 2: {stats['n_recuperados_fase2']}")

    return top_n


def main():
    parser = argparse.ArgumentParser(description="Genera dataset sintético para demo público")
    parser.add_argument("--n", type=int, default=1000, help="Número de entidades a generar (default: 1000)")
    parser.add_argument("--output", default="demo_data/empresas_sinteticas.parquet", help="Ruta de salida Parquet")
    parser.add_argument("--top-n", type=int, default=100, help="Tamaño del Top N diversificado (default: 100)")
    parser.add_argument("--seed", type=int, default=42, help="Semilla para reproducibilidad")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    print("=" * 60)
    print("GENERADOR DE DATASET SINTÉTICO - SALES_INTELLIGENCE DEMO")
    print("=" * 60)
    print(f"Semilla: {args.seed}")
    print(f"Entidades: {args.n}")
    print(f"Top N: {args.top_n}")
    print()

    # 1. Generar entidades base
    df = generar_dataset_sintetico(args.n)

    # 2. Calcular scores con motor real
    df_scored = calcular_scores_sinteticos(df)

    # 3. Guardar dataset completo scored
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df_scored.to_parquet(output_path, index=False)
    print(f"\nDataset scored guardado en: {output_path}")

    # 4. Generar Top N diversificado
    top_n = diversificar_top_n(df_scored, args.top_n)

    # 5. Guardar Top N
    top_n_path = output_path.parent / f"top{args.top_n}_diversificado_sintetico.parquet"
    top_n.to_parquet(top_n_path, index=False)
    print(f"Top {args.top_n} diversificado guardado en: {top_n_path}")

    # 6. También guardar CSV legible
    csv_path = output_path.parent / f"empresas_sinteticas.csv"
    df_scored.to_csv(csv_path, index=False)
    print(f"CSV legible guardado en: {csv_path}")

    top_n_csv = output_path.parent / f"top{args.top_n}_diversificado_sintetico.csv"
    top_n.to_csv(top_n_csv, index=False)
    print(f"Top N CSV guardado en: {top_n_csv}")

    # 7. Resumen de métricas
    print("\n" + "=" * 60)
    print("RESUMEN DE MÉTRICAS SINTÉTICAS")
    print("=" * 60)
    print(f"Total entidades generadas: {len(df_scored)}")
    print(f"  SIN_COINCIDENCIA: {(df_scored['estado_exclusion'] == 'SIN_COINCIDENCIA').sum()}")
    print(f"  CANDIDATO_AMBIGUO: {(df_scored['estado_exclusion'] == 'CANDIDATO_AMBIGUO').sum()}")
    print(f"Score range: {df_scored['score_prioridad_comercial'].min():.2f} - {df_scored['score_prioridad_comercial'].max():.2f}")
    print(f"Score mean: {df_scored['score_prioridad_comercial'].mean():.2f}")
    print(f"Dimensiones con dato: {df_scored['dimensiones_con_dato'].value_counts().to_dict()}")
    print(f"Nivel confianza: {df_scored['nivel_confianza_score'].value_counts().to_dict()}")
    print(f"Sectores: {df_scored['sector_vertical'].value_counts().head(10).to_dict()}")
    print(f"Municipios únicos: {df_scored['municipio_comercial'].nunique()}")
    print(f"Departamentos únicos: {df_scored['departamento'].nunique()}")

    print("\n✅ GENERACIÓN COMPLETA - Listo para demo público")
    print("⚠️  RECUERDO: Datos 100% SINTÉTICOS, no representan empresas reales")


if __name__ == "__main__":
    main()