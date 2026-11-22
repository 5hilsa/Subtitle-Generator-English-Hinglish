// Cutting the video: pick a stretch of the timeline (Shift-drag on the ruler or a lane, or I / O at
// the playhead) and remove it; remove the words picked in the captions from the video; change a
// clip's speed; and join clips with a crossfade or a dip to black.
// Everything here is a ripple edit: what comes after moves up, and captions (which belong to their
// media) follow on their own.
'use strict';

const CUT = {range: null, drag: null};

// ---------- removing a stretch of the timeline ----------
// Every unlocked track loses [T0, T1): clips across it are split, the middle dropped, and later
// clips (and on-screen text) move left. One undo puts it all back.
function removeRange(T0, T1, {history = true, quiet = false} = {}){
  T0 = Math.max(0, T0); T1 = Math.min(dur(), T1);
  const len = T1 - T0;
  if (!(len >= .05)) return 0;
  if (history) pushHistory();
  const skipped = [];
  for (const t of mediaTracks()){
    if (t.locked){ if (t.clips.some(c => clipEnd(c) > T0)) skipped.push(t.name); continue; }
    const keep = [];
    for (const c of t.clips){
      const e = clipEnd(c);
      if (e <= T0 + 1e-3){ keep.push(c); continue; }
      if (c.at >= T1 - 1e-3){ c.at = +(c.at - len).toFixed(3); keep.push(c); continue; }
      const before = c.at < T0 - .02, after = e > T1 + .02;
      const cutA = toAsset(c, T0), cutB = toAsset(c, T1);
      if (before && after){                          // the range is inside the clip: two pieces
        const b = {...c, id: newId('c'), in: +cutB.toFixed(3), at: +T0.toFixed(3)};
        delete b.fadeIn; delete b.trans;
        c.out = +cutA.toFixed(3); delete c.fadeOut;
        keep.push(c, b);
      } else if (before){ c.out = +cutA.toFixed(3); delete c.fadeOut; keep.push(c); }
      else if (after){ c.in = +cutB.toFixed(3); c.at = +T0.toFixed(3); delete c.fadeIn; keep.push(c); }
      // else the whole clip is inside the range: it goes
      if (before) splitCaptionsAt(c.asset, cutA);
      if (after) splitCaptionsAt(c.asset, cutB);
    }
    t.clips = keep;
  }
  // on-screen text: inside goes, across is shortened, after moves up
  const map = x => x <= T0 ? x : x >= T1 ? x - len : T0;
  S.supers = (S.supers || []).filter(sp => {
    sp.t0 = +map(sp.t0).toFixed(3); sp.t1 = +map(sp.t1).toFixed(3);
    return sp.t1 - sp.t0 >= .1;
  });
  if (S.selClip && !clipById(S.selClip.id)) S.selClip = null;
  clearRange();
  clipsChanged();
  clock.currentTime = Math.min(T0, dur());
  followHead();
  if (!quiet){
    toast(`Removed ${fine(len)}${skipped.length ? ` (locked: ${skipped.join(', ')})` : ''}`, {label: 'Undo', run: undo});
  }
  return len;
}

// ---------- the range: Shift-drag, or I / O ----------
function setRange(a, b){
  if (a == null || b == null){ clearRange(); return; }
  const t0 = Math.max(0, Math.min(a, b)), t1 = Math.min(dur(), Math.max(a, b));
  CUT.range = t1 - t0 >= .02 ? {t0, t1} : null;
  rangeRender();
}
function clearRange(){ CUT.range = null; rangeRender(); }
function markIn(){
  const t = clock.currentTime, r = CUT.range;
  setRange(t, r && r.t1 > t + .02 ? r.t1 : (CUT.outMark != null && CUT.outMark > t ? CUT.outMark : Math.min(dur(), t + 1)));
  CUT.inMark = t;
}
function markOut(){
  const t = clock.currentTime, r = CUT.range;
  setRange(r && r.t0 < t - .02 ? r.t0 : (CUT.inMark != null && CUT.inMark < t ? CUT.inMark : Math.max(0, t - 1)), t);
  CUT.outMark = t;
}
function rangeRender(){
  const box = $('tlRange'), bar = $('rangeBar'); if (!box || !bar) return;
  const r = CUT.range;
  box.hidden = bar.hidden = !r;
  if (!r) return;
  box.style.left = (r.t0 * TL.pps) + 'px'; box.style.width = Math.max(2, (r.t1 - r.t0) * TL.pps) + 'px';
  $('rangeLen').textContent = `${fine(r.t0)} – ${fine(r.t1)} · ${fine(r.t1 - r.t0)}`;
}
function initRange(){
  const box = document.createElement('div'); box.className = 'tl-range'; box.id = 'tlRange'; box.hidden = true;
  box.innerHTML = '<i class="rl"></i><i class="rr"></i>';
  tlContent.append(box);
  $('rangeCut').onclick = () => CUT.range && removeRange(CUT.range.t0, CUT.range.t1);
  $('rangeClear').onclick = clearRange;
  // Shift-drag on the ruler or an empty spot in a lane marks a stretch; drag its edges to adjust.
  tlContent.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const edge = e.target.closest('#tlRange i');
    if (!edge && !(e.shiftKey && !e.target.closest('.blk, .clip, .tr-dot'))) return;
    e.preventDefault(); e.stopImmediatePropagation();
    clock.pause();
    const t = Math.max(0, timeAt(e.clientX));
    CUT.drag = edge ? {fixed: edge.classList.contains('rl') ? CUT.range.t1 : CUT.range.t0} : {fixed: t};
    if (!edge) setRange(t, t);
    tlContent.setPointerCapture(e.pointerId);
  }, true);
  tlContent.addEventListener('pointermove', e => {
    if (!CUT.drag) return;
    e.stopImmediatePropagation();
    let t = Math.min(Math.max(0, timeAt(e.clientX)), dur());
    const [s, snapped] = snapTo(t, -1, e.altKey); t = s; showSnap(snapped);
    setRange(CUT.drag.fixed, t);
    clock.currentTime = t; placeHead();
  }, true);
  const end = e => {
    if (!CUT.drag) return;
    e.stopImmediatePropagation();
    CUT.drag = null; showSnap(null);
    if (CUT.range) toast('Press Delete to remove this part, or Esc to cancel');
  };
  tlContent.addEventListener('pointerup', end, true);
  tlContent.addEventListener('pointercancel', end, true);
}

// ---------- cut by editing the text ----------
// The words picked in the captions (or the selected line) -> stretches of the timeline. Picked
// words next to each other become one stretch; a little air around each cut keeps it clean
// without eating into the words that stay.
function textRanges(){
  const out = [];
  const pick = S.selWords?.size ? S.selWords : null;
  for (const [i, c] of S.cues.entries()){
    const wt = c.wt, n = c.words.length;
    if (!pick){
      if (i === S.sel) out.push([c.start, c.end]);
      continue;
    }
    let k = 0;
    while (k < n){
      if (!pick.has(c.words[k].id)){ k++; continue; }
      let j = k; while (j + 1 < n && pick.has(c.words[j + 1].id)) j++;
      const prevEnd = k > 0 ? wt[k - 1][1] : -Infinity, nextStart = j + 1 < n ? wt[j + 1][0] : Infinity;
      out.push([Math.max(wt[k][0] - .04, prevEnd, c.start), Math.min(wt[j][1] + .04, nextStart, c.end)]);
      k = j + 1;
    }
  }
  out.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const r of out){
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1] + .05) last[1] = Math.max(last[1], r[1]); else merged.push([...r]);
  }
  return merged.filter(([a, b]) => b - a >= .05);
}
function removeTextFromVideo(){
  const nWords = S.selWords?.size || 0;
  const ranges = textRanges();
  if (!ranges.length) return toast('Pick words in the captions (or a line) to remove them from the video');
  pushHistory();
  let total = 0;
  for (const [a, b] of ranges.reverse()) total += removeRange(a, b, {history: false, quiet: true});
  S.selWords = new Set();
  if (S.sel >= 0) select(-1, false);
  setScope('all'); refreshWordMarks(); renderCues();
  const what = nWords ? (nWords === 1 ? '1 word' : `${nWords} words`) : 'the line';
  toast(`Removed ${what} from the video (${fine(total)})`, {label: 'Undo', run: undo});
}

// ---------- speed ----------
// The clip keeps its start; what comes after it on the same track moves up or back.
const SPEEDS = [[.5, '0.5×'], [.75, '0.75×'], [1, '1×'], [1.25, '1.25×'], [1.5, '1.5×'], [2, '2×'], [3, '3×']];
function setClipSpeed(v){
  const hit = selectedClip(); if (!hit) return;
  const {t, c} = hit;
  if (t.locked) return toast('This track is locked');
  if (spd(c) === v) return;
  pushHistory();
  const oldEnd = clipEnd(c);
  if (v === 1) delete c.speed; else c.speed = v;
  const delta = clipEnd(c) - oldEnd, len = clipLen(c);
  for (const k of ['fadeIn', 'fadeOut']) if (c[k] > len / 2) c[k] = +(len / 2).toFixed(2);
  for (const o of t.clips) if (o !== c && o.at >= oldEnd - .001) o.at = +(o.at + delta).toFixed(3);
  if (t === mediaTracks().find(x => x.kind === 'video'))
    for (const sp of S.supers) if (sp.t0 >= oldEnd - .001){ sp.t0 = +(sp.t0 + delta).toFixed(3); sp.t1 = +(sp.t1 + delta).toFixed(3); }
  clipsChanged();
}

// ---------- transitions ----------
const TRANS = [['none', 'Cut'], ['cross', 'Crossfade'], ['dip', 'Dip to black']];
// The clip right before this one on its track, if they touch (a transition needs a neighbour).
function clipBefore(t, c){
  return t.clips.find(o => o !== c && Math.abs(clipEnd(o) - c.at) <= .05) || null;
}
function setTransition(type, d){
  const hit = selectedClip(); if (!hit) return;
  if (hit.t.locked) return toast('This track is locked');
  begin();
  if (type === 'none') delete hit.c.trans;
  else hit.c.trans = {type, d: d ?? hit.c.trans?.d ?? .5};
  done();
  engineSync(true); tlRender(); edited();
}
// A diamond on each join between two clips: click it to pick the transition there.
function transDots(tr){
  const out = [], cs = [...tr.clips].sort((a, b) => a.at - b.at), has = clipTransitions(tr);
  for (let i = 1; i < cs.length; i++){
    const b = cs[i];
    if (Math.abs(clipEnd(cs[i - 1]) - b.at) > .05) continue;
    const d = document.createElement('button'); d.type = 'button';
    d.className = 'tr-dot' + (has[b.id] ? ' on' : '');
    d.dataset.id = b.id;
    d.style.left = (b.at * TL.pps) + 'px';
    d.title = has[b.id] ? `${has[b.id].kind === 'cross' ? 'Crossfade' : 'Dip to black'} · ${has[b.id].d.toFixed(1)}s (click to change)` : 'Add a transition';
    d.setAttribute('aria-label', d.title);
    out.push(d);
  }
  return out;
}
function initTransDots(){
  $('lanes').addEventListener('pointerdown', e => { if (e.target.closest('.tr-dot')) e.stopPropagation(); }, true);
  $('lanes').addEventListener('click', e => {
    const dot = e.target.closest('.tr-dot'); if (!dot) return;
    e.stopPropagation();
    selectClip({id: dot.dataset.id});
    const hit = selectedClip();
    if (hit && !hit.c.trans) setTransition('cross');     // first click: a crossfade, change it in the panel
    inspectorSync();
    document.querySelector('.trans-prop')?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
  });
}

// ---------- the clip panel: speed, zoom, transition ----------
function clipEditProps(t, c){
  const out = [];
  out.push(prop('Speed', chipRow(SPEEDS, spd(c), v => setClipSpeed(v))));
  const a = assetOf(c.asset);
  if (t.kind === 'video' && a && a.w){
    const z = el('div', 'sliders');
    z.append(slider('Zoom', 'maximize', 1, 4, .05, c.zoom ?? 1, v => Math.round(v * 100) + '%', (v, live) => setClip('zoom', v <= 1.001 ? null : v, live)));
    z.append(slider('Across', 'arrows-h', 0, 100, 1, Math.round((c.px ?? .5) * 100), v => v + '%', (v, live) => setClip('px', v === 50 ? null : v / 100, live)));
    z.append(slider('Down', 'arrows-v', 0, 100, 1, Math.round((c.py ?? .5) * 100), v => v + '%', (v, live) => setClip('py', v === 50 ? null : v / 100, live)));
    out.push(prop('Zoom & position', z));
  }
  if (clipBefore(t, c)){
    const box = el('div', 'stack');
    box.append(chipRow(TRANS, c.trans?.type || 'none', v => { setTransition(v); inspectorSync(); }));
    if (c.trans){
      const max = Math.max(.2, Math.min(2, clipLen(c) / 2));
      box.append(slider('Length', 'arrows-h', .1, max, .1, Math.min(c.trans.d ?? .5, max), v => v.toFixed(1) + 's',
                        (v, live) => { begin(); c.trans = {...c.trans, d: v}; if (!live) done(); engineSync(true); tlRender(); edited(); }));
    }
    const p = prop('Transition in', box); p.classList.add('trans-prop');
    out.push(p);
  }
  return out;
}

function initCut(){
  initRange(); initTransDots();
  $('cutTextBtn') && ($('cutTextBtn').onclick = removeTextFromVideo);
}
