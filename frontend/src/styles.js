/**
 * Estilos en línea de la aplicación.
 *
 * Vivían al final de `App.jsx`, 160 líneas por debajo del componente que los
 * usaba. Están aquí para que los componentes extraídos puedan importarlos sin
 * arrastrar el fichero entero, no porque haya cambiado nada de cómo se aplican.
 */

export const styles = {
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
