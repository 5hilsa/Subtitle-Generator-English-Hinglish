// Selection and the Style panel. Pick words (click, Shift for a range, ⌘/Ctrl to add),
// a whole line, a super, or nothing for all captions; the panel edits exactly that.
'use strict';

const INS = {scope: 'all', pushed: false};
const SUPER_LOOKS = [['plain', 'Bold'], ['label', 'Label'], ['hook', 'Hook'], ['lower', 'Name tag'], ['neon', 'Neon']];
const ENTER = [['none', 'None'], ['pop', 'Pop'], ['scale', 'Zoom'], ['fade', 'Fade'], ['slide-up', 'Rise'], ['slide-down', 'Drop']];
const ACT = [['none', 'None'], ['color', 'Colour'], ['box', 'Box'], ['scale', 'Grow']];
const PALETTE = ['#FFFFFF', '#FFE81F', '#A6F24D', '#43FF6E', '#1E8DEB', '#5B6CFF', '#BD6CF7', '#FF4D6D', '#F7931E', '#111111'];

// ---------- selection ----------
function findWord(wid){
  for (const c of S.cues) for (const w of c.words) if (w.id === wid) return {w, cue: c};
  for (const sp of S.supers || []) for (const w of sp.words) if (w.id === wid) return {w, sup: sp};
  return null;
}
function selectWord(i, wid, {shift, add}){
  const c = S.cues[i]; if (!c) return;
  if (!S.selWords) S.selWords = new Set();
  if (shift && S.selAnchor && S.cues[S.sel] === c){
    const ids = c.words.map(w => w.id), a = ids.indexOf(S.selAnchor), b = ids.indexOf(wid);
    if (a >= 0 && b >= 0){ S.selWords = new Set(ids.slice(Math.min(a, b), Math.max(a, b) + 1)); }
  } else if (add){
    S.selWords.has(wid) ? S.selWords.delete(wid) : S.selWords.add(wid);
    S.selAnchor = wid;
  } else { S.selWords = new Set([wid]); S.selAnchor = wid; }
  S.selSuper = null; S.selClip = null;
  if (S.sel !== i) select(i, false); else { refreshWordMarks(); drawHits(true); }
  setScope(S.selWords.size ? 'words' : 'line');
}
function selectSuper(id){
  S.selSuper = id; S.selWords = new Set(); S.selClip = null;
  if (S.sel >= 0) select(-1, false);
  setScope('super'); superLaneRender(); drawHits(true);
}
function clearSelection(){
  S.selWords = new Set(); S.selSuper = null; S.selClip = null;
  if (S.sel >= 0) select(-1, false);
  setScope('all'); refreshWordMarks(); superLaneRender(); drawHits(true);
}
function refreshWordMarks(){
  document.querySelectorAll('#cues .w.picked').forEach(w => w.classList.remove('picked'));
  if (!S.selWords?.size) return;
  document.querySelectorAll('#cues .w[data-wid]').forEach(w => { if (S.selWords.has(w.dataset.wid)) w.classList.add('picked'); });
}

// ---------- scope ----------
function setScope(scope){
  if (scope === 'line' && S.sel < 0) scope = 'all';
  INS.scope = scope;
  if (scope === 'words' || scope === 'super') sideTab(true);
  inspectorSync();
}
function targets(){
  if (INS.scope === 'words') return [...S.selWords].map(findWord).filter(Boolean).map(f => f.w);
  if (INS.scope === 'line') return S.cues[S.sel] ? [S.cues[S.sel]] : [];
  if (INS.scope === 'super') { const sp = S.supers.find(s => s.id === S.selSuper); return sp ? [sp] : []; }
  return [];
}
const firstO = () => (targets()[0] || {}).o || {};
function begin(){ if (!INS.pushed){ pushHistory(); INS.pushed = true; } }
function done(){ INS.pushed = false; }
function setO(key, value, keepOpen){
  const ts = targets(); if (!ts.length) return;
  begin();
  for (const t of ts){
    const o = {...(t.o || {})};
    if (value == null || value === false && key !== 'upper') delete o[key]; else o[key] = value;
    if (Object.keys(o).length) t.o = o; else delete t.o;
  }
  if (!keepOpen) done();
  afterStyle();
}
function setAnim(key, value){
  begin();
  const ts = INS.scope === 'all' ? [CAP] : targets();
  for (const t of ts){
    const a = {...(t.anim || {})};
    if (value == null) delete a[key]; else a[key] = value;
    if (Object.keys(a).length) t.anim = a; else delete t.anim;
  }
  done();
  INS.scope === 'all' ? capChanged() : edited();
  inspectorSync();
}
function afterStyle(){
  edited(); inspectorSync();
  if (INS.scope === 'line' || INS.scope === 'words'){ const r = $('cues').children[S.sel]; if (r) renderRow(r, S.sel); refreshWordMarks(); }
  if (INS.scope === 'super') superLaneRender();
}

// ---------- the panel ----------
function el(tag, cls, html){ const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function chipRow(items, current, onPick){
  const row = el('div', 'chips2');
  for (const [v, label] of items){
    const b = el('button', '', ''); b.type = 'button'; b.textContent = label;
    b.setAttribute('aria-pressed', String(v === current)); b.onclick = () => onPick(v);
    row.append(b);
  }
  return row;
}
function colourRow(current, onPick, allowNone = true){
  const row = el('div', 'swatches');
  for (const c of PALETTE){
    const b = el('button', 'swatch'); b.type = 'button'; b.style.background = c; b.title = c;
    b.setAttribute('aria-label', 'Colour ' + c); b.setAttribute('aria-pressed', String((current || '').slice(0, 7).toUpperCase() === c));
    b.onclick = () => onPick(c); row.append(b);
  }
  const custom = el('label', 'swatch custom'); custom.title = 'Any colour';
  const inp = el('input'); inp.type = 'color'; inp.value = (current || '#ffffff').slice(0, 7).toLowerCase();
  inp.setAttribute('aria-label', 'Pick any colour'); inp.onchange = () => onPick(inp.value.toUpperCase());
  custom.append(inp); row.append(custom);
  if (allowNone){
    const x = el('button', 'swatch none', ''); x.type = 'button'; x.title = 'None'; x.setAttribute('aria-label', 'No colour');
    x.setAttribute('aria-pressed', String(!current)); x.onclick = () => onPick(null); row.append(x);
  }
  return row;
}
// A swatch that opens a small palette: keeps the panel short.
function colourPick(label, current, onPick){
  const wrap = el('div', 'pick');
  const btn = el('button', 'pick-btn'); btn.type = 'button';
  btn.innerHTML = `<i class="pick-sw${current ? '' : ' none'}"></i><span>${label}</span>`;
  if (current) btn.querySelector('i').style.background = current.slice(0, 7);
  btn.setAttribute('aria-haspopup', 'true'); btn.setAttribute('aria-expanded', 'false');
  const pop = el('div', 'pick-pop'); pop.hidden = true;
  pop.append(colourRow(current, c => { pop.hidden = true; onPick(c); }));
  btn.onclick = e => {
    e.stopPropagation();
    document.querySelectorAll('.pick-pop').forEach(p => { if (p !== pop) p.hidden = true; });
    pop.hidden = !pop.hidden; btn.setAttribute('aria-expanded', String(!pop.hidden));
  };
  wrap.append(btn, pop);
  return wrap;
}
document.addEventListener('click', e => { if (!e.target.closest('.pick')) document.querySelectorAll('.pick-pop').forEach(p => p.hidden = true); });
function slider(label, icon, min, max, step, value, fmt, onInput){
  const wrap = el('label', 'sl');
  wrap.append(el('span', 'sl-k', `<svg width="14" height="14"><use href="#i-${icon}"/></svg>${label}`));
  const inp = el('input', 'fancy'); Object.assign(inp, {type: 'range', min, max, step, value});
  const out = el('output', '', fmt(value));
  const paint = () => inp.style.setProperty('--p', ((inp.value - min) / (max - min) * 100) + '%');
  paint();
  inp.oninput = () => { out.textContent = fmt(+inp.value); paint(); onInput(+inp.value, true); };
  inp.onchange = () => { onInput(+inp.value, false); };
  wrap.append(inp, out);
  return wrap;
}
function prop(label, body){
  const p = el('div', 'prop prop-stack'); p.append(el('span', 'lbl', label)); p.append(body); return p;
}

function inspectorSync(){
  const bar = $('scopeBar'), panel = $('scopePanel'); if (!bar) return;
  const s = INS.scope, nWords = S.selWords?.size || 0;
  // scope switcher
  const opts = [['all', 'All captions']];
  if (S.sel >= 0) opts.push(['line', `Line ${S.sel + 1}`]);
  if (nWords) opts.push(['words', nWords === 1 ? '1 word' : `${nWords} words`]);
  if (S.selSuper) opts.push(['super', 'Text']);
  if (S.selClip) opts.push(['clip', 'Clip']);
  bar.replaceChildren(...opts.map(([v, label]) => {
    const b = el('button'); b.type = 'button'; b.textContent = label; b.setAttribute('aria-pressed', String(v === s));
    b.onclick = () => setScope(v); return b;
  }));
  $('trackProps').hidden = s !== 'all';
  panel.replaceChildren();
  if (s === 'clip'){ panel.append(...clipPanel()); return; }
  // animation for the whole track lives here too
  if (s === 'all'){
    panel.append(animProps(CAP.anim || {}, true), presetProps());
    return;
  }
  const o = firstO(), body = el('div', 'props');
  if (s === 'super'){
    const sp = targets()[0];
    const text = el('input', 'super-text'); text.id = 'superText'; text.value = sp.words.map(w => w.text).join(' ');
    text.placeholder = 'Type your text'; text.setAttribute('aria-label', 'Text');
    text.onfocus = () => begin();
    text.oninput = () => { setSuperText(sp, text.value); edited(); superLaneRender(); };
    text.onblur = done;
    const row = el('div'); row.append(text);
    row.append(chipRow(SUPER_LOOKS, sp.template || 'plain', v => { begin(); sp.template = v; done(); afterStyle(); }));
    body.append(prop('Text', row));
  }
  const fontBtn = el('button', 'font-btn', `<span>${o.font ? (fontOf(o.font)?.label || o.font) : 'Same as captions'}</span><svg width="16" height="16"><use href="#i-chev"/></svg>`);
  fontBtn.type = 'button'; fontBtn.onclick = () => { INS.fontTarget = s; $('fontBtn').click(); };
  if (o.font) fontBtn.querySelector('span').style.fontFamily = `'F-${o.font}', Manrope`;
  const fontRow = el('div', 'row2'); fontRow.append(fontBtn);
  const toggles = el('div', 'chips2');
  for (const [k, label, title] of [['bold', 'B', 'Bold'], ['italic', 'I', 'Italic'], ['upper', 'AA', 'Capitals']]){
    const b = el('button', 'tog ' + k); b.type = 'button'; b.textContent = label; b.title = title;
    b.setAttribute('aria-pressed', String(!!o[k])); b.onclick = () => setO(k, !o[k] || null);
    toggles.append(b);
  }
  fontRow.append(toggles);
  body.append(prop('Font', fontRow));
  const cols = el('div', 'stack');
  const picks = el('div', 'picks');
  picks.append(colourPick('Text', o.color, c => setO('color', c)),
               colourPick('Outline', o.stroke, c => setO('stroke', c)),
               colourPick('Shadow', o.shadow, c => setO('shadow', c)),
               colourPick('Box', o.box, c => setO('box', c && c.length === 7 ? c + 'F0' : c)));
  cols.append(picks);
  cols.append(slider('Outline', 'type', 0, .3, .01, o.strokeW ?? .06, v => Math.round(v * 100) + '', (v, live) => setO('strokeW', v, live)));
  body.append(prop('Colours', cols));
  const adj = el('div', 'sliders');
  adj.append(slider('Size', 'maximize', .3, 3, .05, o.size ?? 1, v => Math.round(v * 100) + '%', (v, live) => setO('size', v === 1 ? null : v, live)));
  if (s === 'words') adj.append(slider('Scale', 'maximize', .5, 2.5, .05, o.scale ?? 1, v => Math.round(v * 100) + '%', (v, live) => setO('scale', v === 1 ? null : v, live)));
  if (s !== 'super') adj.append(slider('Lift', 'arrows-v', -2, 2, .05, -(o.dy ?? 0), v => (v > 0 ? '+' : '') + v.toFixed(2), (v, live) => setO('dy', v === 0 ? null : -v, live)));
  adj.append(slider('Tilt', 'undo', -45, 45, 1, o.rotate ?? 0, v => v + '°', (v, live) => setO('rotate', v === 0 ? null : v, live)));
  body.append(prop('Adjust', adj));
  if (s === 'words'){
    body.append(prop('Entrance', chipRow(ENTER, o.in || 'none', v => setO('in', v === 'none' ? null : v))));
  } else {
    body.append(animProps(targets()[0]?.anim || {}, false));
  }
  if (s === 'line' || s === 'super'){
    const t = targets()[0], pl = t.place || (s === 'line' && CAP.x != null ? {x: CAP.x, y: CAP.y} : capPlace());
    const pos = el('div', 'sliders');
    const upd = (k, v, live) => { begin(); t.place = {...(t.place || pl), [k]: v / 100}; if (!live) done(); edited(); };
    pos.append(slider('Across', 'arrows-h', 0, 100, 1, Math.round(pl.x * 100), v => v + '%', (v, live) => upd('x', v, live)));
    pos.append(slider('Down', 'arrows-v', 0, 100, 1, Math.round(pl.y * 100), v => v + '%', (v, live) => upd('y', v, live)));
    const p = prop('Position', pos);
    if (s === 'line' && t.place){
      const back = el('button', 'reset-link', '<svg width="13" height="13"><use href="#i-undo"/></svg>Same spot as all captions');
      back.type = 'button'; back.onclick = () => { begin(); delete t.place; done(); afterStyle(); };
      p.append(back);
    }
    body.append(p);
  }
  const foot = el('div', 'ins-foot');
  const reset = el('button', 'btn sm', 'Clear styling here'); reset.type = 'button';
  reset.onclick = () => { begin(); targets().forEach(t => { delete t.o; if (s !== 'words') delete t.anim; }); done(); afterStyle(); };
  foot.append(reset);
  if (s === 'words' || s === 'line'){
    const cut = el('button', 'btn sm danger', '<svg width="14" height="14"><use href="#i-cut-clip"/></svg>' +
                 (s === 'words' ? 'Remove these words from the video' : 'Remove this line from the video'));
    cut.type = 'button'; cut.title = 'Cuts this part out of the video (Shift+Delete)'; cut.onclick = removeTextFromVideo;
    foot.append(cut);
  }
  if (s === 'super'){
    const del = el('button', 'btn sm danger', 'Delete text'); del.type = 'button'; del.onclick = () => deleteSuper(S.selSuper);
    foot.append(del);
  }
  panel.append(body, presetProps(), foot);
}
// The selected clip: its sound, fades, and edits.
function clipPanel(){
  const hit = selectedClip(); if (!hit) return [];
  const {t, c} = hit, a = assetOf(c.asset), out = [];
  const head = el('div', 'clip-head');
  head.innerHTML = `<b></b><small></small>`;
  head.querySelector('b').textContent = (a && (a.name || a.file)) || 'Clip';
  head.querySelector('small').textContent = `${t.name} · starts ${fine(c.at)} · ${fine(clipLen(c))} long${spd(c) !== 1 ? ` at ${spd(c)}×` : ''} · from ${fine(c.in)} of the file`;
  out.push(head);
  const body = el('div', 'props');
  if (!a || a.audio !== false){
    const snd = el('div', 'sliders');
    snd.append(slider('Volume', 'vol', 0, 2, .05, c.volume ?? 1, v => Math.round(v * 100) + '%', (v, live) => setClip('volume', v === 1 ? null : v, live)));
    const len = clipLen(c);
    snd.append(slider('Fade in', 'arrows-h', 0, Math.min(5, len / 2), .1, c.fadeIn ?? 0, v => v.toFixed(1) + 's', (v, live) => setClip('fadeIn', v || null, live)));
    snd.append(slider('Fade out', 'arrows-h', 0, Math.min(5, len / 2), .1, c.fadeOut ?? 0, v => v.toFixed(1) + 's', (v, live) => setClip('fadeOut', v || null, live)));
    const mute = el('button', 'reset-link', `<svg width="13" height="13"><use href="#i-${c.mute ? 'vol' : 'mute'}"/></svg>${c.mute ? 'Unmute this clip' : 'Mute this clip'}`);
    mute.type = 'button'; mute.onclick = () => { begin(); c.mute = !c.mute || undefined; done(); engineSync(); tlRender(); edited(); inspectorSync(); };
    snd.append(mute);
    body.append(prop('Sound', snd));
  }
  body.append(...clipEditProps(t, c));
  const acts = el('div', 'ins-foot');
  const split = el('button', 'btn sm', '<svg width="14" height="14"><use href="#i-scissors"/></svg>Split at playhead'); split.type = 'button';
  split.onclick = () => splitClipAt(clock.currentTime);
  const del = el('button', 'btn sm danger', 'Delete, close the gap'); del.type = 'button'; del.onclick = () => deleteClip(S.selClip, false);
  const gap = el('button', 'btn sm', 'Delete, leave a gap'); gap.type = 'button'; gap.onclick = () => deleteClip(S.selClip, true);
  acts.append(split, del, gap);
  body.append(prop('Edit', acts));
  const hasCaps = [...S.cues, ...(S.hidden || [])].some(g => (g.asset || 'a1') === c.asset);
  if (a && a.w && a.audio !== false && !hasCaps){
    const cap = el('button', 'btn sm primary', '<svg width="14" height="14"><use href="#i-captions"/></svg>Caption this clip\'s speech'); cap.type = 'button';
    cap.onclick = () => transcribeAsset(c.asset);
    body.append(prop('Captions', cap));
  }
  out.push(body);
  return out;
}
function animProps(a, track){
  const box = el('div', 'stack');
  box.append(el('span', 'mini-lbl', 'Entrance'));
  box.append(chipRow(ENTER, a.in || '', v => setAnim('in', v)));
  if (INS.scope !== 'super'){
    box.append(el('span', 'mini-lbl', 'Spoken word'));
    box.append(chipRow(ACT, a.active || '', v => setAnim('active', v)));
    if (a.active && a.active !== 'none' && a.active !== 'scale') box.append(colourRow(a.color, c => setAnim('color', c), false));
  }
  const p = prop(track ? 'Animation (all captions)' : 'Animation', box);
  p.classList.add('anim-prop');
  return p;
}

// ---------- presets: save a look, put it on anything ----------
function presets(){ return store.get('presets') || []; }
function presetProps(){
  const box = el('div', 'stack'), list = presets();
  const row = el('div', 'chips2 presets');
  list.forEach((p, n) => {
    const b = el('button'); b.type = 'button'; b.textContent = p.name; b.title = 'Apply to ' + scopeName();
    b.onclick = () => applyPreset(p);
    b.oncontextmenu = e => { e.preventDefault(); if (confirm(`Delete preset "${p.name}"?`)){ list.splice(n, 1); store.set('presets', list); inspectorSync(); } };
    row.append(b);
  });
  if (!list.length) row.append(el('span', 'hint', 'Save a look here and put it on any word, line or text.'));
  box.append(row);
  if (INS.scope !== 'all'){
    const save = el('button', 'reset-link', '<svg width="13" height="13"><use href="#i-plus"/></svg>Save this look'); save.type = 'button';
    save.onclick = () => {
      const t = targets()[0]; if (!t) return;
      const name = prompt('Name this look', `Look ${list.length + 1}`); if (!name) return;
      list.push({name: name.slice(0, 24), o: {...(t.o || {})}, anim: t.anim ? {...t.anim} : undefined});
      store.set('presets', list); inspectorSync(); toast('Look saved');
    };
    box.append(save);
  }
  return prop('My looks', box);
}
const scopeName = () => ({all: 'all captions', line: 'this line', words: 'the selected words', super: 'this text'})[INS.scope];
function applyPreset(p){
  begin();
  if (INS.scope === 'all'){ S.cues.forEach(c => { c.o = {...(c.o || {}), ...p.o}; if (p.anim) c.anim = {...p.anim}; }); }
  else targets().forEach(t => { t.o = {...(t.o || {}), ...p.o}; if (p.anim && INS.scope !== 'words') t.anim = {...p.anim}; });
  done(); afterStyle(); renderCues(); toast(`"${p.name}" applied to ${scopeName()}`);
}

// Fonts picked in the dialog go to the selection when one is being styled.
function pickFontForScope(key){
  if (INS.scope === 'all' || !INS.fontTarget) return false;
  INS.fontTarget = null; setO('font', key); return true;
}
