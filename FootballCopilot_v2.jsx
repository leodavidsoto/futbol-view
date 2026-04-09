/**
 * Football Copilot v2 — Frontend
 * React + Canvas 2D
 * - WebSocket (frames → backend) o Video file (NDJSON streaming)
 * - Círculos de equipo (verde / rojo)
 * - Heatmap de posiciones
 * - Velocidad km/h por jugador
 * - Edición de nombres en vivo
 * - Exportación JSON
 * - Posesión del balón
 */

import { useState, useEffect, useRef, useCallback } from "react";

// ─── CONFIG ───────────────────────────────────────────────────
const WS_URL        = "ws://localhost:8000/ws/stream";
const API_URL       = "http://localhost:8000";
const FRAME_RATE_MS = 80;   // ~12 fps enviados (CPU friendly)
const TEAM_COLORS   = { team_1: "#00ff88", team_2: "#ff3355", unknown: "#aaaaaa" };
const BALL_COLOR    = "#ffdd00";

// ─── HELPERS ──────────────────────────────────────────────────
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ─── MAIN COMPONENT ───────────────────────────────────────────
export default function FootballCopilotV2() {
  // ── State ──────────────────────────────────────────────────
  const [mode, setMode]               = useState("video");   // "video" | "webcam" | "ws"
  const [wsStatus, setWsStatus]       = useState("disconnected");
  const [frameData, setFrameData]     = useState(null);
  const [playerNames, setPlayerNames] = useState({});
  const [editingId, setEditingId]     = useState(null);
  const [editValue, setEditValue]     = useState("");
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showTrails, setShowTrails]   = useState(true);
  const [showSpeed, setShowSpeed]     = useState(true);
  const [videoFile, setVideoFile]     = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [fps, setFps]                 = useState(0);
  const [exportStatus, setExportStatus] = useState(null);
  const [possession, setPossession]   = useState({ team_1: 0, team_2: 0, none: 0 });

  // ── Refs ───────────────────────────────────────────────────
  const canvasRef       = useRef(null);
  const videoRef        = useRef(null);
  const wsRef           = useRef(null);
  const frameTimerRef   = useRef(null);
  const latestDataRef   = useRef(null);
  const animFrameRef    = useRef(null);
  const heatmapRef      = useRef({});  // track_id → {x,y}[]

  // ─────────────────────────────────────────────────────────
  // CANVAS RENDER
  // ─────────────────────────────────────────────────────────
  const render = useCallback((data, canvas) => {
    if (!canvas || !data) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // ── Heatmap layer (fondo) ──────────────────────────────
    if (showHeatmap && data.players) {
      data.players.forEach(p => {
        const trail = p.trail || [];
        trail.forEach((pt, i) => {
          const alpha = (i / trail.length) * 0.25;
          const color = TEAM_COLORS[p.team] || TEAM_COLORS.unknown;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, 14, 0, Math.PI * 2);
          ctx.fillStyle = hexToRgba(color, alpha);
          ctx.fill();
        });
      });
    }

    // ── Ball trail ─────────────────────────────────────────
    if (showTrails && data.ball?.trail) {
      data.ball.trail.forEach((pt, i) => {
        const alpha = (i / data.ball.trail.length) * 0.5;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(BALL_COLOR, alpha);
        ctx.fill();
      });
    }

    // ── Jugadores ─────────────────────────────────────────
    if (data.players) {
      data.players.forEach(p => {
        const [cx, cy]   = p.center;
        const color      = TEAM_COLORS[p.team] || TEAM_COLORS.unknown;
        const isSelected = editingId === p.track_id;

        // Sombra
        ctx.shadowColor   = color;
        ctx.shadowBlur    = isSelected ? 20 : 10;

        // Círculo exterior (equipo)
        ctx.beginPath();
        ctx.arc(cx, cy, 22, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth   = isSelected ? 3.5 : 2.5;
        ctx.stroke();

        // Relleno semitransparente
        ctx.fillStyle = hexToRgba(color, 0.15);
        ctx.fill();

        ctx.shadowBlur = 0;

        // Punto central
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        // Nombre
        const name = playerNames[p.track_id] || p.name || `#${p.track_id}`;
        ctx.font         = "bold 12px 'Segoe UI', Arial, sans-serif";
        ctx.textAlign    = "center";
        ctx.textBaseline = "bottom";
        // Fondo nombre
        const tw = ctx.measureText(name).width;
        ctx.fillStyle = "rgba(0,0,0,0.6)";
        ctx.fillRect(cx - tw / 2 - 4, cy - 38, tw + 8, 16);
        ctx.fillStyle = color;
        ctx.fillText(name, cx, cy - 24);

        // Velocidad
        if (showSpeed && p.speed_kmh > 0.5) {
          const spd = `${p.speed_kmh} km/h`;
          ctx.font         = "10px monospace";
          ctx.fillStyle    = "rgba(255,255,255,0.75)";
          ctx.textBaseline = "top";
          ctx.fillText(spd, cx, cy + 26);
        }
      });
    }

    // ── Balón ─────────────────────────────────────────────
    if (data.ball) {
      const [bx, by] = data.ball.center;

      ctx.shadowColor = BALL_COLOR;
      ctx.shadowBlur  = 16;
      ctx.beginPath();
      ctx.arc(bx, by, 12, 0, Math.PI * 2);
      ctx.fillStyle   = BALL_COLOR;
      ctx.globalAlpha = 0.9;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.shadowBlur  = 0;

      // Mini ícono pelota (B)
      ctx.font      = "bold 10px Arial";
      ctx.fillStyle = "#000";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("⚽", bx, by);
    }
  }, [showHeatmap, showTrails, showSpeed, editingId, playerNames]);

  // Loop de render
  useEffect(() => {
    const loop = () => {
      if (latestDataRef.current && canvasRef.current) {
        render(latestDataRef.current, canvasRef.current);
      }
      animFrameRef.current = requestAnimationFrame(loop);
    };
    animFrameRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [render]);

  // Sincronizar datos
  useEffect(() => {
    latestDataRef.current = frameData;
    if (frameData?.fps) setFps(frameData.fps);
    if (frameData?.ball?.possession_pct) setPossession(frameData.ball.possession_pct);
  }, [frameData]);

  // ─────────────────────────────────────────────────────────
  // WEBSOCKET (modo cámara en vivo)
  // ─────────────────────────────────────────────────────────
  const connectWS = useCallback(() => {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(WS_URL);
    ws.binaryType = "arraybuffer";
    ws.onopen    = () => setWsStatus("connected");
    ws.onclose   = () => setWsStatus("disconnected");
    ws.onerror   = () => setWsStatus("error");
    ws.onmessage = (e) => {
      try { setFrameData(JSON.parse(e.data)); } catch {}
    };
    wsRef.current = ws;
  }, []);

  const disconnectWS = useCallback(() => {
    clearInterval(frameTimerRef.current);
    if (wsRef.current) wsRef.current.close();
    setWsStatus("disconnected");
  }, []);

  // Capturar frames del video y enviar al WS
  const startSendingFrames = useCallback(() => {
    const offscreen = document.createElement("canvas");
    const video     = videoRef.current;
    frameTimerRef.current = setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      if (!video || video.paused || video.ended) return;
      offscreen.width  = video.videoWidth  || 854;
      offscreen.height = video.videoHeight || 480;
      const ctx2 = offscreen.getContext("2d");
      ctx2.drawImage(video, 0, 0);
      offscreen.toBlob((blob) => {
        if (!blob) return;
        blob.arrayBuffer().then(buf => wsRef.current?.send(buf));
      }, "image/jpeg", 0.75);
    }, FRAME_RATE_MS);
  }, []);

  // ─────────────────────────────────────────────────────────
  // VIDEO FILE (NDJSON streaming)
  // ─────────────────────────────────────────────────────────
  const processVideoFile = useCallback(async (file) => {
    if (!file) return;
    setIsProcessing(true);
    setFrameData(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(`${API_URL}/api/process-video`, {
        method: "POST",
        body: formData,
      });
      const reader = res.body.getReader();
      const dec    = new TextDecoder();
      let buf      = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            setFrameData(data);
            await new Promise(r => setTimeout(r, 30));
          } catch {}
        }
      }
    } catch (err) {
      console.error("Video processing error:", err);
    } finally {
      setIsProcessing(false);
    }
  }, []);

  // ─────────────────────────────────────────────────────────
  // NOMBRE DE JUGADOR
  // ─────────────────────────────────────────────────────────
  const savePlayerName = useCallback(async (trackId, name) => {
    setPlayerNames(prev => ({ ...prev, [trackId]: name }));
    setEditingId(null);
    try {
      await fetch(`${API_URL}/api/player-name`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ track_id: trackId, name }),
      });
    } catch {}
  }, []);

  const handleCanvasClick = useCallback((e) => {
    if (!frameData?.players) return;
    const canvas = canvasRef.current;
    const rect   = canvas.getBoundingClientRect();
    const mx     = (e.clientX - rect.left) * (canvas.width  / rect.width);
    const my     = (e.clientY - rect.top)  * (canvas.height / rect.height);

    let closest = null;
    let minDist  = 35;
    frameData.players.forEach(p => {
      const [cx, cy] = p.center;
      const d = Math.sqrt((cx - mx) ** 2 + (cy - my) ** 2);
      if (d < minDist) { minDist = d; closest = p; }
    });

    if (closest) {
      setEditingId(closest.track_id);
      setEditValue(playerNames[closest.track_id] || closest.name || `#${closest.track_id}`);
    }
  }, [frameData, playerNames]);

  // ─────────────────────────────────────────────────────────
  // EXPORTAR
  // ─────────────────────────────────────────────────────────
  const exportData = useCallback(async () => {
    try {
      const res  = await fetch(`${API_URL}/api/export`);
      const data = await res.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `partido_${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setExportStatus("✅ Exportado");
      setTimeout(() => setExportStatus(null), 2500);
    } catch {
      setExportStatus("❌ Error");
    }
  }, []);

  // ─────────────────────────────────────────────────────────
  // RENDER JSX
  // ─────────────────────────────────────────────────────────
  const stats = frameData?.stats || {};
  const ball  = frameData?.ball;

  return (
    <div style={styles.root}>
      {/* ── HEADER ── */}
      <div style={styles.header}>
        <span style={styles.logo}>⚽ Football Copilot</span>
        <span style={styles.version}>v2.0</span>
        <span style={{
          ...styles.badge,
          background: wsStatus === "connected" ? "#00ff8833" : "#ff335533",
          color:       wsStatus === "connected" ? "#00ff88"   : "#ff3355",
        }}>
          {wsStatus === "connected" ? "🟢 Live" : "⚫ Off"}
        </span>
        <span style={styles.fpsBadge}>{fps} FPS</span>
      </div>

      <div style={styles.body}>
        {/* ── CANVAS AREA ── */}
        <div style={styles.canvasWrap}>
          {/* Video oculto para captura */}
          <video
            ref={videoRef}
            style={{ display: "none" }}
            controls
            onPlay={() => mode === "ws" && startSendingFrames()}
          />

          {/* Canvas principal */}
          <canvas
            ref={canvasRef}
            width={854}
            height={480}
            style={styles.canvas}
            onClick={handleCanvasClick}
          />

          {/* Overlay de estado */}
          {isProcessing && (
            <div style={styles.processingOverlay}>
              <span style={styles.processingText}>⚙️ Procesando video…</span>
              <div style={styles.spinner} />
            </div>
          )}

          {!frameData && !isProcessing && (
            <div style={styles.emptyOverlay}>
              <span style={{ fontSize: 48 }}>⚽</span>
              <p style={{ color: "#555", marginTop: 8 }}>
                Sube un video o conecta stream para comenzar
              </p>
            </div>
          )}

          {/* Editor de nombre (inline) */}
          {editingId !== null && (
            <div style={styles.nameEditor}>
              <span style={{ color: "#aaa", marginRight: 6 }}>Jugador #{editingId}</span>
              <input
                autoFocus
                value={editValue}
                onChange={e => setEditValue(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter") savePlayerName(editingId, editValue);
                  if (e.key === "Escape") setEditingId(null);
                }}
                style={styles.nameInput}
                placeholder="Nombre…"
              />
              <button style={styles.btnSm} onClick={() => savePlayerName(editingId, editValue)}>✓</button>
              <button style={{...styles.btnSm, background:"#333"}} onClick={() => setEditingId(null)}>✕</button>
            </div>
          )}
        </div>

        {/* ── PANEL DERECHO ── */}
        <div style={styles.panel}>

          {/* ── MODO ── */}
          <Section title="📡 Fuente">
            <div style={styles.modeRow}>
              {["video", "webcam"].map(m => (
                <button
                  key={m}
                  style={{ ...styles.modeBtn, ...(mode === m ? styles.modeBtnActive : {}) }}
                  onClick={() => setMode(m)}
                >
                  {m === "video" ? "📁 Video" : "📷 Cámara"}
                </button>
              ))}
            </div>

            {mode === "video" && (
              <>
                <input
                  type="file"
                  accept="video/*"
                  style={{ marginTop: 6, color: "#ccc", fontSize: 11 }}
                  onChange={e => {
                    const f = e.target.files?.[0];
                    if (f) { setVideoFile(f); processVideoFile(f); }
                  }}
                />
              </>
            )}

            {mode === "webcam" && (
              <div style={{ marginTop: 8 }}>
                {wsStatus !== "connected" ? (
                  <button style={styles.btnPrimary} onClick={() => {
                    connectWS();
                    navigator.mediaDevices.getUserMedia({ video: true }).then(stream => {
                      if (videoRef.current) {
                        videoRef.current.srcObject = stream;
                        videoRef.current.play();
                      }
                    });
                  }}>
                    🔴 Iniciar Cámara
                  </button>
                ) : (
                  <button style={{...styles.btnPrimary, background:"#ff3355"}} onClick={disconnectWS}>
                    ⏹ Detener
                  </button>
                )}
              </div>
            )}
          </Section>

          {/* ── OVERLAYS ── */}
          <Section title="👁 Visualización">
            {[
              ["🌡 Heatmap",  showHeatmap,  setShowHeatmap],
              ["〰 Trails",   showTrails,   setShowTrails],
              ["💨 Velocidad",showSpeed,    setShowSpeed],
            ].map(([label, val, setter]) => (
              <ToggleRow key={label} label={label} value={val} onChange={() => setter(v => !v)} />
            ))}
          </Section>

          {/* ── STATS ── */}
          <Section title="📊 Partido">
            <StatRow label="👥 Jugadores" value={stats.total_players || 0} />
            <StatRow label="🟢 Equipo 1"  value={stats.team_1_count || 0} color={TEAM_COLORS.team_1} />
            <StatRow label="🔴 Equipo 2"  value={stats.team_2_count || 0} color={TEAM_COLORS.team_2} />
            <StatRow label="🧠 Clasificador" value={stats.classifier_ready ? "✅ Listo" : "⏳ Aprendiendo…"} />

            {/* Posesión */}
            {ball && (
              <div style={{ marginTop: 8 }}>
                <div style={{ color: "#888", fontSize: 11, marginBottom: 4 }}>Posesión</div>
                <PossessionBar
                  t1={possession.team_1 || 0}
                  t2={possession.team_2 || 0}
                />
              </div>
            )}
          </Section>

          {/* ── JUGADORES ── */}
          <Section title="🏃 Jugadores" scroll>
            {(frameData?.players || []).map(p => (
              <PlayerCard
                key={p.track_id}
                player={p}
                name={playerNames[p.track_id] || p.name}
                isEditing={editingId === p.track_id}
                onEdit={() => {
                  setEditingId(p.track_id);
                  setEditValue(playerNames[p.track_id] || p.name || `#${p.track_id}`);
                }}
              />
            ))}
            {!frameData?.players?.length && (
              <p style={{ color: "#555", fontSize: 11 }}>Sin jugadores detectados</p>
            )}
          </Section>

          {/* ── ACCIONES ── */}
          <Section title="💾 Acciones">
            <button style={styles.btnSecondary} onClick={exportData}>
              📥 Exportar JSON
            </button>
            {exportStatus && <span style={{ color: "#00ff88", fontSize: 11, marginLeft: 8 }}>{exportStatus}</span>}
            <button style={{ ...styles.btnSecondary, marginTop: 6, background: "#1a1a2a" }}
              onClick={async () => { await fetch(`${API_URL}/api/reset`, { method: "POST" }); setFrameData(null); }}>
              🔄 Reset
            </button>
          </Section>

        </div>
      </div>
    </div>
  );
}

// ─── SUB-COMPONENTS ────────────────────────────────────────
function Section({ title, children, scroll }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={styles.sectionTitle}>{title}</div>
      <div style={scroll ? { maxHeight: 200, overflowY: "auto" } : {}}>
        {children}
      </div>
    </div>
  );
}

function StatRow({ label, value, color }) {
  return (
    <div style={styles.statRow}>
      <span style={{ color: "#888", fontSize: 12 }}>{label}</span>
      <span style={{ color: color || "#eee", fontWeight: 600, fontSize: 13 }}>{value}</span>
    </div>
  );
}

function ToggleRow({ label, value, onChange }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
      <span style={{ color: "#bbb", fontSize: 12 }}>{label}</span>
      <div onClick={onChange} style={{
        width: 36, height: 18, borderRadius: 9, cursor: "pointer",
        background: value ? "#00ff88" : "#333", position: "relative", transition: "background .2s"
      }}>
        <div style={{
          position: "absolute", top: 2, left: value ? 18 : 2,
          width: 14, height: 14, borderRadius: "50%",
          background: "#fff", transition: "left .2s"
        }} />
      </div>
    </div>
  );
}

function PlayerCard({ player, name, isEditing, onEdit }) {
  const color = TEAM_COLORS[player.team] || TEAM_COLORS.unknown;
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "4px 6px", marginBottom: 3, borderRadius: 6,
      background: isEditing ? "#1a2a1a" : "#141420",
      border: `1px solid ${isEditing ? color : "#222"}`,
      cursor: "pointer",
    }} onClick={onEdit}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
        <span style={{ color: "#ddd", fontSize: 12 }}>{name}</span>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ color: "#aaa", fontSize: 10 }}>
          {player.speed_kmh > 0 ? `${player.speed_kmh} km/h` : ""}
        </div>
        <div style={{ color: "#666", fontSize: 10 }}>
          {player.total_dist_m > 0 ? `${player.total_dist_m} m` : ""}
        </div>
      </div>
    </div>
  );
}

function PossessionBar({ t1, t2 }) {
  const total = (t1 + t2) || 100;
  const p1 = Math.round(t1 / total * 100);
  const p2 = 100 - p1;
  return (
    <div>
      <div style={{ display: "flex", height: 16, borderRadius: 8, overflow: "hidden" }}>
        <div style={{ width: `${p1}%`, background: TEAM_COLORS.team_1 }} />
        <div style={{ width: `${p2}%`, background: TEAM_COLORS.team_2 }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
        <span style={{ color: TEAM_COLORS.team_1, fontSize: 11 }}>🟢 {p1}%</span>
        <span style={{ color: TEAM_COLORS.team_2, fontSize: 11 }}>{p2}% 🔴</span>
      </div>
    </div>
  );
}

// ─── STYLES ────────────────────────────────────────────────
const styles = {
  root: {
    background: "#0a0a12",
    minHeight:  "100vh",
    fontFamily: "'Segoe UI', Arial, sans-serif",
    color:      "#eee",
    display:    "flex",
    flexDirection: "column",
  },
  header: {
    display:    "flex",
    alignItems: "center",
    gap:        12,
    padding:    "10px 20px",
    background: "#0f0f1c",
    borderBottom: "1px solid #1e1e30",
  },
  logo:    { fontWeight: 700, fontSize: 18, color: "#00ff88" },
  version: { color: "#555", fontSize: 12 },
  badge:   { padding: "2px 10px", borderRadius: 12, fontSize: 12 },
  fpsBadge:{ color: "#ffdd00", fontSize: 12, marginLeft: "auto", fontFamily: "monospace" },
  body: {
    display: "flex",
    flex:    1,
    gap:     0,
    padding: 0,
  },
  canvasWrap: {
    flex:     1,
    position: "relative",
    background: "#060610",
    display:   "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  canvas: {
    display:  "block",
    maxWidth: "100%",
    cursor:   "crosshair",
    borderRadius: 4,
  },
  processingOverlay: {
    position:      "absolute",
    inset:         0,
    background:    "rgba(0,0,0,0.6)",
    display:       "flex",
    flexDirection: "column",
    alignItems:    "center",
    justifyContent:"center",
    gap:           12,
  },
  processingText: { color: "#fff", fontSize: 16 },
  spinner: {
    width: 32, height: 32, border: "3px solid #333",
    borderTop: "3px solid #00ff88", borderRadius: "50%",
    animation: "spin 0.8s linear infinite",
  },
  emptyOverlay: {
    position:      "absolute",
    inset:         0,
    display:       "flex",
    flexDirection: "column",
    alignItems:    "center",
    justifyContent:"center",
  },
  nameEditor: {
    position:   "absolute",
    bottom:     16,
    left:       "50%",
    transform:  "translateX(-50%)",
    background: "#0f0f20",
    border:     "1px solid #00ff88",
    borderRadius: 8,
    padding:    "8px 12px",
    display:    "flex",
    alignItems: "center",
    gap:        6,
    zIndex:     10,
  },
  nameInput: {
    background: "#1a1a2a",
    border:     "1px solid #333",
    borderRadius: 4,
    color:      "#eee",
    padding:    "4px 8px",
    fontSize:   13,
    outline:    "none",
  },
  panel: {
    width:       280,
    background:  "#0d0d1a",
    borderLeft:  "1px solid #1e1e30",
    padding:     14,
    overflowY:   "auto",
  },
  sectionTitle: {
    color:        "#555",
    fontSize:     11,
    fontWeight:   700,
    textTransform:"uppercase",
    letterSpacing:1,
    marginBottom: 6,
    borderBottom: "1px solid #1e1e30",
    paddingBottom:4,
  },
  modeRow:     { display: "flex", gap: 6 },
  modeBtn:     {
    flex: 1, padding: "5px 0", background: "#141420",
    border: "1px solid #222", borderRadius: 6, color: "#888",
    cursor: "pointer", fontSize: 12,
  },
  modeBtnActive: { border: "1px solid #00ff88", color: "#00ff88", background: "#0a1a0a" },
  statRow:     {
    display: "flex", justifyContent: "space-between",
    alignItems: "center", marginBottom: 5,
  },
  btnPrimary:  {
    width: "100%", padding: "7px 0", background: "#00ff88",
    color: "#000", fontWeight: 700, border: "none",
    borderRadius: 6, cursor: "pointer", fontSize: 13,
  },
  btnSecondary:{
    width: "100%", padding: "6px 0", background: "#1a1a2a",
    color: "#aaa", border: "1px solid #333",
    borderRadius: 6, cursor: "pointer", fontSize: 12,
  },
  btnSm:       {
    padding: "3px 8px", background: "#00ff88", color: "#000",
    border: "none", borderRadius: 4, cursor: "pointer", fontWeight: 700,
  },
};

// CSS animation (inject once)
if (typeof document !== "undefined" && !document.getElementById("fc-spin")) {
  const s = document.createElement("style");
  s.id = "fc-spin";
  s.textContent = "@keyframes spin { to { transform: rotate(360deg); } }";
  document.head.appendChild(s);
}
