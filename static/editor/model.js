// The project: caption lines made of words (each with its own time and style), supers,
// the track's look, saving to the server, and opening saved projects.
'use strict';

// A caption line. Words are the real data, timed in their media file ("asset time");
// start/end/wt are views in *timeline* time, through the clip that shows that stretch of the
// file. So moving, trimming or cutting a clip moves its captions with it, and the rest of the
// editor keeps thinking in lines on the timeline.
const CL = {v: 0};                       // bumped whenever clips change
const CLIPCACHE = new WeakMap();
function clipOfCue(c){
  const hit = CLIPCACHE.get(c);
  if (hit && hit.v === CL.v) return hit.clip;
  let best = null, bestOver = 0;
  if (typeof PJ !== 'undefined' && PJ.doc){
    for (const t of PJ.doc.tracks) if (t.kind === 'video' || t.kind === 'audio') for (const k of t.clips){
      if (k.asset !== (c.asset || 'a1')) continue;
      const over = Math.min(c.t1, k.out) - Math.max(c.t0, k.in);
      if (over > bestOver){ best = k; bestOver = over; }
    }
  } else best = {in: 0, out: 1e9, at: 0};
  CLIPCACHE.set(c, {v: CL.v, clip: best});
  return best;
}
class Cue {
  constructor(g){ Object.assign(this, g); if (!this.words) this.words = []; }
  // the clip showing this line (file time <-> timeline time go through it: toTL / toAsset)
  get clip(){ return clipOfCue(this); }
  get start(){ const k = clipOfCue(this); return k ? toTL(k, Math.max(this.t0, k.in)) : NaN; }
  set start(v){ const k = clipOfCue(this); if (k) this.t0 = +toAsset(k, v).toFixed(3); }
  get end(){ const k = clipOfCue(this); return k ? toTL(k, Math.min(this.t1, k.out)) : NaN; }
  set end(v){ const k = clipOfCue(this); if (k) this.t1 = +toAsset(k, v).toFixed(3); }
  get text(){ return this.words.map(w => w.text).join(' '); }
  set text(v){ this.words = rewords(this, v); }
  get wt(){ const k = clipOfCue(this); return this.words.map(w => k ? [toTL(k, w.t0), toTL(k, w.t1)] : [NaN, NaN]); }
  set wt(v){ const k = clipOfCue(this); if (Array.isArray(v) && k) v.forEach((p, i) => { if (this.words[i] && p){ this.words[i].t0 = +toAsset(k, p[0]).toFixed(3); this.words[i].t1 = +toAsset(k, p[1]).toFixed(3); } }); }
}
// Captions whose media is cut away are kept (hidden), so undo or a longer clip brings them back.
function relinkCaptions(){
  CL.v++;
  const all = [...S.cues, ...(S.hidden || [])];
  const shown = all.filter(c => !isNaN(c.start) && c.end > c.start);
  S.hidden = all.filter(c => !shown.includes(c));
  shown.sort((a, b) => a.start - b.start);
  const sel = S.cues[S.sel];
  const sameOrder = shown.length === S.cues.length && shown.every((c, i) => c === S.cues[i]);
  S.cues = shown;
  if (!sameOrder){ S.sel = sel ? S.cues.indexOf(sel) : -1; S.current = -1; renderCues(); }
}
const wrapCue = g => g instanceof Cue ? g : new Cue(g);
const newWordId = () => 'w' + (S.nextId = (S.nextId || 0) + 1);

// Edited text -> words. Words that didn't change keep their timing and style; new or changed
// words share the time of the words they replace (by length), so timing never jumps.
function rewords(cue, text){
  const old = cue.words, toks = text.trim().split(/\s+/).filter(Boolean);
  const n = old.length, m = toks.length;
  const L = Array.from({length: n + 1}, () => new Int16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = old[i].text === toks[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  const flush = (oi, oj, ni, nj) => {           // replace old[oi..oj) with toks[ni..nj)
    if (nj <= ni) return;
    const prev = out[out.length - 1], next = old[oj];
    let t0 = oj > oi ? old[oi].t0 : (prev ? prev.t1 : cue.t0);
    let t1 = oj > oi ? old[oj - 1].t1 : (next ? next.t0 : cue.t1);
    if (t1 - t0 < .08 * (nj - ni)){             // no room: borrow half of the neighbour's time
      const nb = prev || null;
      if (nb && nb.t1 - nb.t0 > .16){ const mid = (nb.t0 + nb.t1) / 2; t0 = mid; nb.t1 = mid; }
      t1 = Math.max(t1, t0 + .08 * (nj - ni));
    }
    const lens = toks.slice(ni, nj).map(t => t.length), total = lens.reduce((a, b) => a + b, 0) || 1;
    let t = t0;
    for (let k = ni; k < nj; k++){
      const d = (t1 - t0) * lens[k - ni] / total, src = old[oi + (k - ni)] || old[oi];
      const w = {id: oj - oi === nj - ni && src ? src.id : newWordId(), t0: +t.toFixed(3), t1: +(t + d).toFixed(3), text: toks[k]};
      if (src && src.o && oj > oi) w.o = {...src.o};
      out.push(w); t += d;
    }
  };
  let oi = 0, ni = 0;
  while (i < n && j < m){
    if (old[i].text === toks[j]){ flush(oi, i, ni, j); out.push({...old[i]}); i++; j++; oi = i; ni = j; }
    else if (L[i + 1][j] >= L[i][j + 1]) i++;
    else j++;
  }
  flush(oi, n, ni, m);
  return out;
}

// ---------- the project document ----------
const PJ = {doc: null, dirty: false, saving: false, timer: 0, rev: 0};
const subTrack = () => PJ.doc && PJ.doc.tracks.find(t => t.kind === 'subtitle');
const superTrack = () => PJ.doc && PJ.doc.tracks.find(t => t.kind === 'super');

// The editor's live state written back into the document (what gets saved and previewed).
function currentDoc(){
  const d = PJ.doc; if (!d) return null;
  const st = subTrack();
  if (st){ st.groups = [...S.cues, ...(S.hidden || [])]; st.style = {...CAP}; }
  const sp = superTrack();
  if (sp) sp.supers = S.supers;
  d.nextId = S.nextId;
  return d;
}

function markDirty(){
  if (!PJ.doc) return;
  PJ.dirty = true; setSaveState('unsaved');
  clearTimeout(PJ.timer); PJ.timer = setTimeout(saveNow, 1500);
}
async function saveNow(){
  clearTimeout(PJ.timer);
  if (!PJ.doc || !PJ.dirty || PJ.saving) return;
  PJ.saving = true; PJ.dirty = false; setSaveState('saving');
  try {
    const r = await fetch('/projects/' + PJ.doc.id, {method: 'PUT', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({project: currentDoc(), rev: PJ.rev})});
    const d = await r.json().catch(() => ({}));
    if (r.status === 409){
      setSaveState('conflict');
      toast('This project was changed in another tab', {label: 'Reload', run: () => location.reload()});
      return;
    }
    if (!r.ok) throw new Error(d.error || r.status);
    PJ.rev = d.rev; setSaveState(PJ.dirty ? 'unsaved' : 'saved');
  } catch {
    PJ.dirty = true; setSaveState('offline');
    PJ.timer = setTimeout(saveNow, 5000);
  } finally {
    PJ.saving = false;
    if (PJ.dirty && PJ.timer === 0) markDirty();
  }
}
function setSaveState(s){
  const el = $('saveState'); if (!el) return;
  el.dataset.state = s;
  el.lastChild.textContent = {saved: 'Saved', saving: 'Saving…', unsaved: 'Edited', offline: 'Offline, retrying', conflict: 'Changed elsewhere'}[s];
}
addEventListener('beforeunload', () => {
  if (PJ.dirty && PJ.doc) navigator.sendBeacon?.('/projects/' + PJ.doc.id + '/beacon', new Blob([JSON.stringify({project: currentDoc(), rev: PJ.rev})], {type: 'application/json'}));
});

// Called whenever the look of the captions changes (template, colour, font, size, place...).
function capChanged(){
  if (capFormat) store.set(capKey(capFormat), CAP);       // also the default for new projects
  markDirty(); schedulePreview();
}
// Called after any change to captions or supers.
function edited(){ markDirty(); schedulePreview(); }

// ---------- opening ----------
async function openProjectById(pid, {fresh = false} = {}){
  let r;
  try { r = await fetch('/projects/' + pid); } catch { return toast('Could not load the project'); }
  if (!r.ok) return toast('That project is no longer available');
  openProject(await r.json(), {fresh});
}
function openProject(doc, {fresh = false} = {}){
  PJ.doc = doc; PJ.rev = doc.rev; PJ.dirty = false;
  S.pid = doc.id; S.nextId = doc.nextId || 1000;
  const asset = doc.assets[0], st = subTrack(), sp = superTrack();
  S.baseName = doc.name; S.language = doc.language; S.mode = doc.mode || 'hinglish';
  if (fresh && S.videoUrl) S.localUrl = S.videoUrl;   // play the file from this computer, not the server
  else S.localUrl = null;
  if (!S.file || !S.videoUrl){                         // reopened from the list: stream it from the server
    S.file = {name: asset.file, size: 0, fromServer: true};
    S.videoUrl = `/projects/${doc.id}/media/${asset.id}`;
    video.src = S.videoUrl;
    $('drop').hidden = true; $('loaded').hidden = false;
    $('fnameStart').textContent = doc.name; $('fnameEnd').textContent = '';
    $('emptyState').hidden = true; $('prep').hidden = false;
  }
  doc.canvas.fit = doc.canvas.fit || 'fit';
  engineReset(); TL.film = {}; TL.peaks = {}; TL.laneKey = ''; CL.v++;
  S.playable = true;
  // the look: a fresh project takes this format's last-used look; a saved one its own
  const fmt = asset.w && asset.h ? (asset.h >= asset.w ? 'vertical' : 'horizontal') : 'vertical';
  if (!fresh && st && st.style){ capFormat = null; useFormat(fmt); Object.keys(CAP).forEach(k => delete CAP[k]); Object.assign(CAP, st.style); }
  else useFormat(fmt);
  S.supers = sp ? sp.supers : [];
  S.cues = (st ? st.groups : []).map(wrapCue); S.hidden = [];
  relinkCaptions();
  S.duration = tlDuration();
  S.sel = -1; S.selWords = new Set(); S.selSuper = null;
  history.replaceState(null, '', '/app?p=' + doc.id);
  renderCues(); refreshTrack(); syncFooter(); applyCaptionStyle();
  resetHistory(); resetExport();
  S.resultJob = null;
  enterEditor();
  applyFrame(); loadMediaVisuals();
  setSaveState('saved');
  if (fresh){ markDirty(); toast(`${S.cues.length} captions ready · saved to your projects`); }
  schedulePreview(true);
}

// ---------- recent projects (on the upload screen) ----------
async function loadRecent(){
  const box = $('recent'); if (!box) return;
  let d;
  try { d = await (await fetch('/projects')).json(); } catch { return; }
  const list = d.projects || [];
  box.hidden = !list.length;
  $('recentList').replaceChildren(...list.slice(0, 12).map(p => {
    const b = document.createElement('div'); b.className = 'proj';
    const open = document.createElement('button'); open.type = 'button'; open.className = 'proj-open';
    const shape = p.canvas.h >= p.canvas.w ? 'v' : 'h';
    const days = Math.max(0, Math.ceil((p.expires - Date.now() / 1000) / 86400));
    open.innerHTML = `<span class="proj-shape ${shape}"></span><span class="proj-txt"><b></b><small></small></span>`;
    open.querySelector('b').textContent = p.name;
    open.querySelector('small').textContent = `${p.captions} captions · ${hms(p.duration)} · ${ago(p.updated)} · kept ${days} more day${days === 1 ? '' : 's'}`;
    open.onclick = () => { clearFile(); openProjectById(p.id); };
    const del = document.createElement('button'); del.type = 'button'; del.className = 'icon-btn danger'; del.title = 'Delete project';
    del.setAttribute('aria-label', `Delete ${p.name}`);
    del.innerHTML = '<svg width="15" height="15" aria-hidden="true"><use href="#i-trash"/></svg>';
    del.onclick = async () => {
      if (!confirm(`Delete "${p.name}" and its video from your projects?`)) return;
      await fetch('/projects/' + p.id, {method: 'DELETE'}).catch(() => {});
      loadRecent();
    };
    b.append(open, del);
    return b;
  }));
}
function ago(ts){
  const s = Date.now() / 1000 - ts;
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
