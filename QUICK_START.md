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

## Flujo de uso

1. Levanta backend y frontend.
2. Sube un vídeo desde el panel derecho.
3. Navega hasta el segundo que te interese y pulsa **Detectar aquí**.
4. Haz clic en cada círculo para corregir equipo y nombre.
5. *(Recomendado)* **Calibrar campo (4 pts)**: marca las esquinas del campo en
   este orden — superior izquierda, superior derecha, inferior derecha,
   inferior izquierda. Sin calibrar, las distancias y velocidades son
   estimaciones a partir de una escala px/m; con homografía son metros reales.
6. **Iniciar análisis** y espera al streaming de resultados.
7. Reproduce el vídeo con el overlay sincronizado y exporta el JSON.

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
