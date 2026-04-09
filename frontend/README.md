# Football Copilot Frontend

Frontend React + Vite para visualizar detecciones, overlays, calibración y análisis de posesión/tracking del backend FastAPI.

## Requisitos

- Node.js 18+
- Backend corriendo en `http://localhost:8000` o una URL configurada vía variables Vite

## Desarrollo

```bash
cd frontend
npm install
npm run dev
```

## Variables de entorno

Crea un `.env` local a partir de `.env.example` si el backend no vive en `localhost`.

```bash
VITE_API_URL=http://localhost:8000
# Opcional: si el websocket usa otra URL/base
VITE_WS_URL=ws://localhost:8000
```

## Verificación

```bash
npm run lint
npm run build
```
