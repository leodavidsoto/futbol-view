# Quick Start — Football Copilot

- Backend FastAPI: `football_copilot_v2_backend.py` (+ paquete `fcopilot/`)
- Frontend Vite/React: `frontend/`
- Dependencias de ejecución: `requirements_v2.txt`
- Dependencias de desarrollo y CI: `requirements-dev.txt`

## Requisitos

- Python 3.10+
- Node.js 18+
- Entorno virtual recomendado en `./venv`

## Backend

```bash
source venv/bin/activate
pip install -r requirements_v2.txt
python football_copilot_v2_backend.py
```

- `http://localhost:8000/health` → estado y capacidades detectadas
- `http://localhost:8000/docs` → Swagger

## Frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
```

## Configuración opcional del frontend

Si el backend no corre en `localhost:8000`, crea `frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Las dos vistas

La aplicación tiene dos pestañas, y son para dos personas distintas:

| Pestaña | Para qué |
|---|---|
| **🎛️ Análisis** | Afinar el sistema: detección, seguimiento, umbrales, overlay |
| **📋 Panel del DT** | Decidir: quién está fundido, quién no corre, posesión |

El panel **empieza por decirte si te puedes fiar de los números**. Si sale «No
decidas con esto», el semáforo de sustituciones se oculta solo y arriba pone por
qué. No es un adorno: sin calibración las distancias no son metros, y con el
seguimiento partiendo jugadores las cifras por jugador reparten entre varios lo
que hizo uno.

## Flujo de uso

1. Levanta backend y frontend.
2. Sube un vídeo desde el panel derecho.
3. Navega hasta el segundo que te interese y pulsa **Detectar aquí**.
4. Haz clic en cada círculo para corregir equipo y nombre.
5. **Calibra el campo.** Sin esto las distancias son estimaciones de una escala
   fija de píxeles por metro que no corresponde a tu campo. Dos formas:
   - **Por puntos con nombre** (recomendado): dices qué campo es —`futbol_11`,
     `futbol_7` o `futbol_sala`— y señalas puntos que reconoces sin saber
     cuánto miden. Admite más de cuatro, y con más sale mejor.
   - **Por 4 esquinas**, la de siempre, que exige escribir las coordenadas del
     mundo en metros.
6. *(Si jugáis en media cancha)* Dibuja la **zona de juego**. Descarta lo que se
   detecte fuera antes de seguirlo, y es lo que hizo que la posesión pasara de
   no adjudicarse nunca a un 48/52 en las pruebas con material real.
7. **Iniciar análisis** y espera al streaming de resultados.
8. Abre **📋 Panel del DT**. Reproduce el vídeo con el overlay o exporta el JSON.

### Calibrar por API, si prefieres

```bash
# Qué campos hay y qué puntos tiene cada uno
curl -s localhost:8000/api/pitches | python3 -m json.tool | head -40

# Calibrar señalando puntos por su nombre (coordenadas en PÍXELES de la imagen)
curl -s -X POST localhost:8000/api/calibrate-landmarks \
  -H 'content-type: application/json' -H 'x-session-id: mi-partido' \
  -d '{"pitch": "futbol_7",
       "points": {"esquina_izq_arriba": [120, 340],
                  "esquina_der_arriba": [1180, 300],
                  "esquina_der_abajo":  [1320, 690],
                  "esquina_izq_abajo":  [40, 720],
                  "medio_arriba":       [650, 315],
                  "medio_abajo":        [660, 700]}}'

# El panel del cuerpo técnico
curl -s localhost:8000/api/dashboard -H 'x-session-id: mi-partido'
```

Si un nombre está mal, la respuesta te dice cuál. Si los puntos están casi
alineados, te dice eso y qué hacer.

## Qué contiene el JSON exportado

```jsonc
{
  "meta":     { "frames_analyzed": 900, "duration_s": 120.0, "calibrated": true },
  "possession": { "share": {...}, "percentages": {...}, "seconds": {...}, "changes": 34 },
  "teams":    { "team_1": { "total_dist_m": 8123.4, "sprints": 27, "zones_m": {...} } },
  "totals":   { "players_tracked": 22, "top_speed_kmh": 31.2 },
  "leaderboards": { "distance": [...], "top_speed": [...], "sprints": [...] },
  "players":  [ { "name": "#7", "team": "team_1", "max_speed_kmh": 29.4, "positions": [...] } ]
}
```

Para el mismo informe sin el rastro de posiciones (mucho más ligero):
`GET /api/report`.

## Sesiones

Cada pestaña usa su propio `session_id` y no interfiere con las demás. El botón
**🆕 Nueva sesión** del panel de acciones descarta la actual y empieza de cero.

## Verificación rápida

```bash
pip install -r requirements-dev.txt && pytest
cd frontend && npm run lint && npm test && npm run build
```
