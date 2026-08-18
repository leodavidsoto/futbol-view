/**
 * Football Copilot v3 — Frontend
 *
 * Flujo:
 *  1. Cargar video → detecta primer frame (preview)
 *  2. Asignar círculos de equipo a cada jugador
 *  3. "Iniciar análisis" → procesa el video completo respetando asignaciones
 *  4. Al terminar: controles custom de reproducción con overlay sincronizado
 *
 * Visualización extendida:
 *  Heatmap, Trails, Velocidad, Distancia, Bounding Boxes, Nombres,
 *  Mini-mapa, Barra posesión canvas, Slider radio círculos, Longitud trail
 */

import { useState, useEffect, useRef, useCallback, useMemo } from "react";

import { api, wsStreamUrl } from "./lib/api.js";
import { findFrameAtTime, parseNdjsonChunk, summarizeFrame } from "./lib/frames.js";
import {
  BALL_COLOR,
  TEAM_COLORS,
  fmtDistance,
  fmtTime,
  hexToRgba,
  speedColor,
  teamColor,
} from "./lib/format.js";
import { getSessionId, resetSessionId } from "./lib/session.js";

// ─── CONFIG ────────────────────────────────────────────────────
const FRAME_RATE_MS = 80;
//: Tope de frames guardados en memoria (~6 min a 3 fps efectivos).
const MAX_BUFFERED_FRAMES = 12000;

// Modos del flujo principal
// "idle" → "loading" → "detecting" → "preview" → "analyzing" → "done"

// ─── HELPERS ───────────────────────────────────────────────────
function logClientError(scope, error) {
  console.debug(`[football-copilot] ${scope}`, error);
}

// ─── MAIN COMPONENT ────────────────────────────────────────────
export default function App() {
  // ── Flujo ──────────────────────────────────────────────────
  const [mode, setMode]               = useState("video"); // "video"|"webcam"
  const [flowStep, setFlowStep]       = useState("idle");  // ver descripción arriba
  const [wsStatus, setWsStatus]       = useState("disconnected");

  // ── Datos de tracking ──────────────────────────────────────
  const [frameData, setFrameData]         = useState(null);
  const [playerNames, setPlayerNames]     = useState({});
  const [playerTeamOverrides, setPlayerTeamOverrides] = useState({});
  const [teamPickerPlayer, setTeamPickerPlayer] = useState(null);
  const [teamPickerName, setTeamPickerName]     = useState("");

  // ── Visualización ──────────────────────────────────────────
  const [showHeatmap,       setShowHeatmap]       = useState(false);
  const [showTrails,        setShowTrails]         = useState(true);
  const [showSpeed,         setShowSpeed]          = useState(true);
  const [showDistance,      setShowDistance]       = useState(false);
  const [showBBoxes,        setShowBBoxes]         = useState(false);
  const [showNames,         setShowNames]          = useState(true);
  const [showMiniMap,       setShowMiniMap]        = useState(true);
  const [showPossessionBar, setShowPossessionBar]  = useState(true);
  const [circleRadius,      setCircleRadius]       = useState(22);
  const [trailLength,       setTrailLength]        = useState(20);

  // ── Video / procesado ──────────────────────────────────────
  const [videoFile,         setVideoFile]          = useState(null);
  const [isProcessing,      setIsProcessing]       = useState(false);
  const [processedFrames,   setProcessedFrames]    = useState(0);
  const [fps,               setFps]                = useState(0);
  const [exportStatus,      setExportStatus]       = useState(null);
  const [possession,        setPossession]         = useState({ team_1: 0, team_2: 0, none: 0 });
  const [isVideoPlaying,    setIsVideoPlaying]     = useState(false);
  const [videoDuration,     setVideoDuration]      = useState(0);
  const [videoCurrentTime,  setVideoCurrentTime]   = useState(0);
  const [analysisPaused,    setAnalysisPaused]     = useState(false);
  const [previewError,      setPreviewError]       = useState(false);
  const [detConf,           setDetConf]            = useState(0.10);
  const [detImgsz,          setDetImgsz]           = useState(1280);
  const [detMode,           setDetMode]            = useState("sahi");
  const [detAugment,        setDetAugment]         = useState(false);
  const [detSahiSlice,      setDetSahiSlice]       = useState(320);
  const [detSahiAvailable,  setDetSahiAvailable]   = useState(true);
  const [detModelPath,      setDetModelPath]       = useState("yolo11x.pt");
  const [detTracker,        setDetTracker]         = useState("norfair");
  const [detNorfairDist,    setDetNorfairDist]     = useState(50);
  const [detNorfairAvail,   setDetNorfairAvail]    = useState(true);
  const [calibrating,       setCalibrating]       = useState(false);  // modo calibración 4 pts
  const [calibPoints,       setCalibPoints]       = useState([]);     // [{x,y}] canvas pts
  const [isCalibrated,      setIsCalibrated]      = useState(false);

  // ── Panel tabs ─────────────────────────────────────────────
  const [panelTab,          setPanelTab]          = useState("config"); // "config"|"models"|"stats"
  const [detTeamClf,        setDetTeamClf]        = useState("grass_kmeans");
  const [detOsnetAvail,     setDetOsnetAvail]     = useState(false);

  // ── Errores visibles y sesión ──────────────────────────────
  const [analysisError,     setAnalysisError]     = useState(null);
  const [backendError,      setBackendError]      = useState(null);
  const [sessionId,         setSessionId]         = useState(() => getSessionId());

  // ── Refs ───────────────────────────────────────────────────
  const canvasRef              = useRef(null);
  const videoRef               = useRef(null);
  const wsRef                  = useRef(null);
  const frameTimerRef          = useRef(null);
  const latestDataRef          = useRef(null);
  const animFrameRef           = useRef(null);
  const allFramesRef           = useRef([]);
  const abortRef               = useRef(null);
  const teamOverridesRef       = useRef({});
  const analysisPausedRef      = useRef(false);
  const resumeRef              = useRef(null);
  const draggingRef            = useRef(null);   // { track_id, player, offsetX, offsetY, startX, startY, moved }
  const posOverridesRef        = useRef({});     // { [track_id]: { x, y } } – posiciones movidas manualmente
  const circleRadiusRef        = useRef(22);
  const calibratingRef         = useRef(false);  // ref para evitar stale closure en handlers
  const videoUrlRef            = useRef(null);   // object URL del vídeo cargado

  // Liberar el object URL: sin esto, cada vídeo cargado quedaba retenido en memoria.
  const revokeVideoUrl = useCallback(() => {
    if (videoUrlRef.current) {
      URL.revokeObjectURL(videoUrlRef.current);
      videoUrlRef.current = null;
    }
  }, []);

  useEffect(() => { teamOverridesRef.current  = playerTeamOverrides; }, [playerTeamOverrides]);
  useEffect(() => { analysisPausedRef.current = analysisPaused;      }, [analysisPaused]);
  useEffect(() => { calibratingRef.current    = calibrating;          }, [calibrating]);
  useEffect(() => { circleRadiusRef.current   = circleRadius;         }, [circleRadius]);

  // Cargar config del backend al iniciar
  useEffect(() => {
    api.getConfig()
      .then(c => {
        setDetConf(c.confidence ?? 0.10);
        setDetImgsz(c.imgsz ?? 1280);
        setDetMode(c.detection_mode ?? "sahi");
        setDetAugment(c.augment ?? false);
        setDetSahiSlice(c.sahi_slice ?? 320);
        setDetSahiAvailable(c.sahi_available ?? false);
        setDetModelPath(c.model ?? "yolo11x.pt");
        setDetTracker(c.tracker_type ?? "norfair");
        setDetNorfairDist(c.norfair_dist ?? 50);
        setDetNorfairAvail(c.norfair_available ?? false);
        setDetTeamClf(c.team_classifier ?? "grass_kmeans");
        setDetOsnetAvail(c.osnet_available ?? false);
      })
      .catch(error => {
        logClientError("config load failed", error);
        setBackendError(error.message || "No se pudo conectar con el backend");
      });
    api.getCalibration()
      .then(c => setIsCalibrated(Boolean(c.calibrated)))
      .catch(error => { logClientError("calibration load failed", error); });
  }, []);

  const postConfig = useCallback((patch) => {
    api.setConfig(patch).catch(error => {
      logClientError("config update failed", error);
      setBackendError(error.message || "No se pudo aplicar la configuración");
    });
  }, []);

  // ─────────────────────────────────────────────────────────
  // CANVAS RENDER
  // ─────────────────────────────────────────────────────────
  const render = useCallback((data, canvas) => {
    if (!canvas || !data) return;
    const ctx      = canvas.getContext("2d");
    const W        = canvas.width;
    const H        = canvas.height;
    const overrides = teamOverridesRef.current;
    ctx.clearRect(0, 0, W, H);

    // ── Barra de posesión (top) ────────────────────────────
    if (showPossessionBar && data.ball?.possession_pct) {
      const { team_1 = 0, team_2 = 0 } = data.ball.possession_pct;
      const total = (team_1 + team_2) || 1;
      const p1    = team_1 / total;
      ctx.fillStyle = TEAM_COLORS.team_1;
      ctx.fillRect(0, 0, W * p1, 5);
      ctx.fillStyle = TEAM_COLORS.team_2;
      ctx.fillRect(W * p1, 0, W * (1 - p1), 5);
    }

    // ── Heatmap layer ──────────────────────────────────────
    if (showHeatmap && data.players) {
      data.players.forEach(p => {
        const team  = overrides[p.track_id] || p.team;
        const color = teamColor(team);
        (p.trail || []).forEach((pt, i, arr) => {
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, 14, 0, Math.PI * 2);
          ctx.fillStyle = hexToRgba(color, (i / arr.length) * 0.28);
          ctx.fill();
        });
      });
    }

    // ── Bounding boxes ─────────────────────────────────────
    if (showBBoxes && data.players) {
      data.players.forEach(p => {
        const [x1, y1, x2, y2] = p.bbox;
        const team  = overrides[p.track_id] || p.team;
        const color = teamColor(team);
        ctx.strokeStyle = hexToRgba(color, 0.45);
        ctx.lineWidth   = 1;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      });
    }
    if (showBBoxes && data.ball?.bbox) {
      const [x1, y1, x2, y2] = data.ball.bbox;
      ctx.strokeStyle = hexToRgba(BALL_COLOR, 0.6);
      ctx.lineWidth   = 1;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    }

    // ── Trail de pelota ────────────────────────────────────
    if (showTrails && data.ball?.trail?.length > 1) {
      const trail = data.ball.trail.slice(-trailLength);
      ctx.beginPath();
      ctx.moveTo(trail[0].x, trail[0].y);
      trail.forEach(pt => ctx.lineTo(pt.x, pt.y));
      ctx.strokeStyle = hexToRgba(BALL_COLOR, 0.35);
      ctx.lineWidth   = 2.5;
      ctx.lineJoin    = "round";
      ctx.stroke();
      trail.forEach((pt, i) => {
        const t = i / trail.length;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 2 + t * 5, 0, Math.PI * 2);
        ctx.fillStyle = hexToRgba(BALL_COLOR, 0.15 + t * 0.65);
        ctx.fill();
      });
    }

    // ── Jugadores ──────────────────────────────────────────
    if (data.players) {
      data.players.forEach(p => {
        // Posición: override manual tiene prioridad sobre la del backend
        const posOv      = posOverridesRef.current[p.track_id];
        const [cx, cy]   = posOv ? [posOv.x, posOv.y] : p.center;
        const team       = overrides[p.track_id] || p.team;
        const color      = teamColor(team);
        const isSelected = teamPickerPlayer?.track_id === p.track_id;
        const isDragging = draggingRef.current?.track_id === p.track_id && draggingRef.current?.moved;
        const r          = circleRadius;

        // Anillo exterior de arrastre (punteado, radio mayor)
        if (isDragging) {
          ctx.setLineDash([5, 3]);
          ctx.beginPath();
          ctx.arc(cx, cy, r + 10, 0, Math.PI * 2);
          ctx.strokeStyle = hexToRgba(color, 0.7);
          ctx.lineWidth   = 1.5;
          ctx.stroke();
          ctx.setLineDash([]);
        }

        // Halo glow
        ctx.shadowColor = color;
        ctx.shadowBlur  = isDragging ? 35 : isSelected ? 28 : 12;

        // Círculo exterior
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth   = isDragging ? 3.5 : isSelected ? 4 : 2.5;
        ctx.stroke();
        ctx.fillStyle   = hexToRgba(color, isDragging ? 0.28 : 0.15);
        ctx.fill();

        ctx.shadowBlur = 0;

        // Punto central
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        // Nombre (encima del círculo)
        if (showNames) {
          const name = playerNames[p.track_id] || p.name || `#${p.track_id}`;
          ctx.font         = `bold 12px 'Segoe UI', Arial, sans-serif`;
          ctx.textAlign    = "center";
          ctx.textBaseline = "bottom";
          const tw = ctx.measureText(name).width;
          ctx.fillStyle = "rgba(0,0,0,0.65)";
          ctx.fillRect(cx - tw / 2 - 4, cy - r - 18, tw + 8, 15);
          ctx.fillStyle = color;
          ctx.fillText(name, cx, cy - r - 4);
        }

        // Velocidad (debajo)
        if (showSpeed && p.speed_kmh > 0.5) {
          ctx.font         = "10px monospace";
          ctx.fillStyle    = "rgba(255,255,255,0.75)";
          ctx.textAlign    = "center";
          ctx.textBaseline = "top";
          ctx.fillText(`${p.speed_kmh} km/h`, cx, cy + r + 4);
        }

        // Distancia (debajo de velocidad)
        if (showDistance && p.total_dist_m > 0) {
          const yOff = showSpeed && p.speed_kmh > 0.5 ? r + 16 : r + 4;
          ctx.font         = "9px monospace";
          ctx.fillStyle    = "rgba(200,200,200,0.55)";
          ctx.textAlign    = "center";
          ctx.textBaseline = "top";
          ctx.fillText(`${p.total_dist_m} m`, cx, cy + yOff);
        }

        // Trail del jugador (si trails activo)
        if (showTrails && p.trail?.length > 1) {
          const trail = p.trail.slice(-trailLength);
          trail.forEach((pt, i) => {
            const alpha = (i / trail.length) * 0.35;
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 3, 0, Math.PI * 2);
            ctx.fillStyle = hexToRgba(color, alpha);
            ctx.fill();
          });
        }
      });
    }

    // ── Pelota ─────────────────────────────────────────────
    if (data.ball) {
      const [bx, by] = data.ball.center;
      ctx.shadowColor = BALL_COLOR;
      ctx.shadowBlur  = 22;
      ctx.beginPath();
      ctx.arc(bx, by, 13, 0, Math.PI * 2);
      ctx.fillStyle   = BALL_COLOR;
      ctx.globalAlpha = 0.95;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.shadowBlur  = 0;
      ctx.font         = "bold 11px Arial";
      ctx.fillStyle    = "#000";
      ctx.textAlign    = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("⚽", bx, by);
    }

    // ── Mini-mapa ──────────────────────────────────────────
    if (showMiniMap && data.players?.length > 0) {
      const mw = 160, mh = 96;
      const mx = W - mw - 10, my = H - mh - 10;

      // Fondo y campo
      ctx.fillStyle = "rgba(0,0,0,0.55)";
      ctx.beginPath();
      ctx.roundRect(mx - 4, my - 4, mw + 8, mh + 8, 6);
      ctx.fill();
      ctx.fillStyle = "#1a4d1a";
      ctx.fillRect(mx, my, mw, mh);

      // Líneas del campo
      ctx.strokeStyle = "rgba(255,255,255,0.3)";
      ctx.lineWidth   = 0.5;
      ctx.strokeRect(mx, my, mw, mh);
      // Línea central
      ctx.beginPath();
      ctx.moveTo(mx + mw / 2, my);
      ctx.lineTo(mx + mw / 2, my + mh);
      ctx.stroke();
      // Círculo central
      ctx.beginPath();
      ctx.arc(mx + mw / 2, my + mh / 2, mh * 0.18, 0, Math.PI * 2);
      ctx.stroke();
      // Áreas
      const ag = mh * 0.3;
      ctx.strokeRect(mx, my + (mh - ag) / 2, mw * 0.12, ag);
      ctx.strokeRect(mx + mw - mw * 0.12, my + (mh - ag) / 2, mw * 0.12, ag);

      // Jugadores — si hay world_pos, usar coordenadas reales del campo
      const hasWorld = data.players.some(p => p.world_pos);
      data.players.forEach(p => {
        const team  = overrides[p.track_id] || p.team;
        const color = teamColor(team);
        let px, py;
        if (hasWorld && p.world_pos) {
          // world_pos = [x_metros, y_metros], campo 105x68m
          px = mx + (p.world_pos[0] / 105) * mw;
          py = my + (p.world_pos[1] / 68)  * mh;
        } else {
          const posOv    = posOverridesRef.current[p.track_id];
          const [cx, cy] = posOv ? [posOv.x, posOv.y] : p.center;
          px = mx + (cx / W) * mw;
          py = my + (cy / H) * mh;
        }
        ctx.beginPath();
        ctx.arc(px, py, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur  = 4;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      // Pelota
      if (data.ball) {
        const [bx, by] = data.ball.center;
        const bwp = data.ball.world_pos;
        const px = bwp ? mx + (bwp[0] / 105) * mw : mx + (bx / W) * mw;
        const py2tmp = bwp ? my + (bwp[1] / 68) * mh : my + (by / H) * mh;
        const py = py2tmp;
        ctx.beginPath();
        ctx.arc(px, py, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = BALL_COLOR;
        ctx.shadowColor = BALL_COLOR;
        ctx.shadowBlur  = 5;
        ctx.fill();
        ctx.shadowBlur = 0;
      }
    }
    // ── Puntos de calibración (overlay) ────────────────────
    if (calibrating || calibPoints.length > 0) {
      const LABELS = ["TL", "TR", "BR", "BL"];
      const COLORS_CAL = ["#ff4444","#ffaa00","#44ff44","#4488ff"];
      calibPoints.forEach((pt, i) => {
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 9, 0, Math.PI * 2);
        ctx.fillStyle = COLORS_CAL[i];
        ctx.globalAlpha = 0.85;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.font = "bold 10px monospace";
        ctx.fillStyle = "#000";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(LABELS[i], pt.x, pt.y);
      });
      if (calibrating) {
        const next = LABELS[calibPoints.length];
        ctx.font = "bold 13px sans-serif";
        ctx.fillStyle = COLORS_CAL[calibPoints.length] || "#fff";
        ctx.textAlign = "left";
        ctx.textBaseline = "top";
        ctx.fillText(`Click → ${next} (${calibPoints.length}/4)`, 12, 12);
      }
    }
  }, [
    showHeatmap, showTrails, showSpeed, showDistance,
    showBBoxes, showNames, showMiniMap, showPossessionBar,
    circleRadius, trailLength,
    teamPickerPlayer, playerNames,
    calibrating, calibPoints,
  ]);

  // Loop de render
  useEffect(() => {
    const loop = () => {
      if (latestDataRef.current && canvasRef.current)
        render(latestDataRef.current, canvasRef.current);
      animFrameRef.current = requestAnimationFrame(loop);
    };
    animFrameRef.current = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [render]);

  // Sync datos
  useEffect(() => {
    latestDataRef.current = frameData;
    if (frameData?.fps) setFps(frameData.fps);
    if (frameData?.ball?.possession_pct) setPossession(frameData.ball.possession_pct);
  }, [frameData]);

  // Listeners de video
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onTime  = () => {
      setVideoCurrentTime(video.currentTime);

      // Al cambiar de frame, liberar correcciones manuales de posición
      // → el círculo vuelve a seguir al jugador según el tracker del backend
      posOverridesRef.current = {};

      // Búsqueda binaria: los frames llegan ordenados por `video_time`.
      const best = findFrameAtTime(allFramesRef.current, video.currentTime);
      if (best) latestDataRef.current = best;
    };
    const onMeta  = () => setVideoDuration(video.duration || 0);
    const onPlay  = () => setIsVideoPlaying(true);
    const onPause = () => setIsVideoPlaying(false);
    const onEnded = () => setIsVideoPlaying(false);
    video.addEventListener("timeupdate",     onTime);
    video.addEventListener("loadedmetadata", onMeta);
    video.addEventListener("play",           onPlay);
    video.addEventListener("pause",          onPause);
    video.addEventListener("ended",          onEnded);
    return () => {
      video.removeEventListener("timeupdate",     onTime);
      video.removeEventListener("loadedmetadata", onMeta);
      video.removeEventListener("play",           onPlay);
      video.removeEventListener("pause",          onPause);
      video.removeEventListener("ended",          onEnded);
    };
  }, []);

  // Limpieza al desmontar: WebSocket, temporizador de frames y object URL.
  useEffect(() => () => {
    clearInterval(frameTimerRef.current);
    wsRef.current?.close();
    abortRef.current?.abort();
    revokeVideoUrl();
  }, [revokeVideoUrl]);

  // ─────────────────────────────────────────────────────────
  // CARGA DE VIDEO → PREVIEW DE PRIMER FRAME
  // ─────────────────────────────────────────────────────────
  // CARGA DE VIDEO → listo para navegar y detectar manualmente
  // ─────────────────────────────────────────────────────────
  const handleVideoFileChange = useCallback(async (file) => {
    if (!file) return;
    setVideoFile(file);
    setFrameData(null);
    setPlayerTeamOverrides({});
    allFramesRef.current = [];
    setFlowStep("loading");
    setTeamPickerPlayer(null);
    setPreviewError(false);

    const video = videoRef.current;
    revokeVideoUrl();
    const url = URL.createObjectURL(file);
    videoUrlRef.current = url;
    video.src = url;

    // Esperar a que el video esté listo
    if (video.readyState < 3) {
      await new Promise((res) => {
        const t = setTimeout(res, 8000);
        video.addEventListener("canplay", () => { clearTimeout(t); res(); }, { once: true });
      });
    }

    // Video listo: el usuario puede navegar y detectar manualmente
    setFlowStep("preview");
  }, [revokeVideoUrl]);

  // ─────────────────────────────────────────────────────────
  // DETECTAR JUGADORES EN EL FRAME ACTUAL
  // ─────────────────────────────────────────────────────────
  const detectCurrentFrame = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;

    setFlowStep("detecting");
    setPreviewError(false);
    setFrameData(null);
    latestDataRef.current = null;

    // Capturar frame actual del video
    const off = document.createElement("canvas");
    off.width  = 854;
    off.height = 480;
    off.getContext("2d").drawImage(video, 0, 0, 854, 480);

    const blob = await new Promise(res => off.toBlob(res, "image/jpeg", 0.88));
    if (!blob) { setPreviewError(true); setFlowStep("preview"); return; }

    try {
      const data = await api.previewFrame(blob, video.currentTime || 0);
      setFrameData(data);
      latestDataRef.current = data;
      setBackendError(null);
      setFlowStep("preview");
    } catch (err) {
      logClientError("preview frame failed", err);
      setPreviewError(true);
      setBackendError(err.message || "No se pudo analizar el frame");
      setFlowStep("preview");
    }
  }, []);

  // ─────────────────────────────────────────────────────────
  // INICIAR / PAUSAR / REANUDAR / CANCELAR ANÁLISIS
  // ─────────────────────────────────────────────────────────
  const cancelProcessing = useCallback(() => {
    // Si está pausado, desbloquear el loop antes de abortar
    if (resumeRef.current) { resumeRef.current(); resumeRef.current = null; }
    setAnalysisPaused(false);
    if (abortRef.current) abortRef.current.abort();
  }, []);

  const pauseAnalysis = useCallback(() => {
    setAnalysisPaused(true);
    // Asegurarse de que el video esté pausado al pausar el análisis
    videoRef.current?.pause();
  }, []);

  const resumeAnalysis = useCallback(() => {
    setAnalysisPaused(false);
    // Desbloquear el loop de lectura
    if (resumeRef.current) { resumeRef.current(); resumeRef.current = null; }
  }, []);

  const startAnalysis = useCallback(async () => {
    if (!videoFile) return;
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();

    setIsProcessing(true);
    setAnalysisPaused(false);
    setFlowStep("analyzing");
    setProcessedFrames(0);
    setFrameData(null);
    allFramesRef.current   = [];
    posOverridesRef.current = {};   // limpiar correcciones del preview

    setAnalysisError(null);
    setBackendError(null);

    try {
      const res    = await api.processVideo(videoFile, abortRef.current.signal);
      const reader = res.body.getReader();
      const dec    = new TextDecoder();
      let buf      = "";
      let uiCount  = 0;

      while (true) {
        // ── Punto de pausa: esperar hasta que se reanude ───
        if (analysisPausedRef.current) {
          await new Promise(res => { resumeRef.current = res; });
        }

        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const { frames, rest } = parseNdjsonChunk(buf, (error) =>
          logClientError("ndjson frame parse failed", error));
        buf = rest;

        for (const data of frames) {
          // El backend informa de sus fallos dentro del propio stream.
          if (data.error) { setAnalysisError(data.error); continue; }
          allFramesRef.current.push(data);
          if (allFramesRef.current.length > MAX_BUFFERED_FRAMES) allFramesRef.current.shift();
          uiCount++;
          if (uiCount % 3 === 0) { setFrameData(data); setProcessedFrames(uiCount); }
          latestDataRef.current = data;
        }
      }
      const last = allFramesRef.current.at(-1);
      if (last) { setFrameData(last); setProcessedFrames(allFramesRef.current.length); }
    } catch (err) {
      if (err.name !== "AbortError") {
        logClientError("analysis failed", err);
        setAnalysisError(err.message || "El análisis falló");
      }
    } finally {
      setIsProcessing(false);
      setAnalysisPaused(false);
      setFlowStep("done");
    }
  }, [videoFile]);

  // ─────────────────────────────────────────────────────────
  // CONTROLES DE VIDEO
  // ─────────────────────────────────────────────────────────
  const handlePlayPause = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused || v.ended) v.play().catch(error => { logClientError("video play failed", error); });
    else v.pause();
  }, []);

  const handleSeek = useCallback((val) => {
    const v = videoRef.current;
    if (v) v.currentTime = parseFloat(val);
  }, []);

  // ─────────────────────────────────────────────────────────
  // WEBSOCKET (modo cámara)
  // ─────────────────────────────────────────────────────────
  const connectWS = useCallback(() => {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(wsStreamUrl());
    ws.binaryType = "arraybuffer";
    ws.onopen    = () => setWsStatus("connected");
    ws.onclose   = () => setWsStatus("disconnected");
    ws.onerror   = () => setWsStatus("error");
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.error) { setBackendError(data.error); return; }
        setFrameData(data);
      } catch (error) {
        logClientError("ws frame parse failed", error);
      }
    };
    wsRef.current = ws;
  }, []);

  const disconnectWS = useCallback(() => {
    clearInterval(frameTimerRef.current);
    if (wsRef.current) wsRef.current.close();
    setWsStatus("disconnected");
  }, []);

  const startSendingFrames = useCallback(() => {
    const off   = document.createElement("canvas");
    const video = videoRef.current;
    frameTimerRef.current = setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      if (!video || video.paused || video.ended) return;
      off.width  = video.videoWidth  || 854;
      off.height = video.videoHeight || 480;
      off.getContext("2d").drawImage(video, 0, 0);
      off.toBlob(blob => {
        if (!blob) return;
        blob.arrayBuffer().then(buf => wsRef.current?.send(buf));
      }, "image/jpeg", 0.75);
    }, FRAME_RATE_MS);
  }, []);

  // ─────────────────────────────────────────────────────────
  // ASIGNACIÓN DE EQUIPO
  // ─────────────────────────────────────────────────────────
  const assignTeam = useCallback(async (trackId, team) => {
    setPlayerTeamOverrides(prev => ({ ...prev, [trackId]: team }));
    setTeamPickerPlayer(prev => prev ? { ...prev, team } : prev);
    try {
      await api.setPlayerTeam(trackId, team);
    } catch (error) {
      logClientError("team override save failed", error);
      setBackendError(error.message || "No se pudo guardar el equipo");
    }
  }, []);

  const savePlayerInfo = useCallback(async () => {
    if (!teamPickerPlayer) return;
    const { track_id } = teamPickerPlayer;
    const name = teamPickerName.trim();
    if (name) {
      setPlayerNames(prev => ({ ...prev, [track_id]: name }));
      try {
        await api.setPlayerName(track_id, name);
      } catch (error) {
        logClientError("player name save failed", error);
        setBackendError(error.message || "No se pudo guardar el nombre");
      }
    }
    setTeamPickerPlayer(null);
  }, [teamPickerPlayer, teamPickerName]);

  // ── Helper: coordenadas canvas desde evento mouse ─────────
  const getCanvasXY = useCallback((e) => {
    const c    = canvasRef.current;
    const rect = c.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (c.width  / rect.width),
      y: (e.clientY - rect.top)  * (c.height / rect.height),
    };
  }, []);

  // ── Helper: jugador más cercano a un punto ─────────────────
  const findPlayerAt = useCallback((x, y) => {
    const data = latestDataRef.current;
    if (!data?.players) return null;
    const threshold = circleRadiusRef.current + 18;
    let closest = null, minDist = threshold;
    data.players.forEach(p => {
      const posOv    = posOverridesRef.current[p.track_id];
      const [px, py] = posOv ? [posOv.x, posOv.y] : p.center;
      const d = Math.hypot(px - x, py - y);
      if (d < minDist) { minDist = d; closest = p; }
    });
    return closest;
  }, []);

  // ── Mouse down: calibración o drag/click ─────────────────
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    const { x, y } = getCanvasXY(e);

    // Modo calibración: acumular hasta 4 puntos
    if (calibratingRef.current) {
      setCalibPoints(prev => {
        const next = [...prev, { x, y }];
        if (next.length === 4) {
          // Enviar al backend: esquinas TL, TR, BR, BL → (0,0)(105,0)(105,68)(0,68)
          const worldPts = [[0,0],[105,0],[105,68],[0,68]];
          api.calibrateHomography(next.map(p => [p.x, p.y]), worldPts)
            .then(() => { setIsCalibrated(true); setCalibrating(false); setBackendError(null); })
            .catch(error => {
              logClientError("field calibration failed", error);
              setBackendError(error.message || "Calibración inválida: revisa los 4 puntos");
              setCalibrating(false);
              setCalibPoints([]);
            });
        }
        return next.length <= 4 ? next : prev;
      });
      return;
    }

    const player   = findPlayerAt(x, y);
    if (!player) { setTeamPickerPlayer(null); return; }

    const posOv    = posOverridesRef.current[player.track_id];
    const [px, py] = posOv ? [posOv.x, posOv.y] : player.center;

    draggingRef.current = {
      track_id: player.track_id,
      player,
      offsetX: x - px,
      offsetY: y - py,
      startX:  x,
      startY:  y,
      moved:   false,
    };
    canvasRef.current.style.cursor = "grabbing";
  }, [getCanvasXY, findPlayerAt]);

  // ── Mouse move: arrastrar o actualizar cursor ──────────────
  const handleMouseMove = useCallback((e) => {
    const { x, y } = getCanvasXY(e);
    const d = draggingRef.current;

    if (d) {
      // Detectar si realmente se movió (umbral 4 px)
      if (!d.moved && Math.hypot(x - d.startX, y - d.startY) > 4) d.moved = true;
      if (d.moved) {
        // Actualizar posición directamente en el ref (sin setState → sin re-render extra)
        posOverridesRef.current = {
          ...posOverridesRef.current,
          [d.track_id]: { x: x - d.offsetX, y: y - d.offsetY },
        };
      }
      return;
    }

    // Sin drag: cursor "grab" si hay jugador debajo
    const player = findPlayerAt(x, y);
    if (canvasRef.current)
      canvasRef.current.style.cursor = player ? "grab" : "crosshair";
  }, [getCanvasXY, findPlayerAt]);

  // ── Mouse up: finalizar drag o abrir TeamPicker ────────────
  const handleMouseUp = useCallback(() => {
    const d = draggingRef.current;
    draggingRef.current = null;
    if (canvasRef.current) canvasRef.current.style.cursor = "crosshair";
    if (!d) return;

    if (!d.moved) {
      // Sin movimiento → tratar como click → abrir TeamPicker
      const overrides = teamOverridesRef.current;
      setTeamPickerPlayer({ ...d.player, team: overrides[d.player.track_id] || d.player.team });
      setTeamPickerName(playerNames[d.player.track_id] || d.player.name || `#${d.player.track_id}`);
    }
    // Si hubo movimiento, la posición ya quedó en posOverridesRef
  }, [playerNames]);

  // ── Mouse leave: cancelar drag si sale del canvas ─────────
  const handleMouseLeave = useCallback(() => {
    draggingRef.current = null;
    if (canvasRef.current) canvasRef.current.style.cursor = "crosshair";
  }, []);

  // ─────────────────────────────────────────────────────────
  // EXPORTAR
  // ─────────────────────────────────────────────────────────
  const exportData = useCallback(async () => {
    try {
      const data = await api.export();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a    = document.createElement("a");
      const url  = URL.createObjectURL(blob);
      a.href     = url;
      a.download = `partido_${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setExportStatus("✅ Exportado");
      setTimeout(() => setExportStatus(null), 2500);
    } catch (error) {
      logClientError("export failed", error);
      setExportStatus("❌ Error");
    }
  }, []);

  // ─────────────────────────────────────────────────────────
  // JSX
  // ─────────────────────────────────────────────────────────
  const stats   = frameData?.stats || {};
  const ball    = frameData?.ball;
  const summary = useMemo(() => summarizeFrame(frameData), [frameData]);
  const notice  = analysisError || backendError;

  return (
    <div style={styles.root}>
      {/* ── HEADER ── */}
      <div style={styles.header}>
        <span style={styles.logo}>⚽ Football Copilot</span>
        <span style={styles.version}>v3.1</span>
        <FlowBadge step={flowStep} />
        <span style={{
          ...styles.badge,
          background: wsStatus === "connected" ? "#00ff8833" : "#ff335533",
          color:      wsStatus === "connected" ? "#00ff88"   : "#ff3355",
          marginLeft: 4,
        }}>
          {wsStatus === "connected" ? "🟢 Live" : "⚫ Off"}
        </span>
        <span style={styles.fpsBadge}>{fps > 0 ? `${fps} FPS` : ""}</span>
        <span style={styles.sessionBadge} title="Sesión de análisis: cada pestaña tiene la suya">
          🔑 {sessionId.slice(0, 10)}
        </span>
      </div>

      {/* ── Aviso de error del backend / análisis ── */}
      {notice && (
        <div style={styles.notice} role="alert">
          <span>⚠️ {notice}</span>
          <button
            style={styles.noticeClose}
            onClick={() => { setAnalysisError(null); setBackendError(null); }}
            aria-label="Cerrar aviso"
          >✕</button>
        </div>
      )}

      <div style={styles.body}>
        {/* ── CANVAS AREA ── */}
        <div style={styles.canvasWrap}>

          <div style={{ position: "relative", display: "inline-block", maxWidth: "100%", lineHeight: 0 }}>
            {/* Video (detrás del canvas) */}
            <video
              ref={videoRef}
              muted
              playsInline
              style={{
                display:  mode === "video" && videoFile ? "block" : "none",
                position: "absolute", top: 0, left: 0,
                width: "100%", height: "100%", objectFit: "fill",
              }}
              onPlay={() => mode === "ws" && startSendingFrames()}
            />

            {/* Canvas overlay */}
            <canvas
              ref={canvasRef}
              width={854} height={480}
              style={styles.canvas}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseLeave}
            />

            {/* Team Picker popup */}
            {teamPickerPlayer && (
              <TeamPicker
                player={teamPickerPlayer}
                name={teamPickerName}
                onNameChange={setTeamPickerName}
                currentTeam={playerTeamOverrides[teamPickerPlayer.track_id] || teamPickerPlayer.team}
                onTeamSelect={(team) => assignTeam(teamPickerPlayer.track_id, team)}
                onSave={savePlayerInfo}
                onClose={() => setTeamPickerPlayer(null)}
              />
            )}
          </div>

          {/* ── Controles de navegación de video en preview ── */}
          {(flowStep === "preview" || flowStep === "detecting") && videoFile && (
            <div style={styles.videoControls}>
              <button style={styles.playBtn} onClick={handlePlayPause}>
                {isVideoPlaying ? "⏸" : "▶"}
              </button>
              <input
                type="range" min={0} max={videoDuration || 100} step={0.05}
                value={videoCurrentTime}
                onChange={e => handleSeek(e.target.value)}
                style={styles.seekBar}
              />
              <span style={styles.timeDisplay}>
                {fmtTime(videoCurrentTime)} / {fmtTime(videoDuration)}
              </span>
            </div>
          )}

          {/* ── Spinner durante detección ── */}
          {flowStep === "detecting" && (
            <div style={styles.previewBanner}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={styles.miniSpinner} />
                <span style={{ color: "#aaa", fontSize: 13 }}>Detectando jugadores…</span>
              </div>
            </div>
          )}

          {/* ── Banner preview ── */}
          {flowStep === "preview" && (
            <div style={styles.previewBanner}>
              {previewError ? (
                <span style={{ color: "#ff6655", fontSize: 13 }}>
                  ⚠️ No se pudo conectar al backend (:8000)
                </span>
              ) : frameData?.players?.length > 0 ? (
                <span style={{ color: "#ffdd00", fontSize: 13 }}>
                  📍 Click en jugadores para asignar equipo · Arrastra para mover
                </span>
              ) : (
                <span style={{ color: "#aaa", fontSize: 13 }}>
                  Navega al segundo donde quieras detectar jugadores
                </span>
              )}
              <div style={{ display: "flex", gap: 6 }}>
                <button style={styles.detectBtn} onClick={detectCurrentFrame}>
                  🔍 Detectar aquí
                </button>
                {(frameData?.players?.length > 0 || previewError) && (
                  <button style={styles.analyzeBtn} onClick={startAnalysis}>
                    ▶ Iniciar análisis
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── Barra de progreso del análisis (no bloquea el canvas) ── */}
          {isProcessing && !analysisPaused && (
            <div style={styles.progressBar}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={styles.miniSpinner} />
                <span style={{ color: "#aaa", fontSize: 12 }}>
                  ⚙️ Analizando… <strong style={{ color: "#eee" }}>{processedFrames}</strong> frames
                </span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button style={styles.pauseBtn} onClick={pauseAnalysis}>⏸ Pausar</button>
                <button style={styles.cancelBtnSm} onClick={cancelProcessing}>✕</button>
              </div>
            </div>
          )}

          {/* ── Banner de análisis pausado ── */}
          {isProcessing && analysisPaused && (
            <div style={styles.pausedBanner}>
              <span style={{ color: "#ffdd00", fontSize: 13 }}>
                ⏸ Pausado — <strong>{processedFrames}</strong> frames analizados · Reproduce lo analizado y luego reanuda
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                <button style={styles.resumeBtn} onClick={resumeAnalysis}>▶ Reanudar</button>
                <button style={styles.cancelBtnSm} onClick={cancelProcessing}>✕ Cancelar</button>
              </div>
            </div>
          )}

          {/* ── Controles de video (disponibles en pausa o análisis terminado) ── */}
          {(flowStep === "done" || analysisPaused) && videoFile && (
            <div style={styles.videoControls}>
              <button style={styles.playBtn} onClick={handlePlayPause}>
                {isVideoPlaying ? "⏸" : "▶"}
              </button>
              <input
                type="range" min={0}
                max={analysisPaused
                  ? (allFramesRef.current.at(-1)?.video_time ?? videoDuration)
                  : (videoDuration || 100)}
                step={0.1} value={videoCurrentTime}
                onChange={e => handleSeek(e.target.value)}
                style={styles.seekBar}
              />
              <span style={styles.timeDisplay}>
                {fmtTime(videoCurrentTime)}
                {analysisPaused
                  ? ` / ${fmtTime(allFramesRef.current.at(-1)?.video_time ?? 0)} analizado`
                  : ` / ${fmtTime(videoDuration)}`}
              </span>
            </div>
          )}

          {/* ── Banner análisis completo ── */}
          {flowStep === "done" && !isVideoPlaying && allFramesRef.current.length > 0 && (
            <div style={styles.analysisBanner}>
              <span style={{ color: "#00ff88", fontSize: 13 }}>
                ✅ Análisis completo — {allFramesRef.current.length} frames listos
              </span>
              <button style={styles.playOverlayBtn} onClick={handlePlayPause}>
                ▶ Reproducir con overlay
              </button>
            </div>
          )}

          {/* ── Overlay solo durante carga inicial del video ── */}
          {flowStep === "loading" && (
            <div style={styles.processingOverlay}>
              <div style={styles.spinner} />
              <span style={{ color: "#aaa", fontSize: 14 }}>Cargando video…</span>
            </div>
          )}

          {/* ── Banner calibración ── */}
          {calibrating && (
            <div style={{ ...styles.previewBanner, background: "#0a1a2a", borderTopColor: "#2255aa33" }}>
              <span style={{ color: "#66ccff", fontSize: 13 }}>
                🏟️ Calibración — Haz click en las 4 esquinas del campo: TL → TR → BR → BL ({calibPoints.length}/4)
              </span>
              <button style={{ ...styles.cancelBtnSm }} onClick={() => { setCalibrating(false); setCalibPoints([]); }}>
                ✕ Cancelar
              </button>
            </div>
          )}
          {isCalibrated && !calibrating && (
            <div style={{ ...styles.previewBanner, background: "#061206", borderTopColor: "#00ff8822", padding: "6px 14px" }}>
              <span style={{ color: "#00ff88", fontSize: 12 }}>✅ Campo calibrado — velocidades y distancias en metros reales</span>
              <button style={{ ...styles.cancelBtnSm, fontSize: 11 }} onClick={() => { setIsCalibrated(false); setCalibPoints([]); }}>Recalibrar</button>
            </div>
          )}

          {/* ── Overlay vacío ── */}
          {flowStep === "idle" && (
            <div style={styles.emptyOverlay}>
              <span style={{ fontSize: 48 }}>⚽</span>
              <p style={{ color: "#555", marginTop: 8, textAlign: "center" }}>
                Sube un video para comenzar a asignar equipos
              </p>
            </div>
          )}
        </div>

        {/* ── PANEL DERECHO ── */}
        <div style={styles.panel}>

          {/* TAB BAR */}
          <div style={{ display: "flex", gap: 2, marginBottom: 12, background: "#0a0a14", borderRadius: 8, padding: 3 }}>
            {[
              { k: "config", label: "⚙️ Config" },
              { k: "models", label: "🔬 Modelos" },
              { k: "stats",  label: "📊 Stats" },
            ].map(({ k, label }) => (
              <button key={k}
                style={{
                  flex: 1, padding: "5px 0", fontSize: 11, fontWeight: 600,
                  cursor: "pointer", border: "none", borderRadius: 6,
                  background: panelTab === k ? "#1a1a30" : "transparent",
                  color: panelTab === k ? "#fff" : "#555",
                  transition: "all .15s",
                }}
                onClick={() => setPanelTab(k)}
              >{label}</button>
            ))}
          </div>

          {/* ═══ TAB: CONFIG ════════════════════════════════ */}
          {panelTab === "config" && <>

            {/* FUENTE */}
            <Section title="📡 Fuente">
              <div style={styles.modeRow}>
                {["video", "webcam"].map(m => (
                  <button key={m}
                    style={{ ...styles.modeBtn, ...(mode === m ? styles.modeBtnActive : {}) }}
                    onClick={() => setMode(m)}
                  >{m === "video" ? "📁 Video" : "📷 Cámara"}</button>
                ))}
              </div>
              {mode === "video" && (
                <input type="file" accept="video/*"
                  style={{ marginTop: 8, color: "#ccc", fontSize: 11, width: "100%" }}
                  onChange={e => { const f = e.target.files?.[0]; if (f) handleVideoFileChange(f); }}
                />
              )}
              {mode === "video" && flowStep === "preview" && (
                <button style={{ ...styles.btnPrimary, marginTop: 8 }} onClick={startAnalysis}>
                  ▶ Iniciar análisis
                </button>
              )}
              {mode === "webcam" && (
                <div style={{ marginTop: 8 }}>
                  {wsStatus !== "connected" ? (
                    <button style={styles.btnPrimary} onClick={() => {
                      connectWS();
                      navigator.mediaDevices.getUserMedia({ video: true }).then(stream => {
                        if (videoRef.current) { videoRef.current.srcObject = stream; videoRef.current.play(); }
                      }).catch(error => {
                        setWsStatus("error");
                        logClientError("camera access failed", error);
                      });
                    }}>🔴 Iniciar Cámara</button>
                  ) : (
                    <button style={{ ...styles.btnPrimary, background: "#ff3355" }} onClick={disconnectWS}>
                      ⏹ Detener
                    </button>
                  )}
                </div>
              )}
            </Section>

            {/* DETECCIÓN */}
            <Section title="🔍 Detección">
              <div style={styles.subLabel}>🏃 Tracker</div>
              <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                {[
                  { k: "norfair",   label: `Norfair${detNorfairAvail ? "" : " ⚠️"}`, title: "Kalman+Euclidean — Tryolabs style, mejor para aéreo" },
                  { k: "bytetrack", label: "ByteTrack", title: "Supervision ByteTrack" },
                ].map(({ k, label, title }) => (
                  <button key={k} title={title}
                    style={{ ...styles.modeBtn, ...(detTracker === k ? styles.modeBtnActive : {}), flex: 1, padding: "4px 0", fontSize: 11 }}
                    onClick={() => { setDetTracker(k); postConfig({ tracker_type: k }); }}
                  >{label}</button>
                ))}
              </div>
              {detTracker === "norfair" && (
                <div style={styles.sliderRow}>
                  <span style={{ color: "#bbb", fontSize: 12 }}>📏 Dist. máx</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <input type="range" min={20} max={150} step={5} value={detNorfairDist}
                      onChange={e => { const v = Number(e.target.value); setDetNorfairDist(v); postConfig({ norfair_dist: v }); }}
                      style={{ width: 65, accentColor: "#00ccff" }} />
                    <span style={{ color: "#666", fontSize: 11, minWidth: 28 }}>{detNorfairDist}px</span>
                  </div>
                </div>
              )}

              <div style={styles.subLabel}>🔬 Detección</div>
              <div style={{ display: "flex", gap: 4, marginBottom: 6 }}>
                {["normal", "sahi"].map(m => (
                  <button key={m}
                    style={{ ...styles.modeBtn, ...(detMode === m ? styles.modeBtnActive : {}), flex: 1, padding: "4px 0", fontSize: 11 }}
                    onClick={() => { setDetMode(m); postConfig({ detection_mode: m }); }}
                    title={m === "sahi" ? "Sliced — mejor para objetos pequeños (drone)" : "Inferencia estándar"}
                  >{m === "sahi" ? `SAHI${detSahiAvailable ? "" : " ⚠️"}` : "Normal"}</button>
                ))}
              </div>
              <div style={styles.sliderRow}>
                <span style={{ color: "#bbb", fontSize: 12 }}>🎯 Confianza</span>
                <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <input type="range" min={0.03} max={0.5} step={0.01} value={detConf}
                    onChange={e => { const v = Number(e.target.value); setDetConf(v); postConfig({ confidence: v }); }}
                    style={{ width: 65, accentColor: "#ffdd00" }} />
                  <span style={{ color: "#666", fontSize: 11, minWidth: 28 }}>{detConf.toFixed(2)}</span>
                </div>
              </div>
              <div style={styles.sliderRow}>
                <span style={{ color: "#bbb", fontSize: 12 }}>🖼️ Img size</span>
                <div style={{ display: "flex", gap: 4 }}>
                  {[640, 1280].map(s => (
                    <button key={s}
                      style={{ ...styles.modeBtn, ...(detImgsz === s ? styles.modeBtnActive : {}), padding: "3px 10px", fontSize: 11 }}
                      onClick={() => { setDetImgsz(s); postConfig({ imgsz: s }); }}
                    >{s}</button>
                  ))}
                </div>
              </div>
              {detMode === "sahi" && (
                <div style={styles.sliderRow}>
                  <span style={{ color: "#bbb", fontSize: 12 }}>✂️ Tile</span>
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <input type="range" min={160} max={640} step={32} value={detSahiSlice}
                      onChange={e => { const v = Number(e.target.value); setDetSahiSlice(v); postConfig({ sahi_slice: v }); }}
                      style={{ width: 65, accentColor: "#66ccff" }} />
                    <span style={{ color: "#666", fontSize: 11, minWidth: 28 }}>{detSahiSlice}px</span>
                  </div>
                </div>
              )}
              <ToggleRow label="🔁 TTA (augment)" value={detAugment}
                onChange={() => { const v = !detAugment; setDetAugment(v); postConfig({ augment: v }); }} />

              <div style={styles.subLabel}>📦 Modelo YOLO</div>
              <div style={{ display: "flex", gap: 3, marginBottom: 4, flexWrap: "wrap" }}>
                {["yolo11x.pt", "yolo11n.pt", "yolov8x.pt",
                  "repos/Football-Object-Detection-main/weights/best.pt",
                  "repos/soccer-video-detection-ai-agent-main/weights/player_detect.pt",
                ].map(m => {
                  const label = m.includes("/") ? m.split("/").pop().replace(".pt","") : m.replace(".pt","");
                  return (
                    <button key={m}
                      style={{ ...styles.modeBtn, ...(detModelPath === m ? styles.modeBtnActive : {}), flex: "none", padding: "2px 6px", fontSize: 10 }}
                      onClick={() => { setDetModelPath(m); postConfig({ model: m }); }}
                      title={m}
                    >{label}</button>
                  );
                })}
              </div>
              <input type="text" value={detModelPath}
                onChange={e => setDetModelPath(e.target.value)}
                onBlur={e => { if (e.target.value.trim()) postConfig({ model: e.target.value.trim() }); }}
                style={{ width: "100%", background: "#0d0d1a", border: "1px solid #1a1a28",
                  color: "#ccc", borderRadius: 4, padding: "3px 6px", fontSize: 10, boxSizing: "border-box" }}
                placeholder="ruta/al/modelo.pt"
              />
              <p style={{ color: "#333", fontSize: 10, marginTop: 5, lineHeight: 1.5 }}>
                🚁 Drone: Norfair · SAHI · conf 0.08 · 1280<br/>
                📺 Broadcast: ByteTrack · Normal · conf 0.25 · 640
              </p>
            </Section>

            {/* VISUALIZACIÓN */}
            <Section title="👁 Visualización">
              <ToggleRow label="🌡 Heatmap"       value={showHeatmap}       onChange={() => setShowHeatmap(v => !v)} />
              <ToggleRow label="〰 Trails"         value={showTrails}        onChange={() => setShowTrails(v => !v)} />
              <ToggleRow label="💨 Velocidad"      value={showSpeed}         onChange={() => setShowSpeed(v => !v)} />
              <ToggleRow label="📏 Distancia"      value={showDistance}      onChange={() => setShowDistance(v => !v)} />
              <ToggleRow label="🔲 Bboxes"         value={showBBoxes}        onChange={() => setShowBBoxes(v => !v)} />
              <ToggleRow label="🏷️ Nombres"        value={showNames}         onChange={() => setShowNames(v => !v)} />
              <ToggleRow label="🗺️ Mini-mapa"      value={showMiniMap}       onChange={() => setShowMiniMap(v => !v)} />
              <ToggleRow label="📊 Pos. bar"       value={showPossessionBar} onChange={() => setShowPossessionBar(v => !v)} />
              <div style={styles.sliderRow}>
                <span style={{ color: "#bbb", fontSize: 12 }}>⭕ Radio círculos</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="range" min={12} max={36} step={1} value={circleRadius}
                    onChange={e => setCircleRadius(Number(e.target.value))}
                    style={{ width: 70, accentColor: "#00ff88" }} />
                  <span style={{ color: "#666", fontSize: 11, minWidth: 20 }}>{circleRadius}</span>
                </div>
              </div>
              <div style={styles.sliderRow}>
                <span style={{ color: "#bbb", fontSize: 12 }}>〰 Long. trail</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="range" min={5} max={60} step={5} value={trailLength}
                    onChange={e => setTrailLength(Number(e.target.value))}
                    style={{ width: 70, accentColor: "#00ff88" }} />
                  <span style={{ color: "#666", fontSize: 11, minWidth: 20 }}>{trailLength}</span>
                </div>
              </div>
            </Section>

            {/* ACCIONES */}
            <Section title="💾 Acciones">
              {flowStep === "preview" && (
                <button style={{ ...styles.btnPrimary, marginBottom: 6 }} onClick={startAnalysis}>
                  ▶ Analizar video
                </button>
              )}
              <button style={styles.btnSecondary} onClick={exportData}>📥 Exportar JSON</button>
              {exportStatus && <span style={{ color: "#00ff88", fontSize: 11, marginLeft: 8 }}>{exportStatus}</span>}
              <button style={{ ...styles.btnSecondary, marginTop: 6 }}
                onClick={async () => {
                  try { await api.reset(); }
                  catch (error) { logClientError("reset failed", error); }
                  setFrameData(null); setFlowStep("idle"); setPlayerTeamOverrides({});
                  setPlayerNames({}); setVideoFile(null); setIsCalibrated(false);
                  setAnalysisError(null); setBackendError(null);
                  allFramesRef.current = [];
                  posOverridesRef.current = {};
                  revokeVideoUrl();
                  if (videoRef.current) videoRef.current.removeAttribute("src");
                }}
              >🔄 Reset</button>
              <button
                style={{ ...styles.btnSecondary, marginTop: 6 }}
                title="Descarta la sesión actual del backend y empieza una nueva y vacía"
                onClick={() => {
                  setSessionId(resetSessionId());
                  setFrameData(null); setFlowStep("idle"); setPlayerTeamOverrides({});
                  setPlayerNames({}); setVideoFile(null); setIsCalibrated(false);
                  setAnalysisError(null); setBackendError(null);
                  allFramesRef.current = [];
                  posOverridesRef.current = {};
                  revokeVideoUrl();
                  if (videoRef.current) videoRef.current.removeAttribute("src");
                }}
              >🆕 Nueva sesión</button>
              {videoFile && (
                <button
                  style={{ ...styles.btnSecondary, marginTop: 6,
                    ...(calibrating ? { border: "1px solid #2255aa", color: "#66ccff" } : {}),
                    ...(isCalibrated ? { border: "1px solid #00ff8844", color: "#00ff88" } : {}),
                  }}
                  onClick={() => {
                    if (calibrating) { setCalibrating(false); setCalibPoints([]); }
                    else { setCalibrating(true); setCalibPoints([]); }
                  }}
                >
                  {calibrating ? "⏹ Cancelar calibración" : isCalibrated ? "✅ Campo calibrado · Recalibrar" : "🏟️ Calibrar campo (4 pts)"}
                </button>
              )}
            </Section>

          </>}

          {/* ═══ TAB: MODELOS ════════════════════════════════ */}
          {panelTab === "models" && <>
            <Section title="🧠 Clasificador de Equipos">
              <p style={{ color: "#555", fontSize: 10, marginBottom: 8, lineHeight: 1.5 }}>
                El clasificador asigna automáticamente los equipos por color de camiseta o apariencia visual.
              </p>

              {/* Grass-aware KMeans */}
              <ModelCard
                active={detTeamClf === "grass_kmeans"}
                available={true}
                title="Grass-aware KMeans"
                badge="Recomendado"
                badgeColor="#00ff88"
                desc="KMeans filtrando píxeles verdes del campo. Usa solo la zona del torso (camiseta). Más robusto que KMeans básico."
                source="Football-Object-Detection / Roboflow"
                onClick={() => { setDetTeamClf("grass_kmeans"); postConfig({ team_classifier: "grass_kmeans" }); }}
              />

              {/* KMeans básico */}
              <ModelCard
                active={detTeamClf === "kmeans"}
                available={true}
                title="KMeans básico"
                badge="Simple"
                badgeColor="#888"
                desc="KMeans sobre color HSV del torso. Rápido pero sensible al verde del campo."
                source="Baseline"
                onClick={() => { setDetTeamClf("kmeans"); postConfig({ team_classifier: "kmeans" }); }}
              />

              {/* OSNet */}
              <ModelCard
                active={detTeamClf === "osnet"}
                available={detOsnetAvail}
                title="OSNet ReID"
                badge={detOsnetAvail ? "512-dim" : "PyTorch req."}
                badgeColor={detOsnetAvail ? "#00ccff" : "#ff6633"}
                desc="Re-identificación por apariencia visual. Embeddings 512-dim, KMeans sobre features de red neuronal. Más preciso con cambios de iluminación."
                source="Tryolabs Soccer Analytics / torchreid"
                onClick={detOsnetAvail ? () => { setDetTeamClf("osnet"); postConfig({ team_classifier: "osnet" }); } : null}
              />
            </Section>

            <Section title="🔍 Modelos de Detección">
              <ModelCard
                active={detModelPath === "yolo11x.pt"}
                available={true}
                title="YOLOv11x"
                badge="General"
                badgeColor="#ffdd00"
                desc="Modelo COCO genérico. Detecta personas (clase 0) y pelota (clase 32). Descarga automática."
                source="Ultralytics"
                onClick={() => { setDetModelPath("yolo11x.pt"); postConfig({ model: "yolo11x.pt" }); }}
              />
              <ModelCard
                active={detModelPath.includes("Football-Object-Detection")}
                available={true}
                title="Football YOLOv8"
                badge="52MB"
                badgeColor="#00ff88"
                desc="Entrenado específicamente en fútbol. Clases: ball, goalkeeper, player, referee. Mejor precisión en vistas de broadcast."
                source="Football-Object-Detection-main/best.pt"
                onClick={() => {
                  const p = "repos/Football-Object-Detection-main/weights/best.pt";
                  setDetModelPath(p); postConfig({ model: p });
                }}
              />
              <ModelCard
                active={detModelPath.includes("player_detect")}
                available={true}
                title="Player Detect"
                badge="Custom"
                badgeColor="#aa88ff"
                desc="Modelo personalizado de Tryolabs Soccer Analytics para detección de jugadores en fútbol."
                source="soccer-video-detection-ai-agent/player_detect.pt"
                onClick={() => {
                  const p = "repos/soccer-video-detection-ai-agent-main/weights/player_detect.pt";
                  setDetModelPath(p); postConfig({ model: p });
                }}
              />
            </Section>

            <Section title="ℹ️ Estado del sistema">
              <StatRow label="🔥 PyTorch"  value={detOsnetAvail || detTeamClf === "osnet" ? "✅ Disponible" : "⚠️ No instalado"} />
              <StatRow label="✂️ SAHI"     value={detSahiAvailable ? "✅ Disponible" : "⚠️ No instalado"} />
              <StatRow label="🛤️ Norfair"  value={detNorfairAvail  ? "✅ Disponible" : "⚠️ No instalado"} />
              <StatRow label="🧠 Clasificador actual" value={detTeamClf} />
            </Section>
          </>}

          {/* ═══ TAB: STATS ══════════════════════════════════ */}
          {panelTab === "stats" && <>
            <Section title="📊 Partido">
              <StatRow label="👥 Jugadores"    value={stats.total_players || 0} />
              <StatRow label="🟢 Equipo 1"     value={stats.team_1_count  || 0} color={TEAM_COLORS.team_1} />
              <StatRow label="🔴 Equipo 2"     value={stats.team_2_count  || 0} color={TEAM_COLORS.team_2} />
              <StatRow label="🧠 Clasificador" value={stats.classifier_ready ? "✅ Listo" : "⏳ Aprendiendo…"} />
              <StatRow label="🛰️ Tracker"      value={stats.tracker || "—"} />
              <StatRow label="🏟️ Campo"        value={stats.calibrated ? "✅ Calibrado" : "⚠️ Escala px/m"} />
              <StatRow label="🎞️ Frames proc." value={processedFrames} />
              <StatRow label="⏱️ Tiempo analiz." value={fmtTime(stats.elapsed_s || 0)} />
              <StatRow label="⚡ FPS"          value={fps > 0 ? `${fps} fps` : "—"} />
              {ball && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ color: "#888", fontSize: 11, marginBottom: 4 }}>Posesión</div>
                  <PossessionBar t1={possession.team_1 || 0} t2={possession.team_2 || 0} />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
                    <span style={{ color: TEAM_COLORS.team_1, fontSize: 12, fontWeight: 700 }}>{possession.team_1 || 0}%</span>
                    <span style={{ color: TEAM_COLORS.team_2, fontSize: 12, fontWeight: 700 }}>{possession.team_2 || 0}%</span>
                  </div>
                  {frameData?.possession?.changes > 0 && (
                    <div style={{ color: "#666", fontSize: 10, marginTop: 4 }}>
                      {frameData.possession.changes} cambios de posesión
                    </div>
                  )}
                </div>
              )}
            </Section>

            <Section title="🏅 Rendimiento en pista">
              <StatRow label="🛣️ Distancia total" value={fmtDistance(summary.totalDistance)} />
              <StatRow label="💨 Punta actual"    value={`${summary.topSpeed.toFixed(1)} km/h`}
                color={speedColor(summary.topSpeed)} />
              <StatRow label="🔥 Sprints"         value={summary.sprints} />
              <p style={{ color: "#555", fontSize: 10, marginTop: 6, lineHeight: 1.4 }}>
                {stats.calibrated
                  ? "Métricas en metros reales (campo calibrado)."
                  : "Métricas estimadas por escala px/m: calibra el campo para valores reales."}
              </p>
            </Section>

            <Section title="🏃 Jugadores" scroll>
              {(frameData?.players || []).map(p => (
                <PlayerCard key={p.track_id} player={p}
                  name={playerNames[p.track_id] || p.name}
                  team={playerTeamOverrides[p.track_id] || p.team}
                  isSelected={teamPickerPlayer?.track_id === p.track_id}
                  onEdit={() => {
                    const overrides = teamOverridesRef.current;
                    setTeamPickerPlayer({ ...p, team: overrides[p.track_id] || p.team });
                    setTeamPickerName(playerNames[p.track_id] || p.name || `#${p.track_id}`);
                  }}
                />
              ))}
              {!frameData?.players?.length && (
                <p style={{ color: "#444", fontSize: 11 }}>Sin jugadores detectados</p>
              )}
            </Section>
          </>}

        </div>
      </div>
    </div>
  );
}

// ─── FLOW BADGE ────────────────────────────────────────────────
const FLOW_LABELS = {
  idle:      { text: "Esperando",         color: "#444",    bg: "#1a1a1a" },
  loading:   { text: "Cargando…",         color: "#aaa",    bg: "#1a1a2a" },
  detecting: { text: "Detectando…",       color: "#ffdd00", bg: "#2a2a00" },
  preview:   { text: "Vista previa",      color: "#ffaa00", bg: "#2a1a00" },
  analyzing: { text: "Analizando…",       color: "#00ccff", bg: "#001a2a" },
  done:      { text: "Análisis completo", color: "#00ff88", bg: "#001a0a" },
};
function FlowBadge({ step }) {
  const { text, color, bg } = FLOW_LABELS[step] || FLOW_LABELS.idle;
  return (
    <span style={{ padding: "2px 10px", borderRadius: 10, fontSize: 12, background: bg, color }}>
      {text}
    </span>
  );
}

// ─── TEAM PICKER POPUP ─────────────────────────────────────────
function TeamPicker({ player, name, onNameChange, currentTeam, onTeamSelect, onSave, onClose }) {
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
function Section({ title, children, scroll }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={styles.sectionTitle}>{title}</div>
      <div style={scroll ? { maxHeight: 210, overflowY: "auto" } : {}}>{children}</div>
    </div>
  );
}

function StatRow({ label, value, color }) {
  return (
    <div style={styles.statRow}>
      <span style={{ color: "#666", fontSize: 12 }}>{label}</span>
      <span style={{ color: color || "#ddd", fontWeight: 600, fontSize: 13 }}>{value}</span>
    </div>
  );
}

function ToggleRow({ label, value, onChange }) {
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

function PlayerCard({ player, name, team, isSelected, onEdit }) {
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

function PossessionBar({ t1, t2 }) {
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

function ModelCard({ active, available, title, badge, badgeColor, desc, source, onClick }) {
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

// ─── STYLES ────────────────────────────────────────────────────
const styles = {
  sessionBadge: {
    marginLeft: "auto", padding: "2px 8px", borderRadius: 8,
    background: "#11111a", color: "#556", fontSize: 11, fontFamily: "monospace",
  },
  notice: {
    display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
    padding: "6px 14px", background: "#2a1010", color: "#ff8877",
    fontSize: 12, borderBottom: "1px solid #442222",
  },
  noticeClose: {
    background: "transparent", border: "none", color: "#ff8877",
    cursor: "pointer", fontSize: 13, lineHeight: 1,
  },
  root: {
    background: "#080810", minHeight: "100vh",
    fontFamily: "'Segoe UI', Arial, sans-serif",
    color: "#ddd", display: "flex", flexDirection: "column",
  },
  header: {
    display: "flex", alignItems: "center", gap: 10,
    padding: "9px 18px", background: "#0d0d1a",
    borderBottom: "1px solid #1a1a28",
  },
  logo:    { fontWeight: 700, fontSize: 17, color: "#00ff88" },
  version: { color: "#444", fontSize: 11 },
  badge:   { padding: "2px 9px", borderRadius: 10, fontSize: 12 },
  fpsBadge:{ color: "#ffdd00", fontSize: 12, marginLeft: "auto", fontFamily: "monospace" },
  body:    { display: "flex", flex: 1, overflow: "hidden" },
  canvasWrap: {
    flex: 1, position: "relative", background: "#050510",
    display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
  },
  canvas: {
    display: "block", maxWidth: "100%", height: "auto",
    cursor: "crosshair", borderRadius: 3,
    position: "relative", background: "transparent",
  },
  previewBanner: {
    display: "flex", alignItems: "center", gap: 12,
    padding: "10px 16px", background: "#1a1500",
    borderTop: "1px solid #ffdd0033",
    width: "100%", boxSizing: "border-box", maxWidth: 854,
    justifyContent: "space-between",
  },
  analyzeBtn: {
    background: "#ffdd00", color: "#000", border: "none",
    borderRadius: 6, padding: "6px 18px", cursor: "pointer",
    fontSize: 13, fontWeight: 700, whiteSpace: "nowrap",
  },
  detectBtn: {
    background: "#1a3a5c", color: "#66ccff", border: "1px solid #2255aa",
    borderRadius: 6, padding: "6px 14px", cursor: "pointer",
    fontSize: 13, fontWeight: 600, whiteSpace: "nowrap",
  },
  videoControls: {
    display: "flex", alignItems: "center", gap: 10,
    padding: "8px 14px", background: "#0d0d1a",
    borderTop: "1px solid #1a1a28",
    width: "100%", boxSizing: "border-box", maxWidth: 854,
  },
  playBtn: {
    background: "#00ff88", color: "#000", border: "none",
    borderRadius: 6, padding: "5px 14px", cursor: "pointer",
    fontSize: 16, fontWeight: 700, minWidth: 44,
  },
  seekBar:     { flex: 1, cursor: "pointer", accentColor: "#00ff88" },
  timeDisplay: { color: "#666", fontSize: 11, fontFamily: "monospace", whiteSpace: "nowrap" },
  analysisBanner: {
    display: "flex", alignItems: "center", gap: 12,
    padding: "8px 14px", background: "#061206",
    borderTop: "1px solid #00ff8822",
    width: "100%", boxSizing: "border-box", maxWidth: 854,
    justifyContent: "space-between",
  },
  playOverlayBtn: {
    background: "#00ff88", color: "#000", border: "none",
    borderRadius: 6, padding: "5px 16px", cursor: "pointer",
    fontSize: 13, fontWeight: 700, whiteSpace: "nowrap",
  },
  processingOverlay: {
    position: "absolute", inset: 0, background: "rgba(0,0,0,0.65)",
    display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center", gap: 14,
  },
  processingText: { color: "#ddd", fontSize: 15 },
  spinner: {
    width: 34, height: 34, border: "3px solid #222",
    borderTop: "3px solid #00ff88", borderRadius: "50%",
    animation: "spin 0.8s linear infinite",
  },
  // Barra de progreso no bloqueante
  progressBar: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "7px 14px", background: "#0a0a18",
    borderTop: "1px solid #1a1a30",
    width: "100%", boxSizing: "border-box", maxWidth: 854,
  },
  miniSpinner: {
    width: 14, height: 14, border: "2px solid #222",
    borderTop: "2px solid #00ff88", borderRadius: "50%",
    animation: "spin 0.8s linear infinite", flexShrink: 0,
  },
  pauseBtn: {
    background: "#ffaa00", color: "#000", border: "none",
    borderRadius: 5, padding: "4px 12px", cursor: "pointer",
    fontSize: 12, fontWeight: 700,
  },
  resumeBtn: {
    background: "#00ff88", color: "#000", border: "none",
    borderRadius: 5, padding: "4px 14px", cursor: "pointer",
    fontSize: 12, fontWeight: 700,
  },
  cancelBtnSm: {
    background: "#2a0a0a", color: "#ff5555", border: "1px solid #441414",
    borderRadius: 5, padding: "4px 10px", cursor: "pointer", fontSize: 12,
  },
  // Banner de análisis pausado
  pausedBanner: {
    display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10,
    padding: "9px 14px", background: "#1a1400",
    borderTop: "1px solid #ffaa0033",
    width: "100%", boxSizing: "border-box", maxWidth: 854,
  },
  emptyOverlay: {
    position: "absolute", inset: 0,
    display: "flex", flexDirection: "column",
    alignItems: "center", justifyContent: "center",
  },
  panel: {
    width: 300, background: "#0b0b18",
    borderLeft: "1px solid #1a1a28",
    padding: "12px 12px", overflowY: "auto",
    flexShrink: 0,
  },
  sectionTitle: {
    color: "#444", fontSize: 10, fontWeight: 700,
    textTransform: "uppercase", letterSpacing: 1.2,
    marginBottom: 7, borderBottom: "1px solid #181828", paddingBottom: 4,
  },
  modeRow:     { display: "flex", gap: 5 },
  modeBtn:     {
    flex: 1, padding: "5px 0", background: "#111118",
    border: "1px solid #1e1e28", borderRadius: 6, color: "#666",
    cursor: "pointer", fontSize: 12,
  },
  modeBtnActive: { border: "1px solid #00ff88", color: "#00ff88", background: "#071207" },
  statRow:       { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 },
  sliderRow:     { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, marginTop: 2 },
  subLabel:      { color: "#555", fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.8, marginTop: 8, marginBottom: 4 },
  btnPrimary:    {
    width: "100%", padding: "7px 0", background: "#00ff88",
    color: "#000", fontWeight: 700, border: "none",
    borderRadius: 6, cursor: "pointer", fontSize: 13,
  },
  btnSecondary:  {
    width: "100%", padding: "6px 0", background: "#111118",
    color: "#888", border: "1px solid #1e1e28",
    borderRadius: 6, cursor: "pointer", fontSize: 12,
  },
};

if (typeof document !== "undefined" && !document.getElementById("fc-spin")) {
  const s = document.createElement("style");
  s.id = "fc-spin";
  s.textContent = "@keyframes spin { to { transform: rotate(360deg); } }";
  document.head.appendChild(s);
}
