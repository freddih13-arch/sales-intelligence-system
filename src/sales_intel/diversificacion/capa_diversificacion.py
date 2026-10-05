"""
Capa de Diversificación — implementación del mecanismo aprobado en
`03_RESULTADOS/especificacion_capa_diversificacion.md`.

REGLA NO NEGOCIABLE: este módulo NUNCA calcula ni modifica ningún score.
Recibe `score_prioridad_comercial` ya calculado (columna de entrada, tratada
como de solo lectura) y únicamente decide QUÉ ENTIDADES componen un Top N y
en qué orden — es un paso de selección posterior, no una re-ponderación.

Diseño deliberado — SIN hardcodear ningún sector ni municipio como caso
especial: todos los umbrales se derivan de la fórmula generalizable
`umbral_activacion(x) = clamp(k * p_x, piso, techo)`, donde `p_x` es la
participación real de la categoría `x` (sector o municipio) en el universo
que se está diversificando. La misma fórmula produce distintos números para
cada categoría observada — el código no contiene ninguna rama condicional
que dependa del NOMBRE de un sector o de una ciudad en particular.

Mecanismo, en 2 fases (ver especificación §5 para la justificación completa):
  Fase 1 — recorrido único del universo ordenado por score descendente:
    - Zona de tolerancia: participación resultante <= umbral_activación en
      ambas dimensiones (sector y municipio) -> admisión directa.
    - Zona soft: participación > umbral_activación pero <= tope_duro en
      ambas dimensiones -> se busca, dentro de una ventana de W candidatos
      no usados más adelante en el orden de score, un reemplazo que (a) sea
      admisible por sí mismo y (b) cumpla el piso de calidad (§ protección).
      Si existe, se admite el reemplazo y el candidato original queda
      diferido. Si no existe, se admite el candidato original de todas
      formas (protección de calidad > diversidad).
    - Tope duro: participación > tope_duro en alguna dimensión -> se difiere
      siempre, sin buscar reemplazo (nunca se admite directamente).
  Fase 2 — cierre garantizado: si el Top N no se completó en la Fase 1
    (universo insuficiente respetando el umbral_activación), se completa con
    los diferidos en orden de score, respetando ÚNICAMENTE el tope_duro.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Parámetros aprobados en la especificación (§4.2, §6, §5).
# Son constantes de la FÓRMULA (aplican igual a cualquier sector/municipio),
# no excepciones para un sector o municipio en particular — ver docstring.
# ---------------------------------------------------------------------------

K_SOBRERREPRESENTACION = 3.0
MARGEN_TOPE_DURO = 0.10

PARAMS_SECTOR = {"piso_activacion": 0.25, "techo_activacion": 0.50, "techo_tope_duro": 0.55}
PARAMS_MUNICIPIO = {"piso_activacion": 0.15, "techo_activacion": 0.35, "techo_tope_duro": 0.45}

PISO_SCORE_ABSOLUTO = 60.0
PISO_SCORE_RELATIVO = 0.85  # el reemplazo debe tener score >= 85% del desplazado

VENTANA_MINIMA = 50
VENTANA_FRACCION_N = 0.01  # W = max(VENTANA_MINIMA, 1% de N)

# MECANISMO DEFINITIVO DE PARTICIPACIÓN — suavizado bayesiano (spec §5,
# sección "Mecanismo de suavizado de participación"). Reemplaza formalmente
# el mecanismo anterior de `CALENTAMIENTO_MINIMO` (un período de admisión
# incondicional al principio de la lista, descartado explícitamente en
# `03_RESULTADOS/decision_mecanismo_suavizado.md`).
#
# El problema que ambos mecanismos abordan: la participación "si se admite"
# calculada de forma ingenua como (conteo+1)/(tamaño+1) es inestable con una
# lista casi vacía (con 1 admitido, CUALQUIER categoría representa el 100%
# de la lista). El calentamiento "resolvía" esto por fuerza bruta (ignorando
# por completo las primeras posiciones); el suavizado bayesiano corrige la
# causa raíz: compara siempre contra `p_x` (la participación real de la
# categoría en el universo), en TODAS las posiciones desde la primera, sin
# ningún rango exento — ver `participacion_suavizada()` más abajo.
#
# M_SUAVIZADO — VALOR DE PRODUCCIÓN APROBADO: 22 (único, compartido entre
# sector y municipio). Decidido en `03_RESULTADOS/decision_final_M_suavizado.md`
# (barrido de 16 valores de M sobre Top 100/500/1.000/5.000, usando ya la
# taxonomía V2 y el desempate F). El desempate F (hash determinístico de
# `entidad_dedup_id`, ver `clave_desempate_hash()` más abajo) ya está
# implementado como el criterio de desempate real de este módulo. M=22 es
# el punto de mínima sensibilidad estructural dentro de la zona donde el
# mecanismo todavía diversifica de forma sustancial (rango de sensibilidad aceptable
# documentado: [20, 26]), no un óptimo matemático único — ver ese reporte
# para la justificación completa y el riesgo residual aceptado. NUNCA usar
# M<5 en producción (comportamiento errático verificado, ver
# `analisis_alternativas_calentamiento.md` §5 y `decision_final_M_suavizado.md` §3).
M_SUAVIZADO = 22

SECTOR_SIN_DATO = "Sin sector"
MUNICIPIO_SIN_DATO = "SIN_DATO"

ESTADOS_UNIVERSO_VALIDOS = {"SIN_COINCIDENCIA"}

# Bucket sectorial — taxonomía V2 (Nivel B), aprobada tras
# `03_RESULTADOS/auditoria_taxonomia_diversificacion.md`,
# `propuesta_taxonomia_diversificacion_v2.md` y validada por simulación en
# `validacion_taxonomia_v2.md` (0 cambios de admisión, 0 violaciones de
# piso frente a la taxonomía anterior). Base original: idéntica al bucket
# usado en las auditorías previas (auditoria_analitica_score_prioridad_
# comercial.md, diagnostico_capa_diversificacion.md) — spec §3: "no una
# nueva taxonomía" —, con 2 entradas añadidas (Entretenimiento, Transporte
# y logística) que antes caían sin distinción en el bucket genérico
# "Otros" junto con Construcción/Inmobiliario/Agro/Financiero-Seguros/
# Minería (que SÍ permanecen en "Otros" — la propuesta v2 encontró que,
# bajo los scores actuales, esas 5 categorías nunca compiten por cupo en
# ningún Top N y no justifican bucket propio, ver propuesta v2 §3-§4).
_SECTOR_BUCKETS = {
    "Gastronomía y Hotelería": "HORECA",
    "Ferretería y construcción menor": "Ferretería",
    "Salud": "Salud",
    "Salud / Farmacias": "Salud/Farmacias",
    "Educación": "Educación",
    "Comercio / Retail": "Comercio/Retail",
    "Manufactura": "Manufactura",
    "Otros servicios": "Servicios",
    "Servicios profesionales": "Servicios",
    "Servicios de apoyo empresarial": "Servicios",
    "Servicios públicos": "Servicios",
    "Tecnología / Comunicaciones": "Tecnología",
    "Entretenimiento": "Entretenimiento",
    "Transporte y logística": "Transporte/logística",
}


def bucket_sector(sector_vertical) -> str:
    if pd.isna(sector_vertical):
        return SECTOR_SIN_DATO
    return _SECTOR_BUCKETS.get(sector_vertical, "Otros")


def categoria_municipio(municipio) -> str:
    if pd.isna(municipio):
        return MUNICIPIO_SIN_DATO
    return str(municipio)


def clave_desempate_hash(entidad_dedup_id) -> int:
    """Desempate F (spec §5, "Criterio de desempate — F"): hash SHA-256
    determinístico de `entidad_dedup_id`, sin semilla externa. Reemplaza
    formalmente `entidad_dedup_id` ascendente como criterio de desempate en
    empates exactos de `score_prioridad_comercial` — `entidad_dedup_id` es
    un identificador secuencial asignado en bloques contiguos por fuente de
    origen durante la deduplicación, por lo que NO es neutral: correlaciona
    con la fuente y, por esa vía, con sector y geografía
    (`analisis_criterio_desempate.md` §2-§3).

    Depende EXCLUSIVAMENTE de `entidad_dedup_id` — ningún otro campo (no
    `score_prioridad_comercial`, no sector, no municipio, no fuente, no
    contacto). Usa `hashlib.sha256`, NUNCA `hash()` nativo de Python (varía
    entre procesos por hash randomization / `PYTHONHASHSEED` — no sería
    reproducible entre ejecuciones). Sin número aleatorio, sin timestamp,
    sin semilla configurable — el propio ID, ya público y ya parte de la
    trazabilidad, es la única entrada.

    Se toma una porción de 15 caracteres hexadecimales (60 bits) del
    digest — suficiente para hacer una colisión prácticamente imposible en
    un universo de cientos de miles de entidades (2^60 valores posibles) y
    se mantiene dentro del rango de un entero de 64 bits con signo, evitando
    cualquier ambigüedad de tipo de dato al ordenar."""
    digest = hashlib.sha256(str(entidad_dedup_id).encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def clamp(valor: float, piso: float, techo: float) -> float:
    return min(max(valor, piso), techo)


def umbral_activacion(p_x: float, piso: float, techo: float, k: float = K_SOBRERREPRESENTACION) -> float:
    """clamp(k * p_x, piso, techo) — fórmula generalizable, spec §4.1."""
    return clamp(k * p_x, piso, techo)


def calcular_tope_duro(activacion: float, piso: float, techo_duro: float, margen: float = MARGEN_TOPE_DURO) -> float:
    return clamp(activacion + margen, piso, techo_duro)


def calcular_participacion_base(categorias: pd.Series) -> dict[str, float]:
    """p_x de cada categoría observada, sobre el universo dado."""
    conteos = categorias.value_counts(dropna=False)
    total = len(categorias)
    return {cat: n / total for cat, n in conteos.items()}


def participacion_suavizada(conteo: int, tamano: int, p_x: float, m: float) -> float:
    """p_suavizada(x) = (conteo_x + 1 + M*p_x) / (tamaño + 1 + M) — spec §5,
    "Mecanismo de suavizado de participación". Media posterior de una
    Dirichlet-Multinomial con prior de media `p_x` y concentración `m`.

    `conteo`/`tamaño` son los admitidos HASTA AHORA en `lista_final` (antes
    de admitir al candidato evaluado); `p_x` es la participación real de la
    categoría en el universo de referencia completo (`calcular_participacion_base`
    sobre TODO el universo pasado a `construir_ranking_diversificado`, nunca
    sobre lo ya admitido ni sobre el propio Top N resultante).

    Se aplica exactamente igual desde `tamano=0` (el primer candidato
    evaluado, de cualquier categoría) — no existe ningún rango de
    posiciones exento de esta fórmula; con `tamano=0` da `(1+m*p_x)/(1+m)`,
    que converge suavemente hacia `p_x` a medida que `m` crece, sin saltar
    nunca a 100% como la fórmula ingenua `(conteo+1)/(tamaño+1)`."""
    return (conteo + 1 + m * p_x) / (tamano + 1 + m)


def calcular_umbrales_por_categoria(
    p_x_por_categoria: dict[str, float], params: dict
) -> dict[str, tuple[float, float]]:
    """{categoria: (umbral_activacion, tope_duro)} para TODAS las categorías
    observadas en el universo — la misma fórmula para cada una, sin excepción."""
    umbrales = {}
    for cat, p_x in p_x_por_categoria.items():
        act = umbral_activacion(p_x, params["piso_activacion"], params["techo_activacion"])
        duro = calcular_tope_duro(act, params["piso_activacion"], params["techo_tope_duro"])
        umbrales[cat] = (act, duro)
    return umbrales


@dataclass(frozen=True)
class ConfiguracionDiversificacion:
    k: float = K_SOBRERREPRESENTACION
    margen_tope_duro: float = MARGEN_TOPE_DURO
    piso_score_absoluto: float = PISO_SCORE_ABSOLUTO
    piso_score_relativo: float = PISO_SCORE_RELATIVO
    ventana_minima: int = VENTANA_MINIMA
    ventana_fraccion_n: float = VENTANA_FRACCION_N
    m_suavizado: float = M_SUAVIZADO
    params_sector: dict = None
    params_municipio: dict = None

    def __post_init__(self):
        if self.params_sector is None:
            object.__setattr__(self, "params_sector", dict(PARAMS_SECTOR))
        if self.params_municipio is None:
            object.__setattr__(self, "params_municipio", dict(PARAMS_MUNICIPIO))


def _preparar_universo(
    df: pd.DataFrame,
    columna_score: str,
    columna_sector: str,
    columna_municipio: str,
    columna_id: str,
) -> pd.DataFrame:
    if not set(df["estado_exclusion"].unique()).issubset(ESTADOS_UNIVERSO_VALIDOS):
        raise ValueError(
            "El universo de entrada a la capa de diversificación debe contener "
            f"únicamente estado_exclusion en {ESTADOS_UNIVERSO_VALIDOS} — "
            "CANDIDATO_AMBIGUO y las EXCLUSION_* deben filtrarse ANTES de llamar "
            "a construir_ranking_diversificado (no es responsabilidad de este módulo)."
        )
    out = df.copy()
    out["_sector_bucket"] = out[columna_sector].apply(bucket_sector)
    out["_municipio_categoria"] = out[columna_municipio].apply(categoria_municipio)
    # Orden determinístico: score descendente, empate roto por el desempate F
    # -- hash SHA-256 determinístico de entidad_dedup_id (clave_desempate_hash),
    # nunca aleatorio ni dependiente del orden de entrada -> misma entrada
    # siempre produce el mismo orden, sin el sesgo por fuente que tenía
    # entidad_dedup_id ascendente (`analisis_criterio_desempate.md` §2-§3).
    out["_clave_desempate"] = out[columna_id].apply(clave_desempate_hash)
    out = out.sort_values([columna_score, "_clave_desempate"], ascending=[False, True], kind="mergesort")
    out = out.reset_index(drop=True)
    out["_posicion_ranking_puro"] = out.index + 1
    return out


def _buscar_reemplazo(
    pos_actual: int,
    ventana: int,
    usado: np.ndarray,
    scores: np.ndarray,
    sectores: np.ndarray,
    municipios: np.ndarray,
    conteo_sector: dict,
    conteo_municipio: dict,
    tam_lista_actual: int,
    umbrales_sector: dict,
    umbrales_municipio: dict,
    piso_absoluto: float,
    piso_relativo_score: float,
    p_sector: dict,
    p_municipio: dict,
    m_suavizado: float,
) -> int | None:
    """Busca, entre los siguientes `ventana` candidatos AÚN NO USADOS después
    de `pos_actual`, el primero que sea admisible por sí mismo Y cumpla el
    piso de calidad. Devuelve su posición en los arreglos, o None."""
    n_total = len(scores)
    j = pos_actual + 1
    examinados = 0
    while j < n_total and examinados < ventana:
        if usado[j]:
            j += 1
            continue
        examinados += 1
        sj = scores[j]
        if sj < piso_absoluto or sj < piso_relativo_score:
            j += 1
            continue
        sec_j, mun_j = sectores[j], municipios[j]
        p_sec = participacion_suavizada(conteo_sector.get(sec_j, 0), tam_lista_actual, p_sector[sec_j], m_suavizado)
        p_mun = participacion_suavizada(conteo_municipio.get(mun_j, 0), tam_lista_actual, p_municipio[mun_j], m_suavizado)
        act_sec, _ = umbrales_sector[sec_j]
        act_mun, _ = umbrales_municipio[mun_j]
        if p_sec <= act_sec and p_mun <= act_mun:
            return j
        j += 1
    return None


def _motivo_texto(
    sector: str, municipio: str,
    p_sec: float, p_mun: float,
    act_sec: float, act_mun: float,
) -> str:
    partes = []
    if p_sec > act_sec:
        partes.append(f"sector='{sector}' superaría {p_sec:.1%} (umbral de activación {act_sec:.1%})")
    if p_mun > act_mun:
        partes.append(f"municipio='{municipio}' superaría {p_mun:.1%} (umbral de activación {act_mun:.1%})")
    return "; ".join(partes) if partes else "umbral superado"


def construir_ranking_diversificado(
    universo: pd.DataFrame,
    n: int,
    config: ConfiguracionDiversificacion | None = None,
    columna_score: str = "score_prioridad_comercial",
    columna_sector: str = "sector_vertical",
    columna_municipio: str = "municipio_nombre_normalizado",
    columna_id: str = "entidad_dedup_id",
) -> dict:
    """Construye un Top N diversificado a partir de `universo` (debe venir
    YA filtrado a estado_exclusion == SIN_COINCIDENCIA por el llamador).

    Devuelve {'top_n': DataFrame de trazabilidad (N filas, ordenado por score
    final descendente), 'stats': dict, 'config': ConfiguracionDiversificacion}.
    `universo` NUNCA se modifica in-place; `score_prioridad_comercial` nunca
    se recalcula ni se altera.
    """
    if config is None:
        config = ConfiguracionDiversificacion()
    if n <= 0:
        raise ValueError("n debe ser positivo")

    prep = _preparar_universo(universo, columna_score, columna_sector, columna_municipio, columna_id)

    p_sector = calcular_participacion_base(prep["_sector_bucket"])
    p_municipio = calcular_participacion_base(prep["_municipio_categoria"])
    umbrales_sector = calcular_umbrales_por_categoria(p_sector, config.params_sector)
    umbrales_municipio = calcular_umbrales_por_categoria(p_municipio, config.params_municipio)

    scores = prep[columna_score].to_numpy(dtype=float)
    sectores = prep["_sector_bucket"].to_numpy()
    municipios = prep["_municipio_categoria"].to_numpy()
    ids = prep[columna_id].to_numpy()
    posiciones_puras = prep["_posicion_ranking_puro"].to_numpy()

    n_total = len(prep)
    ventana = max(config.ventana_minima, math.ceil(config.ventana_fraccion_n * n))

    usado = np.zeros(n_total, dtype=bool)
    conteo_sector: dict[str, int] = {}
    conteo_municipio: dict[str, int] = {}
    admitidos: list[dict] = []
    diferidos_para_fase2: list[int] = []  # posiciones en los arreglos, en orden de score

    def _admitir(pos: int, metodo: str, motivo: str | None, pos_desplazado: int | None):
        sec, mun = sectores[pos], municipios[pos]
        conteo_sector[sec] = conteo_sector.get(sec, 0) + 1
        conteo_municipio[mun] = conteo_municipio.get(mun, 0) + 1
        usado[pos] = True
        registro = {
            "entidad_dedup_id": ids[pos],
            "score_base": scores[pos],
            "posicion_ranking_puro": int(posiciones_puras[pos]),
            "sector": sec,
            "municipio": mun,
            "metodo_seleccion": metodo,
            "motivo_diversificacion": motivo,
            "entro_por_diversificacion": metodo != "tolerancia",
        }
        if pos_desplazado is not None:
            registro["candidato_desplazado"] = ids[pos_desplazado]
            registro["score_candidato_desplazado"] = float(scores[pos_desplazado])
            registro["diferencia_score"] = float(scores[pos] - scores[pos_desplazado])
        else:
            registro["candidato_desplazado"] = None
            registro["score_candidato_desplazado"] = None
            registro["diferencia_score"] = None
        admitidos.append(registro)

    # ------------------------------------------------------------------
    # Fase 1
    # ------------------------------------------------------------------
    n_evaluados_fase1 = 0
    n_reemplazos = 0
    n_proteccion_calidad = 0  # disparó umbral pero no hubo reemplazo elegible
    n_diferidos_tope_duro = 0

    i = 0
    while len(admitidos) < n and i < n_total:
        if usado[i]:
            i += 1
            continue
        n_evaluados_fase1 += 1

        # Sin ningún rango de posiciones exento: la participación se estima
        # con el suavizado bayesiano desde el primer candidato evaluado
        # (tamaño=0 incluido) -- ver participacion_suavizada().
        sec, mun = sectores[i], municipios[i]
        p_sec = participacion_suavizada(conteo_sector.get(sec, 0), len(admitidos), p_sector[sec], config.m_suavizado)
        p_mun = participacion_suavizada(conteo_municipio.get(mun, 0), len(admitidos), p_municipio[mun], config.m_suavizado)
        act_sec, cap_sec = umbrales_sector[sec]
        act_mun, cap_mun = umbrales_municipio[mun]

        sobre_activacion = (p_sec > act_sec) or (p_mun > act_mun)
        sobre_tope_duro = (p_sec > cap_sec) or (p_mun > cap_mun)

        if not sobre_activacion:
            _admitir(i, "tolerancia", None, None)
            i += 1
            continue

        motivo = _motivo_texto(sec, mun, p_sec, p_mun, act_sec, act_mun)

        if sobre_tope_duro:
            diferidos_para_fase2.append(i)
            n_diferidos_tope_duro += 1
            i += 1
            continue

        # Zona soft: buscar reemplazo dentro de la ventana.
        piso_relativo_score = scores[i] * config.piso_score_relativo
        idx_reemplazo = _buscar_reemplazo(
            i, ventana, usado, scores, sectores, municipios,
            conteo_sector, conteo_municipio, len(admitidos),
            umbrales_sector, umbrales_municipio,
            config.piso_score_absoluto, piso_relativo_score,
            p_sector, p_municipio, config.m_suavizado,
        )
        if idx_reemplazo is not None:
            _admitir(idx_reemplazo, "diversificacion", motivo, i)
            diferidos_para_fase2.append(i)
            n_reemplazos += 1
        else:
            _admitir(i, "proteccion_calidad", motivo, None)
            n_proteccion_calidad += 1
        i += 1

    # ------------------------------------------------------------------
    # Fase 2 — cierre garantizado (solo tope duro, en orden de score)
    # ------------------------------------------------------------------
    n_recuperados_fase2 = 0
    if len(admitidos) < n:
        for pos in diferidos_para_fase2:
            if len(admitidos) >= n:
                break
            if usado[pos]:
                continue
            sec, mun = sectores[pos], municipios[pos]
            p_sec = participacion_suavizada(conteo_sector.get(sec, 0), len(admitidos), p_sector[sec], config.m_suavizado)
            p_mun = participacion_suavizada(conteo_municipio.get(mun, 0), len(admitidos), p_municipio[mun], config.m_suavizado)
            _, cap_sec = umbrales_sector[sec]
            _, cap_mun = umbrales_municipio[mun]
            if p_sec <= cap_sec and p_mun <= cap_mun:
                _admitir(pos, "cierre_fase2", "reincorporado en cierre de fase 2 (universo insuficiente bajo el umbral de activación)", None)
                n_recuperados_fase2 += 1

    resultado = pd.DataFrame(admitidos)
    if not resultado.empty:
        # Mismo desempate F que en _preparar_universo -- orden de presentación
        # del Top N consistente con el criterio que decidió las admisiones.
        resultado["_clave_desempate"] = resultado["entidad_dedup_id"].apply(clave_desempate_hash)
        resultado = resultado.sort_values(
            ["score_base", "_clave_desempate"], ascending=[False, True], kind="mergesort"
        ).drop(columns="_clave_desempate").reset_index(drop=True)
        resultado["posicion_ranking_diversificado"] = resultado.index + 1
    else:
        resultado["posicion_ranking_diversificado"] = pd.Series(dtype=int)

    stats = {
        "n_objetivo": n,
        "n_final": len(resultado),
        "ventana_w": ventana,
        "n_evaluados_fase1": n_evaluados_fase1,
        "n_reemplazos": n_reemplazos,
        "n_proteccion_calidad": n_proteccion_calidad,
        "n_diferidos_tope_duro": n_diferidos_tope_duro,
        "n_recuperados_fase2": n_recuperados_fase2,
        "n_diferidos_totales": len(diferidos_para_fase2),
        "n_diferidos_nunca_recuperados": len(diferidos_para_fase2) - n_recuperados_fase2,
        "umbrales_sector": umbrales_sector,
        "umbrales_municipio": umbrales_municipio,
        "p_sector": p_sector,
        "p_municipio": p_municipio,
    }
    return {"top_n": resultado, "stats": stats, "config": config}
