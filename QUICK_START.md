# Quick Start - Football Copilot v2/v3

Esta versión real del proyecto usa:

- Backend FastAPI: `football_copilot_v2_backend.py`
- Frontend Vite/React: `frontend/`
- Dependencias Python: `requirements_v2.txt`

## Requisitos

- Python 3.10+
- Node.js 18+
- Un entorno virtual Python recomendado en `./venv`

## Backend

```bash
source venv/bin/activate
pip install -r requirements_v2.txt
python football_copilot_v2_backend.py
```

API esperada:

- `http://localhost:8000/health`
- `http://localhost:8000/docs`

## Frontend

```bash
cd frontend
npm install
npm run dev
```

UI esperada:

- `http://localhost:5173`

## Configuración opcional del frontend

Si el backend no corre en `localhost:8000`, crea `frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Flujo de uso

1. Levanta backend y frontend.
2. Sube un video desde el panel derecho.
3. Detecta jugadores en un frame de preview.
4. Ajusta equipo/nombre si hace falta.
5. Inicia el análisis completo.
6. Exporta el JSON final desde la interfaz.

## Verificación rápida

```bash
cd frontend && npm run lint && npm run build
python3 -m py_compile football_copilot_v2_backend.py
```

## Nota

En este workspace ya existe `venv` con la mayoría de dependencias instaladas. Si ejecutas fuera de ese entorno, instala `requirements_v2.txt` antes de arrancar.
