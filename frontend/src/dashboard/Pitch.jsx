/**
 * El campo, dibujado a escala, con lo que haya pasado encima.
 *
 * Las líneas no están dibujadas a mano: salen de los **puntos de referencia**
 * que el backend publica para cada campo. Por eso un campo de fútbol 7 o de
 * sala se dibuja con sus medidas de verdad y no con un 105×68 estirado, que es
 * lo que hacía el mini-mapa de la consola.
 */

import { heatColor, zoneGrid } from "./model.js";

const LINE = "rgba(255,255,255,0.28)";
const GRASS = "#0f2318";

/** Punto del campo por su nombre, o `null` si ese campo no lo tiene. */
function kp(pitch, nombre) {
  const punto = pitch?.keypoints?.[nombre];
  return punto ? { x: punto[0], y: punto[1] } : null;
}

function Lineas({ pitch }) {
  const centro = kp(pitch, "centro");
  const circulo = kp(pitch, "circulo_arriba");
  const radio = centro && circulo ? Math.abs(centro.y - circulo.y) : 0;

  const areas = ["izq", "der"].map((lado) => {
    const a = kp(pitch, `area_${lado}_linea_arriba`);
    const b = kp(pitch, `area_${lado}_frontal_abajo`);
    const peqA = kp(pitch, `peq_${lado}_linea_arriba`);
    const peqB = kp(pitch, `peq_${lado}_frontal_abajo`);
    return { lado, a, b, peqA, peqB, penalti: kp(pitch, `penalti_${lado}`) };
  });

  const caja = (a, b) =>
    a && b ? (
      <rect
        x={Math.min(a.x, b.x)}
        y={Math.min(a.y, b.y)}
        width={Math.abs(b.x - a.x)}
        height={Math.abs(b.y - a.y)}
        fill="none"
        stroke={LINE}
        strokeWidth={0.3}
      />
    ) : null;

  return (
    <g>
      <rect
        x={0}
        y={0}
        width={pitch.length_m}
        height={pitch.width_m}
        fill="none"
        stroke={LINE}
        strokeWidth={0.4}
      />
      <line
        x1={pitch.length_m / 2}
        y1={0}
        x2={pitch.length_m / 2}
        y2={pitch.width_m}
        stroke={LINE}
        strokeWidth={0.3}
      />
      {centro && radio > 0 && (
        <circle cx={centro.x} cy={centro.y} r={radio} fill="none" stroke={LINE} strokeWidth={0.3} />
      )}
      {centro && <circle cx={centro.x} cy={centro.y} r={0.4} fill={LINE} />}
      {areas.map(({ lado, a, b, peqA, peqB, penalti }) => (
        <g key={lado}>
          {caja(a, b)}
          {caja(peqA, peqB)}
          {penalti && <circle cx={penalti.x} cy={penalti.y} r={0.4} fill={LINE} />}
        </g>
      ))}
    </g>
  );
}

function Calor({ pitch, occupancy, onHover }) {
  const rejilla = zoneGrid(occupancy);
  if (!rejilla) return null;
  const ancho = pitch.length_m / rejilla.thirds.length;
  const alto = pitch.width_m / rejilla.corridors.length;

  return (
    <g>
      {rejilla.thirds.map((tercio, i) =>
        rejilla.corridors.map((carril, j) => {
          const celda = rejilla.cell(tercio, carril);
          return (
            <rect
              key={`${tercio}|${carril}`}
              x={i * ancho}
              y={j * alto}
              width={ancho}
              height={alto}
              fill={heatColor(celda.pct, rejilla.max)}
              opacity={0.85}
              // Hueco de 2 px de superficie entre celdas: sin él, dos zonas del
              // mismo color se leen como una sola mancha continua.
              stroke={GRASS}
              strokeWidth={0.35}
              onMouseEnter={() => onHover?.({ tercio, carril, ...celda })}
              onMouseLeave={() => onHover?.(null)}
            />
          );
        }),
      )}
    </g>
  );
}

export default function Pitch({ pitch, occupancy, height = 260, caption }) {
  if (!pitch) return null;
  const margen = 2;
  const [ancho, alto] = [pitch.length_m + margen * 2, pitch.width_m + margen * 2];

  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`${-margen} ${-margen} ${ancho} ${alto}`}
        style={{ width: "100%", height, display: "block", background: GRASS, borderRadius: 8 }}
        role="img"
        aria-label={caption || "Campo"}
      >
        <Calor pitch={pitch} occupancy={occupancy} />
        <Lineas pitch={pitch} />
      </svg>
      {caption && (
        <figcaption style={{ fontSize: 12, color: "#778", marginTop: 6 }}>{caption}</figcaption>
      )}
    </figure>
  );
}
