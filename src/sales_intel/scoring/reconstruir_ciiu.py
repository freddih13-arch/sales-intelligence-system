"""
Reconstrucción mecánica de CIIU "fantasma" (código numérico sin letra de
sección, ej. "4,711" en vez de "G4711") — identificados en
auditoria_fit_comercial.md §3.3.

REGLA NO NEGOCIABLE: la letra de sección NUNCA se adivina. Se reconstruye
ÚNICAMENTE cuando el mismo número de 3-4 dígitos aparece, en algún otro
registro del propio dataset, con UNA Y SOLO UNA letra de sección válida
(es decir, la evidencia ya existe en los datos — no se inventa nada). Si el
número nunca aparece con letra, o aparece con más de una letra distinta, el
registro queda SIN modificar y sin `sector_vertical`.

Las entradas marcadas por la propia fuente como
`"... ** NO LOCALIZADO EN TABLA DE CIIUS"` se EXCLUYEN tanto de la
referencia (no son evidencia válida) como de la reconstrucción (no son
candidatos, son códigos que la fuente ya declaró inválidos).

`"9999"` es un placeholder explícito de "sin clasificar" — nunca se
reconstruye, por instrucción explícita.

Nunca se modifica la columna `ciiu_1` original — solo se agregan columnas de
auditoría (`ciiu_1_reconstruido`, `ciiu_1_estado_reconstruccion`) y se
recalculan `sector_vertical` / `encaje_pagos_declarado` SOLO para las
filas reconstruidas.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from sales_intel.enriquecimiento.mapeo_sectorial import obtener_sector_comercial

PLACEHOLDER_EXPLICITO = "9999"
MARCA_INVALIDO_FUENTE = "NO LOCALIZADO"


def _construir_referencia(ciiu_1: pd.Series) -> dict[str, set[str]]:
    """Para cada número de 3-4 dígitos, el conjunto de letras de sección con
    las que YA aparece válidamente en el propio dataset (excluyendo
    entradas que la fuente marcó como inválidas)."""
    validos = ciiu_1.dropna()
    validos = validos[
        validos.str.match(r"^[A-Z]\d{3,4}", na=False)
        & ~validos.str.contains(MARCA_INVALIDO_FUENTE, na=False)
    ]
    extraido = validos.str.extract(r"^([A-Z])(\d{3,4})")
    ref: dict[str, set[str]] = defaultdict(set)
    for letra, digitos in zip(extraido[0], extraido[1]):
        ref[digitos].add(letra)
    return dict(ref)


def _letras_observadas(valor_limpio: str | None, ref: dict[str, set[str]]) -> set[str]:
    # pd.isna cubre None, NaN y pd.NA — el mismo patrón de bug ya visto y
    # corregido en normalización/exclusión: un chequeo "is None" no basta.
    if pd.isna(valor_limpio):
        return set()
    candidatos = {valor_limpio, valor_limpio.lstrip("0") or "0"}
    letras: set[str] = set()
    for c in candidatos:
        letras |= ref.get(c, set())
    return letras


def clasificar_y_reconstruir_ciiu_fantasma(ciiu_1: pd.Series) -> pd.DataFrame:
    """Devuelve un DataFrame (mismo índice que `ciiu_1`) con:
      - ciiu_1_reconstruido: código con letra reconstruido (o None)
      - ciiu_1_estado_reconstruccion: 'no_aplica' | 'reconstruido_inequivoco' |
        'ambiguo_no_reconstruido' | 'sin_evidencia_no_reconstruido' |
        'invalido_marcado_por_fuente' | 'placeholder_9999_excluido' |
        'formato_no_reconocido'
    """
    n = len(ciiu_1)
    ref = _construir_referencia(ciiu_1)

    tiene_letra = ciiu_1.str.match(r"^[A-Z]", na=False)
    es_candidato = ciiu_1.notna() & ~tiene_letra

    limpio = ciiu_1.where(es_candidato).str.replace(",", "", regex=False).str.replace(".", "", regex=False).str.strip()
    marcado_invalido = ciiu_1.str.contains(MARCA_INVALIDO_FUENTE, na=False)
    es_placeholder = limpio == PLACEHOLDER_EXPLICITO
    es_formato_valido = limpio.str.match(r"^\d{3,4}$", na=False)

    estado = pd.Series("no_aplica", index=ciiu_1.index, dtype=object)
    reconstruido = pd.Series(pd.NA, index=ciiu_1.index, dtype=object)

    estado = estado.mask(es_candidato & marcado_invalido, "invalido_marcado_por_fuente")
    estado = estado.mask(es_candidato & ~marcado_invalido & ~es_formato_valido, "formato_no_reconocido")
    estado = estado.mask(es_candidato & ~marcado_invalido & es_formato_valido & es_placeholder, "placeholder_9999_excluido")

    intentar = es_candidato & ~marcado_invalido & es_formato_valido & ~es_placeholder
    letras = limpio.where(intentar).map(lambda v: _letras_observadas(v, ref))

    n_letras = letras.map(lambda s: len(s) if isinstance(s, set) else -1)
    estado = estado.mask(intentar & (n_letras == 0), "sin_evidencia_no_reconstruido")
    estado = estado.mask(intentar & (n_letras > 1), "ambiguo_no_reconstruido")

    es_inequivoco = intentar & (n_letras == 1)
    estado = estado.mask(es_inequivoco, "reconstruido_inequivoco")
    letra_unica = letras.where(es_inequivoco).map(lambda s: next(iter(s)) if isinstance(s, set) and s else None)
    reconstruido = reconstruido.mask(es_inequivoco, letra_unica.astype(object) + limpio.where(es_inequivoco))

    assert len(estado) == n
    return pd.DataFrame({"ciiu_1_reconstruido": reconstruido, "ciiu_1_estado_reconstruccion": estado})


def aplicar_reconstruccion(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aplica la reconstrucción sobre una copia de `df` (no modifica el
    original en memoria), recalculando `sector_vertical` y
    `encaje_pagos_declarado` SOLO para las filas reconstruidas.
    `ciiu_1` original nunca se toca. Devuelve (df_actualizado, stats)."""
    out = df.copy()
    resultado = clasificar_y_reconstruir_ciiu_fantasma(out["ciiu_1"])
    out["ciiu_1_reconstruido"] = resultado["ciiu_1_reconstruido"]
    out["ciiu_1_estado_reconstruccion"] = resultado["ciiu_1_estado_reconstruccion"]

    mask_reconstruido = resultado["ciiu_1_estado_reconstruccion"] == "reconstruido_inequivoco"
    codigos_unicos = resultado.loc[mask_reconstruido, "ciiu_1_reconstruido"].dropna().unique()
    lookup = {c: obtener_sector_comercial(c) for c in codigos_unicos}

    sector_nuevo = resultado["ciiu_1_reconstruido"].map(lambda c: lookup[c]["sector_comercial"] if c in lookup else None)
    encaje_nuevo = resultado["ciiu_1_reconstruido"].map(lambda c: lookup[c]["encaje_pagos"] if c in lookup else None)

    out["sector_vertical_original"] = out["sector_vertical"]
    out["encaje_pagos_declarado_original"] = out["encaje_pagos_declarado"]
    out.loc[mask_reconstruido, "sector_vertical"] = sector_nuevo[mask_reconstruido]
    out.loc[mask_reconstruido, "encaje_pagos_declarado"] = encaje_nuevo[mask_reconstruido]

    stats = {
        "por_estado": resultado["ciiu_1_estado_reconstruccion"].value_counts().to_dict(),
        "n_reconstruidos": int(mask_reconstruido.sum()),
        "codigos_reconstruidos_distintos": len(codigos_unicos),
    }
    return out, stats
