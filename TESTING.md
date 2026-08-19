# Tests

## Backend

```bash
pip install -r requirements-dev.txt
pytest                                                   # toda la suite
pytest tests/test_kinematics.py -v                       # un módulo
pytest --cov=fcopilot --cov-report=term-missing          # con cobertura
```

`requirements-dev.txt` es deliberadamente ligero: **no** instala YOLO, SAHI,
Norfair ni PyTorch. El paquete `fcopilot` importa esas dependencias de forma
opcional y `tests/conftest.py` registra un modelo falso (`FakeYOLO`) en el
registro compartido de detectores, que devuelve las cajas que el test dicta.
Consecuencias:

* la suite completa tarda segundos, no minutos;
* los resultados son deterministas (nada de pesos descargados ni GPU);
* se prueba también el camino degradado, que es el que ve un usuario sin GPU.

### Qué cubre

| Fichero | Qué verifica |
|---|---|
| `test_config.py` | Rangos, enums y rechazo de claves desconocidas. |
| `test_geometry.py` | Homografía exacta en las 4 esquinas y rechazo de puntos degenerados. |
| `test_kinematics.py` | Distancia sin doble conteo, velocidad independiente del muestreo, sprints y zonas. |
| `test_possession.py` | Histéresis, porcentajes que suman 100 y contabilidad en segundos. |
| `test_tracking.py` | Identidades estables, oclusiones y limpieza de tracks. |
| `test_teams.py` | Separación de dos kits, etiquetas estables entre reajustes y voto temporal. |
| `test_report.py` | Agregados por equipo, clasificaciones y casos vacíos. |
| `test_sessions.py` | Aislamiento, TTL, desalojo por límite y persistencia. |
| `test_analyzer.py` | El recorrido completo detección → tracking → métricas. |
| `test_api.py` | Todos los endpoints, el WebSocket y los errores (400/409/413/415/422/429). |

### Escribir un test de análisis

```python
def test_algo(analyzer, fake_yolo, green_frame):
    fake_yolo.set_script([players_row(4) + [ball_box(120, 110)]])  # cajas por frame
    resultado = analyzer.process_frame(green_frame, timestamp=0.0)
    assert resultado["stats"]["total_players"] >= 0
```

`timestamp` es la base de tiempo de las métricas: pásalo siempre en los tests
para que las velocidades sean reproducibles.

## Frontend

```bash
cd frontend
npm test              # vitest, una pasada
npm run test:watch    # modo interactivo
npm run lint
npm run build
```

Las pruebas viven en `src/lib/__tests__/` y cubren la lógica que se puede
extraer del componente: formato, búsqueda binaria de frames, parseo NDJSON,
identificador de sesión y cliente HTTP (con `fetch` simulado).

## CI

`.github/workflows/ci.yml` ejecuta ambas suites en cada push y pull request:
el trabajo de backend instala `requirements-dev.txt` y corre `pytest` con
cobertura; el de frontend hace `npm ci`, lint, tests y build.
