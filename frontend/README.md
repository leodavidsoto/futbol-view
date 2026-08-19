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

## Estructura

- `src/App.jsx` — componente principal: canvas, overlays e interacción.
- `src/lib/` — lógica sin DOM (formato, búfer de frames, sesión, cliente HTTP),
  que es lo que cubren los tests.

## Verificación

```bash
npm run lint
npm test
npm run build
```
