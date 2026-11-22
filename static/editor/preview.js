// The preview: libass (the subtitle engine ffmpeg burns with) running in the browser via
// JASSUB, drawing the exact ASS file the export uses, so the preview is the export.
// On top sits a click layer built from where the server says each word landed:
// click a word to select it, drag a caption or a super to move it, pull a corner to resize.
'use strict';

const PV = {jas: null, ready: false, failed: false, boxes: [], win: null, seq: 0, timer: 0, last: 0, inflight: false,
            again: false, hitKey: '', drag: null};
const VENDOR = '/static/vendor/jassub/';
const EMPTY_ASS = '[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n';

async function initPreview(){
  if (PV.jas || PV.failed) return;
  if (!window.JASSUB || !window.WebAssembly){ PV.failed = true; return; }
  try {
    const fonts = await (await fetch('/fontmap')).json();
    PV.fontmap = fonts;
    // Drawn on our own canvas and driven by the timeline clock (not one <video>), so it works
    // the same for one file or many clips.
    PV.jas = new JASSUB({
      canvas: $('assCanvas'), onDemandRender: false, targetFps: 60, subContent: EMPTY_ASS,
      workerUrl: VENDOR + 'jassub-worker.js', wasmUrl: VENDOR + 'jassub-worker.wasm',
      modernWasmUrl: VENDOR + 'jassub-worker-modern.wasm', availableFonts: fonts, fallbackFont: 'poppins semibold',
    });
    PV.ready = true;
    resizeAss();
    new ResizeObserver(resizeAss).observe(player);
    for (const ev of ['play', 'pause', 'seeked', 'ratechange']) clock.addEventListener(ev, assTime);
    assTime();
    $('capLayer').replaceChildren(); $('capFrame').hidden = true;
    schedulePreview(true);
  } catch (e){
    console.warn('libass preview unavailable, using the HTML preview', e);
    PV.failed = true;
  }
}

// Fonts are handed to libass before the subtitles that use them, so it never draws a stand-in.
const FONTS_LOADED = new Map();
async function fontsFor(ass){
  if (!PV.fontmap) return;
  const names = new Set([...ass.matchAll(/\\fn([^\\}]+)/g)].map(m => m[1].trim().toLowerCase()));
  names.add('poppins semibold');
  const jobs = [];
  for (const n of names){
    const url = PV.fontmap[n]; if (!url || FONTS_LOADED.has(url)) continue;
    const p = fetch(url).then(r => r.ok ? r.arrayBuffer() : null).then(buf => { if (buf) PV.jas.addFont(new Uint8Array(buf)); })
                        .catch(() => FONTS_LOADED.delete(url));
    FONTS_LOADED.set(url, p); jobs.push(p);
  }
  await Promise.all([...FONTS_LOADED.values()]);
}

// The canvas matches the player's size (sharp on retina); libass scales the script to it.
function resizeAss(){
  if (!PV.jas || !PJ.doc) return;
  const r = devicePixelRatio || 1, w = Math.max(2, Math.round(player.clientWidth * r)), h = Math.max(2, Math.round(player.clientHeight * r));
  PV.jas._videoWidth = PJ.doc.canvas.w; PV.jas._videoHeight = PJ.doc.canvas.h;   // no <video>: tell it the frame size
  PV.jas.resize(w, h, 0, 0);
  assTime();
}
function assTime(){ if (PV.jas) PV.jas.setCurrentTime(clock.paused, clock.currentTime, clock.playbackRate); }

// What the server needs to draw the stretch around the playhead.
function previewWindow(){
  const d = dur(), t = clock.currentTime || 0;
  return d <= 300 ? [0, d + 5] : [Math.max(0, t - 30), t + 90];
}
function sliceDoc(win){
  const d = currentDoc(); if (!d) return null;
  const inWin = x => x.t1 >= win[0] - 1 && x.t0 <= win[1] + 1;
  const shown = g => g instanceof Cue && !isNaN(g.start) && g.end >= win[0] - 1 && g.start <= win[1] + 1;
  return {...d, tracks: d.tracks.map(t =>
    t.kind === 'subtitle' ? {...t, groups: t.groups.filter(shown)} :
    t.kind === 'super' ? {...t, supers: t.supers.filter(inWin)} : t)};
}

// Ask for a fresh file soon (debounced; while dragging, at most ~12 times a second).
function schedulePreview(now){
  if (!PV.ready || !PJ.doc) { drawHits(true); return; }
  clearTimeout(PV.timer);
  const wait = now ? 0 : PV.drag ? Math.max(0, 80 - (performance.now() - PV.last)) : 70;
  PV.timer = setTimeout(refreshPreview, wait);
}
async function refreshPreview(){
  if (PV.inflight){ PV.again = true; return; }
  const win = previewWindow(), body = sliceDoc(win); if (!body) return;
  PV.inflight = true; PV.last = performance.now();
  const seq = ++PV.seq;
  try {
    const r = await fetch(`/projects/${PJ.doc.id}/ass`, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({project: body, window: win})});
    if (r.ok && seq === PV.seq){
      const d = await r.json();
      await fontsFor(d.ass);                       // give libass every font first: no fallback flash
      if (seq !== PV.seq){ PV.inflight = false; if (PV.again){ PV.again = false; schedulePreview(true); } return; }
      PV.jas.setTrack(d.ass);
      PV.boxes = d.boxes || []; PV.win = win;
      drawHits(true);
    }
  } catch {}
  PV.inflight = false;
  if (PV.again){ PV.again = false; schedulePreview(true); }
}
// Called every frame while playing: fetch the next stretch before the playhead gets there.
function previewTick(){
  if (!PV.ready || !PV.win) return;
  const t = clock.currentTime;
  if (t < PV.win[0] || t > PV.win[1] - 20) schedulePreview(true);
  if (!clock.paused && performance.now() - (PV.synced || 0) > 1000){ PV.synced = performance.now(); assTime(); }
  drawHits();
}

// ---------- the click / drag layer ----------
const kOf = () => player.clientWidth / (PJ.doc ? PJ.doc.canvas.w : 1080);
function activeBoxes(){
  const t = clock.currentTime;
  return PV.boxes.filter(b => t >= b.t0 && t < b.t1);
}
function drawHits(force){
  const layer = $('hitLayer');
  if (!layer || $('editor').hidden || !PV.ready){ if (layer) layer.replaceChildren(); return; }
  const act = activeBoxes(), key = act.map(b => b.id + b.t0).join('|') + '|' + [...(S.selWords || [])].join(',') + '|' + S.sel + '|' + S.selSuper;
  if (key === PV.hitKey && !force) return;
  PV.hitKey = key;
  const k = kOf(), frag = document.createDocumentFragment();
  for (const b of act){
    const [x, y, w, h] = b.box, pad = 6;
    const page = document.createElement('div');
    const selected = b.kind === 'super' ? S.selSuper === b.id : S.cues[S.sel]?.id === b.id;
    page.className = 'hit-page ' + b.kind + (selected ? ' on' : '');
    page.dataset.kind = b.kind; page.dataset.id = b.id;
    if (unsafe(b.box)){ page.classList.add('unsafe'); page.title = 'Under the Reels / Shorts buttons on phones: may be covered'; }
    Object.assign(page.style, {left: (x * k - pad) + 'px', top: (y * k - pad) + 'px', width: (w * k + pad * 2) + 'px', height: (h * k + pad * 2) + 'px'});
    for (const wd of b.words){
      const s = document.createElement('span'), wid = b.wids[wd.i];
      s.className = 'hit-word' + (S.selWords?.has(wid) ? ' on' : '');
      s.dataset.wid = wid;
      Object.assign(s.style, {left: ((wd.x - x) * k + pad) + 'px', top: ((wd.y - y) * k + pad) + 'px', width: (wd.w * k) + 'px', height: (wd.h * k) + 'px'});
      page.append(s);
    }
    ['nw', 'ne', 'sw', 'se'].forEach(c => { const i = document.createElement('i'); i.dataset.h = c; page.append(i); });
    frag.append(page);
  }
  layer.replaceChildren(frag);
}

// Vertical videos: Reels and Shorts cover the top bar, the caption/buttons strip at the bottom
// and the like/comment column on the right. We warn; we never block.
function unsafe([x, y, w, h]){
  const c = PJ.doc && PJ.doc.canvas; if (!c || c.h <= c.w) return false;
  const W = c.w, H = c.h;
  return y < H * .1 || y + h > H * .83 || (x + w > W * .85 && y + h > H * .42);
}
function placeOf(kind, id, line){
  if (kind === 'super'){ const sp = S.supers.find(s => s.id === id); return sp && sp.place; }
  if (line){ const c = S.cues.find(c => c.id === id); if (c && c.place) return c.place; }
  return CAP.x != null ? {x: CAP.x, y: CAP.y} : null;
}
function initHits(){
  const layer = $('hitLayer');
  layer.addEventListener('pointerdown', e => {
    const page = e.target.closest('.hit-page'); if (!page || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    const kind = page.dataset.kind, id = page.dataset.id, handle = e.target.closest('i[data-h]');
    const cue = kind === 'group' ? S.cues.find(c => c.id === id) : null;
    const line = kind === 'group' && (e.shiftKey || (cue && cue.place) || INS.scope === 'line' && S.cues[S.sel]?.id === id);
    const pr = player.getBoundingClientRect(), r = page.getBoundingClientRect();
    const centre = {x: (r.left + r.width / 2 - pr.left) / pr.width, y: (r.top + r.height / 2 - pr.top) / pr.height};
    PV.drag = {kind, id, line, handle: !!handle, word: e.target.closest('.hit-word')?.dataset.wid, x0: e.clientX, y0: e.clientY,
               start: placeOf(kind, id, line) || centre, centre, moved: false, before: snapshot(), page,
               dist: Math.hypot(e.clientX - (r.left + r.width / 2), e.clientY - (r.top + r.height / 2)) || 1,
               mid: [r.left + r.width / 2, r.top + r.height / 2], size0: sizeOf(kind, id, line)};
    layer.setPointerCapture(e.pointerId);
  });
  layer.addEventListener('pointermove', e => {
    const d = PV.drag; if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 4) return;
    if (!d.moved){ d.moved = true; player.classList.add('placing'); }
    const pr = player.getBoundingClientRect();
    if (d.handle){
      const f = Math.hypot(e.clientX - d.mid[0], e.clientY - d.mid[1]) / d.dist;
      setSize(d.kind, d.id, d.line, Math.min(Math.max(d.size0 * f, .3), 3));
      $('capTip').textContent = Math.round(sizeOf(d.kind, d.id, d.line) * 100) + '%';
    } else {
      let x = d.start.x + (e.clientX - d.x0) / pr.width, y = d.start.y + (e.clientY - d.y0) / pr.height;
      const sx = !e.altKey && Math.abs(x - .5) < .02, sy = !e.altKey && Math.abs(y - .5) < .02;
      if (sx) x = .5; if (sy) y = .5;
      $('guideV').hidden = !sx; $('guideH').hidden = !sy;
      setPlace(d.kind, d.id, d.line, {x: Math.min(Math.max(x, 0), 1), y: Math.min(Math.max(y, 0), 1)});
      // instant feedback: slide the frame now, libass catches up a moment later
      d.page.style.transform = `translate(${e.clientX - d.x0}px, ${e.clientY - d.y0}px)`;
      $('capTip').textContent = `${Math.round(x * 100)}% · ${Math.round(y * 100)}%`;
    }
    schedulePreview();
  });
  const end = () => {
    const d = PV.drag; if (!d) return;
    PV.drag = null; player.classList.remove('placing');
    $('guideV').hidden = $('guideH').hidden = true; $('capTip').textContent = '';
    if (d.moved){
      H.past.push(d.before); H.future = []; syncHist();
      if (d.kind === 'group' && !d.line) capChanged(); else edited();
      syncPlaceUI(); inspectorSync();
      schedulePreview(true);
      justDragged = true; setTimeout(() => justDragged = false, 0);
    } else if (d.kind === 'super'){
      selectSuper(d.id);
    } else {
      const i = S.cues.findIndex(c => c.id === d.id);
      if (d.word) selectWord(i, d.word, {shift: false, add: false});
      else select(i, false);
    }
  };
  layer.addEventListener('pointerup', end);
  layer.addEventListener('pointercancel', end);
  layer.addEventListener('dblclick', e => {
    const page = e.target.closest('.hit-page'); if (!page) return;
    if (page.dataset.kind === 'super'){ selectSuper(page.dataset.id); $('superText')?.focus(); }
    else { const i = S.cues.findIndex(c => c.id === page.dataset.id); if (i >= 0){ select(i, false); startEdit(i); } }
  });
  // clicking empty video plays/pauses (handled by the player); clear word selection too
  player.addEventListener('pointerdown', e => {
    if (!$('editor').hidden && !e.target.closest('.hit-page')){ if (S.selWords?.size || S.selSuper) clearSelection(); }
  });
}

function sizeOf(kind, id, line){
  if (kind === 'super'){ const sp = S.supers.find(s => s.id === id); return (sp && sp.o && sp.o.size) || 1; }
  if (line){ const c = S.cues.find(c => c.id === id); return (c && c.o && c.o.size) || 1; }
  return capScale();
}
function setSize(kind, id, line, v){
  v = +v.toFixed(3);
  if (kind === 'super'){ const sp = S.supers.find(s => s.id === id); sp.o = {...(sp.o || {}), size: v}; }
  else if (line){ const c = S.cues.find(c => c.id === id); c.o = {...(c.o || {}), size: v}; }
  else CAP.scale = v;
}
function setPlace(kind, id, line, p){
  p = {x: +p.x.toFixed(4), y: +p.y.toFixed(4)};
  if (kind === 'super'){ S.supers.find(s => s.id === id).place = p; }
  else if (line){ S.cues.find(c => c.id === id).place = p; }
  else { CAP.x = p.x; CAP.y = p.y; }
}
