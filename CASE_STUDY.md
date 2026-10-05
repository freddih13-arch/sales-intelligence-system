# Case Study — SALES_INTELLIGENCE
**Commercial Intelligence Pipeline for Fintech / Payments / B2B Sales**

---

## 1. PROBLEM STATEMENT

### Contexto comercial
Como profesional de **Business Development / B2B Sales en Fintech & Payments** (7+ años, experiencia en Client, Banco Santander, Banco W), enfrentaba un problema recurrente:

> **El equipo comercial tiene 6M+ registros crudos de 50 fuentes (Cámaras de Comercio, RNT, REPS, directorios sectoriales) pero no sabe a quién llamar primero. Pierde horas en duplicados, re-contacta cuentas ya en pipeline, y no tiene un criterio objetivo y explicable para priorizar.**

### Dolor específico
| Dolor | Impacto |
|-------|---------|
| Duplicados masivos | Misma empresa en 4-5 cámaras → llamadas repetidas, frustración |
| Re-contactar pipeline propio | 31K+ cuentas ya en pipeline interno → molestia al cliente, pérdida de credibilidad |
| Score "caja negra" | Herramientas genéricas no explican *por qué* un prospecto está arriba |
| Sesgo geográfico/sectorial | Equipo solo llama a Bogotá/Medellín y HORECA → deja dinero en la mesa |
| Datos sucios | NITs "0", matrículas placeholder, CIIUs sin letra, formatos de fecha inconsistentes |
| Sin proceso repetible | Cada vendedor usa su Excel, no hay trazabilidad ni aprendizaje institucional |

---

## 2. SOLUTION OVERVIEW

Diseñé y construí **SALES_INTELLIGENCE V1**: un **pipeline local-first de 7 fases** que convierte bases fragmentadas en un **Top N diversificado, explicable y accionable** para el equipo comercial.

```
01_BASES_RAW (50 fuentes, 6.7M regs, SOLO LECTURA)
       │
       ▼
[1] INGESTA → 44 fuentes Parquet inmutables
       │
       ▼
[2] NORMALIZACIÓN → Esquema canónico unificado (541K regs)
       │
       ▼
[3] DEDUPLICACIÓN → Conservadora: NIT exacto + matrícula+cámara fusionan;
                    Razón social/fuzzy = solo candidatos trazables
                    → 408,907 entidades únicas (24.49% reducción)
       │
       ▼
[4] ENRIQUECIMIENTO → CIIU→Sector Vertical (taxonomía V2), Tamaño, Vigencia, Confianza
       │
       ▼
[5] EXCLUSIÓN vs PIPELINE INTERNO → Pipeline interno solo como llaves mínimas (NIT/matrícula)
                    ALTA (NIT exacto): 31,604
                    MEDIA (matrícula+cámara): 88
                    AMBIGUO (nombre/fuzzy): 484 — **nunca exclusión automática**
       │
       ▼
[6] SCORING → Score de Prioridad Comercial determinista
                    Fit Comercial 40% | Escala/Potencial 35% | Contactabilidad 25%
                    + Factor Cobertura (datos faltantes) + Calidad peso 0 (paralela)
       │
       ▼
[7] DIVERSIFICACIÓN → Bayesiana M=22, 2 fases, Tope duro, Piso calidad 60/85%
                    Desempate F: SHA-256(entidad_dedup_id) — elimina sesgo por fuente
       │
       ▼
TOP N LISTO PARA LLAMAR — Explicable, Auditable, Reproducible
```

---

## 3. KEY ENGINEERING DECISIONS (con evidencia)

### 3.1 Deduplicación Conservadora — "Falso negativo > Falso positivo"
- **Solo 2 mecanismos fusionan automáticamente**: NIT válido exacto (con partición por municipio para multi-sede) + Matrícula válida + cámara compatible (nunca matrícula sola)
- **Razón social + municipio exacto + Fuzzy (RapidFuzz ≥85)** generan **candidatos trazables** (`candidato_grupo_id`, `candidato_metodo`, `candidato_confianza`) — **nunca fusionan**
- **Resultado**: 54,715 grupos consolidados (187K regs), 37,264 grupos candidatos (75K regs), 278K sin duplicado, 43K conflictos documentados en JSON — **0 placeholders usados**
- **Evidencia**: `reporte_deduplicacion.md`, `ejecutar_deduplicacion.py`

### 3.2 Exclusión Jerárquica vs Pipeline Interno — Ética por diseño
- **Pipeline interno (42K leads) + 4 HUBS comerciales (Pereira)** se leen **solo para extraer llaves mínimas** (NIT/matrícula/razón_social/ciudad) — **NUNCA se copian nombres de asesores, emails, teléfonos, direcciones, comentarios internos**
- **3 niveles**: ALTA (NIT exacto, 31,604) > MEDIA (matrícula+cámara compatible, 88) > AMBIGUO (razón social exacta/fuzzy, 484 — **nunca exclusión auto**)
- **Principio**: "Ante duda, CANDIDATO_AMBIGUO, nunca EXCLUSION_*" — falso negativo preferido sobre falso positivo
- **Evidencia**: `reporte_exclusion_internal.md`, `ejecutar_exclusion.py`

### 3.3 Score de Prioridad Comercial — Explicable, no "IA"
- **3 dimensiones ponderadas (suman 1.00)**: Fit Comercial 40% | Escala/Potencial 35% | Contactabilidad 25%
- **Calidad/Confianza**: Capa paralela **peso 0** — derivada solo de deduplicación (confianza_deduplicacion + campos_en_conflicto + flag_dane_ambiguo). **Más datos ≠ mejor prospecto**
- **Datos faltantes**: Promedio ponderado renormalizado SOLO sobre dimensiones disponibles + `factor_cobertura = 0.70 + 0.30×(n_disponibles/3)` — **nunca imputa 0**
- **Contactabilidad**: Nunca faltante — valores exactos {0.00, 0.60, 1.00} garantizan ≥1 dimensión siempre
- **Geografía**: Explícitamente **excluida** del score (departamento tiene 1 solo valor en dataset)
- **Evidencia**: `scoring_variables.yaml`, `motor_scoring.py`, `test_score_prioridad_comercial.py` (31 validaciones)

### 3.4 Diversificación Bayesiana — Equidad sectorial/geográfica
- **Mecanismo**: Suavizado Dirichlet-Multinomial `p_suavizada = (conteo + 1 + M·p_x) / (tamaño + 1 + M)` con **M=22** (barrido 16 valores, mínima sensibilidad estructural)
- **2 fases**: Fase 1 (umbral activación + zona soft con búsqueda reemplazo en ventana W + piso calidad) → Fase 2 (cierre garantizado solo tope duro)
- **Tope duro**: `clamp(activación + 10%, piso, techo_duro)` — nunca se admite directo si supera tope
- **Piso calidad**: Reemplazo debe tener score ≥ 60 absoluto Y ≥ 85% del desplazado
- **Taxonomía V2**: 14 buckets sectoriales (HORECA, Ferretería, Salud, Educación, Comercio, Manufactura, Servicios, Tecnología, Entretenimiento, Transporte, Otros, Sin dato) + municipios reales
- **Evidencia**: `capa_diversificacion.py`, `decision_final_M_suavizado.md`, `validacion_taxonomia_v2.md`

### 3.5 Desempate Determinístico F — Elimina sesgo por fuente
- `entidad_dedup_id` es secuencial por bloques de fuente → correlaciona con sector/geografía
- **Solución**: `SHA-256(entidad_dedup_id)[:15]` → int (60 bits) — reproducible, sin `PYTHONHASHSEED`, sin aleatoriedad
- **Evidencia**: `capa_diversificacion.py:clave_desempate_hash`, `analisis_criterio_desempate.md`

---

## 4. VERIFIED METRICS (Sistema Original Auditado)

| Métrica | Valor | Evidencia |
|---------|-------|-----------|
| Fuentes crudas auditadas | 50 | `00_auditoria_01_BASES_RAW.md` |
| Registros crudos totales | ~6.7M (1.4GB nacional) | `ARQUITECTURA.md` |
| Entidades únicas deduplicadas | **408,907** | `reporte_deduplicacion.md`, `empresas_scored.parquet` |
| Reducción neta deduplicación | 24.49% (132,604 regs) | `reporte_deduplicacion.md` |
| Consolidados NIT exacto | 53,213 grupos (184,168 regs) | `reporte_deduplicacion.md` |
| Consolidados matrícula+cámara | 1,169 grupos (2,354 regs) | `reporte_deduplicacion.md` |
| Candidatos razon_social+municipio | 31,476 grupos (63,036 regs) | `reporte_deduplicacion.md` |
| Candidatos fuzzy | 5,788 grupos (12,500 regs) | `reporte_deduplicacion.md` |
| Exclusión ALTA (NIT exacto) | **31,604** | `reporte_exclusion_internal.md` |
| Exclusión MEDIA (matrícula+cámara) | **88** | `reporte_exclusion_internal.md` |
| Candidatos ambiguos (nunca exclusión auto) | **484** | `reporte_exclusion_internal.md` |
| Universo scoreable | 377,215 | `reporte_score_prioridad_comercial.md` |
| Score range validado | 0–99.75 | `test_score_prioridad_comercial.py` |
| Factor_cobertura observado | {0.80, 0.90, 1.00} | `reporte_score_prioridad_comercial.md` |
| Top 100 diversificado | 2026-09-02 | `top_prospectos/top100_diversificado_20260902.csv` |
| Validaciones scoring automatizadas | 31/31 passing | `test_score_prioridad_comercial.py` (11 nuevos + 20 preexistentes) |
| Tests de configuración | 7/7 passing | `test_config.py` |

> **Demo pública**: 1,000 entidades sintéticas generadas con el **mismo motor real** (seed=42, reproducible).

---

## 5. TECH STACK

| Capa | Tecnología | Justificación |
|------|------------|---------------|
| Lenguaje | Python 3.12 | Stdlib-first, ecosistema data |
| Datos | pandas + pyarrow (Parquet) | Vectorización, compresión, tipos |
| Config | YAML (PyYAML) | Versionable, legible, sin código |
| Matching difuso | RapidFuzz (token_sort_ratio) | Velocidad C++, precisión |
| Normalización texto | unidecode + stdlib unicodedata/re | Consistencia tildes/espacios |
| APIs externas | Confecámaras Socrata (opt-in) | Solo NIT, rate-limit, caché TTL |
| Testing | unittest (stdlib) + pytest (opcional) | Sin deps obligatorias para core |
| CLI | argparse | Subcomandos tipados, ayuda integrada |

**Zero dependencias obligatorias no estándar para el core** — PyYAML ya en sistema (python3-yaml via apt).

---

## 6. GUARDRAILS (No negociables)

| Guardrail | Implementación |
|-----------|----------------|
| **01_BASES_RAW solo lectura** | `assert_no_escritura_en_raw()` en todo `to_parquet()` / `to_csv()` |
| **No PII copiada de CRM/HUBS** | `ejecutar_exclusion.py` extrae solo NIT/matrícula/razon_social/ciudad; campos PII listados en `sin_mapear_v1` |
| **No exclusión automática por nombre** | CANDIDATO_AMBIGUO siempre para razon_social/fuzzy — humano revisa |
| **No placeholders como llaves** | `es_placeholder_identificador()` filtra "0", "0000000000000", dígito repetido |
| **Score ≠ Predicción TPV** | `nombre_score_prohibido: "predicción de TPV"` en config; advertencia en cada reporte |
| **No scraping / No enriquecimiento web V1** | Principio #6 ARQUITECTURA.md; Confecámaras solo opt-in vía API oficial |
| **No auto-apply / No envío automático** | Pipeline genera listas; humano decide contacto, canal, mensaje |
| **Reproducibilidad total** | Config YAML versionado, seeds fijas, desempate SHA-256, Parquet inmutables por fase |
| **Trazabilidad completa** | `source_id` + `fila_origen` + `hoja_origen` en cada entidad hasta el final |

---

## 7. COMMERCIAL VALUE DELIVERED

| Para el equipo comercial | Para la organización |
|-------------------------|---------------------|
| **Lista priorizada lista para llamar** (Top 100/500/1K/5K) | **Proceso auditable y defensable** ante auditoría/compliance |
| **Zero re-contacto** a 31K+ cuentas ya en pipeline | **Aprendizaje institucional**: feedback loop → temas de entrevista → prioriza métricas en siguiente outreach |
| **Diversificación real** — no solo HORECA en Bogotá | **Escalable**: mismo motor corre sobre 1K sintéticos o 400K reales |
| **Score explicable** — "¿Por qué este prospecto está arriba?" → desglose variable a variable | **Config como código** — pesos/sectores/umbrales en YAML versionado, no hardcodeado |
| **Trazabilidad** — cada dato rastreable a fuente original | **Zero vendor lock-in** — Python stdlib + pandas, sin cloud obligatorio |

---

## 8. WHAT'S NEXT (Roadmap honesto)

| Próximo paso | Estado | Bloqueador |
|--------------|--------|------------|
| Sensitivity analysis de pesos | Pendiente | Requiere tiempo de cómputo en 400K |
| Web UI simple (filtro/exploración Top N) | Pendiente | Decisión de stack frontend |
| Confecámaras enrichment at scale (Top 1K) | Pendiente | Rate limits API + aprobación legal |
| CRM feedback loop (ganado/perdido → re-peso) | Pendiente | Integración CRM + gobernanza datos |
| Parseo fechas/numéricos por fuente | Abierto | 4+ formatos fecha, 2 convenciones separadores |
| Tabla DANE municipios real | Abierto | Fuente oficial + reglas resolución conflictos |

---

## 9. DEMO PÚBLICA

```bash
# Genera 1,000 entidades sintéticas + scoring + diversificación Top 100
python scripts/generate_synthetic.py --n 1000 --top-n 100 --seed 42

# Ver catálogo de fuentes (templates)
python pipeline.py catalogo

# Correr scoring sobre sintético
python pipeline.py scorear

# Construir Top 50 diversificado
python pipeline.py diversificar --n 50

# Reporte filtrado
python pipeline.py reportar --top 10 --sector "Gastronomía y Hotelería"
```

**Outputs en `demo_data/` (sintéticos, reproducibles, seed=42):**
- `empresas_sinteticas.parquet/.csv` — 1,000 entidades scored completas
- `top100_diversificado_sintetico.parquet/.csv` — Top 100 listo para llamar

---

## 10. RECRUITER VALUE — Por qué esto importa para tu rol

| Rol objetivo | Qué demuestra este proyecto |
|--------------|----------------------------|
| **Business Development / Commercial Growth** | Diseño end-to-end de sistema de prospección: de datos sucios → lista accionable. Pensamiento de funnel, priorización, diversificación de cartera. |
| **Account Executive / Key Account Manager** | Entiende scoring de cuentas, exclusión vs pipeline propio, diversificación sectorial/geográfica, preparación de outreach con inteligencia previa. |
| **Sales Operations / Revenue Operations** | Arquitectura de datos limpia, scoring explicable (no caja negra), guardrails de gobernanza, feedback loop comercial, config versionada. |
| **Fintech / Payments Leadership** | Contexto regulatorio (Cámaras de Comercio, Confecámaras), exclusión ética vs base propia, no predicción TPV (compliance), cero PII risk. |

**Narrativa para entrevista (STAR):**
> **Situation:** 6M+ registros crudos, 50 fuentes, duplicados masivos, re-contactando cuentas propias, sin criterio objetivo.
> **Task:** Construir sistema que priorice prospectos sin re-contactar pipeline, explicable para el equipo comercial, auditable.
> **Action:** Pipeline 7 fases local-first: ingesta → normalización → deduplicación conservadora (Union-Find) → enriquecimiento CIIU → exclusión jerárquica vs CRM (NIT/matrícula) → scoring determinista 3 dims (Fit/Escala/Contacto) + factor_cobertura → diversificación bayesiana M=22 + desempate SHA-256. Config YAML versionado, zero IA, zero scraping, zero auto-apply.
> **Result:** 408,907 entidades únicas, 31,604 excluidas por NIT exacto, 377K scored, Top 100 diversificado listo para llamar. 31 tests automatizados. Equipo comercial usa lista priorizada con confianza.

---

## 11. AI CLAIM VALIDATION

**Veredicto: Automation/data-driven** (NO "AI-powered", NO "AI-assisted", NO "ML")

| Componente | Tipo real | Por qué NO es IA/ML |
|------------|-----------|---------------------|
| Deduplicación | Union-Find + reglas deterministas | RapidFuzz = string matching algorítmico, no ML |
| Exclusión vs pipeline interno | Matching exacto NIT/matrícula + fuzzy determinista | Ningún clasificador entrenado |
| Mapeo CIIU→Sector | Lookup table YAML (sección + excepciones) | Tabla de decisión, no modelo |
| Scoring | Fórmula aritmética vectorizada (pesos YAML) | Reglas → código, cero entrenamiento |
| Calidad/Confianza | Reglas if/else sobre deduplicación | Peso 0, nunca aprende |
| Diversificación | Suavizado Dirichlet-Multinomial paramétrico (M=22) | M elegido por grid search manual, no optimización auto |
| Desempate | SHA-256 determinístico | Criptografía, no aleatoriedad |

**Terminología legítima:** "Sistema de inteligencia comercial automatizado", "Scoring determinista y explicable", "Automatización basada en reglas de negocio versionadas", "Diversificación bayesiana paramétrica".

---

## 12. CONTACT

**Jhon Fredy Holguín**  
Business Development | B2B Sales | Fintech & Payments | Commercial Intelligence

- LinkedIn: [linkedin.com/in/jhonfredyholguin](https://linkedin.com/in/jhonfredyholguin)
- Portfolio: [github.com/jhonfredy/sales-intelligence-system](https://github.com/freddih13-arch/sales-intelligence-system)

> *Disponible para conversaciones sobre Business Development, Sales Operations, Commercial Intelligence en Fintech/Payments.*