"""Validación de la configuración del runtime."""

import pytest

from fcopilot.config import ConfigError, DEFAULTS, default_runtime_config, merge_config, validate_config


def test_los_defaults_son_una_copia():
    a, b = default_runtime_config(), default_runtime_config()
    a["imgsz"] = 640
    assert b["imgsz"] == DEFAULTS["imgsz"] == 1280


def test_clave_desconocida():
    with pytest.raises(ConfigError, match="desconocida"):
        validate_config({"borrar_todo": True})


@pytest.mark.parametrize(
    "patch",
    [
        {"imgsz": 64},            # por debajo del mínimo
        {"imgsz": 4096},          # por encima del máximo
        {"confidence": 1.5},
        {"sahi_overlap": 0.9},
        {"norfair_dist": 0},
        {"frame_skip": 99},
        {"detection_mode": "magia"},
        {"tracker_type": "deepsort"},
        {"team_classifier": "hsv"},
    ],
)
def test_valores_fuera_de_rango(patch):
    with pytest.raises(ConfigError):
        validate_config(patch)


def test_conversion_de_tipos():
    limpio = validate_config({"imgsz": "640", "confidence": "0.4", "augment": 1})
    assert limpio == {"imgsz": 640, "confidence": 0.4, "augment": True}


def test_los_booleanos_no_valen_como_numeros():
    with pytest.raises(ConfigError):
        validate_config({"imgsz": True})


def test_los_none_se_ignoran():
    assert validate_config({"imgsz": None, "confidence": 0.3}) == {"confidence": 0.3}


def test_merge_aplica_el_parche_sobre_los_defaults():
    merged = merge_config(None, {"imgsz": 640, "tracker_type": "simple"})
    assert merged["imgsz"] == 640
    assert merged["tracker_type"] == "simple"
    assert merged["confidence"] == DEFAULTS["confidence"]


def test_merge_descarta_claves_extranas_de_un_estado_guardado():
    merged = merge_config({"imgsz": 800, "obsoleto": 1}, None)
    assert merged["imgsz"] == 800
    assert "obsoleto" not in merged
