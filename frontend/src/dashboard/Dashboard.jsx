/**
 * Panel del cuerpo técnico.
 *
 * No es «el panel del entrenador»: un cuerpo técnico son cinco o seis personas
 * con preguntas distintas, y la interfaz se organiza por esas preguntas y no
 * por la forma de nuestras estructuras de datos. `CUERPO_TECNICO.md` explica de
 * dónde sale cada sección y, sobre todo, qué se decidió **no** enseñar porque
 * no se puede medir con una cámara.
 *
 * | Sección | Quién la mira | Qué responde |
 * |---|---|---|
 * | Partido | El entrenador, en la banda | ¿Me fío? ¿A quién cambio? |
 * | Físico | El preparador físico | Carga por jugador |
 * | Colectivo | Entrenador y segundo | Forma del bloque, ocupación del campo |
 * | Jugador | Todos | El detalle de uno |
 *
 * Encima de las cuatro, siempre, la franja de calidad: si los datos no se
 * sostienen, eso se lee antes que cualquier conclusión.
 *
 * Todo lo que decide vive en `model.js` y en el backend. Aquí sólo hay
 * maquetación.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "../lib/api.js";
import Chart from "./Chart.jsx";
import Pitch from "./Pitch.jsx";
import {
  BAND_ORDER,
  COLLECTIVE_TILES,
  COLUMNS,
  bandColor,
  bandLabel,
  bandShares,
  byTeam,
  cell,
  collectiveTeams,
  confidenceStyle,
  fmt,
  fmtDuration,
  fmtFragmentation,
  hasCollective,
  headline,
  isActionable,
  possessionShare,
  series,
  statusStyle,
  teamColor,
  teamLabel,
} from "./model.js";

const TONE_BG = { good: "#00ff8815", warn: "#ffcc0015", bad: "#ff446618", neutral: "#ffffff08" };
const TONE_FG = { good: "#00ff88", warn: "#ffcc00", bad: "#ff6688", neutral: "#9999bb" };

const s = {
  root: { padding: "18px 22px", overflowY: "auto", flex: 1, background: "#080810" },
  headline: { padding: "16px 20px", borderRadius: 12, fontSize: 19, fontWeight: 600, lineHeight: 1.35, marginBottom: 14 },
  strip: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14, fontSize: 13 },
  chip: { padding: "3px 10px", borderRadius: 20, fontSize: 12, fontWeight: 600 },
  warning: { display: "flex", gap: 9, padding: "9px 13px", borderRadius: 8, fontSize: 13, lineHeight: 1.45, marginBottom: 7 },
  tabs: { display: "flex", gap: 4, borderBottom: "1px solid #1a1a28", margin: "18px 0 4px" },
  tab: {
    padding: "8px 15px", background: "transparent", border: "none", color: "#778",
    borderBottomWidth: 2, borderBottomStyle: "solid", borderBottomColor: "transparent",
    cursor: "pointer", fontSize: 13, fontWeight: 600,
  },
  tabActive: { color: "#00ff88", borderBottomColor: "#00ff88" },
  kpis: { display: "flex", gap: 12, flexWrap: "wrap", margin: "16px 0 20px" },
  kpi: { flex: "1 1 140px", background: "#0d0d1a", border: "1px solid #1a1a28", borderRadius: 10, padding: "12px 15px" },
  kpiLabel: { fontSize: 11, color: "#667", textTransform: "uppercase", letterSpacing: 0.6 },
  kpiValue: { fontSize: 25, fontWeight: 700, color: "#eee", marginTop: 3 },
  kpiNote: { fontSize: 11, color: "#556", marginTop: 2 },
  section: { fontSize: 12, color: "#889", textTransform: "uppercase", letterSpacing: 1, margin: "22px 0 10px" },
  card: { display: "flex", alignItems: "center", gap: 13, padding: "11px 15px", borderRadius: 9, marginBottom: 7, border: "1px solid #1a1a28" },
  cardName: { fontWeight: 700, fontSize: 15, minWidth: 110 },
  cardDetail: { fontSize: 13, color: "#aab", lineHeight: 1.4 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "right", padding: "7px 9px", color: "#667", fontWeight: 600, borderBottom: "1px solid #1a1a28", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5, whiteSpace: "nowrap" },
  td: { textAlign: "right", padding: "7px 9px", borderBottom: "1px solid #12121c", whiteSpace: "nowrap" },
  bar: { display: "flex", height: 6, borderRadius: 3, overflow: "hidden", minWidth: 90 },
  panel: { background: "#0d0d1a", border: "1px solid #1a1a28", borderRadius: 10, padding: 16 },
  grid2: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 },
  foot: { marginTop: 26, fontSize: 12, color: "#556", lineHeight: 1.6, maxWidth: 760 },
  reload: { marginLeft: "auto", padding: "6px 14px", borderRadius: 7, cursor: "pointer", background: "#1a1a28", color: "#aab", border: "1px solid #262636", fontSize: 12 },
  legend: { display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "#778", marginTop: 8 },
  empty: { color: "#667", fontSize: 13, lineHeight: 1.5 },
};

function Kpi({ label, value, note }) {
  return (
    <div style={s.kpi}>
      <div style={s.kpiLabel}>{label}</div>
      <div style={s.kpiValue}>{value}</div>
      {note ? <div style={s.kpiNote}>{note}</div> : null}
    </div>
  );
}

function BandBar({ bands }) {
  const partes = bandShares(bands);
  if (!partes.length) return <span style={{ color: "#445" }}>—</span>;
  return (
    <div style={s.bar} title={partes.map((p) => `${bandLabel(p.name)}: ${Math.round(p.meters)} m`).join("  ·  ")}>
      {partes.map((p) => (
        <div key={p.name} style={{ width: `${p.pct}%`, background: bandColor(p.name) }} />
      ))}
    </div>
  );
}

/** Leyenda de la rampa de bandas. Sin ella, la barra apilada es adorno. */
function BandLegend() {
  return (
    <div style={s.legend}>
      {BAND_ORDER.map((banda) => (
        <span key={banda}>
          <span style={{ color: bandColor(banda) }}>■</span> {bandLabel(banda)}
        </span>
      ))}
    </div>
  );
}

function PlayerTable({ players, onSelect }) {
  return (
    <table style={s.table}>
      <thead>
        <tr>
          {COLUMNS.map((c) => (
            <th key={c.key} style={{ ...s.th, textAlign: c.align || "right" }}>{c.label}</th>
          ))}
          <th style={s.th}>Reparto</th>
        </tr>
      </thead>
      <tbody>
        {players.map((fila) => {
          const estado = statusStyle(fila.status);
          return (
            <tr
              key={fila.track_id}
              onClick={() => onSelect?.(fila.track_id)}
              style={{ cursor: onSelect ? "pointer" : "default" }}
            >
              {COLUMNS.map((c) => (
                <td
                  key={c.key}
                  style={{
                    ...s.td,
                    textAlign: c.align || "right",
                    color: c.key === "name" ? estado.color : "#ccd",
                    fontWeight: c.key === "name" ? 600 : 400,
                  }}
                >
                  {cell(c, fila)}
                </td>
              ))}
              <td style={{ ...s.td, width: 110 }}><BandBar bands={fila.bands_m} /></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ── Secciones ──────────────────────────────────────────────────────────

function Partido({ data, accionable }) {
  const posesion = possessionShare(data.possession);
  return (
    <>
      <div style={s.kpis}>
        <Kpi label="Posesión" value={`${fmt(posesion.team_1)} / ${fmt(posesion.team_2)}`} note="equipo 1 / equipo 2" />
        <Kpi label="Distancia" value={fmt(data.teams?.team_1?.total_dist_m, { unit: "m" })} note="equipo 1" />
        <Kpi label="Alta intensidad" value={fmt(data.teams?.team_1?.high_intensity_m, { unit: "m" })} note="equipo 1" />
        <Kpi label="Sprints" value={fmt(data.teams?.team_1?.sprints)} note="equipo 1" />
        <Kpi label="Campo" value={data.match?.pitch || "sin calibrar"} note={data.match?.distance_unit} />
      </div>

      <div style={s.section}>A quién mirar</div>
      {!accionable ? (
        <div style={{ ...s.warning, background: TONE_BG.bad, color: TONE_FG.bad }}>
          <span>⛔</span>
          <span>
            El semáforo de sustituciones está oculto porque los datos de arriba no lo
            sostienen. Las cifras siguen sirviendo para comparar jugadores entre sí.
          </span>
        </div>
      ) : (data.attention || []).length === 0 ? (
        <p style={s.empty}>Nadie por debajo de su ritmo ahora mismo.</p>
      ) : (
        data.attention.map((fila) => {
          const estado = statusStyle(fila.status);
          return (
            <div key={fila.track_id} style={{ ...s.card, background: estado.bg }}>
              <span style={{ ...s.chip, background: `${estado.color}22`, color: estado.color }}>{estado.label}</span>
              <span style={{ ...s.cardName, color: estado.color }}>{fila.name}</span>
              <span style={s.cardDetail}>{fila.detail}</span>
            </div>
          );
        })
      )}
    </>
  );
}

function Fisico({ data, onSelect }) {
  const grupos = byTeam(data.players);
  return (
    <>
      {grupos.map(({ team, players }) => (
        <div key={team}>
          <div style={s.section}>
            <span style={{ color: teamColor(team) }}>■</span> {teamLabel(team)}
          </div>
          <PlayerTable players={players} onSelect={onSelect} />
        </div>
      ))}
      <BandLegend />
      <p style={{ ...s.empty, marginTop: 14 }}>
        Las columnas <strong>m/min</strong> y <strong>Alta int.</strong> son las que comparan
        esfuerzo y no permanencia: un suplente que entra diez minutos puede estar por
        encima de un titular. Salen «—» hasta que se le ha visto lo bastante como para
        que extrapolar a un minuto no sea inventar.
      </p>
    </>
  );
}

function Colectivo({ data }) {
  const equipos = collectiveTeams(data.collective);
  const [equipo, setEquipo] = useState(equipos[0]);
  const activo = equipos.includes(equipo) ? equipo : equipos[0];
  const bloque = data.collective?.teams?.[activo];

  if (!bloque) return <p style={s.empty}>Todavía no hay datos colectivos.</p>;

  const forma = bloque.shape || {};
  const lineas = bloque.line_gaps_m || {};

  return (
    <>
      {equipos.length > 1 && (
        <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
          {equipos.map((e) => (
            <button
              key={e}
              onClick={() => setEquipo(e)}
              style={{
                ...s.chip, cursor: "pointer", border: "none",
                background: e === activo ? `${teamColor(e)}33` : "#14141f",
                color: e === activo ? teamColor(e) : "#778",
              }}
            >
              {teamLabel(e)}
            </button>
          ))}
        </div>
      )}

      <div style={s.kpis}>
        {COLLECTIVE_TILES.map(({ key, label, unit, help }) => (
          <Kpi
            key={key}
            label={label}
            value={forma[key] ? `${fmt(forma[key].avg)} ${unit}` : "—"}
            note={forma[key] ? `${fmt(forma[key].min)}–${fmt(forma[key].max)} ${unit} · ${help}` : help}
          />
        ))}
      </div>

      <div style={s.grid2}>
        <div style={s.panel}>
          <div style={{ ...s.section, marginTop: 0 }}>Dónde estuvo el equipo</div>
          <Pitch
            pitch={data.pitch}
            occupancy={bloque.occupancy}
            caption="Tiempo acumulado por zona. Más claro, más tiempo. El sentido del ataque no se conoce, así que los tercios van sin nombrar."
          />
        </div>

        <div style={s.panel}>
          <div style={{ ...s.section, marginTop: 0 }}>Cómo cambió el bloque</div>
          <Chart
            unit="m"
            series={[
              { name: "Amplitud", color: "#3d8fe0", points: series(bloque.timeline, "width_m") },
              { name: "Longitud", color: "#c8721f", points: series(bloque.timeline, "length_trimmed_m") },
            ]}
          />
          <p style={{ ...s.empty, marginTop: 10 }}>
            Las dos van en metros, así que comparten eje y se pueden comparar de verdad.
            La longitud es la del bloque sin contar al portero.
          </p>
        </div>
      </div>

      {Object.keys(lineas).length > 0 && (
        <>
          <div style={s.section}>Separación entre líneas</div>
          <div style={s.kpis}>
            {Object.entries(lineas).map(([nombre, valores], i) => (
              <Kpi
                key={nombre}
                label={i === 0 ? "1.ª a 2.ª línea" : "2.ª a 3.ª línea"}
                value={valores ? `${fmt(valores.avg)} m` : "—"}
                note={valores ? `${fmt(valores.min)}–${fmt(valores.max)} m` : ""}
              />
            ))}
          </div>
          <p style={s.empty}>
            Se numeran de la más retrasada a la más adelantada. Llamarlas «defensiva» y
            «ofensiva» exigiría saber hacia dónde ataca el equipo, y con una sola cámara
            y sin detectar porterías eso no consta.
          </p>
        </>
      )}
    </>
  );
}

function Jugador({ data, seleccionado, onSelect }) {
  const jugadores = data.players || [];
  const fila = jugadores.find((p) => p.track_id === seleccionado) || jugadores[0];
  if (!fila) return <p style={s.empty}>Todavía no hay jugadores seguidos.</p>;
  const estado = statusStyle(fila.status);

  return (
    <>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
        {jugadores.map((p) => (
          <button
            key={p.track_id}
            onClick={() => onSelect(p.track_id)}
            style={{
              ...s.chip, cursor: "pointer", border: "none",
              background: p.track_id === fila.track_id ? `${teamColor(p.team)}33` : "#14141f",
              color: p.track_id === fila.track_id ? teamColor(p.team) : "#778",
            }}
          >
            {p.name}
          </button>
        ))}
      </div>

      <div style={{ ...s.card, background: estado.bg, marginBottom: 16 }}>
        <span style={{ ...s.chip, background: `${estado.color}22`, color: estado.color }}>{estado.label}</span>
        <span style={{ ...s.cardName, color: estado.color }}>{fila.name}</span>
        <span style={s.cardDetail}>{fila.detail || "Sin nada que señalar."}</span>
      </div>

      <div style={s.kpis}>
        <Kpi label="Minutos" value={fmt(fila.minutes)} note={teamLabel(fila.team)} />
        <Kpi label="Distancia" value={fmt(fila.dist_m, { unit: "m" })} note={`${fmt(fila.dist_m_per_min)} m/min`} />
        <Kpi label="Alta intensidad" value={fmt(fila.high_intensity_m, { unit: "m" })} note={`${fmt(fila.hi_m_per_min)} m/min`} />
        <Kpi label="Velocidad punta" value={fmt(fila.top_speed_kmh, { unit: "km/h", decimals: 1 })} note={`${fmt(fila.sprints)} sprints`} />
        <Kpi label="Acel. / Fren." value={`${fmt(fila.accelerations)} / ${fmt(fila.decelerations)}`} note="por encima de ±3 m/s²" />
      </div>

      <div style={s.section}>Reparto por intensidad</div>
      <div style={{ ...s.bar, height: 14 }}>
        {bandShares(fila.bands_m).map((p) => (
          <div key={p.name} style={{ width: `${p.pct}%`, background: bandColor(p.name) }} title={`${bandLabel(p.name)}: ${Math.round(p.meters)} m`} />
        ))}
      </div>
      <BandLegend />
    </>
  );
}

// ── El panel ───────────────────────────────────────────────────────────

export default function Dashboard({ autoRefreshMs = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [seccion, setSeccion] = useState("partido");
  const [jugador, setJugador] = useState(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    try {
      setData(await apiFetch("/api/dashboard"));
      setError(null);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => {
    if (!autoRefreshMs) return undefined;
    const id = setInterval(cargar, autoRefreshMs);
    return () => clearInterval(id);
  }, [autoRefreshMs, cargar]);

  const secciones = useMemo(() => {
    const base = [["partido", "Partido"], ["fisico", "Físico"]];
    // La pestaña colectiva no existe si no se pudo medir. Una pestaña vacía
    // invita a pensar que algo falló, cuando lo que pasa es que falta calibrar.
    if (hasCollective(data)) base.push(["colectivo", "Colectivo"]);
    base.push(["jugador", "Jugador"]);
    return base;
  }, [data]);

  const abrirJugador = useCallback((trackId) => {
    setJugador(trackId);
    setSeccion("jugador");
  }, []);

  if (error) {
    return (
      <div style={s.root}>
        <div style={{ ...s.headline, background: TONE_BG.bad, color: TONE_FG.bad }}>
          No se pudo leer el panel: {error}
        </div>
        <button style={{ ...s.reload, marginLeft: 0 }} onClick={cargar}>Reintentar</button>
      </div>
    );
  }
  if (!data) return <div style={s.root}><div style={{ color: "#667" }}>Cargando…</div></div>;

  const titular = headline(data);
  const calidad = data.quality || {};
  const confianza = confidenceStyle(calidad.confidence);
  const accionable = isActionable(calidad);
  const activa = secciones.some(([clave]) => clave === seccion) ? seccion : "partido";

  return (
    <div style={s.root}>
      <div style={{ ...s.headline, background: TONE_BG[titular.tone], color: TONE_FG[titular.tone] }}>
        {titular.text}
      </div>

      <div style={s.strip}>
        <span style={{ ...s.chip, background: `${confianza.color}22`, color: confianza.color }}>
          {confianza.label}
        </span>
        <span style={{ color: "#667" }}>
          {fmtDuration(data.match?.minutes)} analizados · {calidad.players_tracked ?? 0} jugadores
          {fmtFragmentation(calidad.fragmentation) && ` · ${fmtFragmentation(calidad.fragmentation)}`}
        </span>
        <button style={s.reload} onClick={cargar} disabled={loading}>
          {loading ? "Actualizando…" : "Actualizar"}
        </button>
      </div>

      {(calidad.warnings || []).map((aviso) => {
        const critico = aviso.level === "critico";
        return (
          <div
            key={aviso.code}
            style={{ ...s.warning, background: critico ? TONE_BG.bad : TONE_BG.warn, color: critico ? TONE_FG.bad : TONE_FG.warn }}
          >
            <span>{critico ? "⛔" : "⚠️"}</span>
            <span>{aviso.message}</span>
          </div>
        );
      })}

      <div style={s.tabs} role="tablist" aria-label="Sección">
        {secciones.map(([clave, etiqueta]) => (
          <button
            key={clave}
            role="tab"
            aria-selected={activa === clave}
            onClick={() => setSeccion(clave)}
            style={{ ...s.tab, ...(activa === clave ? s.tabActive : null) }}
          >
            {etiqueta}
          </button>
        ))}
      </div>

      {activa === "partido" && <Partido data={data} accionable={accionable} />}
      {activa === "fisico" && <Fisico data={data} onSelect={abrirJugador} />}
      {activa === "colectivo" && <Colectivo data={data} />}
      {activa === "jugador" && <Jugador data={data} seleccionado={jugador} onSelect={setJugador} />}

      <div style={s.foot}>
        {data.thresholds?.note}
        {data.thresholds && (
          <>
            {" "}Umbrales en uso: cambio por debajo de {data.thresholds.dropoff_substitute_pct} %,
            vigilar por debajo de {data.thresholds.dropoff_watch_pct} %, y sólo a partir de{" "}
            {data.thresholds.min_minutes_for_dropoff} minutos jugados.
          </>
        )}
      </div>
    </div>
  );
}
