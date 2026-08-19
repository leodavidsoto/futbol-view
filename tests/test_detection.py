"""Detección: el camino normal, no sólo el degradado.

Antes de este fichero, `fcopilot/detection.py` estaba al 75 % de cobertura y lo
que se probaba era la ausencia de dependencias: que sin `ultralytics` el error
saliera al usar y no al importar. El funcionamiento normal —que es lo que corre
en producción— no se ejercitaba. Aquí se ejercita con dobles, sin meter
`ultralytics` ni `torch` en CI: la regla 7 sigue en pie.
"""

from __future__ import annotations

import numpy as np
import pytest

from fcopilot import detection
from fcopilot.config import BALL_CLASS, PERSON_CLASS
from fcopilot.detection import (
    Detector,
    DetectorUnavailable,
    SharedYOLORegistry,
    shared_yolo_registry,
    split_by_class,
)

CONFIG_NORMAL = {
    "model_path": "yolo11x.pt",
    "confidence": 0.25,
    "iou": 0.45,
    "imgsz": 640,
    "augment": False,
    "agnostic_nms": False,
    "detection_mode": "normal",
    "sahi_slice": 320,
    "sahi_overlap": 0.2,
}


@pytest.fixture
def frame() -> np.ndarray:
    return np.zeros((480, 854, 3), dtype=np.uint8)


# ── Reparto por clase ───────────────────────────────────────────────────
def test_reparte_personas_y_balon():
    personas, confs, balones = split_by_class(
        [
            ((0, 0, 10, 20), 0.9, PERSON_CLASS),
            ((5, 5, 12, 12), 0.5, BALL_CLASS),
            ((1, 1, 9, 19), 0.7, PERSON_CLASS),
        ]
    )
    assert len(personas) == 2 and confs == [0.9, 0.7]
    assert len(balones) == 1 and balones[0][1] == 0.5


def test_ignora_clases_que_no_son_ni_persona_ni_balon():
    personas, confs, balones = split_by_class([((0, 0, 5, 5), 0.9, 7)])
    assert (personas, confs, balones) == ([], [], [])


def test_las_cajas_salen_como_arrays_de_numpy():
    personas, _, balones = split_by_class(
        [((0, 0, 10, 20), 0.9, PERSON_CLASS), ((0, 0, 5, 5), 0.4, BALL_CLASS)]
    )
    assert isinstance(personas[0], np.ndarray)
    assert isinstance(balones[0][0], np.ndarray)


# ── Camino normal ───────────────────────────────────────────────────────
def test_predict_normal_devuelve_lo_que_da_el_modelo(fake_yolo, frame):
    fake_yolo.set_script([[((10, 10, 34, 70), 0.9, PERSON_CLASS), ((100, 100, 112, 112), 0.6, BALL_CLASS)]])
    personas, confs, balones = Detector(dict(CONFIG_NORMAL)).predict(frame)
    assert len(personas) == 1 and confs == [0.9]
    assert len(balones) == 1


def test_predict_normal_pasa_la_configuracion_al_modelo(fake_yolo, frame):
    config = dict(CONFIG_NORMAL, confidence=0.33, iou=0.55, imgsz=960, augment=True, agnostic_nms=True)
    fake_yolo.set_script([[]])
    Detector(config).predict(frame)
    kwargs = fake_yolo.last_kwargs
    assert kwargs["conf"] == pytest.approx(0.33)
    assert kwargs["iou"] == pytest.approx(0.55)
    assert kwargs["imgsz"] == 960
    assert kwargs["augment"] is True and kwargs["agnostic_nms"] is True
    assert sorted(kwargs["classes"]) == sorted([PERSON_CLASS, BALL_CLASS])


def test_un_frame_sin_detecciones_no_es_un_error(fake_yolo, frame):
    fake_yolo.set_script([[]])
    assert Detector(dict(CONFIG_NORMAL)).predict(frame) == ([], [], [])


def test_el_modo_sahi_cae_al_normal_si_sahi_no_esta_listo(fake_yolo, frame, monkeypatch):
    """Degradar es correcto; degradar en silencio y sin detectar nada, no.

    La ausencia de SAHI se fuerza en vez de darla por hecha: la versión anterior
    afirmaba `sahi_ready is False` y sólo pasaba en un entorno donde SAHI no
    estuviera instalado — es decir, probaba el entorno y no el código.
    """
    monkeypatch.setattr(detection, "SAHI_AVAILABLE", False)
    fake_yolo.set_script([[((10, 10, 34, 70), 0.8, PERSON_CLASS)]])
    detector = Detector(dict(CONFIG_NORMAL, detection_mode="sahi"))
    assert detector.sahi_ready is False
    personas, _, _ = detector.predict(frame)
    assert len(personas) == 1, "el modo sahi sin sahi debe seguir detectando"


def test_recargar_cambia_el_modelo(fake_yolo, frame):
    detector = Detector(dict(CONFIG_NORMAL))
    otro = type(fake_yolo)()
    otro.set_script([[((0, 0, 24, 60), 0.7, PERSON_CLASS)]])
    shared_yolo_registry.register("otro.pt", otro)
    detector.reload("otro.pt")
    assert detector.model_path == "otro.pt"
    personas, confs, _ = detector.predict(frame)
    assert confs == [0.7]


# ── Registro compartido ─────────────────────────────────────────────────
def test_dos_detectores_comparten_el_mismo_modelo(fake_yolo):
    uno, dos = Detector(dict(CONFIG_NORMAL)), Detector(dict(CONFIG_NORMAL))
    assert uno.model is dos.model, "cargar YOLO dos veces duplicaría el consumo de memoria"


def test_el_registro_cuenta_los_modelos_cargados(fake_yolo):
    Detector(dict(CONFIG_NORMAL))
    assert shared_yolo_registry.stats()["shared_yolo_models"] >= 1


# ── Camino degradado ────────────────────────────────────────────────────
def test_sin_ultralytics_el_error_sale_al_usar_no_al_importar(monkeypatch):
    """La regla 7: el módulo importa siempre; el fallo llega en la llamada."""
    registro = SharedYOLORegistry()
    monkeypatch.setattr(detection, "YOLO_AVAILABLE", False)
    with pytest.raises(DetectorUnavailable, match="ultralytics"):
        registro.get("cualquier-modelo.pt")


def test_el_registro_vacio_no_conoce_ningun_modelo():
    registro = SharedYOLORegistry()
    assert registro.stats() == {"shared_yolo_models": 0}


# ── Índices de clase configurables ──────────────────────────────────────
#
# Un modelo entrenado para fútbol no usa los índices de COCO: trae sus propias
# clases (`ball`, `player`, `referee`, `goalkeeper`). Con los índices fijos en
# el código, la app sólo podía usar modelos COCO — que son justamente los que
# fallan en tomas elevadas donde los jugadores ocupan pocos píxeles.

CLASES_FUTBOL = {"ball": 0, "goalkeeper": 1, "player": 2, "referee": 3}


def test_reparte_con_los_indices_de_un_modelo_de_futbol():
    personas, confs, balones = split_by_class(
        [
            ((0, 0, 10, 20), 0.9, CLASES_FUTBOL["player"]),
            ((5, 5, 12, 12), 0.5, CLASES_FUTBOL["ball"]),
            ((1, 1, 9, 19), 0.7, CLASES_FUTBOL["referee"]),
        ],
        person_class=CLASES_FUTBOL["player"],
        ball_class=CLASES_FUTBOL["ball"],
    )
    assert len(personas) == 1 and confs == [0.9]
    assert len(balones) == 1
    # El árbitro no es un jugador: con los índices de COCO habría entrado como
    # persona y contaminado las métricas del partido.


def test_por_defecto_siguen_siendo_los_de_coco():
    personas, _, balones = split_by_class(
        [((0, 0, 10, 20), 0.9, PERSON_CLASS), ((0, 0, 5, 5), 0.5, BALL_CLASS)]
    )
    assert len(personas) == 1 and len(balones) == 1


def test_el_detector_pide_al_modelo_sus_propias_clases(fake_yolo, frame):
    """Sin esto, se le piden a un modelo de fútbol las clases 0 y 32, y la 32 no
    existe."""
    fake_yolo.set_script([[]])
    config = dict(CONFIG_NORMAL, person_class=CLASES_FUTBOL["player"], ball_class=CLASES_FUTBOL["ball"])
    Detector(config).predict(frame)
    assert sorted(fake_yolo.last_kwargs["classes"]) == [0, 2]


def test_el_detector_reparte_segun_las_clases_configuradas(fake_yolo, frame):
    fake_yolo.set_script([[
        ((10, 10, 34, 70), 0.9, CLASES_FUTBOL["player"]),
        ((100, 100, 112, 112), 0.6, CLASES_FUTBOL["ball"]),
    ]])
    config = dict(CONFIG_NORMAL, person_class=CLASES_FUTBOL["player"], ball_class=CLASES_FUTBOL["ball"])
    personas, confs, balones = Detector(config).predict(frame)
    assert confs == [0.9] and len(balones) == 1


def test_un_detector_sin_las_claves_nuevas_no_se_rompe(fake_yolo, frame):
    """Sesiones guardadas antes de que existieran estas claves."""
    fake_yolo.set_script([[((10, 10, 34, 70), 0.9, PERSON_CLASS)]])
    detector = Detector(dict(CONFIG_NORMAL))          # sin person_class ni ball_class
    assert (detector.person_class, detector.ball_class) == (PERSON_CLASS, BALL_CLASS)
    assert len(detector.predict(frame)[0]) == 1


def test_cambiar_las_clases_en_caliente_afecta_al_detector(fake_yolo, frame):
    """Se leen en vivo de la configuración, no se congelan en el constructor.

    Era un fallo real: `apply_config` actualiza el diccionario de configuración
    que el detector comparte por referencia, así que un índice cacheado en
    `__init__` sobrevivía a un cambio de modelo. El detector seguía pidiendo las
    clases del modelo anterior y devolvía casi nada, con un síntoma que no se
    parecía en nada a su causa.
    """
    config = dict(CONFIG_NORMAL)
    detector = Detector(config)
    assert detector.person_class == PERSON_CLASS

    config["person_class"] = CLASES_FUTBOL["player"]
    config["ball_class"] = CLASES_FUTBOL["ball"]
    assert detector.person_class == CLASES_FUTBOL["player"]

    fake_yolo.set_script([[((10, 10, 34, 70), 0.9, CLASES_FUTBOL["player"])]])
    assert len(detector.predict(frame)[0]) == 1
    assert sorted(fake_yolo.last_kwargs["classes"]) == [0, 2]
