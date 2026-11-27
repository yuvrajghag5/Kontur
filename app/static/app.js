"use strict";
// Kontur - browser side.
//
// The server holds every annotation. This file draws them, turns mouse positions
// into image pixels, and sends each change to the server as it happens.
// All geometry is in IMAGE pixels; the view transform V only exists on screen.

const $ = id => document.getElementById(id);
const canvas = $("canvas"), ctx = canvas.getContext("2d");

const S = {
  projectId: null, project: null,    // the open project; null on the home page
  classes: [], images: [],
  imageId: null, img: null,          // current image record and its <img>
  anns: [],                          // annotations of the current image
  selected: null,                    // id of the selected annotation
  tool: "box", classId: null,
  mode: "manual",
  draft: null,                       // shape being drawn: {kind, points}
  drag: null,                        // vertex / body move or pan in progress
  cursor: null,                      // last mouse position in image pixels
  openedAt: 0,                       // when the current image was opened (ms)
  proposal: null,                    // AI outline in progress, see newProposal()
  ai: "off",                         // AI status line: off / encoding / ready / error text
  aiNote: "",                        // what the AI is busy with, shown on the image
};

// ---------------------------------------------------------------- event log
//
// Every interaction is logged for the effort evaluation: per object, how many
// clicks and how much time, in manual versus assisted mode.
const SESSION = Math.random().toString(36).slice(2, 10);
let queue = [];

function ev(event, data = {}) {
  queue.push({ event, t: Date.now(), session: SESSION, mode: S.mode, image: S.imageId, ...data });
}
async function flush() {
  if (!queue.length) return;
  const batch = queue; queue = [];
  try {
    await fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" },
                                 body: JSON.stringify({ events: batch }) });
  } catch (_) { queue = batch.concat(queue); }   // server away: keep them for the next try
}
setInterval(flush, 1500);
window.addEventListener("beforeunload", () => {
  leaveImage();
  if (queue.length) navigator.sendBeacon("/api/events",
    new Blob([JSON.stringify({ events: queue })], { type: "application/json" }));
});

// ---------------------------------------------------------------- server calls

// Every call names the project on screen (X-Project). If another project is
// open on the server by then, it refuses: nothing lands in the wrong project.
function projHeaders(h = {}) {
  if (S.projectId !== null) h["X-Project"] = String(S.projectId);
  return h;
}
async function api(method, url, body) {
  const res = await fetch(url, { method, headers: projHeaders(body ? { "Content-Type": "application/json" } : {}),
                                 body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function toast(msg, warn = false, ms = 2200) {
  const t = $("toast");
  t.textContent = msg; t.className = "show" + (warn ? " warn" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.className = "", ms);
}

// ---------------------------------------------------------------- view: zoom and pan
//
// The image is drawn at scale V.s, shifted by (V.tx, V.ty) CSS pixels inside the
// canvas. toImage() is the ONLY screen-to-image conversion; every tool uses it.
const V = { s: 1, tx: 0, ty: 0 };
const dpr = () => window.devicePixelRatio || 1;

function toImage(clientX, clientY) {
  const r = canvas.getBoundingClientRect();
  return [(clientX - r.left - V.tx) / V.s, (clientY - r.top - V.ty) / V.s];
}

function resizeCanvas() {
  const r = canvas.getBoundingClientRect();
  canvas.width = Math.round(r.width * dpr());
  canvas.height = Math.round(r.height * dpr());
  draw();
}

function fit() {
  if (!S.img) return;
  const r = canvas.getBoundingClientRect(), pad = 16;
  V.s = Math.min((r.width - pad) / S.img.width, (r.height - pad) / S.img.height);
  V.tx = (r.width - S.img.width * V.s) / 2;
  V.ty = (r.height - S.img.height * V.s) / 2;
  draw();
}

function zoomAt(factor, clientX, clientY) {
  const r = canvas.getBoundingClientRect();
  const px = clientX - r.left, py = clientY - r.top;
  const s2 = Math.min(40, Math.max(0.02, V.s * factor));
  V.tx = px - (px - V.tx) * (s2 / V.s);
  V.ty = py - (py - V.ty) * (s2 / V.s);
  V.s = s2;
  draw();
}

// ---------------------------------------------------------------- drawing

const colourOf = id => (S.classes.find(c => c.id === id) || { colour: "#ccc" }).colour;
const nameOf = id => (S.classes.find(c => c.id === id) || { name: "?" }).name;

function shapePath(kind, pts) {
  ctx.beginPath();
  if (kind === "box") {
    const [[x1, y1], [x2, y2]] = pts;
    ctx.rect(x1, y1, x2 - x1, y2 - y1);
  } else {
    pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.closePath();
  }
}

// A small label flag above a shape, sized in screen pixels at any zoom.
function tag(x, y, text, bg, fg, px) {
  ctx.font = `600 ${12 * px}px "IBM Plex Sans Condensed", system-ui, sans-serif`;
  const w = ctx.measureText(text).width;
  ctx.fillStyle = bg;
  ctx.fillRect(x, y - 16 * px, w + 10 * px, 16 * px);
  ctx.fillStyle = fg;
  ctx.fillText(text, x + 5 * px, y - 4.5 * px);
}

// The photo lies on the light table like a print: a soft shadow under it and
// registration marks just outside each corner. Drawn in image units, so they
// stay glued to the photo while zooming and panning.
function drawPrintFrame(px) {
  const W = S.img.width, H = S.img.height;
  ctx.save();
  ctx.shadowColor = "rgba(20, 28, 38, 0.35)";
  ctx.shadowBlur = 18 * dpr();                     // shadows ignore the transform: device pixels
  ctx.shadowOffsetY = 4 * dpr();
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
  const gap = 7 * px, len = 16 * px;
  ctx.strokeStyle = "#1c242d"; ctx.lineWidth = 1.5 * px;
  ctx.beginPath();
  for (const [cx, cy, sx, sy] of [[0, 0, -1, -1], [W, 0, 1, -1], [W, H, 1, 1], [0, H, -1, 1]]) {
    ctx.moveTo(cx + sx * gap, cy); ctx.lineTo(cx + sx * (gap + len), cy);   // horizontal tick
    ctx.moveTo(cx, cy + sy * gap); ctx.lineTo(cx, cy + sy * (gap + len));   // vertical tick
  }
  ctx.stroke();
}

function draw() {
  const d = dpr();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  $("empty").style.display = S.img ? "none" : "flex";
  if (!S.img) return;

  ctx.setTransform(d * V.s, 0, 0, d * V.s, d * V.tx, d * V.ty);
  const px = 1 / V.s;                            // one screen pixel, in image units
  drawPrintFrame(px);
  ctx.imageSmoothingEnabled = V.s < 2;          // show real pixels when zoomed in
  ctx.drawImage(S.img, 0, 0);

  for (const a of S.anns) {
    const sel = a.id === S.selected, col = colourOf(a.class_id);
    shapePath(a.kind, a.points);
    ctx.fillStyle = col + (sel ? "55" : "30");
    ctx.fill();
    ctx.lineWidth = (sel ? 3 : 2) * px;
    ctx.strokeStyle = col;
    ctx.stroke();
    const [x0, y0] = a.kind === "box" ? a.points[0]
      : [Math.min(...a.points.map(p => p[0])), Math.min(...a.points.map(p => p[1]))];
    tag(x0, y0, nameOf(a.class_id), col, "#000", px);
    if (sel) handles(a).forEach(([x, y]) => {
      ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = px;
      ctx.fillRect(x - 4 * px, y - 4 * px, 8 * px, 8 * px);
      ctx.strokeRect(x - 4 * px, y - 4 * px, 8 * px, 8 * px);
    });
  }

  drawSuggestions(px);
  drawProposal(px);

  // the shape being drawn
  const dr = S.draft, col = colourOf(S.classId);
  if (dr && dr.kind === "box" && S.cursor) {
    shapePath("box", normBox([dr.points[0], S.cursor]));
    ctx.setLineDash([6 * px, 4 * px]); ctx.lineWidth = 2 * px; ctx.strokeStyle = col; ctx.stroke();
    ctx.setLineDash([]);
  }
  if (dr && dr.kind === "polygon") {
    ctx.beginPath();
    dr.points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    if (S.cursor) ctx.lineTo(...S.cursor);
    ctx.lineWidth = 2 * px; ctx.strokeStyle = col; ctx.stroke();
    dr.points.forEach(([x, y], i) => {
      const r = (i === 0 && nearFirst() ? 7 : 3.5) * px;
      ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = i === 0 ? "#fff" : col; ctx.fill();
    });
  }
  status();
}

function status() {
  const c = S.cursor, img = S.images.find(i => i.id === S.imageId);
  const inside = c && S.img && c[0] >= 0 && c[1] >= 0 && c[0] < S.img.width && c[1] < S.img.height;
  $("status").textContent = [
    img ? `${img.name}  ${img.width}×${img.height}` : "",
    `tool ${S.tool}`, `class ${S.classId ? nameOf(S.classId) : "-"}`, `mode ${S.mode}`,
    `zoom ${S.img ? (V.s * 100).toFixed(0) + "%" : "-"}`,
    inside ? `x ${c[0].toFixed(1)}  y ${c[1].toFixed(1)}` : "",
    S.mode === "assisted" ? `AI ${S.ai}` : "",
    S.proposal ? (S.proposal.busy ? "outlining..." :
      S.proposal.polygon ? `proposal: SAM score ${S.proposal.score}, Enter to accept` : "") : "",
  ].filter(Boolean).join("   ·   ");
  const pr = S.proposal;
  // The banner prefixes "AI ·" itself (CSS), so these read as plain sentences.
  $("aiBanner").textContent = S.mode !== "assisted" ? "" :
    S.aiNote ? S.aiNote :
    S.detNote ? S.detNote :
    pr && pr.busy ? "outlining..." :
    pr && pr.polygon ? `${nameOf(pr.classId)} outline: Enter save · click next object · Shift+click add · right-click remove · Esc discard` :
    S.sugHover ? `click to accept ${S.sugHover.class_name} (${Math.round(S.sugHover.score * 100)}%) · right-click to reject` : "";
}

// ---------------------------------------------------------------- geometry helpers

function normBox([[xa, ya], [xb, yb]]) {
  return [[Math.min(xa, xb), Math.min(ya, yb)], [Math.max(xa, xb), Math.max(ya, yb)]];
}
function clampToImage([x, y]) {
  return [Math.min(Math.max(x, 0), S.img.width), Math.min(Math.max(y, 0), S.img.height)];
}
// Grab handles: box = its four corners, polygon = its vertices.
function handles(a) {
  if (a.kind === "polygon") return a.points;
  const [[x1, y1], [x2, y2]] = a.points;
  return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
}
function inside(a, [x, y]) {
  if (a.kind === "box") {
    const [[x1, y1], [x2, y2]] = a.points;
    return x >= x1 && x <= x2 && y >= y1 && y <= y2;
  }
  let hit = false;                                   // ray casting
  const p = a.points;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    if ((p[i][1] > y) !== (p[j][1] > y) &&
        x < (p[j][0] - p[i][0]) * (y - p[i][1]) / (p[j][1] - p[i][1]) + p[i][0]) hit = !hit;
  }
  return hit;
}
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const nearFirst = () => S.draft && S.draft.kind === "polygon" && S.draft.points.length >= 3 &&
  S.cursor && dist(S.cursor, S.draft.points[0]) * V.s < 9;

// A box corner drag moves that corner; the opposite corner (`anchor`, fixed when
// the drag starts) stays put, even if the dragged corner crosses over it.
function moveHandle(a, i, p, anchor) {
  if (a.kind === "polygon") a.points[i] = p;
  else a.points = normBox([p, anchor]);
}

// ---------------------------------------------------------------- undo
//
// Each entry knows how to reverse one action. Deleting and re-creating gives an
// annotation a new id, so entries refer to ids through `alias`.
const undoStacks = {};          // per image
const alias = {};               // old id -> current id after an undo re-created it
const real = id => (alias[id] !== undefined ? real(alias[id]) : id);
const pushUndo = entry => (undoStacks[S.imageId] ||= []).push(entry);

async function undo() {
  const stack = undoStacks[S.imageId] || [];
  const e = stack.pop();
  if (!e) { toast("nothing to undo on this image"); return; }
  try {
    if (e.type === "create") {
      await api("DELETE", `/api/annotations/${real(e.ann.id)}`);
    } else if (e.type === "delete") {
      const a = e.ann;
      const b = await api("POST", "/api/annotations", { image_id: a.image_id, class_id: a.class_id,
                                                        kind: a.kind, points: a.points, source: a.source });
      alias[a.id] = b.id;
    } else if (e.type === "update") {
      await api("PUT", `/api/annotations/${real(e.id)}`, e.before);
    }
    ev("undo", { undid: e.type, ann: real(e.type === "update" ? e.id : e.ann.id) });
    S.selected = null;
    await loadAnnotations();
  } catch (err) { toast("undo failed: " + err.message, true); }
}

// ---------------------------------------------------------------- annotations

async function loadAnnotations() {
  S.anns = await api("GET", `/api/images/${S.imageId}/annotations`);
  const img = S.images.find(i => i.id === S.imageId);
  if (img) img.n_annotations = S.anns.length;
  renderAnnList(); renderImageList(); draw();
}

async function createAnnotation(kind, points, source = "manual", classId = S.classId) {
  if (!classId) { toast("add or pick a class first", true); return; }
  try {
    const a = await api("POST", "/api/annotations", { image_id: S.imageId, class_id: classId,
                                                      kind, points, source });
    const dup = S.anns.find(b => b.class_id === a.class_id && boxIoU(a, b) > 0.85);
    pushUndo({ type: "create", ann: a });
    ev("ann_create", { ann: a.id, kind, cls: a.class_id, n_points: points.length, source,
                       ms_since_open: Date.now() - S.openedAt, duplicate_of: dup ? dup.id : null });
    S.anns.push(a);
    afterChange();
    // Labelled twice by mistake? (Found in the first export: one person on the
    // bus image had two near-identical boxes.) Warn, don't block; Ctrl+Z undoes.
    if (dup) toast(`this ${nameOf(a.class_id)} almost exactly covers one already labelled; Ctrl+Z if it is a duplicate`, true, 4000);
  } catch (err) { toast(err.message, true); }
}

// Overlap of two annotations' bounding boxes (intersection over union).
function boxIoU(a, b) {
  const bb = x => { const xs = x.points.map(p => p[0]), ys = x.points.map(p => p[1]);
                    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; };
  const [a1, a2, a3, a4] = bb(a), [b1, b2, b3, b4] = bb(b);
  const iw = Math.max(0, Math.min(a3, b3) - Math.max(a1, b1)), ih = Math.max(0, Math.min(a4, b4) - Math.max(a2, b2));
  const inter = iw * ih, uni = (a3 - a1) * (a4 - a2) + (b3 - b1) * (b4 - b2) - inter;
  return uni > 0 ? inter / uni : 0;
}

async function updateAnnotation(a, change, before, what) {
  try {
    const b = await api("PUT", `/api/annotations/${a.id}`, change);
    pushUndo({ type: "update", id: a.id, before });
    ev("ann_update", { ann: a.id, what });
    Object.assign(a, b);
  } catch (err) {
    toast(err.message, true);
    Object.assign(a, before);                         // put the shape back as it was
  }
  afterChange();
}

async function deleteAnnotation(id) {
  const a = S.anns.find(x => x.id === id);
  if (!a) return;
  try {
    await api("DELETE", `/api/annotations/${id}`);
    pushUndo({ type: "delete", ann: a });
    ev("ann_delete", { ann: id, kind: a.kind, cls: a.class_id });
    S.anns = S.anns.filter(x => x.id !== id);
    if (S.selected === id) S.selected = null;
    afterChange();
  } catch (err) { toast(err.message, true); }
}

function afterChange() {
  const img = S.images.find(i => i.id === S.imageId);
  if (img) img.n_annotations = S.anns.length;
  renderAnnList(); renderImageList(); draw();
}

function finishPolygon() {
  const d = S.draft;
  if (!d || d.kind !== "polygon") return;
  // A double-click lands two points on the same spot; drop the duplicate.
  const pts = d.points.filter((p, i) => i === 0 || dist(p, d.points[i - 1]) * V.s > 2);
  if (pts.length < 3) { toast("a polygon needs at least three points", true); return; }
  S.draft = null;
  createAnnotation("polygon", pts);
}

function cancelDraft() {
  if (S.draft) ev("draft_cancel", { kind: S.draft.kind, n_points: S.draft.points.length });
  S.draft = null; draw();
}

// ---------------------------------------------------------------- AI outline (Phase 3)
//
// One proposal = one object. The rules (changed 17 Nov after the first real use,
// when five plain clicks on five different objects were merged into one
// whole-image "object"):
//   plain click / drag  -> a NEW object; the previous outline, if finished, is
//                          saved automatically
//   Shift+click         -> add this spot to the CURRENT object
//   right-click         -> remove this spot from the current object
// Every prompt re-asks SAM with all prompts of that object; the answer is shown
// dashed until it is saved (Enter, or the next object), or discarded (Esc).

const newProposal = () => ({ points: [], labels: [], box: null, polygon: null, score: null,
                             busy: false, seq: 0, pending: null, firstAt: Date.now(),
                             classId: S.classId });

async function aiPrepare() {
  if (S.mode !== "assisted" || S.imageId === null) return;
  const id = S.imageId;
  S.ai = "preparing";
  try {
    const st = await api("GET", "/api/ai/status");
    S.aiNote = st.state === "loading" ? "loading the AI model (first start downloads 40 MB)..."
                                      : "reading this image...";
  } catch (_) { S.aiNote = "reading this image..."; }
  status();
  try {
    const r = await api("POST", "/api/ai/prepare", { image_id: id });
    if (S.imageId !== id) return;
    S.ai = `ready (${r.model}, ${r.device}${r.cached ? "" : `, image read in ${(r.encode_ms / 1000).toFixed(1)} s`})`;
    S.aiNote = "";
    ev("ai_ready", { encode_ms: r.encode_ms, cached: r.cached, model: r.model, device: r.device });
  } catch (err) {
    S.ai = "unavailable"; S.aiNote = "";
    toast("AI model unavailable: " + err.message, true, 6000);
  }
  status();
}

// Apply one change to a proposal's prompts and ask SAM again.
function aiPrompt(pr, change) {
  change(pr);
  if (!pr.points.length && !pr.box) { if (S.proposal === pr) discardProposal(false); return Promise.resolve(); }
  const seq = ++pr.seq, t0 = performance.now();
  pr.busy = true; draw();
  pr.pending = (async () => {
    try {
      const r = await api("POST", "/api/ai/segment", {
        image_id: S.imageId, points: pr.points.length ? pr.points : null,
        labels: pr.points.length ? pr.labels : null, box: pr.box });
      if (seq !== pr.seq) return;                       // a newer prompt superseded this answer
      pr.polygon = r.polygon; pr.score = r.score;
      ev("ai_result", { ms: Math.round(performance.now() - t0), decode_ms: r.decode_ms,
                        score: r.score, n_vertices: r.polygon ? r.polygon.length : 0,
                        n_points: pr.points.length, box: !!pr.box });
      if (!r.polygon && S.proposal === pr) toast("the model found nothing there; try another click or a box", true);
    } catch (err) {
      toast("AI outline failed: " + err.message, true, 5000);
    } finally {
      if (seq === pr.seq) pr.busy = false;
      draw();
    }
  })();
  return pr.pending;
}

// Save the current proposal if it has an outline (waiting for a pending answer
// first), otherwise drop it. `how`: "enter" or "auto" (a new object was started).
async function finishProposal(how) {
  const pr = S.proposal;
  if (!pr) return;
  while (pr.busy && pr.pending) await pr.pending;       // the answer to the LAST prompt
  if (S.proposal !== pr) return;                        // discarded or replaced meanwhile
  S.proposal = null;
  if (!pr.polygon) { draw(); return; }
  ev("ai_accept", { how, n_points: pr.points.length, n_negative: pr.labels.filter(v => v === 0).length,
                    box: !!pr.box, score: pr.score, n_vertices: pr.polygon.length,
                    ms_since_first_prompt: Date.now() - pr.firstAt });
  await createAnnotation("polygon", pr.polygon, "sam", pr.classId);
}

// A plain click or a drag: start a new object, after saving the previous one.
// Chained, so quick clicks while an answer is still on its way are handled one
// after another; otherwise two clicks could both "start" an object and one
// would be lost.
let objectChain = Promise.resolve();
function startObject(prompts) {
  objectChain = objectChain.then(async () => {
    await finishProposal("auto");
    const pr = S.proposal = newProposal();
    aiPrompt(pr, prompts);
  }).catch(err => toast("AI outline failed: " + err.message, true));
  return objectChain;
}

function acceptProposal() {
  if (!S.proposal) { toast("nothing to save: click an object first"); return; }
  finishProposal("enter");
}

function discardProposal(log = true) {
  if (log && S.proposal) ev("ai_discard", { n_points: S.proposal.points.length, box: !!S.proposal.box });
  S.proposal = null; draw();
}

// Backspace: take back the last prompt (the last click, else the box).
function undoPrompt() {
  const pr = S.proposal;
  if (!pr) return false;
  aiPrompt(pr, p => { if (p.points.length) { p.points.pop(); p.labels.pop(); } else p.box = null; });
  return true;
}

function drawProposal(px) {
  const pr = S.proposal;
  if (!pr) return;
  const col = colourOf(pr.classId);
  if (pr.polygon) {
    shapePath("polygon", pr.polygon);
    ctx.fillStyle = col + "40"; ctx.fill();
    ctx.setLineDash([7 * px, 4 * px]); ctx.lineDashOffset = antsOffset(px, 11);
    ctx.lineWidth = 2.5 * px; ctx.strokeStyle = "#fff"; ctx.stroke();
    ctx.setLineDash([]); ctx.lineDashOffset = 0;
  }
  if (pr.box) {
    shapePath("box", pr.box);
    ctx.setLineDash([3 * px, 3 * px]); ctx.lineWidth = 1.5 * px; ctx.strokeStyle = "#ffd400"; ctx.stroke();
    ctx.setLineDash([]);
  }
  pr.points.forEach(([x, y], i) => {
    ctx.beginPath(); ctx.arc(x, y, 5 * px, 0, 2 * Math.PI);
    ctx.fillStyle = pr.labels[i] ? "#22c55e" : "#ef4444"; ctx.fill();
    ctx.lineWidth = 1.5 * px; ctx.strokeStyle = "#fff"; ctx.stroke();
  });
}

// ---------------------------------------------------------------- suggestions (Phase 4)
//
// A detector proposes boxes, each already named with one of the user's classes.
// They are drawn in marker yellow and are only proposals: click one to accept it
// (SAM turns its box into an outline), right-click to reject it. The detector is
// chosen in the panel: YOLO11n (80 COCO classes) or YOLOE (any class name).
// It runs once at a low confidence floor, and the slider filters what is shown,
// so moving the slider is instant.

const SUG_FLOOR = 0.15;
S.det = { key: "yoloe", list: [], conf: 0.35, auto: true };
S.sugs = [];            // [{box, score, class_id, class_name}]
S.sugMeta = null;       // {model, ms, unsupported}
S.sugHover = null;
S.detNote = "";
let sugSeq = 0;

const detLabel = key => (S.det.list.find(d => d.key === key) || { label: key }).label;

// Hidden: below the slider, or already labelled (same class, boxes overlapping
// by IoU > 0.7), so accepting or re-running never doubles a label.
function alreadyLabelled(s) {
  const b = { points: s.box };
  return S.anns.some(a => a.class_id === s.class_id && boxIoU(a, b) > 0.7);
}
const visibleSugs = () => S.sugs.filter(s => s.score >= S.det.conf && !alreadyLabelled(s));

// The smallest visible suggestion under a point (small boxes inside big ones stay reachable).
function sugAt([x, y]) {
  const hits = visibleSugs().filter(s => x >= s.box[0][0] && x <= s.box[1][0] && y >= s.box[0][1] && y <= s.box[1][1]);
  const area = s => (s.box[1][0] - s.box[0][0]) * (s.box[1][1] - s.box[0][1]);
  return hits.sort((a, b) => area(a) - area(b))[0] || null;
}

async function loadDetectors() {
  try { S.det.list = await api("GET", "/api/ai/detectors"); } catch (_) { S.det.list = []; }
  if (!S.det.list.some(d => d.key === S.det.key) && S.det.list[0]) S.det.key = S.det.list[0].key;
  $("detSel").innerHTML = S.det.list.map(d => `<option value="${d.key}">${esc(d.label)}${
    d.state === "ready" ? "" : d.state.startsWith("error") ? " (unavailable)" : " (loading)"}</option>`).join("");
  $("detSel").value = S.det.key;
  const d = S.det.list.find(x => x.key === S.det.key);
  $("detAbout").textContent = d ? d.about : "No detector available.";
}

async function suggest(why = "button") {
  if (S.mode !== "assisted" || S.imageId === null) return;
  const id = S.imageId, seq = ++sugSeq, key = S.det.key, t0 = performance.now();
  S.detNote = `finding objects with ${detLabel(key)}...`; status();
  try {
    const r = await api("POST", "/api/ai/detect", { image_id: id, model: key, conf: SUG_FLOOR });
    if (seq !== sugSeq || S.imageId !== id) return;
    S.sugs = r.suggestions;
    S.sugMeta = { model: key, ms: r.ms, unsupported: r.unsupported, ignored: r.ignored || [] };
    ev("sug_run", { model: key, why, n: r.suggestions.length, n_shown: visibleSugs().length,
                    ms: Math.round(performance.now() - t0), detect_ms: r.ms, unsupported: r.unsupported });
  } catch (err) {
    if (seq === sugSeq) toast("Suggestions failed: " + err.message, true, 5000);
  } finally {
    if (seq === sugSeq) S.detNote = "";
    renderSugs(); draw();
    loadDetectors();
  }
}

function clearSugs() { S.sugs = []; S.sugMeta = null; S.sugHover = null; sugSeq++; S.detNote = ""; renderSugs(); }

// Accepting asks SAM to outline the object inside the box; if SAM is not
// available, the box itself is saved.
async function acceptSug(s, how) {
  const id = S.imageId;
  S.sugs = S.sugs.filter(x => x !== s);
  if (S.sugHover === s) S.sugHover = null;
  renderSugs(); draw();
  let poly = null;
  try { poly = (await api("POST", "/api/ai/segment", { image_id: id, box: s.box })).polygon; } catch (_) {}
  if (S.imageId !== id) { toast("photo changed before the outline came back; suggestion not saved", true); return; }
  ev("sug_accept", { how, model: S.sugMeta && S.sugMeta.model, cls: s.class_id, score: s.score, outlined: !!poly });
  if (poly) await createAnnotation("polygon", poly, "yolo+sam", s.class_id);
  else await createAnnotation("box", s.box, "yolo", s.class_id);
}

function rejectSug(s, how) {
  S.sugs = S.sugs.filter(x => x !== s);
  if (S.sugHover === s) S.sugHover = null;
  ev("sug_reject", { how, model: S.sugMeta && S.sugMeta.model, cls: s.class_id, score: s.score });
  renderSugs(); draw();
}

async function acceptAllSugs() {
  const all = visibleSugs();
  if (!all.length) { toast("no suggestions to accept"); return; }
  ev("sug_accept_all", { n: all.length });
  for (const s of all) await acceptSug(s, "all");
}

function renderSugs() {
  const vis = visibleSugs();
  $("sugCount").textContent = S.sugs.length ? `${vis.length} shown` : "";
  const m = S.sugMeta, hidden = S.sugs.length - vis.length;
  $("sugInfo").innerHTML = !m ? "Press <b>Suggest objects</b>, or turn on suggesting when a photo opens." : [
    `${S.sugs.length} found in ${(m.ms / 1000).toFixed(1)} s`,
    hidden ? `${hidden} hidden (below ${Math.round(S.det.conf * 100)}% or already labelled)` : "",
    m.unsupported.length ? `this detector cannot suggest: ${m.unsupported.map(esc).join(", ")}` : "",
  ].filter(Boolean).join(" · ");
  // Objects the detector saw that are not in the user's classes: never
  // suggested, but said out loud, with a one-click way to start labelling them.
  const ign = {};
  (m ? m.ignored : []).filter(o => o.score >= S.det.conf).forEach(o => ign[o.class_name] = (ign[o.class_name] || 0) + 1);
  const ignNames = Object.keys(ign).sort((a, b) => ign[b] - ign[a]);
  $("sugIgnored").innerHTML = !ignNames.length ? "" :
    `Ignored, not in your classes: ${ignNames.map(n => `${esc(n)}${ign[n] > 1 ? " ×" + ign[n] : ""}`).join(", ")}<br>` +
    ignNames.slice(0, 4).map(n => `<button data-add="${esc(n)}" title="Add '${esc(n)}' as a class">+ ${esc(n)}</button>`).join("");
  $("sugList").innerHTML = vis.map((s, i) => `
    <div class="sug ${s === S.sugHover ? "hover" : ""}" data-i="${i}">
      <span class="swatch" style="background:${colourOf(s.class_id)}"></span>
      <span class="grow">${esc(s.class_name)}${s.matched_as ? ` <span class="as">= ${esc(s.matched_as)}</span>` : ""}</span>
      <span class="score">${Math.round(s.score * 100)}%</span>
      <button data-act="ok" title="Accept">Accept</button>
      <button data-act="no" title="Reject">×</button>
    </div>`).join("");
}

$("sugIgnored").addEventListener("click", async e => {
  const name = e.target.dataset.add;
  if (!name) return;
  try { await addClass(name, "ignored_line"); } catch (err) { toast(err.message, true); }
});

$("sugList").addEventListener("click", e => {
  const act = e.target.dataset.act, row = e.target.closest(".sug");
  if (!act || !row) return;
  const s = visibleSugs()[+row.dataset.i];
  if (s) act === "ok" ? acceptSug(s, "list") : rejectSug(s, "list");
});
$("sugList").addEventListener("mouseover", e => {
  const row = e.target.closest(".sug");
  const s = row ? visibleSugs()[+row.dataset.i] : null;
  if (s !== S.sugHover) { S.sugHover = s; draw(); }
});
$("sugList").addEventListener("mouseleave", () => { S.sugHover = null; draw(); });

// Marching ants: anything the AI proposes (suggestions, the open outline) has a
// slowly moving dashed edge, so it reads as "not saved yet" at a glance.
// period = the dash pattern's length in screen pixels.
function antsOffset(px, period) {
  return reduceMotion() ? 0 : -((performance.now() / 45) % period) * px;
}
let antsLast = 0;
(function antsLoop(now) {
  requestAnimationFrame(antsLoop);
  if (now - antsLast < 40 || document.hidden || reduceMotion()) return;   // ~25 frames a second is plenty
  if (atHome() || !S.img || S.drag) return;
  const proposing = S.proposal && S.proposal.polygon;
  if (!proposing && !(S.mode === "assisted" && S.sugs.length && visibleSugs().length)) return;
  antsLast = now;
  draw();
})(0);

function drawSuggestions(px) {
  if (S.mode !== "assisted") return;
  for (const s of visibleSugs()) {
    const hot = s === S.sugHover;
    shapePath("box", s.box);
    if (hot) { ctx.fillStyle = "rgba(244, 194, 27, 0.18)"; ctx.fill(); }
    ctx.setLineDash(hot ? [] : [8 * px, 5 * px]);
    ctx.lineDashOffset = hot ? 0 : antsOffset(px, 13);
    ctx.lineWidth = (hot ? 3 : 2) * px;
    ctx.strokeStyle = "#f4c21b";
    ctx.stroke();
    ctx.setLineDash([]); ctx.lineDashOffset = 0;
    const as = s.matched_as ? ` (${s.matched_as})` : "";
    tag(s.box[0][0], s.box[0][1], `${s.class_name}${as}  ${Math.round(s.score * 100)}%`, "#f4c21b", "#1b1606", px);
  }
}

// ---------------------------------------------------------------- mouse

let spaceDown = false;

canvas.addEventListener("contextmenu", e => e.preventDefault());

canvas.addEventListener("mousedown", e => {
  if (!S.img) return;
  const p = toImage(e.clientX, e.clientY);
  S.cursor = p;
  ev("click", { button: e.button, tool: S.tool, x: +p[0].toFixed(1), y: +p[1].toFixed(1) });

  // Right/middle button or Space: pan. In the AI tool a right-click that does
  // not move is a "not this" click instead (decided on mouseup).
  if (e.button === 2 || e.button === 1 || spaceDown) {
    S.drag = { type: "pan", x: e.clientX, y: e.clientY, tx: V.tx, ty: V.ty,
               button: e.button, at: clampToImage(p), moved: false };
    return;
  }
  if (e.button !== 0) return;
  if (S.tool !== "select" && !S.classId) { toast("add or pick a class first", true); return; }

  if (S.tool === "ai") {
    // Press-and-release = "this is the object"; press-drag-release = a box.
    S.drag = { type: "ai", start: clampToImage(p), x: e.clientX, y: e.clientY, moved: false };
  } else if (S.tool === "box") {
    S.draft = { kind: "box", points: [clampToImage(p)] };
  } else if (S.tool === "polygon") {
    if (!S.draft) S.draft = { kind: "polygon", points: [] };
    if (nearFirst()) { finishPolygon(); return; }
    S.draft.points.push(clampToImage(p));
  } else if (S.tool === "select") {
    const sel = S.anns.find(a => a.id === S.selected);
    if (sel) {                                                      // grab a handle?
      const hs = handles(sel), i = hs.findIndex(h => dist(h, p) * V.s < 8);
      if (i >= 0) {
        S.drag = { type: "handle", ann: sel, i, anchor: hs[(i + 2) % 4],
                   before: { points: structuredClone(sel.points) } };
        return;
      }
    }
    const hit = [...S.anns].reverse().find(a => inside(a, p));      // topmost first
    S.selected = hit ? hit.id : null;
    if (hit) S.drag = { type: "move", ann: hit, start: p, orig: structuredClone(hit.points),
                        before: { points: structuredClone(hit.points) }, moved: false };
    renderAnnList();
  }
  draw();
});

window.addEventListener("mousemove", e => {
  if (!S.img) return;
  const p = toImage(e.clientX, e.clientY);
  S.cursor = p;
  const d = S.drag;
  if (S.tool === "ai" && !d && S.sugs.length) {          // highlight the suggestion a click would accept
    const h = sugAt(p);
    if (h !== S.sugHover) { S.sugHover = h; renderSugs(); }
  }
  if (d && d.type === "pan") {
    d.moved = d.moved || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 3;
    V.tx = d.tx + e.clientX - d.x; V.ty = d.ty + e.clientY - d.y;
  } else if (d && d.type === "ai") {
    d.moved = d.moved || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4;
    if (d.moved) S.draft = { kind: "box", points: [d.start] };     // preview the box prompt
  } else if (d && d.type === "handle") {
    moveHandle(d.ann, d.i, clampToImage(p), d.anchor);
  } else if (d && d.type === "move") {
    const dx = p[0] - d.start[0], dy = p[1] - d.start[1];
    d.moved = d.moved || Math.hypot(dx, dy) * V.s > 3;
    if (d.moved) d.ann.points = d.orig.map(([x, y]) => clampToImage([x + dx, y + dy]));
  }
  draw();
});

window.addEventListener("mouseup", e => {
  const d = S.drag;
  S.drag = null;
  // Right-click in the AI tool: "not this part" of the CURRENT object.
  if (d && d.type === "pan" && !d.moved && d.button === 2 && S.tool === "ai") {
    if (!S.proposal) {
      const s = sugAt(d.at);                            // right-click on a suggestion: reject it
      if (s) rejectSug(s, "right-click");
      else toast("right-click removes part of an outline: left-click an object first");
      return;
    }
    ev("ai_click", { label: 0, add: true, x: +d.at[0].toFixed(1), y: +d.at[1].toFixed(1) });
    aiPrompt(S.proposal, pr => { pr.points.push(d.at); pr.labels.push(0); });
    return;
  }
  if (d && d.type === "ai") {
    S.draft = null;
    if (!d.moved) {
      // Shift+click adds to the current object; a plain click starts a new one.
      const add = e.shiftKey && !!S.proposal;
      const s = !add && sugAt(d.start);                 // a click on a suggestion accepts it
      if (s) { finishProposal("auto").then(() => acceptSug(s, "click")); return; }
      ev("ai_click", { label: 1, add, x: +d.start[0].toFixed(1), y: +d.start[1].toFixed(1) });
      if (add) aiPrompt(S.proposal, pr => { pr.points.push(d.start); pr.labels.push(1); });
      else startObject(pr => { pr.points.push(d.start); pr.labels.push(1); });
    } else {
      const box = normBox([d.start, clampToImage(toImage(e.clientX, e.clientY))]);
      if ((box[1][0] - box[0][0]) * V.s > 3 && (box[1][1] - box[0][1]) * V.s > 3) {
        ev("ai_box", { box });
        startObject(pr => { pr.box = box; });           // a box is always a new object
      } else draw();
    }
    return;
  }
  if (d && d.type === "handle") {
    updateAnnotation(d.ann, { points: d.ann.points }, d.before, "reshape");
    return;
  }
  if (d && d.type === "move" && d.moved) {
    updateAnnotation(d.ann, { points: d.ann.points }, d.before, "move");
    return;
  }
  if (S.draft && S.draft.kind === "box" && e.button === 0 && S.img) {
    const box = normBox([S.draft.points[0], clampToImage(toImage(e.clientX, e.clientY))]);
    S.draft = null;
    // Ignore a click without a drag: it was meant as a click, not a box.
    if ((box[1][0] - box[0][0]) * V.s > 3 && (box[1][1] - box[0][1]) * V.s > 3) createAnnotation("box", box);
    else draw();
  }
});

canvas.addEventListener("dblclick", () => { if (S.tool === "polygon") finishPolygon(); });

canvas.addEventListener("wheel", e => {
  e.preventDefault();
  zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.clientX, e.clientY);
}, { passive: false });

canvas.addEventListener("mouseleave", () => { S.cursor = null; if (!S.drag) draw(); });

// ---------------------------------------------------------------- keyboard

window.addEventListener("keydown", async e => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if ($("picker").open || $("newProj").open || $("exportDlg").open) return;   // dialogs have their own keys
  if (atHome()) {                                      // the home page has one key: N
    if ((e.key === "n" || e.key === "N") && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); newProjectDialog(); }
    return;
  }
  const k = e.key;
  if (k === " ") { spaceDown = true; e.preventDefault(); return; }
  if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "z") { e.preventDefault(); ev("key", { key: "undo" }); await undo(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (!S.img) return;

  if (k === "b" || k === "B") setTool("box");
  else if (k === "p" || k === "P") setTool("polygon");
  else if (k === "v" || k === "V") setTool("select");
  else if (k === "a" || k === "A") {
    if (S.mode !== "assisted") { toast("AI outline needs assisted mode (top right)"); return; }
    setTool("ai");
  }
  else if (k === "f" || k === "F") fit();
  else if (k >= "0" && k <= "9") {
    const c = S.classes[k === "0" ? 9 : +k - 1];          // 1-9 = first nine, 0 = tenth
    if (c) pickClass(c.id);
  } else if (k === "/") { e.preventDefault(); $("classInp").focus(); }   // find any class by name
  else if (k === "Enter" && e.shiftKey) { if (S.mode === "assisted") acceptAllSugs(); }
  else if (k === "Enter") { if (S.tool === "ai") acceptProposal(); else finishPolygon(); }
  else if (k === "s" || k === "S") {
    if (S.mode !== "assisted") { toast("suggestions need Assisted mode (top right)"); return; }
    suggest("key");
  }
  else if (k === "Escape") {
    if (S.proposal) discardProposal();
    else if (S.draft) cancelDraft();
    else { S.selected = null; renderAnnList(); draw(); }
  }
  else if (k === "Backspace" || k === "Delete") {
    e.preventDefault();
    if (S.tool === "ai" && S.proposal) undoPrompt();
    else if (S.draft && S.draft.kind === "polygon" && S.draft.points.length) { S.draft.points.pop(); draw(); }
    else if (S.selected) deleteAnnotation(S.selected);
  } else if (k === "ArrowRight") stepImage(1);
  else if (k === "ArrowLeft") stepImage(-1);
  else return;
  ev("key", { key: k });
});
window.addEventListener("keyup", e => { if (e.key === " ") spaceDown = false; });

function setTool(t) {
  if (t === "ai" && S.mode !== "assisted") return;
  if (S.draft) cancelDraft();
  if (S.proposal && t !== "ai") discardProposal();
  S.tool = t;
  document.querySelectorAll("#tools button").forEach(b => b.classList.toggle("on", b.dataset.tool === t));
  canvas.style.cursor = t === "select" ? "default" : "crosshair";
  ev("tool", { tool: t });
  draw();
}

// Picking a class sets it for the next shape. In the Select tool it also
// re-classes the selected annotation. Only there: while drawing, a number key
// means "the next object is a dog", not "the last one was". The exception is an
// AI outline still on screen: it is not saved yet, so the class applies to it.
function pickClass(id) {
  S.classId = id;
  ev("class_pick", { cls: id });
  if (S.proposal) S.proposal.classId = id;
  const a = S.tool === "select" && S.anns.find(x => x.id === S.selected);
  if (a && a.class_id !== id) updateAnnotation(a, { class_id: id }, { class_id: a.class_id }, "reclass");
  renderClassList(); draw();
}

// ---------------------------------------------------------------- classes: picker and AI coverage
//
// The class list is the contract with the AI: suggestions only ever use these
// classes. A new project starts empty and opens the picker, so the user decides
// what will be labelled before the AI suggests anything. Every class shows
// which detector can suggest it, so nobody waits for suggestions that cannot come.

S.coverage = {};          // class id -> {yolo11n: COCO name or null, yoloe: true}
S.catalogue = null;       // {group: [COCO names]}

async function refreshCoverage() {
  try { (await api("GET", "/api/classes/coverage")).forEach(c => S.coverage[c.id] = c); } catch (_) {}
  renderClassList();
  if ($("picker").open) renderPicker();
}

function covBadges(id) {
  const c = S.coverage[id];
  if (!c) return "";
  const own = nameOf(id).toLowerCase();
  const t11 = c.yolo11n ? `YOLO11n can suggest this${c.yolo11n !== own ? ` (it calls it "${c.yolo11n}")` : ""}`
                        : "YOLO11n cannot suggest this: it is not one of its 80 COCO classes";
  return `<span class="cov ${c.yolo11n ? "on" : ""}" title="${esc(t11)}">11n</span>` +
         `<span class="cov on" title="YOLOE can suggest this: it reads class names (open vocabulary)">E</span>`;
}

// "table = dining table": shown wherever YOLO11n knows a class under another name.
function asNote(id) {
  const c = S.coverage[id];
  return c && c.yolo11n && c.yolo11n !== nameOf(id).toLowerCase() ? ` <span class="as">= ${esc(c.yolo11n)}</span>` : "";
}

// The one place classes change, so badges and suggestions always follow.
async function addClass(name, why) {
  const existing = S.classes.find(c => c.name.toLowerCase() === name.trim().toLowerCase());
  if (existing) return existing;
  const c = await api("POST", "/api/classes", { name });
  S.classes.push(c);
  ev("class_add", { cls: c.id, name: c.name, why });
  await classesChanged();
  return c;
}

async function removeClass(id) {
  await api("DELETE", `/api/classes/${id}`);
  S.classes = S.classes.filter(c => c.id !== id);
  delete S.coverage[id];
  if (S.classId === id) S.classId = S.classes[0] ? S.classes[0].id : null;
  ev("class_delete", { cls: id });
  await classesChanged();
}

async function renameClass(id) {
  const c = S.classes.find(x => x.id === id);
  if (!c) return;
  const name = prompt(`Rename "${c.name}" to:`, c.name);
  if (!name || name.trim() === c.name) return;
  try {
    Object.assign(c, await api("PUT", `/api/classes/${id}`, { name }));
    ev("class_rename", { cls: id, name: c.name });
    await classesChanged();
    draw();
  } catch (err) { toast(err.message, true); }
}

// After any class change: new badges and, in assisted mode, fresh suggestions
// for the photo on screen, so a class added mid-way is looked for at once.
// (Not while the picker is open: closing it re-suggests once.)
let resuggestTimer = null;
async function classesChanged() {
  if (!S.classId && S.classes[0]) S.classId = S.classes[0].id;
  await refreshCoverage();
  if (S.mode === "assisted" && S.img && !$("picker").open) {
    clearTimeout(resuggestTimer);
    resuggestTimer = setTimeout(() => suggest("class_change"), 300);
  }
}

// ---- the picker dialog

const chosenFor = coco => S.classes.find(c => c.name.toLowerCase() === coco ||
                                              (S.coverage[c.id] && S.coverage[c.id].yolo11n === coco));

function pickerSets() {
  const cat = S.catalogue || {};
  return {
    "Vehicles": ["person", "bicycle", "car", "motorcycle", "bus", "truck"],
    "Indoor": ["chair", "couch", "bed", "dining table", "tv", "laptop", "potted plant", "vase", "book", "clock"],
    "Animals": cat["Animals"] || [],
    "All 80": Object.values(cat).flat(),
  };
}

function renderPicker() {
  $("pkSets").innerHTML = Object.keys(pickerSets())
    .map(k => `<button type="button" data-set="${esc(k)}">${esc(k)}</button>`).join("");
  $("pkGroups").innerHTML = Object.entries(S.catalogue || {}).map(([g, names]) => `
    <div class="pk-group"><h4>${esc(g)}</h4><div class="chips">${names.map(n =>
      `<button type="button" class="chip ${chosenFor(n) ? "on" : ""}" data-coco="${esc(n)}">${esc(n)}</button>`).join("")}
    </div></div>`).join("");
  $("pkCount").textContent = S.classes.length || "";
  $("pkChosen").innerHTML = S.classes.length ? S.classes.map(c => `
    <div class="item" data-id="${c.id}">
      <span class="swatch" style="background:${c.colour}"></span>
      <span class="grow">${esc(c.name)}${asNote(c.id)}</span>
      ${covBadges(c.id)}
      <span class="act" data-ren="${c.id}" title="Rename">✎</span>
      <span class="x" data-del="${c.id}" title="Remove (only if no label uses it)">×</span>
    </div>`).join("")
    : `<div class="pk-empty">No classes yet. Tick common objects on the left, or type your own above.</div>`;
}

async function openPicker(why = "button") {
  if (!S.catalogue) {
    try { S.catalogue = (await api("GET", "/api/ai/catalogue")).groups; } catch (_) { S.catalogue = {}; }
  }
  renderPicker();
  $("pickerDone").textContent = S.images.length ? "Start labelling" : "Next: add photos";
  if (!$("picker").open) $("picker").showModal();
  ev("picker_open", { why });
  setTimeout(() => $("pickerInp").focus(), 50);
}

$("editClassesBtn").onclick = e => { e.currentTarget.blur(); openPicker("button"); };
$("pickerClose").onclick = () => $("picker").close();
$("pickerDone").onclick = () => {
  if (!S.classes.length) { toast("choose at least one class first", true); return; }
  $("picker").close();
  // step 3 of a new project: a project with no photos asks for them at once
  // (this click is the user gesture a file chooser needs)
  if (!S.images.length) $("fileInp").click();
};
$("picker").addEventListener("close", () => {
  ev("picker_close", { n_classes: S.classes.length });
  renderClassList(); draw();
  if (S.mode === "assisted" && S.img) suggest("class_change");
});

$("pkGroups").addEventListener("click", async e => {
  const coco = e.target.dataset.coco;
  if (!coco) return;
  try {
    const have = chosenFor(coco);
    if (have) await removeClass(have.id); else await addClass(coco, "picker");
  } catch (err) { toast(err.message, true); }
  renderPicker();
});

$("pkSets").addEventListener("click", async e => {
  const set = pickerSets()[e.target.dataset.set];
  if (!set) return;
  ev("picker_set", { set: e.target.dataset.set });
  for (const n of set) if (!chosenFor(n)) { try { await addClass(n, "picker_set"); } catch (err) { toast(err.message, true); } }
  renderPicker();
});

$("pickerForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("pickerInp").value.trim();
  if (!name) return;
  try { await addClass(name, "picker_typed"); $("pickerInp").value = ""; } catch (err) { toast(err.message, true); }
  renderPicker();
});

$("pkChosen").addEventListener("click", async e => {
  const del = e.target.dataset.del, ren = e.target.dataset.ren;
  try {
    if (del) await removeClass(+del);
    else if (ren) await renameClass(+ren);
  } catch (err) { toast(err.message, true); }
  renderPicker();
});

// ---------------------------------------------------------------- side panels

// Any number of classes. The first ten have keys (1-9, 0); every class can be
// reached by typing in the find-or-add box (press /), which filters this list.
function classMatches() {
  const q = $("classInp").value.trim().toLowerCase();
  return S.classes.filter(c => !q || c.name.toLowerCase().includes(q));
}

function renderClassList() {
  const counts = {};
  S.anns.forEach(a => counts[a.class_id] = (counts[a.class_id] || 0) + 1);
  const shown = new Set(classMatches().map(c => c.id));
  $("classCount").textContent = S.classes.length || "";
  $("classList").innerHTML = S.classes.map((c, i) => !shown.has(c.id) ? "" : `
    <div class="item ${c.id === S.classId ? "on" : ""}" data-id="${c.id}" title="double-click to rename">
      <span class="key">${i < 9 ? i + 1 : i === 9 ? 0 : ""}</span>
      <span class="swatch" style="background:${c.colour}"></span>
      <span class="grow">${esc(c.name)}${asNote(c.id)}</span>
      <span class="n">${counts[c.id] || ""}</span>
      ${covBadges(c.id)}
      <span class="x" title="delete class (only if unused)" data-del="${c.id}">×</span>
    </div>`).join("") || `<div class="note">No classes yet. <b>Edit classes</b> to choose them.</div>`;
}

function renderAnnList() {
  $("annCount").textContent = S.img ? `(${S.anns.length})` : "";
  $("annList").innerHTML = S.anns.map(a => `
    <div class="item ${a.id === S.selected ? "on" : ""}" data-id="${a.id}">
      <span class="swatch" style="background:${colourOf(a.class_id)}"></span>
      <span class="grow">${esc(nameOf(a.class_id))} <span class="n">${a.kind}</span></span>
      ${a.source !== "manual" ? `<span class="src">${a.source}</span>` : ""}
      <span class="x" title="delete" data-del="${a.id}">×</span>
    </div>`).join("");
  renderClassList();
}

function renderImageList() {
  $("imgCount").textContent = S.images.length || "";
  $("imageList").innerHTML = S.images.map(i => `
    <div class="item ${i.id === S.imageId ? "on" : ""}" data-id="${i.id}" title="${esc(i.name)}">
      <img class="thumb" src="${imgUrl(i.id)}" alt="" loading="lazy">
      <span class="grow"><span class="name">${esc(i.name)}</span>
        <span class="sub">${i.n_annotations ? i.n_annotations + " labels" : "unlabelled"}</span></span>
      <span class="x" title="delete image and its labels" data-del="${i.id}">×</span>
    </div>`).join("");
}

// Image ids restart at 1 in every project: the project id in the URL keeps the
// browser's cache from showing project 1's photo 3 in project 2.
const imgUrl = id => `/api/images/${id}/file?p=${S.projectId}`;

const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

$("classList").addEventListener("click", async e => {
  const del = e.target.dataset.del, row = e.target.closest(".item");
  if (del) {
    try { await removeClass(+del); draw(); } catch (err) { toast(err.message, true); }
  } else if (row) pickClass(+row.dataset.id);
});
$("classList").addEventListener("dblclick", e => {
  const row = e.target.closest(".item");
  if (row) renameClass(+row.dataset.id);
});

// Find-or-add: Enter picks the class whose name matches exactly, or the only
// one left in the filtered list; otherwise it adds the typed name as a new class.
$("classForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("classInp").value.trim();
  if (!name) { $("classInp").blur(); return; }
  const matches = classMatches();
  const pick = S.classes.find(c => c.name.toLowerCase() === name.toLowerCase()) ||
               (matches.length === 1 ? matches[0] : null);
  try {
    const c = pick || await addClass(name, "find_or_add");
    $("classInp").value = "";
    $("classInp").blur();
    pickClass(c.id);
  } catch (err) { toast(err.message, true); }
});
$("classInp").addEventListener("input", renderClassList);
$("classInp").addEventListener("keydown", e => {
  if (e.key === "Escape") { e.target.value = ""; renderClassList(); e.target.blur(); }
});

$("annList").addEventListener("click", e => {
  const del = e.target.dataset.del, row = e.target.closest(".item");
  if (del) deleteAnnotation(+del);
  else if (row) { S.selected = +row.dataset.id; setTool("select"); renderAnnList(); draw(); }
});

$("imageList").addEventListener("click", async e => {
  const del = e.target.dataset.del, row = e.target.closest(".item");
  if (del) {
    const img = S.images.find(i => i.id === +del);
    if (!confirm(`Delete "${img.name}" and its ${img.n_annotations || 0} annotation(s)?`)) return;
    try {
      await api("DELETE", `/api/images/${del}`);
      S.images = S.images.filter(i => i.id !== +del);
      if (S.imageId === +del) { S.imageId = null; S.img = null; S.anns = []; }
      renderImageList(); renderAnnList(); draw();
      if (!S.imageId && S.images.length) openImage(S.images[0].id);
    } catch (err) { toast(err.message, true); }
  } else if (row) openImage(+row.dataset.id);
});

document.querySelectorAll("#tools button").forEach(b => b.onclick = () => setTool(b.dataset.tool));

// Manual mode hides the AI completely, so manual sessions are an honest
// baseline for the evaluation; assisted mode adds the AI tools on top.
function applyMode() {
  const on = S.mode === "assisted";
  $("aiBtn").disabled = !on;
  document.querySelectorAll(".mode button").forEach(b => b.classList.toggle("on", b.dataset.mode === S.mode));
  $("sugOff").style.display = on ? "none" : "";
  $("sugOn").style.display = on ? "" : "none";
  if (!on) {
    if (S.tool === "ai") setTool("box");
    S.ai = "off"; S.aiNote = "";
    clearSugs();
  } else {
    loadDetectors();
    if (S.det.auto && S.img) suggest("mode");      // suggestions first, as on opening a photo
    aiPrepare();
  }
  draw();
}

function setMode(m) {
  if (m === S.mode) return;
  S.mode = m;
  ev("mode", { to: m });
  if (m === "assisted") toast("Assisted: A for AI outline, S for suggestions");
  applyMode();
}
document.querySelectorAll(".mode button").forEach(b => b.onclick = () => { setMode(b.dataset.mode); b.blur(); });

$("detSel").onchange = e => {
  S.det.key = e.target.value;
  ev("det_change", { model: S.det.key });
  e.target.blur();
  clearSugs(); loadDetectors();
  if (S.img) suggest("model_change");
};
$("confRange").oninput = e => {
  S.det.conf = +e.target.value;
  $("confVal").textContent = `${Math.round(S.det.conf * 100)}%`;
  renderSugs(); draw();
};
$("confRange").onchange = e => { ev("sug_conf", { conf: S.det.conf }); e.target.blur(); };
$("autoSug").onchange = e => { S.det.auto = e.target.checked; ev("sug_auto", { on: S.det.auto }); e.target.blur(); };
$("suggestBtn").onclick = e => { e.currentTarget.blur(); suggest("button"); };
$("acceptAllBtn").onclick = e => { e.currentTarget.blur(); acceptAllSugs(); };
$("confVal").textContent = `${Math.round(S.det.conf * 100)}%`;

// ---------------------------------------------------------------- images

function leaveImage() {
  if (S.imageId !== null && S.openedAt)
    ev("image_leave", { ms_open: Date.now() - S.openedAt, n_annotations: S.anns.length });
}

async function openImage(id) {
  if (S.draft) cancelDraft();
  if (S.proposal) discardProposal();
  clearSugs();
  leaveImage();
  S.imageId = id; S.selected = null; S.anns = [];
  const img = new Image();
  img.onload = async () => {
    if (S.imageId !== id) return;                 // another image was opened meanwhile
    S.img = img;
    S.openedAt = Date.now();
    ev("image_open", { width: img.width, height: img.height });
    fit();
    await loadAnnotations();
    // The models take turns on the server (one at a time is faster than side by
    // side on a CPU). Suggestions are asked for first: accepting them is usually
    // the first thing done on a photo; the outline model's encode queues behind.
    if (S.mode === "assisted" && S.det.auto) suggest("open");
    aiPrepare();                                  // embed now, so the first AI click is quick
  };
  img.onerror = () => toast("could not load the image", true);
  img.src = imgUrl(id);
  renderImageList();
}

function stepImage(step) {
  if (!S.images.length) return;
  const i = S.images.findIndex(x => x.id === S.imageId);
  openImage(S.images[(i + step + S.images.length) % S.images.length].id);
}

// ---- adding photos: single files, whole folders (subfolders too), or a drop of both

const IMG_EXT = /\.(jpe?g|png|webp|bmp|gif|tiff?)$/i;
const isImage = f => (f.type && f.type.startsWith("image/")) || IMG_EXT.test(f.name);
const BATCH = 12;                 // files per request: a big folder goes up in steps, with progress

// A dropped folder arrives as a directory entry: walk it, subfolders included.
// readEntries() hands back at most ~100 entries per call, so call until empty.
async function filesFromEntry(entry, path = "") {
  if (entry.isFile) {
    const f = await new Promise((ok, no) => entry.file(ok, no));
    return [{ file: f, name: path + f.name }];
  }
  if (!entry.isDirectory) return [];
  const reader = entry.createReader(), out = [];
  for (;;) {
    const batch = await new Promise((ok, no) => reader.readEntries(ok, no));
    if (!batch.length) break;
    for (const e of batch) out.push(...await filesFromEntry(e, path + entry.name + "/"));
  }
  return out;
}

async function filesFromDrop(dt) {
  const entries = [...(dt.items || [])].map(it => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  if (!entries.length) return [...dt.files].map(f => ({ file: f, name: f.name }));
  const all = [];
  for (const e of entries) all.push(...await filesFromEntry(e));
  return all;
}

function progress(done, total, label) {
  const box = $("upProg");
  if (total === null) { box.classList.remove("show"); return; }
  $("upText").textContent = `${label} ${done} / ${total}`;
  $("upBar").style.width = `${Math.round(100 * done / Math.max(total, 1))}%`;
  box.classList.add("show");
}

// items: [{file, name}], where name may carry the folder path ("trip/day1/a.jpg").
async function upload(items, how = "files") {
  items = [...items].map(it => it.file ? it : { file: it, name: it.webkitRelativePath || it.name });
  const skipped = items.filter(it => !isImage(it.file)).length;
  items = items.filter(it => isImage(it.file));
  if (!items.length) { toast(skipped ? `no photos found (${skipped} other file${skipped > 1 ? "s" : ""} skipped)` : "no photos found", true); return; }
  ev("upload_start", { how, n: items.length, skipped });
  let added = 0, rejected = [];
  const firstNew = [];
  progress(0, items.length, "Adding photos");
  for (let k = 0; k < items.length; k += BATCH) {
    const form = new FormData();
    items.slice(k, k + BATCH).forEach(it => form.append("files", it.file, it.name));
    try {
      const res = await fetch("/api/images", { method: "POST", body: form, headers: projHeaders() });
      const r = await res.json();
      if (!res.ok) throw new Error(r.detail || res.statusText);
      S.images.push(...r.added.map(i => ({ ...i, n_annotations: 0 })));
      if (r.added.length && !firstNew.length) firstNew.push(r.added[0].id);
      added += r.added.length; rejected.push(...r.rejected);
      renderImageList();
    } catch (err) {
      progress(0, null);
      toast(`adding photos stopped after ${added}: ${err.message}`, true, 5000);
      return;
    }
    progress(Math.min(k + BATCH, items.length), items.length, "Adding photos");
  }
  setTimeout(() => progress(0, null), 600);
  const extra = [rejected.length ? `${rejected.length} could not be read` : "",
                 skipped ? `${skipped} non-photo file${skipped > 1 ? "s" : ""} skipped` : ""].filter(Boolean).join(", ");
  toast(`${added} photo${added === 1 ? "" : "s"} added${extra ? ` · ${extra}` : ""}`, !!rejected.length, 3500);
  if (firstNew.length && !S.imageId) openImage(firstNew[0]);
}

["fileInp", "fileInp2"].forEach(id => $(id).onchange = e => { upload(e.target.files, "files"); e.target.value = ""; });
["dirInp", "dirInp2"].forEach(id => $(id).onchange = e => { upload(e.target.files, "folder"); e.target.value = ""; });

// Dragging files over the window shows the drop overlay; a counter, because
// dragenter/dragleave fire for every child element crossed.
let dragDepth = 0;
const dragHasFiles = e => [...(e.dataTransfer && e.dataTransfer.types || [])].includes("Files");
window.addEventListener("dragenter", e => { if (!dragHasFiles(e)) return; dragDepth++; document.body.classList.add("dragover"); });
window.addEventListener("dragover", e => { e.preventDefault(); });
window.addEventListener("dragleave", e => { if (!dragHasFiles(e)) return; if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragover"); } });
window.addEventListener("drop", async e => {
  e.preventDefault(); dragDepth = 0; document.body.classList.remove("dragover");
  if (atHome()) { toast("open or create a project first, then drop photos into it", true, 3500); return; }
  upload(await filesFromDrop(e.dataTransfer), "drop");
});

// ---------------------------------------------------------------- export dialog
//
// The user ticks the formats they need; the server builds one zip with just
// those. The choice is remembered (in this browser only) for the next export.

const EXPORT_FORMATS = [
  { key: "coco",     name: "COCO JSON",         what: "Boxes and outlines",   use: "Detectron2, MMDetection, pycocotools" },
  { key: "yolo_det", name: "YOLO detection",    what: "Boxes",                use: "Train Ultralytics YOLO detectors" },
  { key: "yolo_seg", name: "YOLO segmentation", what: "Outlines only",        use: "Train YOLO segmentation models" },
  { key: "voc",      name: "Pascal VOC XML",    what: "Boxes",                use: "TensorFlow Object Detection, older detectors" },
  { key: "masks",    name: "PNG masks",         what: "Outlines only",        use: "Semantic segmentation: U-Net, DeepLab" },
  { key: "csv",      name: "CSV table",         what: "Boxes and outlines",   use: "Spreadsheets and quick analysis" },
  { key: "preview",  name: "Photos with labels drawn", what: "For viewing, not training", use: "Check labels at a glance, share, put in a report", view: true },
];
const EXPORT_PREF = "kontur.export";

function loadExportPref() {
  try { return JSON.parse(localStorage.getItem(EXPORT_PREF)) || null; } catch (_) { return null; }
}
function saveExportPref(p) {
  try { localStorage.setItem(EXPORT_PREF, JSON.stringify(p)); } catch (_) {}
}

function exportChoice() {
  return {
    formats: EXPORT_FORMATS.map(f => f.key).filter(k => $(`ex_${k}`).checked),
    images: $("exImages").checked,
    only_labelled: $("exOnlyLab").checked,
  };
}

function refreshExport() {
  const c = exportChoice();
  const labelled = S.images.filter(i => i.n_annotations).length;
  const nImg = c.only_labelled ? labelled : S.images.length;
  const nLab = S.images.reduce((a, i) => a + (i.n_annotations || 0), 0);
  $("exportSummary").textContent = `${nImg} photo${nImg === 1 ? "" : "s"} · ${nLab} label${nLab === 1 ? "" : "s"} · ${S.classes.length} classes`;
  $("exGo").disabled = !c.formats.length || !nImg;
  const notes = [];
  if (!c.formats.length) notes.push("Tick at least one format.");
  else if (!nImg) notes.push(S.images.length ? "No photo has labels yet." : "This project has no photos yet.");
  if (!c.images && c.formats.some(k => k.startsWith("yolo"))) notes.push("YOLO datasets train only with the photos next to the labels.");
  if (c.formats.some(k => k === "yolo_seg" || k === "masks")) notes.push("Outline formats skip box labels: a box has no outline.");
  if (c.formats.length === 1 && c.formats[0] === "preview") notes.push("Drawn-on photos are for looking at; add a label format to train a model.");
  $("exNote").textContent = notes.join(" ");
  $("exGo").textContent = c.formats.length === 1 ? `Download ${EXPORT_FORMATS.find(f => f.key === c.formats[0]).name}` : `Download zip (${c.formats.length} formats)`;
  document.querySelectorAll("#exFormats .exf").forEach(el => el.classList.toggle("on", el.querySelector("input").checked));
}

function openExport() {
  if (!S.images.length) { toast("add photos first, then export their labels", true); return; }
  const pref = loadExportPref() || { formats: ["coco", "yolo_det"], images: true, only_labelled: false };
  $("exFormats").innerHTML = EXPORT_FORMATS.map((f, i) => `
    <label class="exf${f.view ? " view" : ""}" style="--i:${i}">
      <input type="checkbox" id="ex_${f.key}" ${pref.formats.includes(f.key) ? "checked" : ""}>
      <span class="exf-name">${f.name}</span>
      <span class="exf-what">${f.what}</span>
      <span class="exf-use">${f.use}</span>
    </label>`).join("");
  $("exImages").checked = pref.images !== false;
  $("exOnlyLab").checked = !!pref.only_labelled;
  refreshExport();
  $("exportDlg").showModal();
  ev("export_open");
}

$("exportBtn").onclick = e => { e.currentTarget.blur(); openExport(); };
$("exportForm").addEventListener("change", refreshExport);
$("exAll").onclick = () => {
  const all = EXPORT_FORMATS.every(f => $(`ex_${f.key}`).checked);
  EXPORT_FORMATS.forEach(f => $(`ex_${f.key}`).checked = !all);
  refreshExport();
};
$("exCancel").onclick = () => $("exportDlg").close();
$("exportForm").addEventListener("submit", e => {
  e.preventDefault();
  const c = exportChoice();
  if (!c.formats.length) return;
  saveExportPref(c);
  ev("export", c);
  // a plain link click downloads the zip without leaving the page
  const a = document.createElement("a");
  a.href = `/api/export?formats=${c.formats.join(",")}&images=${c.images ? 1 : 0}&only_labelled=${c.only_labelled ? 1 : 0}`;
  a.download = "";
  document.body.appendChild(a); a.click(); a.remove();
  $("exportDlg").close();
  toast("building the export: the download starts in a moment", false, 3000);
});

window.addEventListener("resize", () => { resizeCanvas(); });

// ---------------------------------------------------------------- projects and the home page
//
// Two views in one page, each with its own address, so Back works:
//   #/        the home page: every project as a card, plus "New project"
//   #/p/<id>  the workspace for one project
// A new project goes: name -> class picker -> add photos -> labelling.

const atHome = () => document.body.classList.contains("at-home");

// Forget everything about the project on screen (before going home or switching).
function resetWorkspace() {
  if (S.draft) cancelDraft();
  if (S.proposal) discardProposal();
  clearSugs();
  leaveImage();
  if ($("picker").open) $("picker").close();
  Object.assign(S, { imageId: null, img: null, anns: [], selected: null, classes: [], images: [],
                     classId: null, coverage: {}, openedAt: 0, ai: "off", aiNote: "", cursor: null });
  renderImageList(); renderAnnList(); renderSugs(); draw();
}

async function showHome() {
  if (S.projectId !== null) {
    resetWorkspace();
    ev("project_leave", { project: S.projectId });
    await flush();                                 // the old project's events go to its own log
    S.projectId = null; S.project = null;
  }
  // also on first load: the server reopens the last project at start, for the
  // models' warm-up; the home page closes it so nothing is logged into it
  try { await api("POST", "/api/projects/close"); } catch (_) {}
  document.body.classList.add("at-home");
  document.title = "Projects · Kontur";
  await renderHome();
}

async function enterProject(pid) {
  if (S.projectId === pid && !atHome()) return;
  if (S.projectId !== null) { resetWorkspace(); await flush(); }
  let st;
  try {
    st = await api("POST", `/api/projects/${pid}/open`);
  } catch (err) {
    toast("could not open the project: " + err.message, true, 4000);
    location.hash = "#/";
    return;
  }
  S.projectId = pid; S.project = st.project;
  S.classes = st.classes; S.images = st.images;
  S.classId = S.classes[0] ? S.classes[0].id : null;
  document.body.classList.remove("at-home");
  $("projName").textContent = st.project.name;
  document.title = `${st.project.name} · Kontur`;
  ev("project_open", { project: pid, n_images: S.images.length, n_classes: S.classes.length });
  resizeCanvas(); fit();
  applyMode();
  await refreshCoverage();
  renderImageList(); renderAnnList(); renderSugs(); draw();
  if (S.images.length) openImage(S.images[0].id);
  if (!S.classes.length) openPicker("first_run");      // step 2: decide what to label before anything else
}

function route() {
  const m = location.hash.match(/^#\/p\/(\d+)/);
  return m ? enterProject(+m[1]) : showHome();
}
window.addEventListener("hashchange", route);

// ---- the home page

function ago(ts) {
  if (!ts) return "never opened";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "opened just now";
  if (s < 3600) return `opened ${Math.round(s / 60)} min ago`;
  if (s < 86400) return `opened ${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d < 30 ? `opened ${d} day${d > 1 ? "s" : ""} ago` : `opened ${new Date(ts * 1000).toLocaleDateString()}`;
}

function projectCard(p, n) {
  const pct = p.n_images ? Math.round(100 * p.n_labelled / p.n_images) : 0;
  const cls = p.classes.slice(0, 5).map((c, i) => `<span><i style="background:${p.colours[i]}"></i>${esc(c)}</span>`).join("") +
              (p.classes.length > 5 ? `<span>+${p.classes.length - 5}</span>` : "") +
              (!p.classes.length ? `<span class="warn">no classes chosen yet</span>` : "");
  // a contact sheet: up to four of the project's photos
  const t = p.thumbs || [];
  const ph = t.length
    ? `<div class="mosaic m${t.length}">${t.map(id => `<img src="/api/projects/${p.id}/thumb/${id}" alt="" loading="lazy">`).join("")}</div>`
    : `<span class="none">no photos yet</span>`;
  return `
    <article class="proj" tabindex="0" data-id="${p.id}" style="--i:${n}" aria-label="Open project ${esc(p.name)}">
      <svg class="ants" aria-hidden="true"><rect x="1" y="1" rx="11"/></svg>
      <div class="ph">${ph}
        <div class="ph-acts">
          <button type="button" class="icon" data-ren="${p.id}" title="Rename this project" aria-label="Rename ${esc(p.name)}">✎</button>
          <button type="button" class="icon del" data-del="${p.id}" title="Delete this project (moved to the trash folder)" aria-label="Delete ${esc(p.name)}"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M6.5 4V2.5h3V4M4 4l.7 9.5h6.6L12 4M6.8 6.5v4.8M9.2 6.5v4.8"/></svg></button>
        </div>
        ${pct === 100 ? `<span class="done">all labelled</span>` : ""}
      </div>
      <div class="bd">
        <div class="nm">${esc(p.name)}</div>
        <div class="meta"><b>${p.n_labelled}</b>/${p.n_images} photos labelled · <b>${p.n_annotations}</b> labels</div>
        <div class="bar" title="${pct}% of photos have at least one label"><i style="width:${pct}%"></i></div>
        <div class="cls">${cls}</div>
      </div>
      <div class="ft"><span class="when">${ago(p.last_opened)}</span><span class="open">Open →</span></div>
    </article>`;
}

let homeProjects = [];
async function renderHome() {
  try { homeProjects = (await api("GET", "/api/projects")).projects; }
  catch (err) { toast("could not load projects: " + err.message, true, 4000); homeProjects = []; }
  const sum = k => homeProjects.reduce((a, p) => a + p[k], 0);
  $("homeStats").textContent = homeProjects.length
    ? `${homeProjects.length} project${homeProjects.length > 1 ? "s" : ""} · ${sum("n_images")} photos · ${sum("n_annotations")} labels`
    : "";
  $("projGrid").innerHTML = `
    <button type="button" class="proj new" id="newProjCard" style="--i:0">
      <span class="plus" aria-hidden="true">+</span><b>New project</b><span>name it, choose classes, add photos</span>
    </button>` + homeProjects.map((p, n) => projectCard(p, n + 1)).join("");
  sizeAnts();
}

// The marching-ants border on a hovered card is an SVG rect: size it to the card.
function sizeAnts() {
  document.querySelectorAll(".proj .ants rect").forEach(r => {
    const c = r.closest(".proj");
    r.setAttribute("width", Math.max(0, c.offsetWidth - 2));
    r.setAttribute("height", Math.max(0, c.offsetHeight - 2));
  });
}
window.addEventListener("resize", () => { if (atHome()) sizeAnts(); });

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

$("projGrid").addEventListener("click", async e => {
  if (e.target.closest("#newProjCard")) { newProjectDialog(); return; }
  const ren = e.target.dataset.ren, del = e.target.dataset.del;
  if (ren) { await renameProject(+ren); return; }
  if (del) { await deleteProject(+del); return; }
  const card = e.target.closest(".proj[data-id]");
  if (card) location.hash = `#/p/${card.dataset.id}`;
});
$("projGrid").addEventListener("keydown", e => {
  const card = e.target.closest(".proj[data-id]");
  if (card && e.target === card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); location.hash = `#/p/${card.dataset.id}`; }
});

async function renameProject(pid) {
  const p = homeProjects.find(x => x.id === pid);
  const name = prompt("Rename the project to:", p ? p.name : "");
  if (!name || (p && name.trim() === p.name)) return;
  try { await api("PUT", `/api/projects/${pid}`, { name }); await renderHome(); }
  catch (err) { toast(err.message, true, 4000); }
}

async function deleteProject(pid) {
  const p = homeProjects.find(x => x.id === pid);
  if (!p) return;
  const what = `${p.n_images} photo${p.n_images === 1 ? "" : "s"} and ${p.n_annotations} label${p.n_annotations === 1 ? "" : "s"}`;
  const note = p.legacy
    ? "\n\nThis is the project from before projects existed: its database, photos and log are moved out of the data folder."
    : "";
  if (!confirm(`Delete "${p.name}" (${what})?${note}\n\nIt is moved to the data folder's trash, not erased, so it can be restored by hand.`)) return;
  const card = document.querySelector(`.proj[data-id="${pid}"]`);
  if (card) { card.classList.add("leaving"); await new Promise(r => setTimeout(r, reduceMotion() ? 0 : 280)); }
  try {
    const r = await api("DELETE", `/api/projects/${pid}`);
    toast(`"${p.name}" moved to ${r.moved_to}`, false, 4000);
    await renderHome();
  } catch (err) { toast(err.message, true, 4000); await renderHome(); }
}

// ---- step 1 of a new project: its name

function newProjectDialog() {
  $("newProjInp").value = ""; $("newProjErr").textContent = "";
  $("newProj").showModal();
  setTimeout(() => $("newProjInp").focus(), 30);
}
["newProjBtn", "newProjBtn2"].forEach(id => $(id).onclick = e => { e.currentTarget.blur(); newProjectDialog(); });
$("newProjCancel").onclick = () => $("newProj").close();
$("newProjForm").addEventListener("submit", async e => {
  e.preventDefault();
  const name = $("newProjInp").value.trim();
  if (!name) { $("newProjErr").textContent = "Give the project a name."; return; }
  try {
    const p = await api("POST", "/api/projects", { name });
    $("newProj").close();
    location.hash = `#/p/${p.id}`;                 // -> enterProject -> the class picker opens (step 2)
  } catch (err) { $("newProjErr").textContent = err.message; }
});

// ---------------------------------------------------------------- start

(function boot() {
  ev("session_start", { screen: [screen.width, screen.height], dpr: dpr(), ua: navigator.userAgent });
  setTool("box");
  loadDetectors();
  route();                                         // #/ = home, #/p/<id> = a project
})();
