// Supers: on-screen text that isn't a caption (a name, a hook, a key point). Each has its own
// time, place, look and animation, on its own "Text" track, so it never clashes with captions.
'use strict';

function setSuperText(sp, text){
  const toks = text.trim().split(/\s+/).filter(Boolean);
  const old = sp.words;
  sp.words = (toks.length ? toks : ['Text']).map((t, i) => {
    const w = {id: old[i] ? old[i].id : newWordId(), text: t};
    if (old[i] && old[i].o) w.o = {...old[i].o};
    return w;
  });
}
function addSuper(){
  const t = Math.max(0, clock.currentTime), end = Math.min(t + 3, dur());
  pushHistory();
  const sp = {id: 'x' + (S.nextId = (S.nextId || 0) + 1), t0: +t.toFixed(3), t1: +Math.max(end, t + .5).toFixed(3),
              words: [], place: {x: .5, y: S.format === 'horizontal' ? .2 : .25}, template: 'plain'};
  setSuperText(sp, 'Your text here');
  S.supers.push(sp);
  edited(); selectSuper(sp.id);
  setTimeout(() => { const i = $('superText'); if (i){ i.focus(); i.select(); } }, 30);
}
function deleteSuper(id){
  const i = S.supers.findIndex(s => s.id === id); if (i < 0) return;
  pushHistory(); S.supers.splice(i, 1);
  edited(); clearSelection(); toast('Text deleted', {label: 'Undo', run: undo});
}

// ---------- the "Text" lane on the timeline ----------
function superLaneRender(){
  const lane = $('tlSups'); if (!lane || $('editor').hidden) return;
  const v = view(), frag = document.createDocumentFragment();
  for (const sp of S.supers || []){
    if (sp.t1 < v.t0 - 2 || sp.t0 > v.t1 + 2) continue;
    const d = document.createElement('div');
    d.className = 'blk sup' + (sp.id === S.selSuper ? ' sel' : '');
    d.dataset.id = sp.id;
    d.style.left = (sp.t0 * TL.pps) + 'px'; d.style.width = Math.max(4, (sp.t1 - sp.t0) * TL.pps) + 'px';
    const text = sp.words.map(w => w.text).join(' ');
    d.title = text;
    d.innerHTML = '<i class="hl"></i><span></span><i class="hr"></i>';
    d.querySelector('span').textContent = text;
    frag.append(d);
  }
  lane.replaceChildren(frag);
}
function initSupers(){
  const lane = $('tlSups');
  let drag = null;
  lane.addEventListener('pointerdown', e => {
    const b = e.target.closest('.blk'); if (!b || e.button !== 0) return;
    e.preventDefault(); e.stopPropagation();
    const sp = S.supers.find(s => s.id === b.dataset.id);
    const kind = e.target.classList.contains('hl') ? 'l' : e.target.classList.contains('hr') ? 'r' : 'move';
    drag = {sp, kind, x: e.clientX, t0: sp.t0, t1: sp.t1, before: snapshot(), moved: false};
    lane.setPointerCapture(e.pointerId);
    if (S.selSuper !== sp.id) selectSuper(sp.id);
  });
  lane.addEventListener('pointermove', e => {
    if (!drag) return;
    if (!drag.moved && Math.abs(e.clientX - drag.x) < 3) return;
    drag.moved = true;
    const dt = (e.clientX - drag.x) / TL.pps, len = drag.t1 - drag.t0, end = dur();
    const snap = t => (!e.altKey && TL.snap && Math.abs(t - clock.currentTime) < 8 / TL.pps) ? clock.currentTime : t;
    if (drag.kind === 'move'){ const s = Math.min(Math.max(snap(drag.t0 + dt), 0), end - len); drag.sp.t0 = +s.toFixed(3); drag.sp.t1 = +(s + len).toFixed(3); }
    else if (drag.kind === 'l') drag.sp.t0 = +Math.min(Math.max(snap(drag.t0 + dt), 0), drag.t1 - .2).toFixed(3);
    else drag.sp.t1 = +Math.max(Math.min(snap(drag.t1 + dt), end), drag.t0 + .2).toFixed(3);
    superLaneRender(); schedulePreview();
  });
  const end = () => {
    if (!drag) return;
    if (drag.moved){ H.past.push(drag.before); H.future = []; syncHist(); edited(); }
    else if (S.playable){ clock.currentTime = drag.sp.t0 + .001; }
    drag = null; superLaneRender();
  };
  lane.addEventListener('pointerup', end);
  lane.addEventListener('pointercancel', end);
  lane.addEventListener('dblclick', e => { if (e.target.closest('.blk')) $('superText')?.focus(); });
}
