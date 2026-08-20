/**
 * Componentes de presentación.
 *
 * Ninguno tiene estado propio ni habla con el backend: reciben props y pintan.
 * Estaban al final de `App.jsx`, donde no se podían probar sin montar la
 * aplicación entera.
 */

import { TEAM_COLORS, fmtDistance, speedColor, teamColor } from "../lib/format.js";
import { styles } from "../styles.js";

// ─── FLOW BADGE ────────────────────────────────────────────────
const FLOW_LABELS = {
  idle:      { text: "Esperando",         color: "#444",    bg: "#1a1a1a" },
  loading:   { text: "Cargando…",         color: "#aaa",    bg: "#1a1a2a" },
  detecting: { text: "Detectando…",       color: "#ffdd00", bg: "#2a2a00" },
  preview:   { text: "Vista previa",      color: "#ffaa00", bg: "#2a1a00" },
  analyzing: { text: "Analizando…",       color: "#00ccff", bg: "#001a2a" },
  done:      { text: "Análisis completo", color: "#00ff88", bg: "#001a0a" },
};
export function FlowBadge({ step }) {
  const { text, color, bg } = FLOW_LABELS[step] || FLOW_LABELS.idle;
  return (
    <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 12, background: bg, color }}>
      {text}
    </span>
  );
}

// ─── TEAM PICKER POPUP ─────────────────────────────────────────
export function TeamPicker({ player, name, onNameChange, currentTeam, onTeamSelect, onSave, onClose }) {
  const [cx, cy] = player.center;
  return (
    <div style={{
      position: "absolute",
      left: Math.min(cx + 28, 630), top: Math.max(cy - 95, 8),
      background: "#0f0f20", border: "1px solid #2a2a40",
      borderRadius: 10, padding: "12px 14px",
      zIndex: 20, minWidth: 220,
      boxShadow: "0 8px 30px rgba(0,0,0,0.85)",
    }}>
      <div style={{ color: "#555", fontSize: 10, marginBottom: 6, letterSpacing: 1 }}>
        JUGADOR #{player.track_id}
      </div>

      <input
        autoFocus value={name}
        onChange={e => onNameChange(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") onSave(); if (e.key === "Escape") onClose(); }}
        style={{
          background: "#1a1a2a", border: "1px solid #333", borderRadius: 5,
          color: "#eee", padding: "5px 9px", fontSize: 13, outline: "none",
          width: "100%", boxSizing: "border-box", marginBottom: 10,
        }}
        placeholder="Nombre del jugador…"
      />

      <div style={{ color: "#444", fontSize: 10, marginBottom: 6, letterSpacing: 1 }}>
        ASIGNAR CÍRCULO / EQUIPO
      </div>
      <div style={{ display: "flex", gap: 5, marginBottom: 10 }}>
        {[
          { key: "team_1",  label: "🟢 Eq. 1",   color: "#00ff88" },
          { key: "team_2",  label: "🔴 Eq. 2",   color: "#ff3355" },
          { key: "unknown", label: "⚫ Ninguno",  color: "#888888" },
        ].map(({ key, label, color }) => (
          <button
            key={key}
            onClick={() => onTeamSelect(key)}
            style={{
              flex: 1, padding: "6px 0", fontSize: 11, fontWeight: 700,
              cursor: "pointer", borderRadius: 6, color,
              background: currentTeam === key ? `${color}22` : "#1a1a2a",
              border: `2px solid ${currentTeam === key ? color : "#2a2a2a"}`,
            }}
          >{label}</button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 6 }}>
        <button
          onClick={onSave}
          style={{
            flex: 1, padding: "6px 0", background: "#00ff88", color: "#000",
            border: "none", borderRadius: 6, cursor: "pointer", fontWeight: 700, fontSize: 12,
          }}
        >✓ Guardar</button>
        <button
          onClick={onClose}
          style={{
            flex: 1, padding: "6px 0", background: "#1a1a2a", color: "#888",
            border: "1px solid #2a2a2a", borderRadius: 6, cursor: "pointer", fontSize: 12,
          }}
        >✕</button>
      </div>
    </div>
  );
}

// ─── SUB-COMPONENTS ────────────────────────────────────────────
export function Section({ title, children, scroll }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={styles.sectionTitle}>{title}</div>
      <div style={scroll ? { maxHeight: 210, overflowY: "auto" } : {}}>{children}</div>
    </div>
  );
}

export function StatRow({ label, value, color }) {
  return (
    <div style={styles.statRow}>
      <span style={{ color: "#666", fontSize: 12 }}>{label}</span>
      <span style={{ color: color || "#ddd", fontWeight: 600, fontSize: 13 }}>{value}</span>
    </div>
  );
}

export function ToggleRow({ label, value, onChange }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
      <span style={{ color: "#aaa", fontSize: 12 }}>{label}</span>
      <div onClick={onChange} style={{
        width: 34, height: 17, borderRadius: 9, cursor: "pointer",
        background: value ? "#00ff88" : "#2a2a2a", position: "relative", transition: "background .2s",
      }}>
        <div style={{
          position: "absolute", top: 1.5, left: value ? 17 : 1.5,
          width: 14, height: 14, borderRadius: "50%",
          background: "#fff", transition: "left .2s",
        }} />
      </div>
    </div>
  );
}

export function PlayerCard({ player, name, team, isSelected, onEdit }) {
  const color = teamColor(team);
  return (
    <div
      style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "4px 7px", marginBottom: 3, borderRadius: 6,
        background: isSelected ? "#0f1f0f" : "#111118",
        border: `1px solid ${isSelected ? color : "#1e1e28"}`,
        cursor: "pointer",
      }}
      onClick={onEdit}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <div style={{
          width: 10, height: 10, borderRadius: "50%",
          background: color, boxShadow: `0 0 5px ${color}66`, flexShrink: 0,
        }} />
        <span style={{ color: "#ccc", fontSize: 12 }}>{name || `#${player.track_id}`}</span>
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ color: speedColor(player.speed_kmh), fontSize: 10 }}>
          {player.speed_kmh > 0 ? `${player.speed_kmh} km/h` : ""}
        </div>
        <div style={{ color: "#555", fontSize: 10 }}>
          {player.total_dist_m > 0 ? fmtDistance(player.total_dist_m) : ""}
          {player.sprints > 0 ? ` · 🔥${player.sprints}` : ""}
        </div>
      </div>
    </div>
  );
}

export function PossessionBar({ t1, t2 }) {
  const total = (t1 + t2) || 100;
  const p1    = Math.round(t1 / total * 100);
  return (
    <div>
      <div style={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden" }}>
        <div style={{ width: `${p1}%`, background: TEAM_COLORS.team_1, transition: "width .5s" }} />
        <div style={{ flex: 1, background: TEAM_COLORS.team_2 }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
        <span style={{ color: TEAM_COLORS.team_1, fontSize: 11 }}>🟢 {p1}%</span>
        <span style={{ color: TEAM_COLORS.team_2, fontSize: 11 }}>{100 - p1}% 🔴</span>
      </div>
    </div>
  );
}

export function ModelCard({ active, available, title, badge, badgeColor, desc, source, onClick }) {
  return (
    <div
      onClick={available && onClick ? onClick : undefined}
      style={{
        padding: "9px 10px", marginBottom: 7, borderRadius: 8,
        background: active ? "#0a1a0f" : "#0e0e1a",
        border: `1px solid ${active ? "#00ff8866" : available ? "#1e1e28" : "#2a1a10"}`,
        cursor: available && onClick ? "pointer" : "default",
        opacity: available ? 1 : 0.5,
        transition: "border .15s",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <span style={{ color: active ? "#00ff88" : "#ccc", fontWeight: 700, fontSize: 12 }}>{title}</span>
        <span style={{
          fontSize: 9, fontWeight: 700, color: badgeColor,
          background: `${badgeColor}22`, padding: "1px 6px",
          borderRadius: 5, border: `1px solid ${badgeColor}44`,
        }}>{badge}</span>
      </div>
      <div style={{ color: "#666", fontSize: 10, lineHeight: 1.5, marginBottom: 3 }}>{desc}</div>
      <div style={{ color: "#333", fontSize: 9 }}>📦 {source}</div>
      {active && <div style={{ color: "#00ff88", fontSize: 9, marginTop: 3 }}>✓ Activo</div>}
    </div>
  );
}

