/**
 * Interacción con el canvas: del ratón a las coordenadas del análisis.
 *
 * El canvas se dibuja en las dimensiones del vídeo procesado (854×480 por
 * defecto) pero se muestra escalado al ancho disponible. Confundir los dos
 * sistemas hace que los círculos se seleccionen desplazados, y es un fallo que
 * sólo se ve probando con la ventana a un tamaño raro. Estas funciones son
 * puras justamente para poder probar esa conversión sin navegador.
 */

/** Holgura sobre el radio del círculo para que no haya que clicar al píxel. */
export const CLICK_SLACK_PX = 18;

/**
 * Convierte las coordenadas de un evento de ratón a coordenadas del canvas.
 *
 * `rect` es lo que devuelve `getBoundingClientRect()`: el tamaño **mostrado**.
 * `canvas` lleva el tamaño **real** del búfer de dibujo. La razón entre los dos
 * es el factor de escala.
 */
export function canvasPointFromEvent(event, canvas, rect) {
  if (!canvas || !rect || !rect.width || !rect.height) return null;
  return {
    x: (event.clientX - rect.left) * (canvas.width / rect.width),
    y: (event.clientY - rect.top) * (canvas.height / rect.height),
  };
}

/**
 * Jugador más cercano a un punto, o `null` si ninguno está lo bastante cerca.
 *
 * Respeta las posiciones movidas a mano: si el usuario arrastró un círculo, hay
 * que poder volver a cogerlo donde lo dejó, no donde lo ve el detector.
 */
export function findPlayerAt(players, x, y, { radius = 22, posOverrides = {} } = {}) {
  if (!players?.length) return null;
  const threshold = radius + CLICK_SLACK_PX;
  let closest = null;
  let minDist = threshold;
  players.forEach((player) => {
    const override = posOverrides[player.track_id];
    const [px, py] = override ? [override.x, override.y] : player.center;
    const distance = Math.hypot(px - x, py - y);
    if (distance < minDist) {
      minDist = distance;
      closest = player;
    }
  });
  return closest;
}
