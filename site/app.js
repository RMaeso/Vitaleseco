"use strict";

const NS = "http://www.w3.org/2000/svg";
const COLORS = ["var(--s1)", "var(--s2)"];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const state = { years: 10, data: null, charts: [] };

/* ---------------------------------------------------------------- Utilidades */
const nf = {};
function fmt(v, dec = 1) {
  if (v == null || Number.isNaN(v)) return "–";
  nf[dec] ??= new Intl.NumberFormat("es-ES", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  return nf[dec].format(v).replace("-", "−");
}
function signed(v, dec) {
  const r = Number(v.toFixed(dec)) || 0; // evita "−0,0"
  return (r > 0 ? "+" : "") + fmt(r, dec);
}

function periodNum(p) {
  if (p.includes("-Q")) { const [y, q] = p.split("-Q"); return +y + (q * 3 - 1.5) / 12; }
  const [y, m] = p.split("-");
  return m ? +y + (m - 0.5) / 12 : +y + 0.5;
}
function freqOf(p) { return p.includes("-Q") ? "Q" : p.length === 7 ? "M" : "A"; }
function periodLabel(p, long = false) {
  if (p.includes("-Q")) { const [y, q] = p.split("-Q"); return long ? `${q}.º trimestre ${y}` : `${q}T ${y}`; }
  const [y, m] = p.split("-");
  return m ? `${MONTHS[m - 1]} ${y}` : y;
}
const PREV = { M: "mes anterior", Q: "trimestre anterior", A: "año anterior" };

function unitSuffix(unit) { return unit === "%" ? "%" : unit ? unit.trim() : ""; }
function deltaUnit(unit) { return unit.trim() === "pb" ? "pb" : unit ? "pp" : ""; }

function el(tag, attrs = {}, ...kids) {
  const n = tag.startsWith("svg:") ? document.createElementNS(NS, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.setAttribute("class", v);
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const c of kids) if (c != null) n.append(c);
  return n;
}

function niceTicks(min, max, count = 5) {
  if (min === max) { min -= 1; max += 1; }
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => s >= raw);
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let t = lo; t <= hi + step / 2; t += step) ticks.push(+t.toFixed(10));
  return { ticks, lo, hi, step };
}

/* ------------------------------------------------------------------ Resumen */
function latest(series) {
  const d = series?.data;
  if (!d?.length) return null;
  const [p, v] = d[d.length - 1];
  const prev = d.length > 1 ? d[d.length - 2] : null;
  return { p, v, prev };
}

function headlineFacts(ind) {
  const [main, comp] = ind.series;
  const L = latest(main);
  if (!L) return null;
  const dec = ind.decimals ?? 1;
  const facts = { value: fmt(L.v, dec), unit: unitSuffix(ind.unit), period: periodLabel(L.p, true), delta: null, comp: null };
  if (L.prev) {
    const dv = L.v - L.prev[1];
    const du = deltaUnit(ind.unit);
    facts.delta = {
      text: `${signed(dv, dec)}${du ? " " + du : ""}`,
      dir: Math.abs(dv) < 10 ** -dec / 2 ? "" : dv > 0 ? "up" : "down",
      vs: PREV[freqOf(L.p)],
    };
  }
  if (comp) {
    const C = latest(comp);
    if (C) {
      const same = comp.data.find(([p]) => p === L.p);
      const use = same ? { p: L.p, v: same[1] } : C;
      facts.comp = `${comp.label}: ${fmt(use.v, dec)}${unitSuffix(ind.unit) === "%" ? "%" : ""}${use.p !== L.p ? ` (${periodLabel(use.p)})` : ""}`;
    }
  }
  return facts;
}

function renderTiles(indicators) {
  const box = document.getElementById("tiles");
  box.replaceChildren();
  for (const ind of indicators.filter(i => i.headline)) {
    const f = headlineFacts(ind);
    if (!f) continue;
    box.append(el("a", { class: "tile", href: `#${ind.id}` },
      el("div", { class: "tile-label", text: ind.headline_label || ind.title }),
      el("div", { class: "tile-value" }, f.value, f.unit ? el("small", { text: f.unit }) : null),
      el("div", { class: "tile-meta", text: [periodLabel(latest(ind.series[0]).p), f.delta ? `${f.delta.text}` : null].filter(Boolean).join(" · ") }),
    ));
  }
}

/* ------------------------------------------------------------------ Gráfico */
function drawChart(host, ind) {
  const W = Math.max(260, host.clientWidth), H = host.clientHeight || 210;
  const m = { t: 10, r: 46, b: 22, l: 38 };
  const all = ind.series.map(s => s.data.map(([p, v]) => ({ p, v, x: periodNum(p) })));
  const maxX = Math.max(...all.flat().map(d => d.x));
  const minX = state.years ? maxX - state.years : -Infinity;
  const vis = all.map(s => s.filter(d => d.x >= minX));
  const pts = vis.flat();
  if (!pts.length) { host.replaceChildren(el("p", { class: "period", text: "Sin datos en este periodo." })); return; }

  let lo = Math.min(...pts.map(d => d.v)), hi = Math.max(...pts.map(d => d.v));
  if (ind.zero_line) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  for (const ref of [ind.target, ind.baseline]) if (ref != null) { lo = Math.min(lo, ref); hi = Math.max(hi, ref); }
  const pad = (hi - lo) * 0.06 || 1;
  const Y = niceTicks(lo - (lo === 0 ? 0 : pad), hi + pad, H < 200 ? 4 : 5);
  const x0 = Math.min(...pts.map(d => d.x)), x1 = maxX;
  const sx = x => m.l + ((x - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = v => m.t + (1 - (v - Y.lo) / (Y.hi - Y.lo)) * (H - m.t - m.b);

  const svg = el("svg:svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${ind.title}: gráfico de líneas` });
  const dec = ind.decimals ?? 1;
  const tickDec = Y.step < 1 ? (Y.step < 0.1 ? 2 : 1) : 0;

  for (const t of Y.ticks) {
    svg.append(el("svg:line", { class: t === 0 && ind.zero_line ? "zero-line" : "grid-line", x1: m.l, x2: W - m.r, y1: sy(t), y2: sy(t) }));
    svg.append(el("svg:text", { x: m.l - 6, y: sy(t) + 3.5, "text-anchor": "end", text: fmt(t, tickDec) }));
  }
  const span = x1 - x0;
  const yStep = span > 16 ? 4 : span > 8 ? 2 : 1;
  for (let y = Math.ceil(x0); y <= x1; y++) {
    if (y % yStep) continue;
    const X = sx(y);
    if (X < m.l + 8 || X > W - m.r - 8) continue;
    svg.append(el("svg:line", { class: "grid-line", x1: X, x2: X, y1: H - m.b, y2: H - m.b + 4 }));
    svg.append(el("svg:text", { x: X, y: H - 6, "text-anchor": "middle", text: String(y) }));
  }
  for (const ref of [ind.target, ind.baseline]) {
    if (ref == null) continue;
    svg.append(el("svg:line", { class: "target-line", x1: m.l, x2: W - m.r, y1: sy(ref), y2: sy(ref) }));
  }

  // Líneas
  vis.forEach((s, i) => {
    if (!s.length) return;
    const d = s.map((p, j) => `${j ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.v).toFixed(1)}`).join("");
    svg.append(el("svg:path", { class: "series", d, stroke: COLORS[i] }));
  });

  // Etiquetas directas al final de cada línea, separadas si chocan.
  const ends = vis.map((s, i) => s.length ? { i, p: s[s.length - 1], y: sy(s[s.length - 1].v) } : null).filter(Boolean);
  const placed = [...ends].sort((a, b) => a.y - b.y);
  for (let k = 1; k < placed.length; k++) if (placed[k].y - placed[k - 1].y < 13) placed[k].y = placed[k - 1].y + 13;
  for (const e of placed) {
    svg.append(el("svg:circle", { class: "end-dot", cx: sx(e.p.x), cy: sy(e.p.v), r: 4, fill: COLORS[e.i] }));
    svg.append(el("svg:text", { class: "end-label", x: sx(e.p.x) + 7, y: e.y + 4, text: fmt(e.p.v, dec) }));
  }

  // Capa interactiva: cruz + tooltip con todas las series en esa fecha.
  const cross = el("svg:line", { class: "crosshair", y1: m.t, y2: H - m.b, visibility: "hidden" });
  const dots = vis.map((_, i) => el("svg:circle", { class: "hover-dot", r: 4, fill: COLORS[i], visibility: "hidden" }));
  svg.append(cross, ...dots);
  const xs = [...new Set(pts.map(d => d.x))].sort((a, b) => a - b);
  const tip = document.getElementById("tooltip");
  let idx = xs.length - 1;

  const show = (i, clientX, clientY) => {
    idx = Math.max(0, Math.min(xs.length - 1, i));
    const X = xs[idx];
    cross.setAttribute("x1", sx(X)); cross.setAttribute("x2", sx(X)); cross.setAttribute("visibility", "visible");
    const rows = [];
    let label = null;
    vis.forEach((s, k) => {
      const hit = s.find(d => Math.abs(d.x - X) < 1e-6);
      if (!hit) { dots[k].setAttribute("visibility", "hidden"); return; }
      label ??= periodLabel(hit.p, true);
      dots[k].setAttribute("cx", sx(hit.x)); dots[k].setAttribute("cy", sy(hit.v)); dots[k].setAttribute("visibility", "visible");
      rows.push(el("div", { class: "tt-row" }, el("i", { style: `border-color:${COLORS[k]}` }),
        el("b", { text: fmt(hit.v, dec) + (unitSuffix(ind.unit) === "%" ? "%" : "") }), el("span", { text: ind.series[k].label })));
    });
    tip.replaceChildren(el("div", { class: "tt-date", text: label || "" }), ...rows);
    tip.hidden = false;
    const r = host.getBoundingClientRect();
    const px = clientX ?? r.left + sx(X) * r.width / W;
    const py = clientY ?? r.top + 20;
    const tw = tip.offsetWidth;
    tip.style.left = `${Math.min(window.innerWidth - tw - 8, Math.max(8, px + 14 + tw > window.innerWidth ? px - tw - 14 : px + 14))}px`;
    tip.style.top = `${Math.max(8, py - 10)}px`;
  };
  const hide = () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.forEach(d => d.setAttribute("visibility", "hidden")); };
  const nearest = (clientX) => {
    const r = svg.getBoundingClientRect();
    const xv = x0 + ((clientX - r.left) * W / r.width - m.l) / (W - m.l - m.r) * (x1 - x0);
    let best = 0;
    for (let k = 1; k < xs.length; k++) if (Math.abs(xs[k] - xv) < Math.abs(xs[best] - xv)) best = k;
    return best;
  };
  svg.addEventListener("pointermove", e => show(nearest(e.clientX), e.clientX, e.clientY));
  svg.addEventListener("pointerleave", hide);
  host.tabIndex = 0;
  host.onfocus = () => show(idx);
  host.onblur = hide;
  host.onkeydown = e => {
    if (e.key === "ArrowLeft") { show(idx - 1); e.preventDefault(); }
    if (e.key === "ArrowRight") { show(idx + 1); e.preventDefault(); }
  };
  host.replaceChildren(svg);
}

/* ------------------------------------------------------------------ Tarjeta */
function renderCard(ind) {
  const card = el("article", { class: "card", id: ind.id });
  const stale = ind.series.some(s => s.status === "stale");
  card.append(el("h3", {}, ind.title, stale ? el("span", { class: "badge", title: "La última descarga falló; se muestra el último dato disponible.", text: "sin actualizar" }) : null));
  const f = headlineFacts(ind);
  if (!f) {
    card.append(el("p", { class: "period", text: "Este indicador todavía no tiene datos." }));
    return card;
  }
  card.append(el("div", { class: "headline" },
    el("span", { class: "big" }, f.value, f.unit ? el("small", { text: f.unit }) : null),
    el("span", { class: "period", text: `${ind.series[0].label} · ${f.period}` })));
  const facts = el("div", { class: "facts" });
  if (f.delta) facts.append(el("span", {}, el("span", { class: `delta ${f.delta.dir}`, text: f.delta.text }), ` vs ${f.delta.vs}`));
  if (f.comp) facts.append(el("span", { text: f.comp }));
  card.append(facts);

  if (ind.series.length > 1 || ind.target != null || ind.baseline != null) {
    const lg = el("div", { class: "legend" });
    ind.series.forEach((s, i) => lg.append(el("span", {}, el("i", { style: `border-color:${COLORS[i]}` }), s.label)));
    if (ind.target != null) lg.append(el("span", {}, el("i", { class: "dash" }), ind.id === "deficit" ? "Límite −3%" : "Objetivo BCE"));
    if (ind.baseline != null) lg.append(el("span", {}, el("i", { class: "dash" }), "Media histórica"));
    card.append(lg);
  }

  const host = el("div", { class: "chart" });
  card.append(host);
  state.charts.push({ host, ind });

  // Vista de tabla (accesible sin ratón): últimos 12 periodos.
  const periods = [...new Set(ind.series.flatMap(s => s.data.map(d => d[0])))].sort((a, b) => periodNum(b) - periodNum(a)).slice(0, 12);
  const maps = ind.series.map(s => new Map(s.data));
  const table = el("table", {},
    el("thead", {}, el("tr", {}, el("th", { text: "Periodo" }), ...ind.series.map(s => el("th", { text: s.label })))),
    el("tbody", {}, ...periods.map(p => el("tr", {}, el("td", { text: periodLabel(p) }),
      ...maps.map(mp => el("td", { text: mp.has(p) ? fmt(mp.get(p), ind.decimals ?? 1) : "–" }))))));
  card.append(el("details", {}, el("summary", { text: "Ver datos" }), table));

  const src = ind.series.find(s => s.url) || ind.series[0];
  const foot = el("div", { class: "card-foot" }, el("p", { text: ind.note || "" }));
  if (src?.url) foot.append(el("a", { href: src.url, target: "_blank", rel: "noopener", text: src.source?.startsWith("BCE") ? "BCE" : "Eurostat" }));
  card.append(foot);
  return card;
}

/* ------------------------------------------------------------------ Página */
function render() {
  const { data } = state;
  const content = document.getElementById("content");
  const nav = document.getElementById("sections-nav");
  content.replaceChildren(); nav.replaceChildren(); state.charts = [];
  const inds = data.sections.flatMap(s => s.indicators);
  renderTiles(inds);
  for (const sec of data.sections) {
    nav.append(el("a", { href: `#${sec.id}`, text: sec.title }));
    const grid = el("div", { class: "grid" }, ...sec.indicators.map(renderCard));
    content.append(el("section", { class: "section", id: sec.id },
      el("div", { class: "section-head" }, el("h2", { text: sec.title }), el("p", { text: sec.intro })), grid));
  }
  drawAll();

  const when = new Date(data.generated_at);
  document.getElementById("updated").textContent =
    `Datos actualizados el ${when.toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" })} a las ${when.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })}.`;

  const errBox = document.getElementById("errors");
  errBox.replaceChildren();
  if (data.errors?.length) {
    errBox.append(el("details", { class: "errors" },
      el("summary", { text: `${data.errors.length} series no se pudieron actualizar en la última descarga` }),
      el("ul", {}, ...data.errors.map(e => el("li", {}, el("strong", { text: `${e.indicator} · ${e.series}: ` }), el("code", { text: e.error }))))));
  }
}

function drawAll() { for (const c of state.charts) drawChart(c.host, c.ind); }

function setupRange() {
  const btns = document.querySelectorAll(".range button");
  btns.forEach(b => b.addEventListener("click", () => {
    btns.forEach(x => x.setAttribute("aria-checked", String(x === b)));
    state.years = +b.dataset.years;
    drawAll();
  }));
}

let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawAll, 120); });

async function init() {
  setupRange();
  try {
    const r = await fetch(`data/data.json?v=${new Date().toISOString().slice(0, 13)}`);
    if (!r.ok) throw new Error(r.status);
    state.data = await r.json();
    render();
  } catch (e) {
    document.getElementById("updated").textContent = "";
    document.getElementById("content").replaceChildren(el("div", { class: "notice",
      text: "Todavía no hay datos. Se generan automáticamente con la primera ejecución del flujo «Actualizar datos» en GitHub Actions." }));
  }
}
init();
