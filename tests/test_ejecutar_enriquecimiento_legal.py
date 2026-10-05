"""
Pruebas del ejecutor versionado del enriquecimiento legal
(`reportes.ejecutar_enriquecimiento_legal.ejecutar_enriquecimiento_legal`).

Prueba EL EJECUTOR (composición, parámetros, propagación), no las capas
inferiores -- esas ya tienen ~1500 líneas de tests propias
(`test_enriquecimiento_legal.py`, `test_resiliencia_confecamaras.py`,
`test_orquestador_enriquecimiento.py`, `test_escritor_enriquecimiento.py`).
Aquí se usan exclusivamente clientes FAKE (protocolo `ClienteConfecamaras`,
sin red) o, para probar qué pasa cuando `cliente=None`, una clase "espía"
que sustituye a `ClienteConfecamarasSocrata` sin construirla de verdad.

Un fixture `autouse` bloquea cualquier llamada real a `urllib.request.urlopen`
en todo este archivo -- prueba explícita de que ningún test hace HTTP real.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import pytest

from bold_intel.enriquecimiento_legal.capa_enriquecimiento_legal import CAMPOS_COMERCIALES
from bold_intel.enriquecimiento_legal.cliente_confecamaras import (
    CacheEnMemoria,
    PoliticaResiliencia,
    RegistradorEnMemoria,
    RespuestaConfecamaras,
)
from bold_intel.reportes.ejecutar_enriquecimiento_legal import ejecutar_enriquecimiento_legal


# ---------------------------------------------------------------------------
# Bloqueo de HTTP real para TODO este archivo (punto M) -- si algún camino
# de código llegara a intentar una conexión real, el test falla de inmediato
# en vez de colgarse o hacer una llamada real por accidente.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _bloquear_http_real(monkeypatch):
    def _prohibido(*args, **kwargs):
        raise AssertionError("Intento de HTTP real detectado -- prohibido en esta suite de tests.")
    monkeypatch.setattr("urllib.request.urlopen", _prohibido)


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

REGISTRO_ACTIVO = {
    "nit": "901955318", "digito_verificacion": "3",
    "razon_social": "INVERSIONES GRUPO C&D S.A.S.",
    "organizacion_juridica": "SOCIEDADES POR ACCIONES SIMPLIFICADAS SAS",
    "representante_legal": "REPRESENTANTE EJEMPLO S.A.S.",
    "estado_matricula": "ACTIVA", "matricula": "18228847", "camara_comercio": "PEREIRA",
}


class ClienteFake:
    """Cumple el protocolo `ClienteConfecamaras` -- una consulta a un NIT no
    programado hace fallar el test explícitamente en vez de devolver algo
    silenciosamente incorrecto."""

    def __init__(self, respuestas: dict):
        self._respuestas = respuestas
        self.llamadas = []

    def consultar_nit(self, nit_base):
        self.llamadas.append(nit_base)
        if nit_base not in self._respuestas:
            raise AssertionError(f"ClienteFake: consulta inesperada para NIT base {nit_base!r}")
        return self._respuestas[nit_base]


def _prospecto(entidad_dedup_id, posicion, nit, razon_social):
    return {
        "entidad_dedup_id": entidad_dedup_id,
        "posicion_diversificada": posicion,
        "nit": nit,
        "razon_social": razon_social,
    }


def _construir_top_n_csv(tmp_path, filas, nombre="topn.csv") -> Path:
    df = pd.DataFrame(filas)
    ruta = tmp_path / nombre
    df.to_csv(ruta, index=False)
    return ruta


def _crear_clase_espia_cliente():
    """Sustituye a `ClienteConfecamarasSocrata` (vía monkeypatch) sin
    construirla de verdad -- captura los kwargs del constructor y nunca hace
    HTTP (su `consultar_nit` devuelve NO_MATCH sintético)."""
    llamadas_constructor = []

    class _Espia:
        def __init__(self, **kwargs):
            llamadas_constructor.append(kwargs)

        def consultar_nit(self, nit_base):
            return RespuestaConfecamaras(ok=True, registros=())

    return _Espia, llamadas_constructor


def _clase_espia_que_nunca_debe_construirse():
    class _NuncaConstruir:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "ClienteConfecamarasSocrata NO debía construirse -- se inyectó un cliente explícito."
            )
    return _NuncaConstruir


# ---------------------------------------------------------------------------
# A. ruta_entrada inexistente
# ---------------------------------------------------------------------------

def test_A_ruta_entrada_inexistente_falla(tmp_path):
    with pytest.raises(FileNotFoundError):
        ejecutar_enriquecimiento_legal(
            tmp_path / "no_existe.csv", tmp_path / "salida.csv",
            cliente=ClienteFake({}),
        )


# ---------------------------------------------------------------------------
# B. Lectura correcta de un Top N sintético
# ---------------------------------------------------------------------------

def test_B_lectura_correcta_de_top_n_sintetico(tmp_path):
    filas = [
        _prospecto("ENT-1", 1, "9019553183", "INVERSIONES GRUPO C&D S.A.S."),
        _prospecto("ENT-2", 2, None, "SIN NIT"),
    ]
    ruta_entrada = _construir_top_n_csv(tmp_path, filas)
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})

    resultado = ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente)

    assert len(resultado["registros"]) == 2
    assert resultado["registros"][0]["entidad_dedup_id"] == "ENT-1"
    assert resultado["registros"][1]["entidad_dedup_id"] == "ENT-2"
    assert resultado["registros"][1]["resultado_match"] == "NO_CONSULTABLE"  # sin NIT


# ---------------------------------------------------------------------------
# C. cliente inyectado -> NO se construye un cliente real
# ---------------------------------------------------------------------------

def test_C_cliente_inyectado_no_construye_cliente_real(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bold_intel.reportes.ejecutar_enriquecimiento_legal.ClienteConfecamarasSocrata",
        _clase_espia_que_nunca_debe_construirse(),
    )
    ruta_entrada = _construir_top_n_csv(
        tmp_path, [_prospecto("ENT-1", 1, "9019553183", "INVERSIONES GRUPO C&D S.A.S.")]
    )
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})

    # Si el ejecutor intentara construir ClienteConfecamarasSocrata, la
    # clase parchada lanzaría AssertionError -- que esto no lance nada
    # ES la prueba de que nunca se construyó.
    resultado = ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente)
    assert resultado["registros"][0]["resultado_match"] == "MATCH_CONFIRMADO"
    assert cliente.llamadas == ["901955318"]


# ---------------------------------------------------------------------------
# D. cache=None -> NO se crea CacheEnMemoria automáticamente
# ---------------------------------------------------------------------------

def test_D_cache_none_no_reutiliza_entre_prospectos(tmp_path):
    # 2 prospectos con el MISMO nit_consultado -- sin caché, cada uno debe
    # disparar su propia consulta al cliente (ninguna reutilización).
    filas = [
        _prospecto("ENT-1", 1, "9019553183", "X"),
        _prospecto("ENT-2", 2, "9019553183", "Y"),
    ]
    ruta_entrada = _construir_top_n_csv(tmp_path, filas)
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})

    ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente, cache=None)

    assert cliente.llamadas == ["901955318", "901955318"]  # 2 llamadas -- SIN caché


# ---------------------------------------------------------------------------
# E. cache inyectada -> se pasa correctamente (SÍ se reutiliza)
# ---------------------------------------------------------------------------

def test_E_cache_inyectada_se_pasa_correctamente(tmp_path):
    filas = [
        _prospecto("ENT-1", 1, "9019553183", "X"),
        _prospecto("ENT-2", 2, "9019553183", "Y"),
    ]
    ruta_entrada = _construir_top_n_csv(tmp_path, filas)
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    cache = CacheEnMemoria(ahora=lambda: 1000.0)

    ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente, cache=cache)

    assert cliente.llamadas == ["901955318"]  # 1 sola llamada -- la 2da vino de la caché inyectada


# ---------------------------------------------------------------------------
# F. registrador inyectado -> se pasa al construir el cliente (cliente=None)
# ---------------------------------------------------------------------------

def test_F_registrador_inyectado_se_pasa_correctamente(tmp_path, monkeypatch):
    Espia, llamadas_constructor = _crear_clase_espia_cliente()
    monkeypatch.setattr(
        "bold_intel.reportes.ejecutar_enriquecimiento_legal.ClienteConfecamarasSocrata", Espia
    )
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    registrador_custom = RegistradorEnMemoria()

    ejecutar_enriquecimiento_legal(
        ruta_entrada, tmp_path / "salida.csv", cliente=None, registrador=registrador_custom,
    )

    assert len(llamadas_constructor) == 1
    assert llamadas_constructor[0]["registrador"] is registrador_custom


# ---------------------------------------------------------------------------
# G. política inyectada -> se usa al construir el cliente (cliente=None)
# ---------------------------------------------------------------------------

def test_G_politica_inyectada_se_usa_al_construir_cliente(tmp_path, monkeypatch):
    Espia, llamadas_constructor = _crear_clase_espia_cliente()
    monkeypatch.setattr(
        "bold_intel.reportes.ejecutar_enriquecimiento_legal.ClienteConfecamarasSocrata", Espia
    )
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    politica_custom = PoliticaResiliencia(timeout_segundos=1.0, max_intentos=1)

    ejecutar_enriquecimiento_legal(
        ruta_entrada, tmp_path / "salida.csv", cliente=None, politica=politica_custom,
    )

    assert len(llamadas_constructor) == 1
    assert llamadas_constructor[0]["politica"] is politica_custom


def test_G_sin_politica_no_se_fuerza_ninguna(tmp_path, monkeypatch):
    """Si no se inyecta `politica`, el ejecutor no debe pasar `politica=None`
    al constructor (rompería el default real de `ClienteConfecamarasSocrata`,
    que es `PoliticaResiliencia()`, no `None`)."""
    Espia, llamadas_constructor = _crear_clase_espia_cliente()
    monkeypatch.setattr(
        "bold_intel.reportes.ejecutar_enriquecimiento_legal.ClienteConfecamarasSocrata", Espia
    )
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])

    ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=None)

    assert "politica" not in llamadas_constructor[0]


# ---------------------------------------------------------------------------
# H. n_esperado se deriva del número real de prospectos (no hardcodeado)
# ---------------------------------------------------------------------------

def test_H_n_esperado_se_deriva_del_top_n(tmp_path):
    filas = [_prospecto(f"ENT-{i}", i, None, f"EMPRESA {i}") for i in range(1, 5)]  # 4 filas, no 100
    ruta_entrada = _construir_top_n_csv(tmp_path, filas)

    resultado = ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=ClienteFake({}))

    assert resultado["stats"]["n_prospectos"] == 4
    assert len(resultado["registros"]) == 4
    salida_df = pd.read_csv(tmp_path / "salida.csv", dtype=str, keep_default_na=False)
    assert len(salida_df) == 4


# ---------------------------------------------------------------------------
# I. El escritor recibe los registros correctamente y protege overwrite
# ---------------------------------------------------------------------------

def test_I_escritor_recibe_registros_y_protege_overwrite(tmp_path):
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})
    ruta_salida = tmp_path / "salida.csv"

    resultado = ejecutar_enriquecimiento_legal(ruta_entrada, ruta_salida, cliente=cliente)
    assert resultado["ruta_salida"] == ruta_salida
    assert ruta_salida.exists()
    contenido_original = ruta_salida.read_bytes()

    with pytest.raises(FileExistsError):
        ejecutar_enriquecimiento_legal(ruta_entrada, ruta_salida, cliente=cliente)
    assert ruta_salida.read_bytes() == contenido_original

    ejecutar_enriquecimiento_legal(ruta_entrada, ruta_salida, cliente=cliente, overwrite=True)  # no lanza


# ---------------------------------------------------------------------------
# J. Esquema de salida correcto (12 columnas aprobadas)
# ---------------------------------------------------------------------------

def test_J_esquema_de_salida_correcto(tmp_path):
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})

    ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente)

    salida_df = pd.read_csv(tmp_path / "salida.csv", dtype=str, keep_default_na=False)
    assert list(salida_df.columns) == list(CAMPOS_COMERCIALES)
    assert "num_identificacion_representante_legal" not in salida_df.columns


# ---------------------------------------------------------------------------
# K. Propagación correcta de ERROR_CONSULTA
# ---------------------------------------------------------------------------

def test_K_propagacion_error_consulta(tmp_path):
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    # ok=False representa un fallo técnico YA final (reintentos agotados en
    # el cliente real) -- el ejecutor no debe interpretarlo ni convertirlo
    # en NO_MATCH.
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=False, registros=(), error="timeout agotado")})

    resultado = ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente)

    assert resultado["registros"][0]["resultado_match"] == "ERROR_CONSULTA"
    assert resultado["stats"]["conteo_resultado_match"] == {"ERROR_CONSULTA": 1}
    salida_df = pd.read_csv(tmp_path / "salida.csv", dtype=str, keep_default_na=False)
    assert salida_df.iloc[0]["resultado_match"] == "ERROR_CONSULTA"


# ---------------------------------------------------------------------------
# L. Propagación correcta de MATCH_RESUELTO_HISTORICO
# ---------------------------------------------------------------------------

def test_L_propagacion_match_resuelto_historico(tmp_path):
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    r_historico = dict(REGISTRO_ACTIVO, estado_matricula="CANCELADA", matricula="1")
    r_vigente = dict(REGISTRO_ACTIVO, estado_matricula="ACTIVA", matricula="2")
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(r_historico, r_vigente))})

    resultado = ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente)

    assert resultado["registros"][0]["resultado_match"] == "MATCH_RESUELTO_HISTORICO"
    assert resultado["registros"][0]["matricula"] == "2"  # el vigente, no el histórico
    salida_df = pd.read_csv(tmp_path / "salida.csv", dtype=str, keep_default_na=False)
    assert salida_df.iloc[0]["resultado_match"] == "MATCH_RESUELTO_HISTORICO"
    assert salida_df.iloc[0]["matricula"] == "2"


# ---------------------------------------------------------------------------
# M. Sin HTTP -- ver también el fixture autouse `_bloquear_http_real`
# ---------------------------------------------------------------------------

def test_M_ningun_test_de_este_archivo_hace_http(tmp_path):
    """Prueba explícita adicional de que el bloqueo autouse está activo --
    si `urllib.request.urlopen` se invocara aquí, este test fallaría
    inmediatamente en vez de intentar una conexión real."""
    import urllib.request
    with pytest.raises(AssertionError, match="prohibido"):
        urllib.request.urlopen("https://www.datos.gov.co/resource/c82u-588k.json")


# ---------------------------------------------------------------------------
# N. Determinismo de la composición
# ---------------------------------------------------------------------------

def test_N_determinismo(tmp_path):
    filas = [
        _prospecto("ENT-1", 1, "9019553183", "INVERSIONES GRUPO C&D S.A.S."),
        _prospecto("ENT-2", 2, None, "SIN NIT"),
    ]
    ruta_entrada = _construir_top_n_csv(tmp_path, filas)

    def _cliente():
        return ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})

    salida1 = tmp_path / "salida1.csv"
    salida2 = tmp_path / "salida2.csv"
    ejecutar_enriquecimiento_legal(ruta_entrada, salida1, cliente=_cliente())
    ejecutar_enriquecimiento_legal(ruta_entrada, salida2, cliente=_cliente())

    hash1 = hashlib.sha256(salida1.read_bytes()).hexdigest()
    hash2 = hashlib.sha256(salida2.read_bytes()).hexdigest()
    assert hash1 == hash2


# ---------------------------------------------------------------------------
# O. Integridad del CSV de entrada
# ---------------------------------------------------------------------------

def test_O_integridad_del_csv_de_entrada(tmp_path):
    ruta_entrada = _construir_top_n_csv(tmp_path, [_prospecto("ENT-1", 1, "9019553183", "X")])
    hash_antes = hashlib.sha256(ruta_entrada.read_bytes()).hexdigest()
    cliente = ClienteFake({"901955318": RespuestaConfecamaras(ok=True, registros=(REGISTRO_ACTIVO,))})

    ejecutar_enriquecimiento_legal(ruta_entrada, tmp_path / "salida.csv", cliente=cliente)

    hash_despues = hashlib.sha256(ruta_entrada.read_bytes()).hexdigest()
    assert hash_antes == hash_despues


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
