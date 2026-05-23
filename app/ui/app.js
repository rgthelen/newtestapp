// pi5-hailo-vision — single-page UI. No build step, no framework.
// Three views: live grid, semantic search, recent events list.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const tpl = (id) => document.getElementById(id).content.cloneNode(true);

const fmtTs = (t) => new Date(t * 1000).toLocaleString();
const fmtClock = (t) => new Date(t * 1000).toLocaleTimeString();

const router = {
  routes: { live: renderLive, search: renderSearch, events: renderEvents },
  current: null,
  go() {
    const hash = (location.hash || "#/live").replace(/^#\//, "");
    const route = this.routes[hash] || this.routes.live;
    if (this.current && this.current.cleanup) this.current.cleanup();
    $$(".nav-link").forEach((a) => a.classList.toggle("active", a.dataset.view === hash));
    this.current = route();
  },
};

window.addEventListener("hashchange", () => router.go());
window.addEventListener("DOMContentLoaded", () => {
  if (!location.hash) location.hash = "#/live";
  router.go();
  startGlobalStatus();
});

// ---------------------------------------------------------------------------
// Global status — heartbeat in header
// ---------------------------------------------------------------------------
async function startGlobalStatus() {
  const el = $("#globalStatus");
  const tick = async () => {
    try {
      const r = await fetch("/api/cameras");
      const data = await r.json();
      const ok = data.cameras.filter((c) => c.connected).length;
      el.textContent = `${ok}/${data.cameras.length} cams · v${await getVersion()}`;
    } catch {
      el.textContent = "offline";
    }
  };
  tick();
  setInterval(tick, 3000);
}

let _version = null;
async function getVersion() {
  if (_version) return _version;
  try {
    const r = await fetch("/api/health");
    const d = await r.json();
    _version = d.version;
  } catch { _version = "?"; }
  return _version;
}

// ---------------------------------------------------------------------------
// LIVE view
// ---------------------------------------------------------------------------
function renderLive() {
  const view = $("#view");
  view.innerHTML = "";
  view.appendChild(tpl("tpl-live"));

  const grid = view.querySelector('[data-bind="grid"]');
  const camCountEl = view.querySelector('[data-bind="camCount"]');
  const tiles = new Map();          // camera_id -> tile + state
  const sockets = new Map();        // camera_id -> WebSocket

  const cleanup = () => {
    sockets.forEach((ws) => ws.close());
    sockets.clear();
    tiles.forEach((t) => { if (t.img.src) URL.revokeObjectURL?.(t.img.src); });
    tiles.clear();
  };

  (async () => {
    let cams = [];
    try {
      const r = await fetch("/api/cameras");
      cams = (await r.json()).cameras;
    } catch (e) {
      grid.innerHTML = `<div class="empty">Couldn't reach API: ${e.message}</div>`;
      return;
    }
    camCountEl.textContent = `${cams.length} configured`;
    if (cams.length === 0) {
      grid.innerHTML = `<div class="empty">No cameras configured. Edit <code>~/.config/pi5-hailo-vision/cameras.yaml</code>.</div>`;
      return;
    }

    for (const cam of cams) {
      const tile = createTile(cam);
      grid.appendChild(tile.root);
      tiles.set(cam.id, tile);
      attachStreams(cam.id, tile, sockets);
    }
  })();

  return { cleanup };
}

function createTile(cam) {
  const frag = tpl("tpl-camera-tile");
  const root = frag.querySelector(".cam");
  const name = root.querySelector('[data-bind="name"]');
  const stats = root.querySelector('[data-bind="stats"]');
  const img = root.querySelector('[data-bind="img"]');
  const overlay = root.querySelector('[data-bind="overlay"]');
  name.textContent = cam.name;
  return { root, name, stats, img, overlay, lastBoxes: [] };
}

function attachStreams(cameraId, tile, sockets) {
  // MJPEG for video frames (cheap, browser handles decode).
  tile.img.src = `/api/cameras/${encodeURIComponent(cameraId)}/stream.mjpeg`;

  // WebSocket for structured detection/track data.
  const wsScheme = location.protocol === "https:" ? "wss" : "ws";
  const url = `${wsScheme}://${location.host}/ws/cameras/${encodeURIComponent(cameraId)}`;

  let ws;
  const connect = () => {
    ws = new WebSocket(url);
    sockets.set(cameraId, ws);
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type !== "state") return;
      drawOverlay(tile, msg);
      tile.stats.textContent =
        `${msg.fps_out.toFixed(1)} fps · ${msg.inference_ms.toFixed(0)}ms · ` +
        `${msg.tracks.length} tracks`;
    });
    ws.addEventListener("close", () => {
      // Reconnect with backoff. Tailscale sometimes idles connections.
      setTimeout(connect, 1000);
    });
  };
  connect();
}

function drawOverlay(tile, state) {
  const svg = tile.overlay;
  svg.setAttribute("viewBox", `0 0 ${state.width} ${state.height}`);
  svg.innerHTML = "";
  for (const t of state.tracks) {
    const [x1, y1, x2, y2] = t.bbox;
    const w = x2 - x1, h = y2 - y1;
    const color = trackColor(t.id);
    const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    r.setAttribute("x", x1); r.setAttribute("y", y1);
    r.setAttribute("width", w); r.setAttribute("height", h);
    r.setAttribute("stroke", color);
    svg.appendChild(r);
    const lbl = document.createElementNS("http://www.w3.org/2000/svg", "text");
    lbl.setAttribute("x", x1 + 4);
    lbl.setAttribute("y", y1 + 16);
    lbl.textContent = `#${t.id} ${t.cls_name} ${(t.confidence * 100).toFixed(0)}%`;
    svg.appendChild(lbl);
  }
}

function trackColor(id) {
  // Mirror the backend's per-ID color scheme (close enough).
  const r = (id * 9176 + 1) % 200 + 55;
  const g = (id * 6173 + 7) % 200 + 55;
  const b = (id * 3389 + 11) % 200 + 55;
  return `rgb(${r},${g},${b})`;
}

// ---------------------------------------------------------------------------
// SEARCH view
// ---------------------------------------------------------------------------
function renderSearch() {
  const view = $("#view");
  view.innerHTML = "";
  view.appendChild(tpl("tpl-search"));
  const form = view.querySelector('[data-bind="searchForm"]');
  const results = view.querySelector('[data-bind="results"]');

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = form.q.value.trim();
    if (!q) return;
    results.innerHTML = `<div class="empty">searching…</div>`;
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}&top_k=48`);
      const data = await r.json();
      renderResults(results, data.results, { showScore: true });
    } catch (e) {
      results.innerHTML = `<div class="empty">error: ${e.message}</div>`;
    }
  });

  return { cleanup: () => {} };
}

// ---------------------------------------------------------------------------
// EVENTS view
// ---------------------------------------------------------------------------
function renderEvents() {
  const view = $("#view");
  view.innerHTML = "";
  view.appendChild(tpl("tpl-events"));

  const camSel = view.querySelector('[data-bind="cameraFilter"]');
  const clsSel = view.querySelector('[data-bind="classFilter"]');
  const results = view.querySelector('[data-bind="results"]');

  (async () => {
    const r = await fetch("/api/cameras");
    const cams = (await r.json()).cameras;
    for (const c of cams) {
      const opt = document.createElement("option");
      opt.value = c.id; opt.textContent = c.name;
      camSel.appendChild(opt);
    }
    refresh();
  })();

  const refresh = async () => {
    const params = new URLSearchParams({ limit: "120" });
    if (camSel.value) params.set("camera_id", camSel.value);
    if (clsSel.value) params.set("cls", clsSel.value);
    results.innerHTML = `<div class="empty">loading…</div>`;
    try {
      const r = await fetch(`/api/events?${params}`);
      const data = await r.json();
      renderResults(results, data.events, { showScore: false });
    } catch (e) {
      results.innerHTML = `<div class="empty">error: ${e.message}</div>`;
    }
  };

  camSel.addEventListener("change", refresh);
  clsSel.addEventListener("change", refresh);
  const id = setInterval(refresh, 5000);
  return { cleanup: () => clearInterval(id) };
}

// ---------------------------------------------------------------------------
function renderResults(container, items, { showScore }) {
  if (!items || items.length === 0) {
    container.innerHTML = `<div class="empty">no results</div>`;
    return;
  }
  container.innerHTML = "";
  for (const ev of items) {
    const el = document.createElement("div");
    el.className = "result";
    el.innerHTML = `
      <img src="${ev.snapshot_url}" loading="lazy" alt="">
      <div class="meta">
        <span class="cls">${ev.cls_name}</span>
        <span>${fmtClock(ev.ts)}</span>
        ${showScore && ev.score != null ? `<span class="score">${ev.score.toFixed(2)}</span>` : ""}
      </div>`;
    el.addEventListener("click", () => openModal(ev));
    container.appendChild(el);
  }
}

function openModal(ev) {
  const modal = document.createElement("div");
  modal.className = "modal";
  modal.innerHTML = `
    <div class="close">×</div>
    <img src="${ev.snapshot_url}">`;
  modal.addEventListener("click", () => modal.remove());
  document.body.appendChild(modal);
}
