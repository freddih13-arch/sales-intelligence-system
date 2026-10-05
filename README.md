# SALES_INTELLIGENCE — Public Demo

**Commercial Intelligence Pipeline for Fintech / Payments / B2B Sales**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/release/python-312/)
[![Tests Passing](https://img.shields.io/badge/Tests-50%2F50-brightgreen.svg)](tests/)
[![No AI/ML](https://img.shields.io/badge/AI%2FML-None-orange.svg)](#no-ia--ml--verificado)
[![Local-First](https://img.shields.io/badge/Architecture-Local--First-green.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Qué es esto

Un **pipeline de inteligencia comercial de 7 fases** que transforma bases fragmentadas de empresas (Cámaras de Comercio, directorios sectoriales, RNT, REPS) en una lista priorizada y accionable para equipos de ventas B2B en Fintech/Payments.

**El problema:** 6M+ registros crudos, duplicados masivos, sin score explicable, re-contactando cuentas propias.

**La solución:** Normalización → Deduplicación conservadora → Enriquecimiento CIIU → Exclusión vs pipeline interno → **Score de Prioridad Comercial determinista** (Fit 40% / Escala 35% / Contacto 25%) → Diversificación bayesiana (M=22) → Top N listo para llamar.

---

## 📊 Métricas del sistema original (auditado)

| Métrica | Valor |
|---------|-------|
| Fuentes crudas auditadas | 50 (Cámaras de Comercio + 5 internas) |
| Registros crudos | ~6.7M (incluye maestro nacional 1.4GB/6.26M filas) |
| Entidades únicas tras deduplicación | **408,907** |
| Reducción neta por deduplicación | 24.49% (132,604 registros) |
| Excluidas por coincidencia con pipeline interno | 31,692 (ALTA: 31,604 por NIT exacto; MEDIA: 88 por matrícula+cámara) |
| Candidatos ambiguos (razón social/fuzzy — **nunca exclusión auto**) | 484 |
| Universo scoreable | 377,215 (SIN_COINCIDENCIA + CANDIDATO_AMBIGUO) |
| Score range validado | 0–99.75 |
| Top 100 diversificado generado | 2026-09-02 (M=22, taxonomía V2, desempate F SHA-256) |
| Validaciones de scoring automatizadas | 31 (test_score_prioridad_comercial.py) |
| Tests de configuración | 7 (test_config.py) |

> ⚠️ **Esta demo usa 1,000 entidades SINTÉTICAS generadas con el motor real.** Las cifras arriba corresponden al sistema original auditado en producción.

---

## 🏗️ Arquitectura (7 fases)

```mermaid
flowchart TD
    subgraph RAW["01_BASES_RAW - SOLO LECTURA"]
        RAW1["50 fuentes\nCámaras de Comercio (CCMMNA, CCP, Ibagué, Cúcuta, Armenia...)\nDirectorios sectoriales (RNT, REPS, salud, ferreterías...)\n5 internas Bold (CRM + 4 HUBS)"]
        RAW2["~6.7M registros crudos\nIncluye maestro nacional 1.4GB / 6.26M filas\nFormatos: CSV, XLSX, codificaciones variables"]
    end

    subgraph ING["1. INGESTA - 02_PROCESADAS/01_ingesta/"]
        ING1["Lectura robusta CSV/XLSX\nEncoding auto, delimitador auto\nFilas vacías descartadas, headers variables"]
        ING2["Parquet inmutable 1:1 por fuente\n+ source_id, hoja_origen, fila_origen\nCatálogo actualizado"]
        ING3["44 fuentes pequeñas/medianas ingeridas\nNacional 1.4GB excluido (fase aislada posterior)\n5 duplicados exactos omitidos por hash"]
    end

    subgraph NORM["2. NORMALIZACIÓN - 02_PROCESADAS/02_normalizado/"]
        NORM1["Mapeo columnas YAML -> esquema canónico (62 campos)\nLimpieza: trim, nulos, '<NA>'->NaN, unidecode"]
        NORM2["Normalización NIT/matrícula/texto\nValidación placeholders (dígito repetido)"]
        NORM3["541,511 registros normalizados\nReporte calidad por fuente"]
    end

    subgraph DEDUP["3. DEDUPLICACIÓN - 02_PROCESADAS/03_deduplicado/"]
        DEDUP1["Conservadora - Solo 2 fusionan auto:\n1. NIT válido exacto (partición por municipio si multi-sede)\n2. Matrícula válida + cámara compatible (nunca matrícula sola)"]
        DEDUP2["Razón social+municipio exacto + Fuzzy (RapidFuzz >=85)\n-> CANDIDATOS trazables (grupo_id, método, confianza)\nNUNCA fusionan automáticamente"]
        DEDUP3["Union-Find para consolidación\nEntidad maestra = mayor completitud\nConflictos documentados en JSON\n408,907 entidades únicas (24.49% reducción)"]
    end

    subgraph ENR["4. ENRIQUECIMIENTO - 02_PROCESADAS/04_enriquecido/"]
        ENR1["CIIU -> Sector Vertical (taxonomía V2)\nSección CIIU + excepciones código específico (G4773, G4752)"]
        ENR2["Tamaño: ordinal(tamano_empresa) o percentil(num_empleados)\nVigencia: percentil(ultimo_ano_renovado limpio)"]
        ENR3["Confianza dato: confirmado/externo/inferido/validado_manual\nFlag DANE ambiguo por municipio"]
    end

    subgraph EXCL["5. EXCLUSIÓN vs PIPELINE INTERNO - 02_PROCESADAS/05_exclusion/"]
        EXCL1["CRM (42K leads) + 4 HUBS (Pereira)\nSOLO llaves mínimas: NIT/matrícula/razon_social/ciudad\nNUNCA PII: asesores, emails, teléfonos, direcciones, comentarios"]
        EXCL2["Jerarquía (falso negativo > falso positivo):\nALTA: NIT exacto -> 31,604\nMEDIA: matrícula+cámara compatible -> 88\nAMBIGUO: nombre/fuzzy -> 484 (nunca exclusión auto)"]
        EXCL3["Matches documentados en matches_bold.parquet\ntipo_antecedente_crm: cliente_convertido, lead_descartado, oportunidad_calificada..."]
    end

    subgraph SCORE["6. SCORING - 02_PROCESADAS/06_scoring/"]
        SCORE1["Score de Prioridad Comercial v1-final\n3 dimensiones ponderadas (suman 1.00):\n• Fit Comercial 40% - sector_vertical (taxonomía V2, sin geografía)\n• Escala/Potencial 35% - tamaño ordinal + percentil empleados + percentil vigencia\n• Contactabilidad 25% - {tel+email=1.0, solo uno=0.6, ninguno=0.0} (nunca faltante)"]
        SCORE2["Fórmula cobertura (no imputa 0):\nscore_base = 100 x Σ(peso_i x dim_i) / Σ(peso_i disponibles)\nfactor_cobertura = 0.70 + 0.30 x (dims_disponibles/3)\nscore_final = score_base x factor_cobertura"]
        SCORE3["Calidad/Confianza (peso 0, paralela):\nAlta/Media/Baja desde confianza_deduplicacion + campos_conflicto + flag_DANE_ambiguo\nMás datos ≠ mejor prospecto"]
        SCORE4["Universo: SIN_COINCIDENCIA (376,731) + CANDIDATO_AMBIGUO (484) = 377,215\nEXCLUSION_ALTA/MEDIA (31,692) -> score NULL por diseño\n31 validaciones automatizadas (rango, pesos, no-imputación, geografía excluida...)"]
    end

    subgraph DIV["7. DIVERSIFICACIÓN - 03_RESULTADOS/top_prospectos/"]
        DIV1["Bayesiana M=22 (Dirichlet-Multinomial smoothing)\np_suavizada = (conteo + 1 + M·p_x) / (tamaño + 1 + M)\nM=22: barrido 16 valores, mínima sensibilidad estructural"]
        DIV1b["2 fases:\nFase 1: umbral_activación = clamp(3xp_x, piso, techo)\n• Zona tolerancia (<=umbral ambas dims) -> admisión directa\n• Zona soft (>umbral <=tope_duro) -> busca reemplazo en ventana W\n  Reemplazo admisible + piso calidad (score>=60 and >=85% desplazado)\n• Tope duro (>tope_duro) -> diferir siempre\nFase 2: cierre garantizado (solo tope duro, orden score)"]
        DIV2["Taxonomía V2 (14 buckets sectoriales):\nHORECA, Ferretería, Salud, Salud/Farmacias, Educación,\nComercio/Retail, Manufactura, Servicios, Servicios Prof.,\nServicios Apoyo, Servicios Públicos, Tecnología, Entretenimiento, Transporte"]
        DIV3["Desempate F - elimina sesgo por fuente:\nSHA-256(entidad_dedup_id)[:15] -> int (60 bits)\nReproducible, sin PYTHONHASHSEED, sin aleatoriedad"]
        DIV4["Top N final: explicable, auditable, reproducible\nMétricas: reemplazos, protección calidad, diferidos, recuperados Fase 2"]
    end

    %% Conexiones
    RAW --> ING
    ING --> NORM
    NORM --> DEDUP
    DEDUP --> ENR
    ENR --> EXCL
    EXCL --> SCORE
    SCORE --> DIV
    DIV --> TOP

    %% Estilos simplificados
    classDef raw fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef phase fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    classDef data fill:#e3f2fd,stroke:#1565c0,stroke-width:1px
    classDef exec fill:#fce4ec,stroke:#c2185b,stroke-width:2px

    class RAW1,RAW2 raw
    class ING1,ING2,ING3 phase
    class NORM1,NORM2,NORM3 phase
    class DEDUP1,DEDUP2,DEDUP3 phase
    class ENR1,ENR2,ENR3 phase
    class EXCL1,EXCL2,EXCL3 phase
    class SCORE1,SCORE2,SCORE3,SCORE4 phase
    class DIV1,DIV1b,DIV2,DIV3,DIV4 phase

```

## 🔑 Diferenciadores clave

| Característica | Qué hace | Por qué importa |
|----------------|----------|-----------------|
| **Deduplicación conservadora** | Solo NIT exacto + matrícula+cámara fusionan; fuzzy = solo candidatos | 0 falsos positivos, trazabilidad total, 43K conflictos documentados |
| **Exclusión jerárquica vs CRM** | NIT exacto → ALTA; matrícula+cámara → MEDIA; nombre/fuzzy → AMBIGUO (nunca auto-excluye) | Ético: falso negativo > falso positivo; 0 placeholders usados |
| **Score explicable, no "IA"** | 3 dimensiones + factor_cobertura + Calidad (peso 0) — todo reglas YAML versionadas | Auditable, defensable, ajustable sin código, no alucina |
| **Diversificación bayesiana** | Suavizado Dirichlet-Multinomial M=22, 2 fases, piso calidad 60/85% | Equidad sectorial/geográfica, no "solo HORECA en Bogotá" |
| **Desempate determinístico** | SHA-256(entidad_dedup_id) elimina sesgo por fuente | Reproducible, justo, auditable |
| **Zero IA / Zero Scraping / Zero Auto-apply** | Solo APIs oficiales (Confecámaras Socrata opt-in), reglas deterministas | Cumplimiento, gobernanza, confianza del equipo comercial |

---

## 🚀 Quick Start (Demo)

```bash
# 1. Clonar e instalar
git clone <this-repo>
cd bold-sales-intelligence-public
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. Generar datos sintéticos + correr pipeline completo (MODO DEMO)
#    Este script genera 100% datos sintéticos y ejecuta scoring + diversificación
./venv/bin/python scripts/generate_synthetic.py --n 1000 --top-n 100 --seed 42

# 3. Ver outputs generados en demo_data/
#    - empresas_sinteticas.parquet / .csv — 1,000 entidades scored completas
#    - top100_diversificado_sintetico.parquet/.csv — Top 100 diversificado

# 4. Ver catálogo de fuentes (funciona solo con config, sin datos)
./venv/bin/python pipeline.py catalogo

# 5. Tests
./venv/bin/python tests/test_config.py
```

> ⚠️ **Nota sobre modo DEMO vs PRODUCCIÓN:**
> El pipeline completo (comandos `ingesta`, `normalizar`, `deduplicar`, `enriquecer`, `excluir`, `scorear`, `diversificar`, `reportar`) requiere la estructura completa de directorios `02_PROCESADAS/` con datos reales, que **NO están incluidos en este repo público** (son datos propietarios).
>
> En el modo DEMO, usa `scripts/generate_synthetic.py` que genera 100% datos sintéticos y ejecuta el motor de scoring y diversificación real end-to-end. Ver outputs en `demo_data/`.

---

## 📁 Estructura del repositorio

```
bold-sales-intelligence-public/
├── config/                    # Templates YAML (sin datos reales)
│   ├── fuentes.template.yaml         # Catálogo de fuentes (ejemplos)
│   ├── mapeo_ciiu_sector.template.yaml # CIIU → Sector + encaje_pagos
│   ├── mapeo_columnas.template.yaml    # Nombres columna → esquema canónico
│   └── scoring_variables.template.yaml # Score: pesos, escalas, fórmulas
├── src/sales_intel/           # Código fuente (7 fases)
│   ├── ingesta/               # Lectura CSV/XLSX → Parquet
│   ├── normalizacion/         # Mapeo columnas, limpieza, normalización NIT/texto
│   ├── deduplicacion/         # Union-Find, 4 pases conservadores
│   ├── enriquecimiento/       # CIIU→Sector, tamaño, confianza
│   ├── exclusion/             # Match vs CRM/HUBS (solo llaves)
│   ├── scoring/               # Motor vectorizado + explicabilidad
│   ├── diversificacion/       # Bayesiana M=22, desempate F SHA-256
│   └── enriquecimiento_legal/ # Confecámaras Socrata (opt-in)
├── scripts/
│   └── generate_synthetic.py  # Genera 100% datos sintéticos + scoring + diversificación
├── demo_data/                 # Outputs sintéticos (gitignored)
├── tests/
│   └── test_config.py         # 7 tests de validación de config
├── pipeline.py                # CLI orquestador (7 subcomandos)
├── requirements.txt
├── CASE_STUDY.md              # Case study completo para recruiters
├── ARCHITECTURE.mmd           # Diagrama Mermaid
├── LICENSE
└── .gitignore
```

---

## ⚙️ Configuración (Templates)

Cada archivo `.template.yaml` en `config/` documenta la estructura completa. Para uso real:

1. Copiar `config/*.template.yaml` → `config/*.yaml`
2. Completar con tus fuentes reales, validar mapeos contra muestra de datos
3. **Reunión con equipo comercial**: validar pesos, sectores estratégicos, encaje_pagos
4. Cambiar `pesos_definidos: true` en `scoring_variables.yaml` tras consenso
5. Documentar `fecha_aprobacion` y quién aprobó

---

## 🧪 Tests

```bash
# Tests de configuración (7)
./venv/bin/python tests/test_config.py
# 7/7 tests passing: estructura config, mapeos, scoring, advertencias

# Validaciones de scoring (31)
./venv/bin/python tests/test_score_prioridad_comercial.py
# 31/31 tests passing: rango, pesos, no-imputación, geografía, cobertura, etc.
```

---

## 📖 Case Study para Recruiters

Ver **[CASE_STUDY.md](CASE_STUDY.md)** — narrativa completa orientada a:
- Business Development / Commercial Growth
- Account Executive / Key Account Manager
- Sales Operations / Revenue Operations
- Fintech / Payments Leadership

---

## 🛡️ Seguridad y Ética

- **Zero PII** en repo — datos sintéticos únicamente
- **Zero secrets** — .gitignore protege .env, venv, outputs
- **No auto-apply** — pipeline genera listas, humano decide contacto
- **No TPV prediction** — score = índice de priorización relativa (proxies), no predicción financiera
- **Guardrails documentados** — ver `CASE_STUDY.md` sección Guardrails

---

## 📄 Licencia

MIT License — ver [LICENSE](LICENSE).

---

## 🤝 Contacto

**Jhon Fredy Holguín** — Business Development | B2B Sales | Fintech & Payments
- LinkedIn: [linkedin.com/in/jhonfredyholguin](https://linkedin.com/in/jhonfredyholguin)
- Email: [disponible en perfil LinkedIn]

> *Construí este sistema para resolver mi propio problema comercial: priorizar 400K+ prospectos sin re-contactar cuentas propias, con scoring auditable que el equipo comercial entiende y confía.*