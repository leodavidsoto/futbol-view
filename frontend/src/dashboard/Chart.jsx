/**
 * Gráfico de líneas para las series colectivas del partido.
 *
 * Un solo eje, siempre. Amplitud y longitud del bloque se dibujan juntas
 * porque **están en las mismas unidades** —metros— y por tanto comparten
 * escala de verdad. Dos ejes con escalas distintas dejan que quien dibuja
 * decida qué línea va por encima de cuál, que es la forma más fácil de mentir
 * con un gráfico sin decir una sola cosa falsa.
 */

import { useState } from "react";

const AXIS = "rgba(255,255,255,0.16)";
const INK = "#889";

function escala(valores, minimoRango) {
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 };
  if (max - min < minimoRango) {
    const centro = (max + min) / 2;
    return { min: centro - minimoRango / 2, max: centro + minimoRango / 2 };
  }
  return { min, max };
}

/**
 * @param {Array<{name, color, points: Array<{x, y}>}>} series - misma unidad, un eje
 */
export default function Chart({ series = [], unit = "", height = 200, xLabel = "min" }) {
  const [activo, setActivo] = useState(null);
  const conDatos = series.filter((s) => s.points.length > 1);
  if (!conDatos.length) {
    return (
      <p style={{ color: "#667", fontSize: 13 }}>
        Todavía no hay bastantes minutos analizados para dibujar la evolución.
      </p>
    );
  }

  const W = 640;
  const H = height;
  const pad = { top: 12, right: 14, bottom: 26, left: 40 };
  const todosX = conDatos.flatMap((s) => s.points.map((p) => p.x));
  const todosY = conDatos.flatMap((s) => s.points.map((p) => p.y));
  const ex = escala(todosX, 1);
  // El eje **no** se fuerza a cero, y es deliberado. La amplitud de un equipo
  // se mueve entre 20 y 30 m: con el cero dentro, toda la señal se aplasta
  // contra el techo del gráfico y no se ve nada de lo que se quiere ver. Un
  // eje que no arranca en cero exagera las diferencias, así que la defensa es
  // que las marcas del eje están siempre rotuladas: quien mira ve el rango.
  // (Una barra sí tendría que arrancar en cero; una línea de una magnitud
  // continua, no.)
  const ey = escala(todosY, 5);

  const px = (x) => pad.left + ((x - ex.min) / (ex.max - ex.min || 1)) * (W - pad.left - pad.right);
  const py = (y) => H - pad.bottom - ((y - ey.min) / (ey.max - ey.min || 1)) * (H - pad.top - pad.bottom);

  const marcasY = [ey.min, (ey.min + ey.max) / 2, ey.max];

  // Etiquetas directas separadas: dos series que terminan en el mismo valor
  // escriben su nombre encima del otro y no se lee ninguno. Se reparten en
  // vertical manteniendo el orden en el que acaban.
  const etiquetas = conDatos
    .map((s, i) => ({ s, i, y: py(s.points[s.points.length - 1].y) }))
    .sort((a, b) => a.y - b.y);
  const MINIMA_SEPARACION = 14;
  etiquetas.forEach((etiqueta, k) => {
    if (k > 0) {
      etiqueta.y = Math.max(etiqueta.y, etiquetas[k - 1].y + MINIMA_SEPARACION);
    }
  });
  const alturaEtiqueta = new Map(etiquetas.map((e) => [e.s.name, e.y]));

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height }} role="img">
        {marcasY.map((valor) => (
          <g key={valor}>
            <line x1={pad.left} y1={py(valor)} x2={W - pad.right} y2={py(valor)} stroke={AXIS} strokeWidth={1} />
            <text x={pad.left - 6} y={py(valor) + 4} textAnchor="end" fontSize={11} fill={INK}>
              {Math.round(valor)}
            </text>
          </g>
        ))}
        <text x={pad.left} y={H - 6} fontSize={11} fill={INK}>
          {Math.round(ex.min)} {xLabel}
        </text>
        <text x={W - pad.right} y={H - 6} fontSize={11} fill={INK} textAnchor="end">
          {Math.round(ex.max)} {xLabel}
        </text>

        {conDatos.map((s) => (
          <g key={s.name}>
            <path
              d={s.points.map((p, i) => `${i ? "L" : "M"}${px(p.x)},${py(p.y)}`).join(" ")}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {/* Etiqueta directa en el último punto: la identidad no depende
                sólo del color, que es lo que pide no fiarlo todo al daltónico. */}
            <text
              x={px(s.points[s.points.length - 1].x) - 4}
              y={alturaEtiqueta.get(s.name) - 6}
              fontSize={11}
              fill={s.color}
              textAnchor="end"
            >
              {s.name}
            </text>
          </g>
        ))}

        {/* Capa de interacción: una banda por bloque de tiempo. */}
        {conDatos[0].points.map((punto, i) => {
          const ancho = (W - pad.left - pad.right) / Math.max(conDatos[0].points.length, 1);
          return (
            <rect
              key={i}
              x={px(punto.x) - ancho / 2}
              y={pad.top}
              width={ancho}
              height={H - pad.top - pad.bottom}
              fill="transparent"
              onMouseEnter={() => setActivo(i)}
              onMouseLeave={() => setActivo(null)}
            />
          );
        })}
        {activo !== null && conDatos[0].points[activo] && (
          <line
            x1={px(conDatos[0].points[activo].x)}
            y1={pad.top}
            x2={px(conDatos[0].points[activo].x)}
            y2={H - pad.bottom}
            stroke="rgba(255,255,255,0.35)"
            strokeWidth={1}
          />
        )}
      </svg>

      {activo !== null && conDatos[0].points[activo] && (
        <div
          style={{
            position: "absolute", top: 4, right: 8, padding: "6px 10px",
            background: "#11111c", border: "1px solid #262636", borderRadius: 6,
            fontSize: 12, color: "#ccd", pointerEvents: "none",
          }}
        >
          <div style={{ color: INK, marginBottom: 2 }}>
            minuto {Math.round(conDatos[0].points[activo].x)}
          </div>
          {conDatos.map((s) => (
            <div key={s.name}>
              <span style={{ color: s.color }}>■</span> {s.name}:{" "}
              {s.points[activo] ? `${Math.round(s.points[activo].y)} ${unit}` : "—"}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 14, fontSize: 12, color: INK, marginTop: 4 }}>
        {conDatos.map((s) => (
          <span key={s.name}>
            <span style={{ color: s.color }}>■</span> {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}
