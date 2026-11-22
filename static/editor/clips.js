// Clips and tracks: import media, move / trim / split / delete clips (later clips close the gap),
// mute or turn tracks down, fade sound in and out, and pick the frame (9:16, 1:1, 4:5, 16:9).
// Captions belong to their clip's media, so they follow every one of these edits.
'use strict';

const trackOf = id => PJ.doc.tracks.find(t => t.id === id);
const clipById = id => { for (const t of mediaTracks()) { const c = t.clips.find(c => c.id === id); if (c) return {t, c}; } return null; };
const newId = p => p + (S.nextId = (S.nextId || 0) + 1);

// After any change to clips: captions re-link, the preview, the player and the timeline catch up.
function clipsChanged(){
  for (const t of mediaTracks()) t.clips.sort((a, b) => a.at - b.at);
  relinkCaptions();
  S.duration = tlDuration();
  engineSync(true); tlRender(); edited(); updateStatus(); inspectorSync();
}

// ---------- selection ----------
function selectClip(ref){
  S.selClip = ref;
  if (ref){ S.selWords = new Set(); S.selSuper = null; if (S.sel >= 0){ const rows = $('cues').children; rows[S.sel]?.classList.remove('sel'); S.sel = -1; } }
  setScope(ref ? 'clip' : 'all');
  if (ref) sideTab(true);
  tlRender(); drawHits(true);
}
function selectedClip(){ return S.selClip ? clipById(S.selClip.id) : null; }

// ---------- edits ----------
function splitClipAt(T){
  let hit = selectedClip();
  if (!hit || !(T > hit.c.at + .05 && T < clipEnd(hit.c) - .05)){        // else the top clip under the playhead
    hit = null;
    for (const t of [...mediaTracks()].reverse()) { const c = t.clips.find(c => T > c.at + .05 && T < clipEnd(c) - .05); if (c){ hit = {t, c}; break; } }
  }
  if (!hit) return toast('Move the playhead over a clip to split it');
  if (hit.t.locked) return toast('This track is locked');
  pushHistory();
  const {t, c} = hit, cut = toAsset(c, T);
  const b = {...c, id: newId('c'), in: +cut.toFixed(3), at: +T.toFixed(3)};
  c.out = +cut.toFixed(3);
  delete b.fadeIn; delete c.fadeOut;
  t.clips.push(b);
  splitCaptionsAt(c.asset, cut);
  selectClip({id: b.id});
  clipsChanged();
  toast('Clip split', {label: 'Undo', run: undo});
}
// A caption line can't sit across a cut: split it at the word nearest the cut.
function splitCaptionsAt(asset, cut){
  const all = [...S.cues, ...(S.hidden || [])];
  for (const g of all){
    if ((g.asset || 'a1') !== asset || !(g.t0 < cut - .02 && g.t1 > cut + .02)) continue;
    let k = g.words.findIndex(w => (w.t0 + w.t1) / 2 >= cut);
    if (k <= 0 || k >= g.words.length){                 // the cut falls before the first or after the last word
      if (k <= 0) g.t0 = Math.max(g.t0, cut); else g.t1 = Math.min(g.t1, cut);
      continue;
    }
    const a = newCueRaw(g, g.words.slice(0, k), g.t0, cut), b = newCueRaw(g, g.words.slice(k), cut, g.t1);
    const list = S.cues.includes(g) ? S.cues : S.hidden;
    list.splice(list.indexOf(g), 1, a, b);
  }
}
function newCueRaw(from, words, t0, t1){
  const c = wrapCue({id: newId('g'), asset: from.asset || 'a1', t0: +t0.toFixed(3), t1: +t1.toFixed(3),
                     words: words.map(w => ({...w})), orig: words.map(w => w.text).join(' '), source: ''});
  for (const k of ['o', 'anim', 'place']) if (from[k]) c[k] = JSON.parse(JSON.stringify(from[k]));
  return c;
}
function deleteClip(ref, keepGap){
  const hit = clipById(ref.id); if (!hit) return;
  if (hit.t.locked) return toast('This track is locked');
  pushHistory();
  const {t, c} = hit, len = clipLen(c), end = clipEnd(c);
  t.clips.splice(t.clips.indexOf(c), 1);
  if (!keepGap){
    for (const o of t.clips) if (o.at >= end - .001) o.at = +(o.at - len).toFixed(3);   // close the gap
    if (t === mediaTracks().find(x => x.kind === 'video'))                              // main video: text moves along
      for (const sp of S.supers) if (sp.t0 >= end - .001){ sp.t0 = +(sp.t0 - len).toFixed(3); sp.t1 = +(sp.t1 - len).toFixed(3); }
  }
  selectClip(null);
  clipsChanged();
  toast(keepGap ? 'Clip deleted' : 'Clip deleted, the gap closed', {label: 'Undo', run: undo});
}
function setClip(key, value, live){
  const hit = selectedClip(); if (!hit) return;
  begin();
  if (value == null) delete hit.c[key]; else hit.c[key] = value;
  if (!live) done();
  engineSync(); tlRender(); edited();
}

// ---------- dragging clips: move (also onto another track of the same kind) and trim ----------
function initClipDrag(){
  const lanes = $('lanes');
  lanes.addEventListener('pointerdown', e => {
    const b = e.target.closest('.clip'); if (!b || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    const hit = clipById(b.dataset.id); if (!hit) return;
    if (S.selClip?.id !== hit.c.id) selectClip({id: hit.c.id});
    if (hit.t.locked) return;
    const kind = e.target.classList.contains('hl') ? 'l' : e.target.classList.contains('hr') ? 'r' : 'move';
    TL.clipDrag = {hit, kind, x: e.clientX, t: timeAt(e.clientX), o: {...hit.c}, before: snapshot(), moved: false, track: hit.t};
    lanes.setPointerCapture(e.pointerId);
  });
  lanes.addEventListener('pointermove', e => {
    const d = TL.clipDrag; if (!d) return;
    if (!d.moved && Math.abs(e.clientX - d.x) < 3) return;
    d.moved = true;
    const {c} = d.hit, o = d.o, a = assetOf(c.asset), dt = timeAt(e.clientX) - d.t, len = clipLen(o), sp = spd(o);
    // which lane is under the pointer (same kind only)
    const laneEl = document.elementsFromPoint(e.clientX, e.clientY).find(el => el.classList?.contains('lane'));
    const target = laneEl ? trackOf(laneEl.dataset.track) : d.track;
    const dest = target && target.kind === d.hit.t.kind && !target.locked && (target.kind !== 'video' || a.w) ? target : d.track;
    const others = dest.clips.filter(x => x !== c);
    let snapped = null;
    if (d.kind === 'move'){
      let at = Math.max(0, o.at + dt);
      const [s1, n1] = snapTo(at, -1, e.altKey, c.id), [s2, n2] = snapTo(at + len, -1, e.altKey, c.id);
      if (n1 != null){ at = s1; snapped = n1; } else if (n2 != null){ at = s2 - len; snapped = n2; }
      // no overlaps: stay in the gap the pointer is in
      const prev = others.filter(x => clipEnd(x) <= at + len / 2).reduce((m, x) => Math.max(m, clipEnd(x)), 0);
      const next = others.filter(x => x.at >= at + len / 2).reduce((m, x) => Math.min(m, x.at), Infinity);
      if (next - prev < len - .001) return;                  // doesn't fit here
      c.at = +Math.min(Math.max(at, prev), next - len).toFixed(3);
      if (dest !== d.track){ d.track.clips.splice(d.track.clips.indexOf(c), 1); dest.clips.push(c); d.track = dest; d.hit.t = dest; }
    } else if (d.kind === 'l'){
      const prev = others.filter(x => clipEnd(x) <= o.at + .001).reduce((m, x) => Math.max(m, clipEnd(x)), 0);
      let at = Math.min(Math.max(o.at + dt, o.at - o.in / sp, prev), o.at + len - .1);
      [at, snapped] = snapTo(at, -1, e.altKey, c.id);
      at = Math.min(Math.max(at, o.at - o.in / sp, prev), o.at + len - .1);
      c.in = +(o.in + (at - o.at) * sp).toFixed(3); c.at = +at.toFixed(3);
    } else {
      const next = others.filter(x => x.at >= clipEnd(o) - .001).reduce((m, x) => Math.min(m, x.at), Infinity);
      let end = Math.max(Math.min(clipEnd(o) + dt, o.at + (a.duration - o.in) / sp, next), o.at + .1);
      [end, snapped] = snapTo(end, -1, e.altKey, c.id);
      end = Math.max(Math.min(end, o.at + (a.duration - o.in) / sp, next), o.at + .1);
      c.out = +(o.in + (end - o.at) * sp).toFixed(3);
    }
    showSnap(snapped);
    relinkCaptions(); tlRender(); engineSync(true); schedulePreview();
  });
  const end = () => {
    const d = TL.clipDrag; if (!d) return;
    TL.clipDrag = null; showSnap(null);
    if (d.moved){ H.past.push(d.before); H.future = []; syncHist(); clipsChanged(); }
  };
  lanes.addEventListener('pointerup', end);
  lanes.addEventListener('pointercancel', end);
}

// ---------- tracks ----------
function initTrackHeads(){
  $('trackHeads').addEventListener('click', e => {
    const b = e.target.closest('.th-b'); if (!b) return;
    const t = trackOf(b.closest('.th').dataset.track); if (!t) return;
    const act = b.dataset.act;
    if (act === 'vol'){ openTrackVolume(b, t); return; }
    pushHistory();
    if (act === 'mute') t.mute = !t.mute || undefined;
    if (act === 'lock') t.locked = !t.locked || undefined;
    if (act === 'del'){
      const same = mediaTracks().filter(x => x.kind === t.kind);
      if (t.clips.length && !confirm(`Remove "${t.name}" and its ${t.clips.length} clip${t.clips.length > 1 ? 's' : ''}?`)){ H.past.pop(); syncHist(); return; }
      if (t.kind === 'video' && same.length === 1 && t.clips.length){ H.past.pop(); syncHist(); return toast('Keep at least one video track'); }
      PJ.doc.tracks.splice(PJ.doc.tracks.indexOf(t), 1);
    }
    TL.laneKey = ''; clipsChanged();
  });
}
function openTrackVolume(btn, t){
  document.querySelector('.vol-pop')?.remove();
  const pop = document.createElement('div'); pop.className = 'vol-pop';
  const r = btn.getBoundingClientRect();
  Object.assign(pop.style, {left: r.left + 'px', top: (r.bottom + 6) + 'px'});
  pop.append(slider('Volume', 'vol', 0, 2, .05, t.volume ?? 1, v => Math.round(v * 100) + '%', (v, live) => {
    begin(); if (v === 1) delete t.volume; else t.volume = v; if (!live) done();
    btn.querySelector('span').textContent = Math.round(v * 100); engineSync(); edited();
  }));
  document.body.append(pop);
  setTimeout(() => document.addEventListener('pointerdown', function away(ev){
    if (!pop.contains(ev.target)){ pop.remove(); document.removeEventListener('pointerdown', away); TL.laneKey = ''; tlRender(); }
  }), 0);
}
function addTrack(kind){
  pushHistory();
  const n = mediaTracks().filter(t => t.kind === kind).length + 1;
  const t = {id: newId(kind === 'video' ? 'v' : 'm'), kind, name: `${kind === 'video' ? 'Video' : 'Audio'} ${n}`, clips: []};
  const subIdx = PJ.doc.tracks.findIndex(x => x.kind === 'subtitle');
  // video tracks sit before the caption track (drawn under it); audio goes at the end
  if (kind === 'video') PJ.doc.tracks.splice(subIdx < 0 ? PJ.doc.tracks.length : subIdx, 0, t); else PJ.doc.tracks.push(t);
  TL.laneKey = ''; clipsChanged();
  return t;
}

// ---------- importing media ----------
function importFiles(files, dropAt, dropTrack){
  [...files].forEach(f => importOne(f, dropAt, dropTrack));
}
async function importOne(file, dropAt, dropTrack){
  if (!PJ.doc) return;
  PJ.dirty = true; await saveNow();
  const note = toastStay(`Adding ${file.name}… 0%`);
  const fd = new FormData(); fd.append('file', file);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', `/projects/${PJ.doc.id}/assets`);
  xhr.upload.onprogress = ev => ev.lengthComputable && note.set(`Adding ${file.name}… ${Math.round(ev.loaded / ev.total * 100)}%`);
  xhr.onload = () => {
    note.close();
    let r = {}; try { r = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status !== 200) return toast(r.error || 'Could not add that file');
    PJ.doc.assets.push(r.asset); PJ.rev = r.rev;
    placeAsset(r.asset, dropAt, dropTrack);
    loadPeaksFor(r.asset.id); loadFilmFor(r.asset.id);
    if (r.asset.w && r.asset.audio)
      toast(`${r.asset.name || 'Clip'} added`, {label: 'Caption its speech', run: () => transcribeAsset(r.asset.id)});
    else toast(`${r.asset.name || 'File'} added`);
  };
  xhr.onerror = () => { note.close(); toast('Upload failed'); };
  xhr.send(fd);
}
// Video goes on the end of the main video track (or where it was dropped); sound on an audio track.
function placeAsset(a, dropAt, dropTrack){
  pushHistory();
  let t = dropTrack && trackOf(dropTrack);
  if (t && (t.kind === 'video') !== !!a.w) t = null;
  if (!t){
    t = a.w ? mediaTracks().find(x => x.kind === 'video') : mediaTracks().find(x => x.kind === 'audio' && !x.clips.some(c => c.at < clock.currentTime + a.duration && clipEnd(c) > clock.currentTime));
    if (!t) t = addTrack(a.w ? 'video' : 'audio');
  }
  let at = dropAt != null ? dropAt : a.w ? t.clips.reduce((m, c) => Math.max(m, clipEnd(c)), 0) : clock.currentTime;
  // no overlap: slide to the first free spot
  for (const c of [...t.clips].sort((x, y) => x.at - y.at)) if (at < clipEnd(c) && at + a.duration > c.at) at = clipEnd(c);
  const c = {id: newId('c'), asset: a.id, in: 0, out: a.duration, at: +at.toFixed(3)};
  t.clips.push(c);
  TL.laneKey = '';
  selectClip({id: c.id});
  clipsChanged();
}
async function transcribeAsset(aid){
  let r;
  try {
    r = await fetch(`/projects/${PJ.doc.id}/assets/${aid}/transcribe`, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: PJ.doc.mode, words: +$('words').value})});
  } catch { return toast('Could not reach the server'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok){ toast(d.error || 'Could not caption that clip'); if (d.upgrade) openPlans(); return; }
  const note = toastStay('Captioning the clip…');
  const iv = setInterval(async () => {
    let j; try { j = await (await fetch('/status/' + d.job)).json(); } catch { return; }
    if (j.status === 'running'){ note.set(`${j.stage || 'Captioning…'} ${j.progress ? Math.round(j.progress * 100) + '%' : ''}`); return; }
    clearInterval(iv); note.close();
    if (j.status !== 'done') return toast(j.error || 'Captioning stopped');
    pushHistory();
    for (const cue of j.cues){
      const words = cue.text.split(/\s+/), wt = cue.wt && cue.wt.length === words.length ? cue.wt : null;
      const g = wrapCue({id: newId('g'), asset: aid, t0: cue.start, t1: cue.end, words: [], orig: cue.text, source: cue.source || ''});
      g.words = words.map((w, k) => ({id: newWordId(), t0: wt ? wt[k][0] : cue.start, t1: wt ? wt[k][1] : cue.end, text: w}));
      if (!wt){ g.words = []; g.text = cue.text; }
      (S.hidden = S.hidden || []).push(g);
    }
    clipsChanged(); renderCues(); loadAccount();
    toast(`${j.cues.length} captions added for the clip`);
  }, 1500);
}
// A toast that stays until closed (for uploads and long jobs).
function toastStay(msg){
  const el = document.createElement('div'); el.className = 'toast'; el.textContent = msg;
  $('toasts').append(el);
  return {set: m => { el.textContent = m; }, close: () => el.remove()};
}

// ---------- the frame: size and fit ----------
const FORMATS = [['9:16', 1080, 1920, 'Reels, Shorts'], ['1:1', 1080, 1080, 'Square'], ['4:5', 1080, 1350, 'Feed'], ['16:9', 1920, 1080, 'YouTube']];
function frameLabel(){
  const c = PJ.doc.canvas, f = FORMATS.find(([, w, h]) => w === c.w && h === c.h);
  return `${f ? f[0] : `${c.w}×${c.h}`} · ${c.fit === 'fill' ? 'Fill' : 'Fit'}`;
}
function applyFrame(){
  const c = PJ.doc.canvas;
  player.style.setProperty('--ar', c.w / c.h);
  $('mediaLayer').dataset.fit = c.fit || 'fit';
  $('frameBtn').querySelector('span').textContent = frameLabel();
  S.format = c.h >= c.w ? 'vertical' : 'horizontal';
  document.body.dataset.fmt = S.format;
  $('tplRow').classList.toggle('wide', S.format === 'horizontal');
}
function openFrameMenu(){
  const m = $('frameMenu');
  if (!m.hidden){ m.hidden = true; return; }
  const c = PJ.doc.canvas, a = PJ.doc.assets.find(x => x.w);
  const opts = [...FORMATS]; if (a) opts.push(['Original', a.w, a.h, `${a.w}×${a.h}`]);
  m.replaceChildren(...opts.map(([label, w, h, hint]) => {
    const b = document.createElement('button'); b.type = 'button'; b.setAttribute('role', 'menuitemradio');
    b.setAttribute('aria-checked', String(c.w === w && c.h === h));
    b.innerHTML = `<i class="fr" style="aspect-ratio:${w}/${h}"></i><span><b></b><small></small></span>`;
    b.querySelector('b').textContent = label; b.querySelector('small').textContent = hint;
    b.onclick = () => setFrame({w, h}); return b;
  }));
  const fit = document.createElement('div'); fit.className = 'seg fit-seg';
  for (const [v, l] of [['fit', 'Fit (whole picture)'], ['fill', 'Fill (crop to frame)']]){
    const b = document.createElement('button'); b.type = 'button'; b.textContent = l; b.setAttribute('aria-pressed', String((c.fit || 'fit') === v));
    b.onclick = () => setFrame({fit: v}); fit.append(b);
  }
  m.append(fit);
  m.hidden = false;
}
function setFrame(ch){
  pushHistory();
  Object.assign(PJ.doc.canvas, ch);
  $('frameMenu').hidden = true;
  applyFrame(); edited(); schedulePreview(true); updateOverlay(true);
  setTimeout(() => { resizeAss(); drawHits(true); }, 50);
}

function initClips(){
  initClipDrag(); initTrackHeads();
  $('addVideoTrack').onclick = () => { addTrack('video'); };
  $('addAudioTrack').onclick = () => { addTrack('audio'); };
  $('importBtn').onclick = $('railMedia').onclick = () => $('importFile').click();
  $('importFile').onchange = () => { importFiles($('importFile').files); $('importFile').value = ''; };
  $('clipSplitBtn').onclick = () => splitClipAt(clock.currentTime);
  $('frameBtn').onclick = e => { e.stopPropagation(); openFrameMenu(); };
  document.addEventListener('click', e => { if (!e.target.closest('#frameMenu, #frameBtn')) $('frameMenu').hidden = true; });
  // drop files straight onto the timeline (onto a lane, at that time)
  const tl = $('timeline');
  tl.addEventListener('dragover', e => { if (e.dataTransfer?.types?.includes('Files')){ e.preventDefault(); tl.classList.add('drop-on'); } });
  tl.addEventListener('dragleave', e => { if (!tl.contains(e.relatedTarget)) tl.classList.remove('drop-on'); });
  tl.addEventListener('drop', e => {
    e.preventDefault(); tl.classList.remove('drop-on');
    const lane = document.elementsFromPoint(e.clientX, e.clientY).find(el => el.classList?.contains('lane'));
    importFiles(e.dataTransfer.files, lane ? Math.max(0, timeAt(e.clientX)) : null, lane?.dataset.track);
  });
}
