// The timeline: ruler, caption and text lanes, and a lane per video / audio track with its
// clips. Everything is drawn for the visible stretch only, once per frame at most.
'use strict';

const TL = {pps: 60, mode: store.get('tl_mode') || 'line', snap: true, drag: null, raf: 0, film: {}, peaks: {}, clipDrag: null};
const tlScroll = $('tlScroll'), tlContent = $('tlContent');
const dur = () => (typeof PJ !== 'undefined' && PJ.doc ? tlDuration() : 0) || S.duration || (S.cues.length ? S.cues[S.cues.length - 1].end + 1 : 10);
const ZMIN = () => Math.max(1, (tlScroll.clientWidth - 40) / Math.max(dur(), 1)), ZMAX = 600;
const zoomToSlider = pps => Math.round(1000 * Math.log(pps / ZMIN()) / Math.log(ZMAX / ZMIN()));
const sliderToZoom = v => ZMIN() * Math.pow(ZMAX / ZMIN(), v / 1000);
function contentWidth(){ return Math.ceil(dur() * TL.pps + Math.max(240, tlScroll.clientWidth * .5)); }
function tlLayout(reset){
  if ($('editor').hidden || !tlScroll.clientWidth) return;
  if (reset) TL.pps = tlScroll.clientWidth / Math.min(Math.max(dur(), 8), 24);   // about 24 seconds in view to start with
  TL.pps = Math.min(ZMAX, Math.max(ZMIN(), TL.pps));
  tlContent.style.width = contentWidth() + 'px';
  $('zoom').value = zoomToSlider(TL.pps);
  buildLanes(); tlRender();
}
function setZoom(pps, anchorT, anchorX){
  const old = TL.pps;
  TL.pps = Math.min(ZMAX, Math.max(ZMIN(), pps));
  if (anchorT == null){ anchorT = clock.currentTime; anchorX = anchorT * old - tlScroll.scrollLeft; }
  tlContent.style.width = contentWidth() + 'px';
  tlScroll.scrollLeft = anchorT * TL.pps - anchorX;
  $('zoom').value = zoomToSlider(TL.pps);
  tlRender();
}
$('zoom').oninput = () => setZoom(sliderToZoom(+$('zoom').value));
$('zoomIn').onclick = () => setZoom(TL.pps * 1.5);
$('zoomOut').onclick = () => setZoom(TL.pps / 1.5);
$('zoomFit').onclick = () => { setZoom(ZMIN(), 0, 0); tlScroll.scrollLeft = 0; };
tlScroll.addEventListener('wheel', e => {
  if (e.ctrlKey || e.metaKey){                         // pinch / ⌘-scroll zooms around the pointer
    e.preventDefault();
    const x = e.clientX - tlScroll.getBoundingClientRect().left, t = (tlScroll.scrollLeft + x) / TL.pps;
    setZoom(TL.pps * Math.exp(-e.deltaY * .0025), t, x);
  } else if (e.shiftKey || (Math.abs(e.deltaY) > Math.abs(e.deltaX) && $('tlBody').scrollHeight <= $('tlBody').clientHeight + 1)){
    e.preventDefault(); tlScroll.scrollLeft += e.deltaY;   // wheel scrolls along time (Shift: always)
  }
}, {passive: false});
tlScroll.addEventListener('scroll', () => tlRender(), {passive: true});
new ResizeObserver(() => { tlLayout(); updateOverlay(true); }).observe(tlScroll);
document.querySelectorAll('#tlMode button').forEach(b => b.onclick = () => {
  TL.mode = b.dataset.v; store.set('tl_mode', TL.mode); syncMode(); tlRender();
});
function syncMode(){ document.querySelectorAll('#tlMode button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === TL.mode))); }
syncMode();
$('snapBtn').onclick = () => { TL.snap = !TL.snap; $('snapBtn').setAttribute('aria-pressed', String(TL.snap)); };

function tlRender(){
  if (TL.raf || $('editor').hidden) return;
  TL.raf = requestAnimationFrame(() => {
    TL.raf = 0;
    if (tlContent.style.width !== contentWidth() + 'px') tlContent.style.width = contentWidth() + 'px';
    drawRuler(); drawBlocks(); superLaneRender(); drawLanes(); placeHead();
    if (typeof rangeRender === 'function') rangeRender();
  });
}
function view(){
  const w = tlScroll.clientWidth, x0 = tlScroll.scrollLeft;
  return {w, x0, t0: x0 / TL.pps, t1: (x0 + w) / TL.pps};
}
function canvasFor(cv, w, h){
  const r = devicePixelRatio || 1;
  if (cv.width !== Math.round(w * r) || cv.height !== Math.round(h * r)){
    cv.width = Math.round(w * r); cv.height = Math.round(h * r); cv.style.width = w + 'px'; cv.style.height = h + 'px';
  }
  const g = cv.getContext('2d'); g.setTransform(r, 0, 0, r, 0, 0); g.clearRect(0, 0, w, h);
  return g;
}
const STEPS = [.1, .2, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];
function drawRuler(){
  const v = view(), h = 26, g = canvasFor($('tlRuler'), v.w, h);
  const step = STEPS.find(s => s * TL.pps >= 80) || 1800, minor = step / 5;
  g.font = '500 10.5px ui-monospace, SFMono-Regular, Menlo, monospace'; g.textBaseline = 'middle';
  if (!isFinite(v.t0) || !isFinite(v.t1) || !(minor > 0)) return;
  for (let t = Math.floor(v.t0 / minor) * minor, n = 0; t <= v.t1 + minor && n < 4000; t += minor, n++){
    const x = Math.round(t * TL.pps - v.x0) + .5, major = Math.abs(t / step - Math.round(t / step)) < 1e-6;
    g.fillStyle = major ? 'rgba(255,255,255,.35)' : 'rgba(255,255,255,.12)';
    g.fillRect(x, major ? 14 : 19, 1, major ? 12 : 7);
    if (major && t >= 0){
      const m = Math.floor(t / 60), s = t % 60;
      g.fillStyle = 'rgba(255,255,255,.55)';
      g.fillText(step < 1 ? `${m}:${s.toFixed(1).padStart(4, '0')}` : `${m}:${String(Math.round(s)).padStart(2, '0')}`, x + 4, 8);
    }
  }
  const end = dur() * TL.pps - v.x0;               // the end of the video
  if (end > 0 && end < v.w){ g.fillStyle = 'rgba(255,255,255,.04)'; g.fillRect(end, 0, v.w - end, h); }
}

// ---------- caption blocks (line and word view) ----------
function drawBlocks(){
  const v = view(), lo = v.t0 - 2, hi = v.t1 + 2, box = $('tlCaps'), frag = document.createDocumentFragment();
  S.cues.forEach((c, i) => {
    if (c.end < lo || c.start > hi) return;
    if (TL.mode === 'word'){
      const words = c.text.split(/\s+/), times = wordTimesOf(c, words.length);
      words.forEach((w, k) => {
        const [s, e] = times[k];
        if (e < lo || s > hi) return;
        frag.append(block(i, s, e, w, 'blk word' + (i === S.sel ? ' sel' : ''), k));
      });
    } else frag.append(block(i, c.start, c.end, c.text, 'blk' + (i === S.sel ? ' sel' : '') + (i === S.current ? ' cur' : '')));
  });
  box.replaceChildren(frag);
}
function block(i, s, e, text, cls, k){
  const d = document.createElement('div');
  d.className = cls + (TL.drag && TL.drag.i === i ? ' drag' : ''); d.dataset.i = i; if (k != null) d.dataset.k = k;
  d.style.left = (s * TL.pps) + 'px'; d.style.width = Math.max(2, (e - s) * TL.pps) + 'px';
  d.title = text;
  const sp = document.createElement('span'); sp.textContent = text;
  const l = document.createElement('i'); l.className = 'hl'; const r = document.createElement('i'); r.className = 'hr';
  d.append(l, sp, r);
  return d;
}
function tlMarkCurrent(){
  if (TL.mode !== 'line') return;
  $('tlCaps').querySelectorAll('.blk').forEach(b => b.classList.toggle('cur', +b.dataset.i === S.current));
}
function placeHead(){ $('tlHead').style.transform = `translateX(${clock.currentTime * TL.pps}px)`; }
function followHead(){                    // keep the playhead on screen while playing
  const x = clock.currentTime * TL.pps, v = view();
  if (x < v.x0 || x > v.x0 + v.w - 60) tlScroll.scrollLeft = x - v.w * .15;
}

const timeAt = clientX => (clientX - tlScroll.getBoundingClientRect().left + tlScroll.scrollLeft) / TL.pps;
// Edges worth snapping to: the playhead, captions, and every clip's start and end.
function snapTo(t, ignore, alt, ignoreClip){
  if (!TL.snap || alt) return [t, null];
  const tol = 8 / TL.pps, pts = [clock.currentTime, 0];
  S.cues.forEach((c, i) => { if (i !== ignore){ pts.push(c.start, c.end); } });
  for (const tr of mediaTracks()) for (const c of tr.clips) if (c.id !== ignoreClip) pts.push(c.at, clipEnd(c));
  let best = null;
  for (const p of pts) if (Math.abs(p - t) < tol && (best == null || Math.abs(p - t) < Math.abs(best - t))) best = p;
  return best == null ? [t, null] : [best, best];
}
function showSnap(t){
  let line = tlContent.querySelector('.snapline');
  if (t == null){ line?.remove(); return; }
  if (!line){ line = document.createElement('div'); line.className = 'snapline'; tlContent.append(line); }
  line.style.left = (t * TL.pps) + 'px';
}
// Dragging: a caption's body moves it, its edges trim it; a word's edges retime that word.
$('tlCaps').addEventListener('pointerdown', e => {
  const b = e.target.closest('.blk'); if (!b || e.button !== 0) return;
  e.preventDefault();
  const i = +b.dataset.i, c = S.cues[i], k = b.dataset.k == null ? null : +b.dataset.k;
  const kind = e.target.classList.contains('hl') ? 'l' : e.target.classList.contains('hr') ? 'r' : 'move';
  if (S.editing >= 0) commitEdit(true);
  const clip = clipOfCue(c);
  TL.drag = {i, k, kind, x: e.clientX, t: timeAt(e.clientX), orig: wrapCue(JSON.parse(JSON.stringify(c))), before: snapshot(), moved: false,
             prevEnd: Math.max(S.cues[i - 1]?.end ?? 0, clip ? clip.at : 0),
             nextStart: Math.min(S.cues[i + 1]?.start ?? dur(), clip ? clipEnd(clip) : dur())};
  $('tlCaps').setPointerCapture(e.pointerId); b.classList.add('drag');
  if (S.sel !== i) select(i, false);
});
$('tlCaps').addEventListener('pointermove', e => {
  const d = TL.drag; if (!d) return;
  if (!d.moved && Math.abs(e.clientX - d.x) < 3) return;
  d.moved = true;
  const c = S.cues[d.i], o = d.orig, dt = timeAt(e.clientX) - d.t, MIN = .12;
  let snapped = null;
  if (d.k != null){                                   // one word
    const n = o.text.split(/\s+/).length, times = wordTimesOf(o, n).map(x => [...x]);
    const w = times[d.k], lo = d.k ? times[d.k - 1][1] : d.prevEnd, hi = d.k < n - 1 ? times[d.k + 1][0] : d.nextStart;
    if (d.kind === 'l'){ [w[0], snapped] = snapTo(Math.min(Math.max(w[0] + dt, lo), w[1] - .05), d.i, e.altKey); }
    else if (d.kind === 'r'){ [w[1], snapped] = snapTo(Math.max(Math.min(w[1] + dt, hi), w[0] + .05), d.i, e.altKey); }
    else { const len = w[1] - w[0]; w[0] = Math.min(Math.max(w[0] + dt, lo), hi - len); w[1] = w[0] + len; }
    c.wt = times.map(([s, x]) => [+s.toFixed(3), +x.toFixed(3)]);
    c.start = Math.min(o.start, c.wt[0][0]); c.end = Math.max(o.end, c.wt[n - 1][1]);
    if (d.k === 0) c.start = c.wt[0][0];
    if (d.k === n - 1) c.end = c.wt[n - 1][1];
  } else if (d.kind === 'move'){
    const len = o.end - o.start;
    let s = Math.min(Math.max(o.start + dt, d.prevEnd), d.nextStart - len);
    const [ss, sn] = snapTo(s, d.i, e.altKey), [es, en] = snapTo(s + len, d.i, e.altKey);
    if (sn != null){ s = ss; snapped = sn; } else if (en != null){ s = es - len; snapped = en; }
    s = Math.min(Math.max(s, d.prevEnd), d.nextStart - len);
    Object.assign(c, {start: o.start, end: o.end, wt: o.wt}); retime(c, s, s + len);
  } else if (d.kind === 'l'){
    let [s, sn] = snapTo(Math.min(Math.max(o.start + dt, d.prevEnd), o.end - MIN), d.i, e.altKey); snapped = sn;
    Object.assign(c, {start: o.start, end: o.end, wt: o.wt}); retime(c, s, o.end);
  } else {
    let [en, sn] = snapTo(Math.max(Math.min(o.end + dt, d.nextStart), o.start + MIN), d.i, e.altKey); snapped = sn;
    Object.assign(c, {start: o.start, end: o.end, wt: o.wt}); retime(c, o.start, en);
  }
  showSnap(snapped);
  drawBlocks(); syncTools(); capState = ''; updateOverlay(true); schedulePreview();
});
function endDrag(){
  const d = TL.drag; if (!d) return;
  TL.drag = null; showSnap(null);
  if (d.moved){
    H.past.push(d.before); H.future = []; syncHist();
    const row = $('cues').children[d.i]; if (row) renderRow(row, d.i);
    refreshTrack(); tlRender(); edited();
  } else {
    const c = S.cues[d.i];
    if (S.playable){ clock.currentTime = d.k != null ? wordTimesOf(c, c.text.split(/\s+/).length)[d.k][0] + .001 : c.start + .001; }
    setCurrent(d.i, true); tlRender();
  }
}
$('tlCaps').addEventListener('pointerup', endDrag);
$('tlCaps').addEventListener('pointercancel', endDrag);
$('tlCaps').addEventListener('dblclick', e => { const b = e.target.closest('.blk'); if (b) startEdit(+b.dataset.i); });

// Scrubbing: drag on the ruler, the playhead knob, or click an empty spot on any lane.
let scrub = false, wasPlaying = false;
function scrubTo(x){ const t = Math.min(Math.max(timeAt(x), 0), dur()); clock.currentTime = t; placeHead(); syncToVideo(); }
tlContent.addEventListener('pointerdown', e => {
  if (e.button !== 0 || e.target.closest('.blk, .clip, .tr-dot')) return;
  if (e.target.closest('.t-cap') && S.sel >= 0){ select(-1, false); }
  if (e.target.closest('.lane') && S.selClip){ selectClip(null); }
  scrub = true; wasPlaying = !clock.paused; clock.pause();
  tlContent.setPointerCapture(e.pointerId); scrubTo(e.clientX);
});
tlContent.addEventListener('pointermove', e => { if (scrub) scrubTo(e.clientX); });
const endScrub = () => { if (!scrub) return; scrub = false; if (wasPlaying) clock.play(); };
tlContent.addEventListener('pointerup', endScrub);
tlContent.addEventListener('pointercancel', endScrub);

// ---------- media lanes ----------
const LANE_H = {video: 58, audio: 46};
function buildLanes(){
  const heads = $('trackHeads'), lanes = $('lanes');
  if (!heads || typeof PJ === 'undefined' || !PJ.doc) return;
  const tracks = [...mediaTracks()].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === 'video' ? -1 : 1));
  // video tracks top-down = highest first (the one drawn on top)
  const vids = tracks.filter(t => t.kind === 'video').reverse(), auds = tracks.filter(t => t.kind === 'audio');
  const order = [...vids, ...auds];
  const key = order.map(t => `${t.id}:${t.mute ? 1 : 0}:${t.locked ? 1 : 0}:${t.volume ?? 1}:${t.name}`).join('|');
  if (TL.laneKey === key && lanes.children.length === order.length) return;
  TL.laneKey = key;
  heads.replaceChildren(...order.map(t => trackHead(t)));
  lanes.replaceChildren(...order.map(t => {
    const lane = document.createElement('div');
    lane.className = 'lane ' + t.kind + (t.mute ? ' muted' : '') + (t.locked ? ' locked' : '');
    lane.dataset.track = t.id; lane.style.height = LANE_H[t.kind] + 'px';
    lane.innerHTML = '<canvas class="lane-cv"></canvas><div class="lane-clips"></div>';
    return lane;
  }));
}
function trackHead(t){
  const h = document.createElement('div');
  h.className = 'th ' + t.kind; h.style.height = LANE_H[t.kind] + 'px'; h.dataset.track = t.id;
  const icon = t.kind === 'video' ? 'film' : 'wave';
  h.innerHTML = `<span class="th-name"><svg width="14" height="14"><use href="#i-${icon}"/></svg><b></b></span>
    <span class="th-btns">
      <button type="button" class="th-b" data-act="mute" title="${t.mute ? 'Unmute' : 'Mute'} this track" aria-pressed="${!!t.mute}"><svg width="13" height="13"><use href="#i-${t.mute ? 'mute' : 'vol'}"/></svg></button>
      <button type="button" class="th-b" data-act="vol" title="Track volume"><span>${Math.round((t.volume ?? 1) * 100)}</span></button>
      <button type="button" class="th-b" data-act="lock" title="${t.locked ? 'Unlock' : 'Lock'} this track" aria-pressed="${!!t.locked}"><svg width="13" height="13"><use href="#i-lock"/></svg></button>
      <button type="button" class="th-b" data-act="del" title="Remove this track"><svg width="13" height="13"><use href="#i-x"/></svg></button>
    </span>`;
  h.querySelector('b').textContent = t.name;
  return h;
}

// Filmstrip and waveform for each clip, painted on one canvas per lane (visible part only).
function drawLanes(){
  const lanes = $('lanes'); if (!lanes || typeof PJ === 'undefined' || !PJ.doc) return;
  buildLanes();
  const v = view();
  for (const lane of lanes.children){
    const tr = PJ.doc.tracks.find(t => t.id === lane.dataset.track); if (!tr) continue;
    const h = LANE_H[tr.kind], g = canvasFor(lane.querySelector('.lane-cv'), v.w, h);
    const frag = document.createDocumentFragment();
    for (const c of tr.clips){
      const x0 = c.at * TL.pps - v.x0, x1 = clipEnd(c) * TL.pps - v.x0;
      if (x1 < -50 || x0 > v.w + 50) continue;
      const a = assetOf(c.asset);
      g.save(); g.beginPath(); g.roundRect ? g.roundRect(x0, 3, x1 - x0, h - 6, 7) : g.rect(x0, 3, x1 - x0, h - 6); g.clip();
      g.fillStyle = tr.kind === 'video' ? '#16202e' : '#10251f'; g.fillRect(x0, 3, x1 - x0, h - 6);
      if (tr.kind === 'video') drawFilm(g, c, a, x0, x1, h);
      drawWaveIn(g, c, x0, x1, tr.kind === 'video' ? h - 18 : 6, tr.kind === 'video' ? h - 4 : h - 4,
                 tr.kind === 'video' ? 'rgba(67,211,158,.6)' : 'rgba(67,211,158,.85)', v);
      drawFades(g, c, x0, x1, h);
      g.restore();
      frag.append(clipBlock(tr, c, a));
    }
    if (typeof transDots === 'function') frag.append(...transDots(tr));
    lane.querySelector('.lane-clips').replaceChildren(frag);
  }
}
function clipBlock(tr, c, a){
  const d = document.createElement('div');
  const sel = S.selClip && S.selClip.id === c.id;
  d.className = 'clip ' + tr.kind + (sel ? ' sel' : '') + (c.mute ? ' muted' : '');
  d.dataset.id = c.id; d.dataset.track = tr.id;
  d.style.left = (c.at * TL.pps) + 'px'; d.style.width = Math.max(4, clipLen(c) * TL.pps) + 'px';
  const name = (a && (a.name || a.file.replace(/^[0-9a-f]{6,}_(?:[0-9a-f]{6}_)?/, ''))) || 'Clip';
  const vol = c.volume != null && c.volume !== 1 ? ` · ${Math.round(c.volume * 100)}%` : '';
  d.innerHTML = '<i class="hl"></i><span class="clip-name"></span><i class="hr"></i>';
  const fx = (spd(c) !== 1 ? ` · ${spd(c)}×` : '') + ((c.zoom || 1) > 1 ? ` · ${Math.round(c.zoom * 100)}%` : '');
  d.querySelector('.clip-name').textContent = name + vol + fx;
  d.title = `${name} · ${fine(clipLen(c))} long`;
  return d;
}
function drawFilm(g, c, a, x0, x1, h){
  const f = TL.film[c.asset];
  if (!f || !f.imgs.length) return;
  const th = h - 22, tw = th * (a && a.w ? a.w / a.h : 16 / 9);
  if (!(tw > 2) || !isFinite(x0) || !isFinite(x1)) return;
  for (let x = Math.max(x0, x0 + Math.floor((-x0) / tw) * tw), n = 0; x < x1 && n < 400; x += tw, n++){
    const t = c.in + (x - x0 + tw / 2) / TL.pps * spd(c);
    const k = Math.min(f.imgs.length - 1, Math.max(0, Math.round(t / f.step)));
    const img = f.imgs[k] || f.imgs.find(Boolean);
    if (img) g.drawImage(img, x, 4, tw, th);
  }
}
function drawWaveIn(g, c, x0, x1, top, bottom, colour, v){
  const p = TL.peaks[c.asset]; if (!p || !p.data.length) return;
  const rate = p.rate, mid = (top + bottom) / 2, amp = (bottom - top) / 2;
  g.fillStyle = colour;
  const from = Math.max(0, Math.floor(x0)), to = Math.min(v.w, Math.ceil(x1));
  if (!isFinite(from) || !isFinite(to)) return;
  for (let x = from; x < to; x++){
    const t0 = c.in + (x - x0) / TL.pps * spd(c), t1 = c.in + (x + 1 - x0) / TL.pps * spd(c);
    const a = Math.floor(t0 * rate), b = Math.max(a + 1, Math.floor(t1 * rate));
    let m = 0;
    for (let k = a; k < b && k < p.data.length; k++) if (p.data[k] > m) m = p.data[k];
    const y = Math.max(.5, m / 255 * amp * (c.volume ?? 1));
    g.fillRect(x, mid - y, 1, y * 2);
  }
}
function drawFades(g, c, x0, x1, h){
  g.fillStyle = 'rgba(0,0,0,.45)';
  if (c.fadeIn > 0){ const w = c.fadeIn * TL.pps; g.beginPath(); g.moveTo(x0, 3); g.lineTo(x0 + w, 3); g.lineTo(x0, h - 3); g.fill(); }
  if (c.fadeOut > 0){ const w = c.fadeOut * TL.pps; g.beginPath(); g.moveTo(x1, 3); g.lineTo(x1 - w, 3); g.lineTo(x1, h - 3); g.fill(); }
}

// Waveforms and filmstrips per media file, loaded once.
async function loadPeaksFor(aid){
  if (TL.peaks[aid] || !PJ.doc) return;
  TL.peaks[aid] = {data: new Uint8Array(0), rate: 50};
  try {
    const r = await fetch(`/projects/${PJ.doc.id}/peaks/${aid}`); if (!r.ok) return;
    TL.peaks[aid] = {data: new Uint8Array(await r.arrayBuffer()), rate: +r.headers.get('X-Peaks-Per-Sec') || 50};
    tlRender();
  } catch {}
}
const filmQueue = [];
let filmBusy = false;
function loadFilmFor(aid){
  const a = assetOf(aid);
  if (!a || !a.w || TL.film[aid]) return;
  const n = Math.max(8, Math.min(120, Math.ceil(a.duration / 2)));
  TL.film[aid] = {imgs: new Array(n).fill(null), step: a.duration / n};
  filmQueue.push(aid); pumpFilm();
}
function pumpFilm(){
  if (filmBusy || !filmQueue.length) return;
  filmBusy = true;
  const aid = filmQueue.shift(), f = TL.film[aid], a = assetOf(aid);
  const v = document.createElement('video');
  v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = assetUrl(aid);
  const c = document.createElement('canvas'), g = c.getContext('2d');
  let k = 0;
  const done = () => { v.removeAttribute('src'); v.load(); filmBusy = false; pumpFilm(); };
  // one still at a time, in idle moments, and never while the video is playing (keeps playback smooth)
  const idle = window.requestIdleCallback || (fn => setTimeout(fn, 40));
  const next = () => {
    if (k >= f.imgs.length || TL.film[aid] !== f) return done();
    if (!clock.paused) return setTimeout(next, 400);
    idle(() => { v.currentTime = Math.min(a.duration - .05, (k + .5) * f.step); }, {timeout: 300});
  };
  v.addEventListener('loadeddata', () => { c.height = 72; c.width = Math.round(72 * v.videoWidth / v.videoHeight) || 128; next(); }, {once: true});
  v.addEventListener('error', done, {once: true});
  v.addEventListener('seeked', () => {
    const k0 = k;
    try {
      g.drawImage(v, 0, 0, c.width, c.height);
      if (window.createImageBitmap) createImageBitmap(c).then(bm => { f.imgs[k0] = bm; tlRender(); });
      else { const img = new Image(); img.src = c.toDataURL('image/jpeg', .7); f.imgs[k0] = img; img.onload = tlRender; }
    } catch {}
    k++; next();
  });
}
function loadMediaVisuals(){
  if (!PJ.doc) return;
  for (const a of PJ.doc.assets){ loadPeaksFor(a.id); loadFilmFor(a.id); }
}

// Resizing the timeline by its grip.
$('tlGrip').addEventListener('pointerdown', e => {
  const y0 = e.clientY, h0 = $('timeline').offsetHeight;
  const mv = ev => { const h = Math.min(Math.max(h0 - (ev.clientY - y0), 170), innerHeight * .65); $('editor').style.setProperty('--tl-h', h + 'px'); };
  const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); store.set('tl_h', $('editor').style.getPropertyValue('--tl-h')); };
  addEventListener('pointermove', mv); addEventListener('pointerup', up);
});
if (store.get('tl_h')) $('editor').style.setProperty('--tl-h', store.get('tl_h'));
