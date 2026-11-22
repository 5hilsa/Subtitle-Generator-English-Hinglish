// Playback for a timeline of clips. `clock` is the editor's sense of time: it looks like a
// <video> (currentTime, paused, play(), pause(), events) so the rest of the editor doesn't care
// whether one file or twenty clips are playing. The engine keeps one media element per clip
// that is on screen or about to be, seeks it to the right spot, and mixes its sound.
'use strict';

class Clock extends EventTarget {
  constructor(){ super(); this._t = 0; this._paused = true; this._rate = 1; this._muted = false; this._p0 = 0; this._w0 = 0; this._raf = 0; }
  get duration(){ return typeof tlDuration === 'function' ? tlDuration() : 0; }
  get currentTime(){ return this._paused ? this._t : this._p0 + (performance.now() - this._w0) / 1000 * this._rate; }
  set currentTime(v){
    v = Math.min(Math.max(+v || 0, 0), this.duration || 0);
    this._t = v; this._p0 = v; this._w0 = performance.now();
    engineSync(true);
    this.emit('seeked'); this.emit('timeupdate');
  }
  get paused(){ return this._paused; }
  get playbackRate(){ return this._rate; }
  set playbackRate(r){ this._t = this.currentTime; this._p0 = this._t; this._w0 = performance.now(); this._rate = r; engineSync(true); this.emit('ratechange'); }
  get muted(){ return this._muted; }
  set muted(m){ this._muted = !!m; engineSync(); this.emit('volumechange'); }
  play(){
    if (!this._paused) return Promise.resolve();
    if (this._t >= this.duration - .05) this._t = 0;
    this._paused = false; this._p0 = this._t; this._w0 = performance.now();
    ENG.ctx?.resume?.();
    engineSync(true);
    const tick = () => {
      if (this._paused) return;
      const t = this.currentTime;
      if (t >= this.duration){ this.pause(); this._t = this.duration; this.emit('timeupdate'); return; }
      engineFollow();
      engineSync();
      this.emit('timeupdate');
      this._raf = requestAnimationFrame(tick);
    };
    this._raf = requestAnimationFrame(tick);
    this.emit('play');
    return Promise.resolve();
  }
  pause(){
    if (this._paused) return;
    this._t = this.currentTime; this._paused = true;
    cancelAnimationFrame(this._raf);
    engineSync(true);
    this.emit('pause');
  }
  emit(type){ this.dispatchEvent(new Event(type)); }
}
const clock = new Clock();

// ---------- the engine ----------
const ENG = {els: new Map(), ctx: null, layer: null, master: null};
const mediaTracks = () => (typeof PJ !== 'undefined' && PJ.doc ? PJ.doc.tracks.filter(t => t.kind === 'video' || t.kind === 'audio') : []);
// A clip shows file time in..out from timeline time `at`, played at `speed` (so it lasts (out-in)/speed).
const spd = c => c.speed || 1;
const clipLen = c => (c.out - c.in) / spd(c);
const clipEnd = c => c.at + clipLen(c);
const toTL = (c, m) => c.at + (m - c.in) / spd(c);        // file time -> timeline time
const toAsset = (c, T) => c.in + (T - c.at) * spd(c);     // timeline time -> file time
// Transitions on a track: {clip id: {kind, d, prev}} for clips joined to the clip before them
// (the same rules as compose.transitions on export).
function clipTransitions(track){
  const out = {}, cs = [...track.clips].sort((a, b) => a.at - b.at);
  for (let i = 1; i < cs.length; i++){
    const a = cs[i - 1], b = cs[i], tr = b.trans;
    if (!tr || Math.abs(clipEnd(a) - b.at) > .05) continue;
    const d = Math.min(tr.d ?? .5, clipLen(a) * (tr.type === 'cross' ? .5 : 1), clipLen(b) * .5);
    if (d >= .04) out[b.id] = {kind: tr.type, d, prev: a};
  }
  return out;
}
function assetUrl(aid){
  if (aid === 'a1' && S.localUrl) return S.localUrl;          // just uploaded: play the file from this computer
  return `/projects/${PJ.doc.id}/media/${aid}`;
}
const assetOf = aid => PJ.doc && PJ.doc.assets.find(a => a.id === aid);

function tlDuration(){
  const tr = mediaTracks();
  let d = 0;
  for (const t of tr) for (const c of t.clips) d = Math.max(d, clipEnd(c));
  for (const sp of (S.supers || [])) d = Math.max(d, sp.t1);
  return d || S.duration || 0;
}

function ensureAudio(){
  if (ENG.ctx || !window.AudioContext) return;
  try { ENG.ctx = new AudioContext(); } catch { ENG.ctx = null; }
}
function elementFor(track, clip){
  let e = ENG.els.get(clip.id);
  if (e && e.asset === clip.asset) return e;
  if (e) dropElement(clip.id);
  const a = assetOf(clip.asset);
  const el = document.createElement(a && a.w ? 'video' : 'audio');
  el.preload = 'auto'; el.playsInline = true; el.src = assetUrl(clip.asset);
  el.className = 'clip-media';
  // the moment it can show a frame, put it at the clock's time (a seek made while loading is lost)
  el.addEventListener('loadedmetadata', () => engineSync(true));
  el.addEventListener('canplay', () => { if (clock.paused) engineSync(true); }, {once: true});
  e = {el, asset: clip.asset, gain: null, kind: track.kind};
  if (el.tagName === 'VIDEO') ENG.layer.append(el); else document.body.append(el);
  if (el.tagName === 'AUDIO') el.style.display = 'none';
  ensureAudio();
  if (ENG.ctx){
    try { const src = ENG.ctx.createMediaElementSource(el); e.gain = ENG.ctx.createGain(); src.connect(e.gain).connect(ENG.ctx.destination); }
    catch { e.gain = null; }
  }
  ENG.els.set(clip.id, e);
  return e;
}
function dropElement(id){
  const e = ENG.els.get(id); if (!e) return;
  e.el.pause(); e.el.removeAttribute('src'); e.el.load(); e.el.remove();
  ENG.els.delete(id);
}
function gainAt(track, clip, t){
  if (clock.muted || track.mute || clip.mute) return 0;
  let g = (clip.volume ?? 1) * (track.volume ?? 1);
  const into = t - clip.at, left = clipEnd(clip) - t;
  if (left < 0) return g;                    // playing on under a crossfade: faded by the caller
  if (clip.fadeIn > 0 && into < clip.fadeIn) g *= Math.max(0, into / clip.fadeIn);
  if (clip.fadeOut > 0 && left < clip.fadeOut) g *= Math.max(0, left / clip.fadeOut);
  return g;
}

// Put every clip's media where the clock says it should be.
function engineSync(hard){
  if (!ENG.layer || !PJ.doc || $('editor').hidden) return;
  const t = clock.currentTime, playing = !clock.paused, keep = new Set();
  const tracks = mediaTracks();
  let z = 1;
  ENG.master = null;
  const shown = [];                          // video on screen, bottom track first
  for (const tr of tracks){
    const clips = tr.clips, trans = clipTransitions(tr);
    const act = clips.find(c => t >= c.at && t < clipEnd(c));
    const nxt = clips.filter(c => c.at > t && c.at - t < 2.5).sort((a, b) => a.at - b.at)[0];
    if (nxt){ const e = elementFor(tr, nxt); keep.add(nxt.id); e.el.style.visibility = 'hidden'; if (!e.el.seeking && Math.abs(e.el.currentTime - nxt.in) > .05 && e.el.readyState >= 1) e.el.currentTime = nxt.in; if (!e.el.paused) e.el.pause(); }
    if (!act) continue;
    // what's on this track right now: the clip, and under it the clip before it if it's crossfading in
    const layers = [], ti = trans[act.id];
    let mix = 1;                              // how far in the active clip has faded
    if (ti){
      const into = t - act.at;
      if (ti.kind === 'cross' && into < ti.d){ mix = into / ti.d; layers.push({c: ti.prev, a: 1, g: 1 - mix}); }
      else if (ti.kind === 'dip' && into < ti.d / 2) mix = into / (ti.d / 2);
    }
    let out = 1;                              // dipping to black at the end
    const nt = Object.values(trans).find(x => x.prev === act);
    if (nt && nt.kind === 'dip'){ const left = clipEnd(act) - t; if (left < nt.d / 2) out = left / (nt.d / 2); }
    layers.push({c: act, a: Math.min(mix, out), g: Math.min(mix, out)});
    for (const {c, a, g: fade} of layers){
      const e = elementFor(tr, c); keep.add(c.id);
      const m = toAsset(c, t), el = e.el;
      if (el.tagName === 'VIDEO'){
        el.style.visibility = 'visible'; el.style.zIndex = z++; el.style.opacity = a < 1 ? a.toFixed(3) : '';
        const zm = c.zoom || 1;
        el.style.transform = zm > 1 ? `scale(${zm})` : '';
        el.style.transformOrigin = zm > 1 ? `${(c.px ?? .5) * 100}% ${(c.py ?? .5) * 100}%` : '';
        shown.push({el, asset: c.asset, solid: a >= 1});
      }
      const g = gainAt(tr, c, t) * fade;
      if (e.gain){ e.gain.gain.value = g; el.volume = 1; } else el.volume = Math.min(1, g);
      el.playbackRate = clock.playbackRate * spd(c);
      if (el.readyState < 1) continue;
      const end = el.duration || Infinity, want = Math.min(m, end - .02);   // past the file's end: hold the last frame
      const drift = Math.abs(el.currentTime - want);
      if (playing && m < end - .02){
        if (el.paused){ if (drift > .03) el.currentTime = want; el.play().catch(() => {}); }
        else if (drift > .3 && !el.seeking) el.currentTime = want;
        if (c === act && (el.tagName === 'VIDEO' || !ENG.master)) ENG.master = {el, clip: c};
      } else {
        if (!el.paused) el.pause();
        if ((hard || drift > .02) && !el.seeking && drift > .001) el.currentTime = want;
      }
    }
  }
  // A clip that fills the whole frame hides everything under it: don't paint what can't be seen.
  const cv = PJ.doc.canvas, covers = x => { const a = assetOf(x.asset); return cv.fit === 'fill' || (a && a.w && Math.abs(a.w / a.h - cv.w / cv.h) < .01); };
  const top = shown.map(x => x.solid && covers(x)).lastIndexOf(true);
  shown.forEach((x, k) => { if (k < top) x.el.style.visibility = 'hidden'; });
  for (const id of [...ENG.els.keys()]) if (!keep.has(id)){
    const e = ENG.els.get(id);
    if (e.el.tagName === 'VIDEO'){ e.el.style.visibility = 'hidden'; e.el.style.opacity = ''; }
    if (!e.el.paused) e.el.pause();
    if (!e.lastUsed) e.lastUsed = performance.now();
    else if (performance.now() - e.lastUsed > 8000) dropElement(id);
  }
  for (const id of keep){ const e = ENG.els.get(id); if (e) e.lastUsed = 0; }
}
// While playing, follow the media's own clock so sound and picture never drift apart.
// Only while that media is really moving: if it stalls or the browser refused to play it, the
// clock keeps time on its own (and engineSync nudges the media back in line).
function engineFollow(){
  const m = ENG.master; if (!m || clock.paused) return;
  const el = m.el, now = performance.now();
  if (el._lastT !== el.currentTime){ el._lastT = el.currentTime; el._movedAt = now; }
  if (el.paused || el.seeking || el.readyState < 3 || now - (el._movedAt || 0) > 250) return;
  const t = toTL(m.clip, el.currentTime);
  if (t >= m.clip.at && t < clipEnd(m.clip) && Math.abs(t - clock.currentTime) > .02 && Math.abs(t - clock.currentTime) < .5){
    clock._p0 = t; clock._w0 = now;
  }
}
function engineReset(){
  for (const id of [...ENG.els.keys()]) dropElement(id);
}
function initEngine(){
  ENG.layer = $('mediaLayer');
}
