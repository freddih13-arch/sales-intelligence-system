# SALES_INTELLIGENCE — Public Demo

**Commercial Intelligence Pipeline for Fintech / Payments / B2B Sales**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/release/python-312/)
[![Tests Passing](https://img.shields.io/badge/Tests-7%2F7-brightgreen.svg)](tests/)
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
| Tests automatizados | 31 validaciones de scoring + tests de config |

> ⚠️ **Esta demo usa 1,000 entidades SINTÉTICAS generadas con el motor real.** Las cifras arriba corresponden al sistema original auditado en producción.

---

## 🏗️ Arquitectura (7 fases)

```mermaid
flowchart TD
    RAW[01_BASES_RAW<br/>50 fuentes / 6.7M registros<br/>SOLO LECTURA] --> ING[1. INGESTA<br/>44 fuentes pequeñas/medianas<br/>Parquet inmutable]
    ING --> NORM[2. NORMALIZACIÓN<br/>Esquema canónico unificado<br/>541,511 registros]
    NORM --> DEDUP[3. DEDUPLICACIÓN<br/>Conservadora: solo NIT exacto + matrícula+cámara fusionan<br/>408,907 entidades / 37K candidatos trazables]
    DEDUP --> ENR[4. ENRIQUECIMIENTO<br/>CIIU → Sector Vertical (taxonomía V2)<br/>Tamaño, vigencia, confianza]
    ENR --> EXCL[5. EXCLUSIÓN vs PIPELINE INTERNO<br/>CRM + HUBS solo como llaves<br/>ALTA/MEDIA/AMBIGUO — nunca exclusión por nombre]
    EXCL --> SCORE[6. SCORING<br/>Fit 40% / Escala 35% / Contacto 25%<br/>Factor cobertura + Calidad peso 0]
    SCORE --> DIV[7. DIVERSIFICACIÓN<br/>Bayesiana M=22 / 2 fases / Tope duro<br/>Desempate F: SHA-256(entidad_dedup_id)]
    DIV --> TOP[TOP N LISTO PARA LLAMAR<br/>Explicable / Auditable / Reproducible]
```

---

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
./venv/bin/python tests/test_config.py
# 7/7 tests passing: estructura config, mapeos, scoring, advertencias
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