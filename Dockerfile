# Football Copilot — imagen de producción.
#
# Tres etapas y dos targets:
#   `servicio` → la API (lo que se despliega)
#   `web`      → nginx sirviendo el cliente compilado
#
# Van separados porque el backend **no** monta estáticos: `football_copilot_v2_backend.py`
# pertenece al carril API y montarlos desde aquí sería tocar un carril ajeno.
# Hay una solicitud abierta en `worklog/API/STATE.md` para que lo haga; mientras
# tanto, nginx delante es la separación correcta de todas formas.
#
# Los pesos del modelo NO van en la imagen: pesan cientos de megas, cambian de
# versión y no deben quedar congelados en una capa. Se montan como volumen y se
# provisionan con `scripts/fetch_weights.py` (ver INSTALACION_V2.md).

# ── Etapa 1: cliente ────────────────────────────────────────────────────
FROM node:20-slim AS cliente
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# La URL de la API la fija quien construye: en el compose por defecto es el
# mismo origen, así que se deja vacía y el cliente usa rutas relativas.
ARG VITE_API_URL=""
ARG VITE_API_KEY=""
ENV VITE_API_URL=$VITE_API_URL VITE_API_KEY=$VITE_API_KEY
RUN npm run build

# ── Etapa 2: servicio ───────────────────────────────────────────────────
FROM python:3.11-slim AS servicio

# libGL y libglib son de OpenCV: sin ellas `import cv2` falla en tiempo de
# ejecución con un error que no dice que falte un paquete del sistema.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch en CPU va en un índice aparte y pesa mucho menos que la variante CUDA.
# Si despliegas con GPU, quita esta línea y deja que requirements_v2.txt mande.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY requirements_v2.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch torchvision --index-url $TORCH_INDEX \
    && pip install --no-cache-dir -r requirements_v2.txt

COPY fcopilot/ ./fcopilot/
COPY football_copilot_v2_backend.py ./
COPY scripts/ ./scripts/
# Usuario sin privilegios: el proceso recibe vídeos de fuera y los decodifica
# con librerías nativas, que es exactamente donde no conviene ser root.
RUN useradd --create-home --uid 10001 copilot \
    && mkdir -p /app/.session_state /app/weights \
    && chown -R copilot:copilot /app
USER copilot

ENV HOST=0.0.0.0 \
    PORT=8000 \
    MODEL_ROOT=/app/weights \
    SESSION_STATE_DIR=/app/.session_state \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# `/health` responde sin credencial a propósito: una sonda de vida que exige
# credencial no sirve de sonda de vida.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "football_copilot_v2_backend:app", "--host", "0.0.0.0", "--port", "8000"]


# ── Etapa 3: cliente servido ────────────────────────────────────────────
FROM nginx:1.27-alpine AS web
COPY --from=cliente /app/frontend/dist /usr/share/nginx/html
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
