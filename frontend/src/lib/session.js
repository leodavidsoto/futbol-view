/**
 * Identificador de sesión de análisis.
 *
 * El backend aísla el estado (jugadores, equipos, calibración, métricas) por
 * `session_id`. Sin esto, dos pestañas —o dos personas— compartían la sesión
 * "default" y se pisaban los datos mutuamente.
 */

export const SESSION_STORAGE_KEY = "football-copilot:session-id";

/** Genera un identificador válido para el backend: `[A-Za-z0-9_-]{1,64}`. */
export function createSessionId(random = Math.random) {
  const suffix = Math.floor(random() * 1e9).toString(36);
  return `s${Date.now().toString(36)}-${suffix}`;
}

export function isValidSessionId(value) {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value);
}

/**
 * Devuelve el id de esta pestaña, creándolo la primera vez.
 * Se guarda en `sessionStorage`: recargar mantiene el análisis, pero una
 * pestaña nueva empieza limpia.
 */
export function getSessionId(storage = globalThis.sessionStorage) {
  if (!storage) return createSessionId();
  let id = null;
  try {
    id = storage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return createSessionId();
  }
  if (!isValidSessionId(id)) {
    id = createSessionId();
    try {
      storage.setItem(SESSION_STORAGE_KEY, id);
    } catch {
      /* modo privado: se usa el id en memoria */
    }
  }
  return id;
}

/** Descarta el id actual (para empezar un partido nuevo desde cero). */
export function resetSessionId(storage = globalThis.sessionStorage) {
  try {
    storage?.removeItem(SESSION_STORAGE_KEY);
  } catch {
    /* ignorado */
  }
  return getSessionId(storage);
}
