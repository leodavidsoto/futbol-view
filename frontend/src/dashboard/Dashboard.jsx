/**
 * Panel del director técnico.
 *
 * La otra vista de esta aplicación es una consola de análisis con cuarenta
 * controles: sirve para afinar el sistema, no para dirigir un partido. Ésta es
 * lo contrario — no tiene ni un ajuste, y responde tres preguntas en el orden
 * en que se hacen: si los datos valen, quién está fundido y quién no corre.
 *
 * Todo lo que decide vive en `model.js` y en el backend. Aquí sólo hay
 * maquetación.
 */

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "../lib/api.js";
import {
  COLUMNS,
  bandColor,
  bandShares,
  byTeam,
  cell,
  confidenceStyle,
  fmt,
  fmtDuration,
  fmtFragmentation,
  headline,
  isActionable,
  possessionShare,
  statusStyle,
} from "./model.js";

const TONE_BG = {
  good: "#00ff8815",
  warn: "#ffcc0015",
  bad: "#ff446618",
  neutral: "#ffffff08",
};
const TONE_FG = {
  good: "#00ff88",
  warn: "#ffcc00",
  bad: "#ff6688",
  neutral: "#9999bb",
};

const s = {
  root: { padding: "18px 22px", overflowY: "auto", flex: 1, background: "#080810" },
  headline: {
    padding: "16px 20px", borderRadius: 12, fontSize: 19, fontWeight: 600,
    lineHeight: 1.35, marginBottom: 14,
  },
  strip: {
    display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
    marginBottom: 16, fontSize: 13,
  },
  chip: { padding: "3px 10px", borderRadius: 20, fontSize: 12, fontWeight: 600 },
  warning: {
    display: "flex", gap: 9, padding: "9px 13px", borderRadius: 8,
    fontSize: 13, lineHeight: 1.45, marginBottom: 7,
  },
  kpis: { display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 },
  kpi: {
    flex: "1 1 130px", background: "#0d0d1a", border: "1px solid #1a1a28",
    borderRadius: 10, padding: "12px 15px",
  },
  kpiLabel: { fontSize: 11, color: "#667", textTransform: "uppercase", letterSpacing: 0.6 },
  kpiValue: { fontSize: 25, fontWeight: 700, color: "#eee", marginTop: 3 },
  kpiNote: { fontSize: 11, color: "#556", marginTop: 2 },
  section: { fontSize: 13, color: "#889", textTransform: "uppercase", letterSpacing: 1, margin: "22px 0 10px" },
  card: {
    display: "flex", alignItems: "center", gap: 13, padding: "11px 15px",
    borderRadius: 9, marginBottom: 7, border: "1px solid #1a1a28",
  },
  cardName: { fontWeight: 700, fontSize: 15, minWidth: 110 },
  cardDetail: { fontSize: 13, color: "#aab", lineHeight: 1.4 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: {
    textAlign: "right", padding: "7px 9px", color: "#667", fontWeight: 600,
    borderBottom: "1px solid #1a1a28", fontSize: 11, textTransform: "uppercase",
    letterSpacing: 0.5, whiteSpace: "nowrap",
  },
  td: { textAlign: "right", padding: "7px 9px", borderBottom: "1px solid #12121c", whiteSpace: "nowrap" },
  bar: { display: "flex", height: 6, borderRadius: 3, overflow: "hidden", minWidth: 90 },
  foot: { marginTop: 26, fontSize: 12, color: "#556", lineHeight: 1.6, maxWidth: 760 },
  reload: {
    marginLeft: "auto", padding: "6px 14px", borderRadius: 7, cursor: "pointer",
    background: "#1a1a28", color: "#aab", border: "1px solid #262636", fontSize: 12,
  },
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
    <div style={s.bar} title={partes.map((p) => `${p.name}: ${Math.round(p.meters)} m`).join("  ·  ")}>
      {partes.map((p) => (
        <div key={p.name} style={{ width: `${p.pct}%`, background: bandColor(p.name) }} />
      ))}
    </div>
  );
}

function PlayerTable({ players }) {
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
            <tr key={fila.track_id}>
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

export default function Dashboard({ autoRefreshMs = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

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
  const posesion = possessionShare(data.possession);
  const grupos = byTeam(data.players);

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
            style={{
              ...s.warning,
              background: critico ? TONE_BG.bad : TONE_BG.warn,
              color: critico ? TONE_FG.bad : TONE_FG.warn,
            }}
          >
            <span>{critico ? "⛔" : "⚠️"}</span>
            <span>{aviso.message}</span>
          </div>
        );
      })}

      <div style={{ ...s.kpis, marginTop: 16 }}>
        <Kpi
          label="Posesión"
          value={`${fmt(posesion.team_1)} / ${fmt(posesion.team_2)}`}
          note="equipo 1 / equipo 2"
        />
        <Kpi label="Distancia total" value={fmt(data.teams?.team_1?.total_dist_m, { unit: "m" })} note="equipo 1" />
        <Kpi label="Alta intensidad" value={fmt(data.teams?.team_1?.high_intensity_m, { unit: "m" })} note="equipo 1" />
        <Kpi label="Sprints" value={fmt(data.teams?.team_1?.sprints)} note="equipo 1" />
        <Kpi label="Campo" value={data.match?.pitch || "sin calibrar"} note={data.match?.distance_unit} />
      </div>

      {accionable ? (
        <>
          <div style={s.section}>A quién mirar</div>
          {(data.attention || []).length === 0 ? (
            <div style={{ color: "#667", fontSize: 13 }}>
              Nadie por debajo de su ritmo ahora mismo.
            </div>
          ) : (
            data.attention.map((fila) => {
              const estado = statusStyle(fila.status);
              return (
                <div key={fila.track_id} style={{ ...s.card, background: estado.bg }}>
                  <span style={{ ...s.chip, background: `${estado.color}22`, color: estado.color }}>
                    {estado.label}
                  </span>
                  <span style={{ ...s.cardName, color: estado.color }}>{fila.name}</span>
                  <span style={s.cardDetail}>{fila.detail}</span>
                </div>
              );
            })
          )}
        </>
      ) : (
        <div style={{ ...s.warning, background: TONE_BG.bad, color: TONE_FG.bad }}>
          <span>⛔</span>
          <span>
            El semáforo de sustituciones está oculto porque los datos de arriba no lo
            sostienen. Las cifras siguen sirviendo para comparar jugadores entre sí.
          </span>
        </div>
      )}

      {grupos.map(({ team, players }) => (
        <div key={team}>
          <div style={s.section}>{team.replace("_", " ")}</div>
          <PlayerTable players={players} />
        </div>
      ))}

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
