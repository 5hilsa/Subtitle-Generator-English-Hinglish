// The editor page: file picking, generating, the caption list, timeline and styles.
// Loaded after the inline values CTX, FONTS and LOOKS (see templates/index.html).
CaptionLook.init({fonts: FONTS, looks: LOOKS});
const $ = id => document.getElementById(id);
const form = $('form'), fileIn = $('file'), video = $('video'), player = $('player');

const S = {
  file: null, duration: null, playable: false, baseName: 'subtitles', mode: 'hinglish',
  cues: [], original: [], edited: new Set(), current: -1, editing: -1, autoScroll: true,
  job: null, xhr: null, poll: null, tick: null, startedAt: 0, track: null, videoUrl: null,
};

// ---------- helpers ----------
const hms = s => {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
};
const bytes = n => n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GB' : (n / 1048576).toFixed(1) + ' MB';
const langName = code => {
  try { return new Intl.DisplayNames(['en'], {type: 'language'}).of(code) || code; } catch { return code; }
};
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
const store = {
  get(k){ try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

function toast(msg, action){
  const el = document.createElement('div'); el.className = 'toast'; el.textContent = msg;
  if (action){
    const b = document.createElement('button'); b.type = 'button'; b.textContent = action.label;
    b.onclick = () => { action.run(); el.remove(); };
    el.append(b);
  }
  $('toasts').append(el);
  setTimeout(() => el.remove(), action ? 6000 : 2500);
}

// ---------- file picking ----------
function setFile(f){
  if (!f) return;
  S.file = f;
  S.baseName = f.name.replace(/\.[^.]+$/, '');
  const cut = f.name.length > 20 ? f.name.length - 12 : f.name.length;
  $('fnameStart').textContent = f.name.slice(0, cut);
  $('fnameEnd').textContent = f.name.slice(cut);
  $('fname').title = f.name;
  S.duration = null; S.format = null; S.dims = null;
  $('thumbImg').hidden = true; $('thumbImg').removeAttribute('src'); $('fmtChip').hidden = true;
  renderFileMeta();
  $('drop').hidden = true; $('loaded').hidden = false;

  resetResults();
  if (S.videoUrl) URL.revokeObjectURL(S.videoUrl);
  S.videoUrl = URL.createObjectURL(f);
  S.playable = false;
  player.classList.remove('audio'); player.hidden = false; $('previewNote').hidden = true;
  video.src = S.videoUrl;
  makeThumb(S.videoUrl);
  $('emptyState').hidden = true; $('prep').hidden = false; $('errorBox').hidden = true;
  showPending('Your captions will appear here.', 'Hit Generate when your settings look right.');
  syncFooter();
}
function clearFile(){
  S.file = null; S.duration = null; fileIn.value = '';
  video.removeAttribute('src'); video.load();
  if (S.videoUrl) URL.revokeObjectURL(S.videoUrl), S.videoUrl = null;
  $('drop').hidden = false; $('loaded').hidden = true;
  resetResults();
  $('prep').hidden = true; $('emptyState').hidden = false;
  syncFooter();
}
function renderFileMeta(){
  if (!S.file) return;
  const d = S.duration == null ? 'reading duration…' : S.duration === 0 ? 'duration unknown' : hms(S.duration);
  $('fmeta').textContent = `${bytes(S.file.size)} · ${d}` + (S.dims ? ` · ${S.dims[0]}×${S.dims[1]}` : '');
}
// A still from the video for the file card (a second, muted copy so the player keeps its place).
function makeThumb(url){
  const v = document.createElement('video');
  v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = url;
  v.addEventListener('loadeddata', () => { v.currentTime = Math.min(1, (v.duration || 2) / 4); }, {once: true});
  v.addEventListener('seeked', () => {
    if (S.videoUrl === url && v.videoWidth){
      const k = 160 / Math.max(v.videoWidth, v.videoHeight), c = document.createElement('canvas');
      c.width = Math.round(v.videoWidth * k); c.height = Math.round(v.videoHeight * k);
      c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
      try { $('thumbImg').src = c.toDataURL('image/jpeg', .8); $('thumbImg').hidden = false; } catch {}
    }
    v.removeAttribute('src'); v.load();
  }, {once: true});
}
// Vertical (Reels, Shorts) or horizontal (YouTube) changes the defaults, not what's possible.
function ratioName(w, h){
  const r = w / h, known = [[9, 16], [16, 9], [1, 1], [4, 5], [4, 3], [3, 4], [21, 9]];
  const hit = known.find(([a, b]) => Math.abs(r - a / b) < .03);
  return hit ? `${hit[0]}:${hit[1]}` : `${w}×${h}`;
}
function applyFormat(w, h){
  const fmt = w && h ? (h >= w ? 'vertical' : 'horizontal') : null;
  S.format = fmt; S.dims = fmt ? [w, h] : null;
  document.body.dataset.fmt = fmt || 'audio';
  for (const chip of [$('fmtChip')]){
    chip.hidden = !fmt;
    if (!fmt) continue;
    chip.className = 'fmt fmt-chip ' + (fmt === 'vertical' ? 'v' : 'h');
    chip.innerHTML = `<i class="${fmt === 'vertical' ? 'v' : 'h'}"></i>`;
    chip.append(`${fmt === 'vertical' ? 'Vertical' : 'Horizontal'} · ${ratioName(w, h)}`);
  }
  useFormat(fmt || 'vertical');
}
fileIn.onchange = () => fileIn.files[0] && setFile(fileIn.files[0]);
$('emptyState').onclick = () => fileIn.click();
$('emptyState').onkeydown = e => { if (e.key === 'Enter' || e.key === ' '){ e.preventDefault(); fileIn.click(); } };
$('changeBtn').onclick = () => fileIn.click();
$('removeBtn').onclick = () => { clearFile(); fileIn.focus(); };

for (const zone of [$('drop'), $('loaded'), $('emptyState')]){
  ['dragenter', 'dragover'].forEach(e => zone.addEventListener(e, ev => { ev.preventDefault(); zone.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(e => zone.addEventListener(e, ev => { ev.preventDefault(); zone.classList.remove('over'); }));
  zone.addEventListener('drop', ev => {
    const f = ev.dataTransfer.files[0]; if (!f || $('settings').disabled) return;
    const dt = new DataTransfer(); dt.items.add(f); fileIn.files = dt.files; setFile(f);
  });
}

video.addEventListener('loadedmetadata', () => {
  S.duration = isFinite(clock.duration) ? clock.duration : 0;
  S.playable = true;
  $('exportBtn').hidden = false;
  const w = video.videoWidth, h = video.videoHeight;
  if (w && h){
    player.style.setProperty('--ar', w / h);
    player.classList.remove('audio');
  } else player.classList.add('audio');
  applyFormat(w, h);
  renderFileMeta(); syncFooter();
});
video.addEventListener('error', () => {
  if (!S.file) return;
  S.duration = 0; S.playable = false;
  player.hidden = true; $('previewNote').hidden = false;
  applyFormat(0, 0);
  renderFileMeta(); syncFooter();
});

// ---------- options ----------
const SAMPLES = {
  hinglish: 'aaj main aapko ek naya app dikhane wala hoon jisse aap ghar baithe paise kama sakte hain',
  hindi: 'आज मैं आपको एक नया ऐप दिखाने वाला हूँ जिससे आप घर बैठे पैसे कमा सकते हैं',
  english: 'today I am going to show you a new app that lets you earn money from home',
  original: 'today I am going to show you a new app that lets you earn money from home',
};
function renderPreview(){
  const n = +$('words').value, w = SAMPLES[form.mode.value].split(' ');
  $('wordsOut').textContent = n;
  $('pvLine').textContent = w.slice(0, n).join(' ');
  const next = w.slice(n, n * 2).join(' ');
  $('pvNext').textContent = next ? `next: ${next}` : '';
}
function syncSpoken(){
  const m = form.mode.value;
  $('spokenWrap').hidden = m === 'hinglish' || m === 'hindi';
}
const WORDS_HINT = {vertical: 'Fewer words hit harder on Reels and Shorts', horizontal: '8 to 10 words read naturally on YouTube'};
const WORDS_DEFAULT = {vertical: 6, horizontal: 9};
function setWordsFor(fmt){
  $('words').value = store.get('words_' + fmt) || WORDS_DEFAULT[fmt];
  $('wordsHint').textContent = WORDS_HINT[fmt];
  renderPreview();
}
$('words').oninput = () => { renderPreview(); store.set('words_' + (S.format || 'vertical'), +$('words').value); };
form.querySelectorAll('[name=mode]').forEach(r => r.onchange = () => { syncSpoken(); renderPreview(); syncFooter(); });
$('spoken').onchange = syncFooter;
syncSpoken(); setWordsFor('vertical');

// ---------- time estimate ----------
// Rough defaults for Apple-silicon MLX; refined from this Mac's own past runs.
const MODEL_DEFAULTS = {turbo: {load: 15, rate: 1 / 12}, small: {load: 8, rate: 1 / 25}};
const modelFor = () => form.mode.value === 'english' && $('spoken').value !== 'en' ? 'small' : 'turbo';
function estimate(){
  if (!S.duration) return null;
  const m = modelFor(), d = MODEL_DEFAULTS[m], rate = store.get('rate_' + m) || d.rate;
  return d.load + S.duration * rate;
}
function fmtEstimate(sec){
  if (sec < 60) return 'under a minute';
  return `~${Math.round(sec / 60)} min`;
}
function syncFooter(){
  const running = !!(S.xhr || S.job);
  $('goBtn').hidden = running; $('run').hidden = !running;
  $('goBtn').disabled = !S.file;
  $('goLabel').textContent = S.cues.length ? 'Generate again' : 'Generate captions';
  const hint = $('footHint');
  hint.hidden = running;
  if (!S.file) hint.textContent = 'Add a file to get started';
  else if (S.duration == null) hint.textContent = 'Reading file…';
  else if (ACC && ACC.max_seconds && S.duration > ACC.max_seconds + 1)
    hint.textContent = `This is ${hms(S.duration)} long; the ${ACC.plan_name} plan allows up to ${hms(ACC.max_seconds)}. Upgrade or trim it.`;
  else if (ACC && ACC.remaining_seconds != null && S.duration > ACC.remaining_seconds + 1)
    hint.textContent = `You have ${hms(ACC.remaining_seconds)} left this month. Upgrade or add minutes to process this.`;
  else {
    const e = estimate();
    hint.textContent = e ? `Estimated time: ${fmtEstimate(e)} for ${hms(S.duration)} of media` : 'Ready when you are';
  }
}

// ---------- generate / progress ----------
function stageLabel(stage, p){
  if (!stage) return 'Starting…';
  if (/^(Transcribing|Translating)/.test(stage) && !p) return 'Loading model…';
  return stage;
}
function showProgress(label, frac, indeterminate){
  $('runStage').textContent = label;
  const pct = Math.round(frac * 100);
  $('runPct').textContent = indeterminate ? '' : pct + '%';
  $('bar').classList.toggle('indeterminate', !!indeterminate);
  $('bar').setAttribute('aria-valuenow', pct);
  $('barFill').style.width = pct + '%';
}
function startTimer(){
  S.startedAt = Date.now();
  const upd = () => $('elapsed').textContent = `${hms((Date.now() - S.startedAt) / 1000)} elapsed`;
  upd(); S.tick = setInterval(upd, 1000);
}
function stopRun(){
  clearInterval(S.poll); clearInterval(S.tick);
  S.poll = S.tick = S.xhr = S.job = null;
  $('settings').disabled = false;
  syncFooter();
}

form.onsubmit = e => {
  e.preventDefault();
  if (!S.file || S.xhr || S.job) return;
  if ((editedCount() || H.past.length) && !confirm('Generating again will discard your edits. Continue?')) return;
  const fd = new FormData(form);        // build before disabling the fieldset
  S.mode = form.mode.value;
  S.runModel = modelFor(); S.runDuration = S.duration;
  $('settings').disabled = true;
  $('errorBox').hidden = true;
  resetResults();
  showPending('Generating captions…', 'Listening to every word. You can keep using the page.', true);

  const xhr = S.xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload');
  xhr.upload.onprogress = ev => ev.lengthComputable && showProgress('Uploading…', ev.loaded / ev.total);
  xhr.onload = () => {
    let r = {}; try { r = JSON.parse(xhr.responseText || '{}'); } catch {}
    S.xhr = null;
    if (xhr.status === 401) return location.assign('/');
    if (r.upgrade){ fail(r.error); return openPlans(); }
    if (r.error || xhr.status !== 200) return fail(r.error || 'Upload failed');
    S.job = r.job; poll(r.job);
  };
  xhr.onerror = () => fail('Could not reach the server. Is app.py still running?');
  xhr.onabort = () => {};
  syncFooter();
  showProgress('Uploading…', 0);
  startTimer();
  xhr.send(fd);
};

function fail(msg){
  stopRun();
  $('errorText').textContent = msg; $('errorBox').hidden = false;
  showPending('Your captions will appear here.', 'Something went wrong. Check the message above and try again.');
}

function poll(job){
  S.poll = setInterval(async () => {
    let j;
    try { j = await (await fetch('/status/' + job)).json(); } catch { return; }
    if (S.job !== job) return;
    if (j.status === 'running'){
      const p = j.progress || 0, label = stageLabel(j.stage, p);
      return showProgress(label, p, label === 'Loading model…' || /^(Starting|Waiting|Fixing)/.test(label));
    }
    const elapsed = (Date.now() - S.startedAt) / 1000;
    if (j.status === 'done') S.resultJob = job;
    stopRun();
    if (j.status === 'cancelled') return;
    if (j.status === 'error') return fail(j.error);
    if (S.runDuration > 30){           // learn this Mac's speed for future estimates
      const d = MODEL_DEFAULTS[S.runModel];
      const rate = Math.max(0.005, (elapsed - d.load) / S.runDuration);
      const prev = store.get('rate_' + S.runModel);
      store.set('rate_' + S.runModel, prev ? (prev + rate) / 2 : rate);
    }
    if (j.project) openProjectById(j.project, {fresh: true});
    else loadCues(j.cues, j.language);
    loadAccount(); loadRecent();
    if (j.warning) toast(j.warning, {label: 'OK', run: () => {}});
  }, 1500);
}

$('cancelBtn').onclick = () => {
  if (S.xhr) S.xhr.abort();
  if (S.job) fetch('/cancel/' + S.job, {method: 'POST'}).catch(() => {});
  stopRun();
  showPending('Your captions will appear here.', 'Generation was cancelled.');
  toast('Generation cancelled');
  $('goBtn').focus();
};

// ---------- results: setup preview, then the editor ----------
function showPending(title, hint, busy){
  $('pendingSpin').hidden = !busy;
  $('openEditor').hidden = busy || !S.cues.length;
  $('pendingTitle').textContent = title; $('pendingHint').textContent = hint;
}
function resetResults(){
  S.cues = []; S.current = -1; S.editing = -1; S.sel = -1; S.language = null;
  S.resultJob = null; S.peaks = null; resetExport(); resetHistory();
  $('cues').innerHTML = ''; $('capLayer').replaceChildren(); capState = '';
  $('find').value = ''; $('replace').value = '';
  refreshTrack();
}
function loadCues(cues, language){       // only for a server without projects
  S.cues = cues.map((c, i) => wrapCue({id: 'g' + i, t0: c.start, t1: c.end, words: c.text.split(/\s+/).map((t, k) => ({id: 'w' + i + '_' + k, t0: c.start, t1: c.end, text: t})), orig: c.text, source: c.source || ''}));
  S.nextId = 10 ** 6; S.language = language; S.supers = [];
  S.sel = -1;
  renderCues(); refreshTrack(); syncFooter(); applyCaptionStyle();
  toast(`${cues.length} captions ready`);
  enterEditor();
}
const editedCount = () => S.cues.filter(c => c.text !== c.orig).length;
function updateStatus(){
  const bits = [`${S.cues.length} captions`];
  if (S.language) bits.push(`${langName(S.language)} audio`);
  if (S.duration) bits.push(hms(S.duration));
  const n = editedCount();
  if (n) bits.push(`${n} edited`);
  if (ACC && ACC.watermark) bits.push('free exports carry a small watermark');
  $('statusText').textContent = bits.join(' · ');
  if (n){ const s = document.createElement('span'); s.className = 'saved'; s.textContent = ' · fixes saved'; $('statusText').append(s); }
  $('cueCount').textContent = S.cues.length;
}

// ----- entering / leaving the editor -----
function enterEditor(){
  if (!S.cues.length) return;
  $('stageBox').append(player);           // the player moves between the two screens
  video.controls = false; video.pause(); player.classList.add('ed-mode');
  $('edName').textContent = S.baseName;
  $('exportBtn').hidden = !S.playable;
  $('editor').hidden = false; document.body.classList.add('editing');
  updateStatus(); syncPlayBtn(); tlLayout(true); updateOverlay(true); initPreview(); inspectorSync();
  requestAnimationFrame(() => { tlLayout(true); updateOverlay(true); });
}
function leaveEditor(){
  if (S.editing >= 0) commitEdit(true);
  clock.pause(); engineReset();
  $('setupSlot').append(player); player.classList.remove('ed-mode');
  if (video.videoWidth) player.style.setProperty('--ar', video.videoWidth / video.videoHeight);
  video.controls = true;
  $('safeZone').hidden = true; $('safeBtn').setAttribute('aria-pressed', 'false');
  $('editor').hidden = true; document.body.classList.remove('editing');
  showPending(`${S.cues.length} captions ready`, 'Change the settings and Generate again, or go back to editing.');
  syncFooter(); updateOverlay(true);
}
$('edBack').onclick = leaveEditor;
$('openEditor').onclick = enterEditor;

// ----- find / replace -----
function findRegex(){
  const q = $('find').value;
  if (!q) return null;
  let src = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const flags = 'gu' + ($('matchCase').checked ? '' : 'i');
  if ($('wholeWord').checked){
    // Unicode-aware word edges so Devanagari works too (\b is ASCII-only).
    try { return new RegExp(`(?<![\\p{L}\\p{M}\\p{N}_])${src}(?![\\p{L}\\p{M}\\p{N}_])`, flags); }
    catch { return new RegExp(`\\b${src}\\b`, flags); }
  }
  return new RegExp(src, flags);
}
function fillText(span, text, re, cue){
  span.textContent = '';
  if (!re){                                 // words as chips: pickable, and the spoken one lights up
    let k = 0;
    text.split(/(\s+)/).forEach(part => {
      if (!part) return;
      if (/^\s+$/.test(part)){ span.append(part); return; }
      const w = document.createElement('span'); w.className = 'w'; w.textContent = part;
      const word = cue && cue.words[k++];
      if (word){
        w.dataset.wid = word.id;
        if (word.o){ w.classList.add('styled'); if (word.o.color) w.style.setProperty('--wc', word.o.color.slice(0, 7)); }
        if (S.selWords?.has(word.id)) w.classList.add('picked');
      }
      span.append(w);
    });
    return 0;
  }
  let last = 0, n = 0;
  for (const m of text.matchAll(re)){
    if (!m[0]) continue;
    span.append(text.slice(last, m.index));
    const mk = document.createElement('mark'); mk.textContent = m[0]; span.append(mk);
    last = m.index + m[0].length; n++;
  }
  span.append(text.slice(last));
  return n;
}
function applySearch(){
  const re = findRegex(), rows = $('cues').children;
  let total = 0, lines = 0;
  S.cues.forEach((c, i) => {
    const row = rows[i]; if (!row || i === S.editing) return;
    const n = fillText(row.querySelector('.text'), c.text, re, c);
    total += n; if (n) lines++;
    row.hidden = !!re && !n;
  });
  $('matchCount').textContent = re ? (total ? `${total} in ${lines} line${lines > 1 ? 's' : ''}` : 'No matches') : '';
  $('replaceBtn').disabled = !total;
}
['find', 'wholeWord', 'matchCase'].forEach(id => $(id).addEventListener('input', applySearch));
$('find').addEventListener('keydown', e => { if (e.key === 'Escape'){ e.stopPropagation(); if ($('find').value){ $('find').value = ''; applySearch(); } else showFind(false); } });
$('replace').addEventListener('keydown', e => { if (e.key === 'Enter' && !$('replaceBtn').disabled){ e.preventDefault(); $('replaceBtn').click(); } });
$('replaceBtn').onclick = () => {
  const re = findRegex(); if (!re) return;
  const rep = $('replace').value;
  pushHistory();
  let total = 0, lines = 0;
  S.cues.forEach((c, i) => {
    let n = 0;
    const next = c.text.replace(re, () => (n++, rep));
    if (n){ c.text = next; total += n; lines++; learn(i); }
  });
  $('find').value = '';
  changed();
  toast(`Replaced ${total} in ${lines} line${lines > 1 ? 's' : ''}`, {label: 'Undo', run: undo});
};
function showFind(on){
  $('findBox').hidden = !on;
  $('railFind').setAttribute('aria-pressed', String(on));
  if (on) $('find').focus();
  else { $('find').value = ''; applySearch(); }
}
$('railFind').onclick = () => showFind($('findBox').hidden);
$('railCaptions').onclick = () => { showFind(false); if (S.current >= 0) scrollToRow($('cues').children[S.current]); $('cues').focus?.(); };
$('railFonts').onclick = () => $('fontBtn').click();
$('railFixes').onclick = () => $('learnBtn').click();
$('railKeys').onclick = () => $('keysDlg').showModal();
$('keysClose').onclick = () => $('keysDlg').close();
$('keysDlg').addEventListener('click', e => { if (e.target === $('keysDlg')) $('keysDlg').close(); });

// ----- feedback: every edit is saved so future videos learn from it -----
const pendingLearn = new Set();
let learnTimer = null;
function learn(i){
  pendingLearn.add(i);
  clearTimeout(learnTimer);
  learnTimer = setTimeout(flushLearn, 800);
}
async function flushLearn(){
  if (!pendingLearn.size) return;
  const items = [...pendingLearn].filter(i => S.cues[i]).map(i => ({
    index: S.cues[i].id, before: S.cues[i].orig, after: S.cues[i].text, source: S.cues[i].source || ''}));
  pendingLearn.clear();
  try {
    const r = await fetch('/feedback', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({video: S.baseName, mode: S.mode, items})});
    if (r.ok) refreshLearnCount();
  } catch {}
}
addEventListener('pagehide', () => { clearTimeout(learnTimer); flushLearn(); });

async function fetchRules(){
  try { return await (await fetch('/feedback/rules')).json(); } catch { return null; }
}
async function refreshLearnCount(){
  const d = await fetchRules(); if (!d) return;
  $('learnCount').textContent = $('railFixCount').textContent = d.rules.length; $('learnCount').hidden = $('railFixCount').hidden = !d.rules.length;
}
const MODE_NAMES = {hinglish: 'Hinglish', hindi: 'Hindi', english: 'English', original: 'Original'};
async function renderRules(){
  const d = await fetchRules(), list = $('learnList');
  if (!d){ list.innerHTML = '<p class="hint learn-empty">Couldn\'t load learned fixes.</p>'; return; }
  $('learnSummary').textContent = `${d.corrections} corrected line${d.corrections === 1 ? '' : 's'} from ${d.videos} video${d.videos === 1 ? '' : 's'}`;
  $('learnCount').textContent = $('railFixCount').textContent = d.rules.length; $('learnCount').hidden = $('railFixCount').hidden = !d.rules.length;
  list.innerHTML = '';
  if (!d.rules.length){
    list.innerHTML = '<p class="hint learn-empty">Nothing learned yet. Edit a subtitle line and the fix will show up here.</p>';
    return;
  }
  d.rules.forEach(r => {
    const row = document.createElement('div'); row.className = 'rule' + (r.disabled ? ' off' : '');
    const pair = document.createElement('div'); pair.className = 'pair';
    const w = document.createElement('span'); w.className = 'wrong'; w.textContent = r.wrong;
    const arrow = document.createElement('span'); arrow.className = 'meta'; arrow.textContent = '→';
    const rt = document.createElement('span'); rt.className = 'right'; rt.textContent = r.right;
    const meta = document.createElement('span');
    meta.className = 'meta' + (r.auto ? ' auto' : '');
    meta.textContent = `${MODE_NAMES[r.mode] || r.mode} · ${r.count}× · ` +
      (r.disabled ? 'off' : r.auto ? 'auto-applied' : r.ambiguous ? 'AI hint (everyday word)' : 'AI hint');
    pair.append(w, arrow, rt, meta);
    const tog = document.createElement('button');
    tog.type = 'button'; tog.className = 'btn sm'; tog.textContent = r.disabled ? 'Turn on' : 'Turn off';
    tog.onclick = async () => {
      await fetch('/feedback/rules/' + encodeURIComponent(r.id), {method: 'POST',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({disabled: !r.disabled})});
      renderRules();
    };
    const del = document.createElement('button');
    del.type = 'button'; del.className = 'icon-btn'; del.setAttribute('aria-label', `Delete fix ${r.wrong} to ${r.right}`);
    del.innerHTML = '<svg width="16" height="16" aria-hidden="true"><use href="#i-trash"/></svg>';
    del.onclick = async () => {
      await fetch('/feedback/rules/' + encodeURIComponent(r.id), {method: 'DELETE'});
      renderRules(); toast('Fix deleted');
    };
    row.append(pair, tog, del); list.append(row);
  });
}
$('learnBtn').onclick = async () => { await flushLearn(); renderRules(); $('learnDlg').showModal(); };
$('learnClose').onclick = () => $('learnDlg').close();
$('learnDlg').addEventListener('click', e => { if (e.target === $('learnDlg')) $('learnDlg').close(); });
refreshLearnCount();
// ----- caption list -----
const fine = s => {               // 1:05.3
  s = Math.max(0, s);
  const m = Math.floor(s / 60), sec = (s % 60).toFixed(1).padStart(4, '0');
  return `${m}:${sec}`;
};
const ICON = n => `<svg width="15" height="15" aria-hidden="true"><use href="#i-${n}"/></svg>`;
function renderRow(row, i){
  const c = S.cues[i];
  row.innerHTML = '';
  row.classList.toggle('current', i === S.current);
  row.classList.toggle('sel', i === S.sel);
  const num = document.createElement('span'); num.className = 'num'; num.textContent = i + 1;
  const body = document.createElement('div'); body.className = 'cbody';
  const txt = document.createElement('div'); txt.className = 'txt';
  const span = document.createElement('span'); span.className = 'text';
  txt.append(span);
  if (c.text !== c.orig){
    const d = document.createElement('span'); d.className = 'dot'; d.title = 'Edited (saved to your learned fixes)';
    d.setAttribute('role', 'img'); d.setAttribute('aria-label', 'Edited'); txt.append(d);
  }
  txt.onclick = e => {                    // click a word to pick it (Shift: a range, ⌘/Ctrl: add); elsewhere: the line
    const w = e.target.closest('.w[data-wid]');
    if (w) selectWord(i, w.dataset.wid, {shift: e.shiftKey, add: e.metaKey || e.ctrlKey});
    else { S.selWords = new Set(); select(i, false); }
  };
  txt.ondblclick = () => { select(i, false); startEdit(i); };
  row.onclick = e => { if (!e.target.closest('button, .txt, input')){ S.selWords = new Set(); select(i, false); } };
  const ts = document.createElement('button');
  ts.type = 'button'; ts.className = 'ts';
  ts.textContent = `${fine(c.start)} → ${fine(c.end)}`;
  ts.setAttribute('aria-label', `Line ${i + 1}, play from ${hms(c.start)}`);
  ts.onclick = () => seekTo(i, true);
  body.append(txt, ts);
  const acts = document.createElement('div'); acts.className = 'acts';
  const act = (icon, label, fn, cls = '') => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'icon-btn ' + cls; b.title = label; b.setAttribute('aria-label', `${label}, line ${i + 1}`);
    b.innerHTML = ICON(icon); b.onclick = e => { e.stopPropagation(); fn(); };
    acts.append(b);
  };
  act('pencil', 'Edit', () => { select(i, false); startEdit(i); });
  act('scissors', 'Split', () => splitCue(i));
  if (i < S.cues.length - 1) act('merge', 'Merge with next', () => mergeCue(i));
  act('trash', 'Delete', () => deleteCue(i), 'danger');
  row.append(num, body, acts);
  fillText(span, c.text, findRegex(), c);
}
function renderCues(){
  const box = $('cues'); box.innerHTML = ''; S.editing = -1;
  const frag = document.createDocumentFragment();
  S.cues.forEach((c, i) => {
    const row = document.createElement('div'); row.className = 'cue'; row.setAttribute('role', 'listitem');
    renderRow(row, i); frag.append(row);
  });
  box.append(frag);
  applySearch();
}
function startEdit(i){
  if (S.editing === i) return;
  if (S.editing >= 0) commitEdit(true);
  const row = $('cues').children[i]; if (!row) return;
  row.hidden = false;
  S.editing = i;
  const txt = row.querySelector('.txt'), inp = document.createElement('input');
  inp.value = S.cues[i].text; inp.setAttribute('aria-label', `Text of line ${i + 1}`);
  txt.innerHTML = ''; txt.onclick = null; txt.append(inp);
  inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length);
  inp.onkeydown = e => {
    if (e.key === 'Enter'){ e.preventDefault(); commitEdit(true); }
    else if (e.key === 'Escape'){ e.preventDefault(); e.stopPropagation(); commitEdit(false); }
    else if (e.key === 'Tab' && i + 1 < S.cues.length && !e.shiftKey){ e.preventDefault(); commitEdit(true); select(i + 1, true); startEdit(i + 1); }
  };
  inp.onblur = () => S.editing === i && commitEdit(true);
}
function commitEdit(save){
  const i = S.editing; if (i < 0) return;
  const row = $('cues').children[i], inp = row.querySelector('.txt input');
  S.editing = -1;
  if (save && inp){
    const v = inp.value.trim().replace(/\s+/g, ' ');
    if (v && v !== S.cues[i].text){
      pushHistory();
      const c = S.cues[i];
      c.text = v; learn(i);               // unchanged words keep their timing and style
      refreshTrack(); updateStatus(); tlRender(); edited();
    }
  }
  renderRow(row, i);
  if ($('find').value) applySearch();
  updateOverlay(true);
}

// ----- playback position -----
function cueAt(t){
  let lo = 0, hi = S.cues.length - 1;
  while (lo <= hi){
    const mid = (lo + hi) >> 1, c = S.cues[mid];
    if (t < c.start) hi = mid - 1; else if (t >= c.end) lo = mid + 1; else return mid;
  }
  return -1;
}
let litRow = null, litWord = -1;
function setCurrent(i, forceScroll){
  const rows = $('cues').children;
  if (i !== S.current){
    rows[S.current]?.classList.remove('current');
    S.current = i;
    rows[i]?.classList.add('current');
    tlMarkCurrent();
  }
  if (i >= 0 && (forceScroll || (S.autoScroll && S.editing < 0))) scrollToRow(rows[i]);
  updateOverlay();
}
function lightWord(){                     // the spoken word lights up in the list too
  const i = S.current, row = $('cues').children[i];
  let k = -1;
  if (row && i !== S.editing){
    const c = S.cues[i], words = c.text.split(/\s+/), t = clock.currentTime;
    const times = wordTimesOf(c, words.length);
    for (let j = 0; j < times.length; j++) if (t >= times[j][0]) k = j;
  }
  if (row === litRow && k === litWord) return;
  litRow?.querySelectorAll('.w.on').forEach(w => w.classList.remove('on'));
  litRow = row; litWord = k;
  if (row && k >= 0) row.querySelectorAll('.w')[k]?.classList.add('on');
}
function scrollToRow(row){
  if (!row || row.hidden) return;
  const box = $('cues'), top = row.offsetTop - box.offsetTop, bottom = top + row.offsetHeight;
  if (top < box.scrollTop || bottom > box.scrollTop + box.clientHeight)
    box.scrollTo({top: Math.max(0, top - box.clientHeight / 3), behavior: reducedMotion ? 'auto' : 'smooth'});
}
function select(i, seek){
  if (i !== S.sel){
    const rows = $('cues').children;
    rows[S.sel]?.classList.remove('sel');
    S.sel = i;
    rows[i]?.classList.add('sel');
  }
  const c = S.cues[i];
  if (S.selWords?.size && !(c && c.words.some(w => S.selWords.has(w.id)))) S.selWords = new Set();
  if (i >= 0){ S.selSuper = null; S.selClip = null; }
  if (seek && c) seekTo(i, false);
  tlRender(); syncTools();
  if (typeof setScope === 'function'){ refreshWordMarks(); setScope(S.selWords?.size ? 'words' : i >= 0 ? 'line' : S.selSuper ? 'super' : S.selClip ? 'clip' : 'all'); drawHits(true); }
}

// ----- word timings -----
function wordTimesOf(c, n){
  if (c.wt && c.wt.length === n) return c.wt.map(([s, e]) => [Math.max(s, c.start), Math.min(Math.max(e, s), c.end)]);
  const words = c.text.split(/\s+/), total = words.reduce((a, w) => a + w.length, 0) || 1, span = c.end - c.start;
  let t = c.start;
  return words.map(w => { const d = span * w.length / total, r = [t, t + d]; t += d; return r; });
}
// Moving or trimming a caption carries its word timings along.
function retime(c, start, end){
  const n = c.text.split(/\s+/).length;
  if (c.wt && c.wt.length === n){
    const k = (end - start) / Math.max(c.end - c.start, .01);
    c.wt = c.wt.map(([s, e]) => [+(start + (s - c.start) * k).toFixed(3), +(start + (e - c.start) * k).toFixed(3)]);
  }
  c.start = +start.toFixed(3); c.end = +end.toFixed(3);
}

// ----- edits: split, merge, add, delete (all undoable) -----
const H = {past: [], future: []};
const snapshot = () => JSON.stringify({cues: S.cues, hidden: S.hidden || [], supers: S.supers || [], cap: CAP, sel: S.sel, nextId: S.nextId,
  media: PJ.doc ? PJ.doc.tracks.filter(t => t.kind === 'video' || t.kind === 'audio') : null, canvas: PJ.doc && PJ.doc.canvas});
function resetHistory(){ H.past = []; H.future = []; syncHist(); }
function pushHistory(){
  H.past.push(snapshot()); if (H.past.length > 150) H.past.shift();
  H.future = []; syncHist();
  setTimeout(edited, 0);                  // after the change itself: save and redraw the preview
}
function restore(snap){
  const before = new Map(S.cues.map(c => [c.id, c.text]));
  const d = JSON.parse(snap);
  S.cues = d.cues.map(wrapCue); S.hidden = (d.hidden || []).map(wrapCue); S.sel = d.sel; S.nextId = d.nextId; S.supers = d.supers || [];
  if (d.media && PJ.doc){                 // put the clips and tracks back where they were
    const others = PJ.doc.tracks.filter(t => t.kind !== 'video' && t.kind !== 'audio');
    const vids = d.media.filter(t => t.kind === 'video'), auds = d.media.filter(t => t.kind === 'audio');
    PJ.doc.tracks = [...vids, ...others, ...auds];
    if (d.canvas) PJ.doc.canvas = d.canvas;
    TL.laneKey = ''; applyFrame();
  }
  relinkCaptions(); engineSync(true);
  if (d.cap){ Object.keys(CAP).forEach(k => delete CAP[k]); Object.assign(CAP, d.cap); applyCaptionStyle(); }
  S.selWords = new Set(); if (S.selSuper && !S.supers.some(x => x.id === S.selSuper)) S.selSuper = null;
  if (S.selClip && !clipById(S.selClip.id)) S.selClip = null;
  S.cues.forEach((c, i) => { if (before.has(c.id) && before.get(c.id) !== c.text) learn(i); });
  S.current = -1;
  changed();
}
function undo(){ if (!H.past.length) return; if (S.editing >= 0) commitEdit(false); H.future.push(snapshot()); restore(H.past.pop()); syncHist(); }
function redo(){ if (!H.future.length) return; if (S.editing >= 0) commitEdit(false); H.past.push(snapshot()); restore(H.future.pop()); syncHist(); }
function syncHist(){ $('undoBtn').disabled = !H.past.length; $('redoBtn').disabled = !H.future.length; }
$('undoBtn').onclick = undo; $('redoBtn').onclick = redo;
function changed(){                       // after anything that changes the captions
  renderCues(); refreshTrack(); updateStatus(); tlRender(); syncTools();
  capState = ''; syncToVideo(); edited(); inspectorSync(); superLaneRender();
}
// A new caption line from words (keeping their times and styles), or from plain text.
const newCue = (start, end, text, words, from) => {
  // timeline time -> the media file's time, through the clip there (or the one `from` is on)
  let asset = 'a1', k = null;
  if (from){ asset = from.asset || 'a1'; k = from.clip; }
  else if (PJ.doc){
    k = [...mediaTracks()].reverse().map(t => t.clips.find(c => start >= c.at - .001 && start < clipEnd(c))).find(Boolean);
    if (k) asset = k.asset;
  }
  const fileT = T => k ? toAsset(k, T) : T;
  const ws = words ? words.map(w => ({...w})) : text.split(/\s+/).map(t => ({id: newWordId(), t0: fileT(start), t1: fileT(end), text: t}));
  const c = wrapCue({id: 'g' + (S.nextId = (S.nextId || 0) + 1), asset, t0: +fileT(start).toFixed(3), t1: +fileT(end).toFixed(3), words: ws,
                     orig: ws.map(w => w.text).join(' '), source: ''});
  if (!words){ c.words = []; c.text = text; }   // spread plain text over the time
  if (from){ if (from.o) c.o = {...from.o}; if (from.anim) c.anim = {...from.anim}; if (from.place) c.place = {...from.place}; }
  return c;
};
function splitCue(i, at){
  const c = S.cues[i]; if (!c) return;
  const words = c.text.split(/\s+/);
  if (words.length < 2) return toast('One word: nothing to split');
  const times = wordTimesOf(c, words.length), t = at ?? clock.currentTime;
  let k = times.findIndex(([s, e]) => (s + e) / 2 >= t);           // first word after the split point
  if (at == null && !(t > c.start && t < c.end)) k = Math.ceil(words.length / 2);
  k = Math.min(Math.max(k, 1), words.length - 1);
  const cut = (t > c.start + .05 && t < c.end - .05) ? t : times[k][0];
  pushHistory();
  const a = newCue(c.start, cut, '', c.words.slice(0, k), c);
  const b = newCue(cut, c.end, '', c.words.slice(k), c);
  S.cues.splice(i, 1, a, b); S.sel = i + 1;
  changed(); toast('Split into two captions', {label: 'Undo', run: undo});
}
function mergeCue(i){
  const a = S.cues[i], b = S.cues[i + 1]; if (!a || !b) return;
  if ((a.asset || 'a1') !== (b.asset || 'a1') || clipOfCue(a) !== clipOfCue(b)) return toast('These two lines are on different clips');
  pushHistory();
  S.cues.splice(i, 2, newCue(a.start, b.end, '', [...a.words, ...b.words], a)); S.sel = i;
  changed();
}
function deleteCue(i){
  if (!S.cues[i]) return;
  pushHistory();
  S.cues.splice(i, 1); S.sel = Math.min(i, S.cues.length - 1);
  changed(); toast('Caption deleted', {label: 'Undo', run: undo});
}
function addCue(){
  const t = clock.currentTime, end = dur();
  let i = S.cues.findIndex(c => c.end > t);                 // first caption ending after the playhead
  if (i < 0) i = S.cues.length;
  let start = t;
  if (S.cues[i] && S.cues[i].start <= t){ start = S.cues[i].end; i++; }   // inside one: add right after it
  const next = S.cues[i] ? S.cues[i].start : end;
  const stop = Math.min(start + 2, next);
  if (stop - start < .3) return toast('No room here: move the playhead to a gap');
  pushHistory();
  S.cues.splice(i, 0, newCue(start, stop, 'New caption')); S.sel = i;
  changed(); startEdit(i);
  $('cues').children[i]?.querySelector('input')?.select();
}
const selOrCurrent = () => S.sel >= 0 ? S.sel : S.current;
$('addBtn').onclick = addCue;
$('splitBtn').onclick = () => { const i = S.current >= 0 ? S.current : S.sel; if (i >= 0) splitCue(i); };
$('mergeBtn').onclick = () => { const i = selOrCurrent(); if (i >= 0) mergeCue(i); };
$('delBtn').onclick = () => { const i = selOrCurrent(); if (i >= 0) deleteCue(i); };
function syncTools(){
  const i = selOrCurrent();
  $('splitBtn').disabled = !(S.current >= 0 || S.sel >= 0);
  $('mergeBtn').disabled = !(i >= 0 && i < S.cues.length - 1);
  $('delBtn').disabled = i < 0;
  const c = S.cues[S.sel];
  $('tlSel').textContent = c ? `#${S.sel + 1}  ${fine(c.start)} → ${fine(c.end)}  (${(c.end - c.start).toFixed(1)}s)` : '';
}

// ---------- caption templates (preview + burned-in export) ----------
const SIZE = {small: .8, medium: 1, large: 1.25};
const OLD_STYLES = {clean: 'classic', bold_pop: 'beast', boxed: 'notebook', yellow: 'hustle', minimal: 'luxe'};
// Vertical and horizontal videos each keep their own look; long-form starts on the plain, readable one.
const CAP_START = {vertical: LOOKS.default, horizontal: LOOKS.templates.classic ? 'classic' : LOOKS.default};
const capKey = fmt => fmt === 'horizontal' ? 'caption_h' : 'caption';
const CAP = {};
let capFormat = null;
function useFormat(fmt){
  if (fmt !== capFormat){
    capFormat = fmt;
    Object.keys(CAP).forEach(k => delete CAP[k]);
    Object.assign(CAP, {template: CAP_START[fmt], accent: null, font: null, position: 'bottom', size: 'medium', x: null, y: null, scale: null}, store.get(capKey(fmt)) || {});
    if (CAP.style){ CAP.template = OLD_STYLES[CAP.style] || LOOKS.default; delete CAP.style; }
    if (!LOOKS.templates[CAP.template]) CAP.template = CAP_START[fmt];
    tileState.clear();
  }
  $('tplRow').classList.toggle('wide', fmt === 'horizontal');
  $('styleNote').textContent = fmt === 'horizontal' ? 'Your horizontal videos keep this look. Vertical videos have their own.'
                                                    : 'Your vertical videos keep this look. Horizontal videos have their own.';
  setWordsFor(fmt);
  applyCaptionStyle();
}
const currentTpl = () => CaptionLook.resolve(CAP.template, CAP);
let capState = '', capPage = '';
function updateOverlay(force){
  if (typeof PV !== 'undefined' && PV.ready && S.pid){   // libass draws the captions; this is the fallback
    if ($('capLayer').childElementCount) $('capLayer').replaceChildren();
    $('capFrame').hidden = true; return;
  }
  const layer = $('capLayer'), i = S.playable ? cueAt(clock.currentTime) : -1;
  const st = i >= 0 ? CaptionLook.at(S.cues[i], clock.currentTime, currentTpl()) : null;
  if (!st){ if (capState){ layer.replaceChildren(); capState = capPage = ''; } placeFrame(); return; }
  const key = `${i}|${st.key}|${S.cues[i].text}`;
  if (key === capState && !force) return;
  const page = `${i}|${st.pageKey}|${S.cues[i].text}`, newPage = page !== capPage;
  capState = key; capPage = page;
  const tpl = currentTpl(), w = player.clientWidth, h = player.clientHeight;
  CaptionLook.draw(layer, {tpl, words: st.page, active: st.active, position: CAP.position, newPage: newPage && !force,
                           em: CaptionLook.emFor(w, h, tpl, capScale()), landscape: w > h, x: CAP.x, y: CAP.y});
  placeFrame();
}
const capScale = () => CAP.scale ?? SIZE[CAP.size] ?? 1;
function saveCap(){ pushStyleHistory(); capChanged(); applyCaptionStyle(); }
let styleHist = 0;
function pushStyleHistory(){              // a burst of style changes is one undo step
  if (typeof H === 'undefined' || !S.cues.length) return;
  if (Date.now() - styleHist > 800){ H.past.push(snapshot()); H.future = []; syncHist(); }
  styleHist = Date.now();
}
function applyCaptionStyle(){
  const tpl = LOOKS.templates[CAP.template], f = fontOf(CAP.font);
  $('fontName').textContent = f ? f.label : `${fontOf(tpl.font).label} (template)`;
  $('fontName').style.fontFamily = `'F-${f ? f.key : tpl.font}', Manrope, sans-serif`;
  CaptionLook.loadFont(f ? f.key : tpl.font);
  $('tplDesc').textContent = tpl.desc; $('tplName').textContent = tpl.name;
  $('tplRow').querySelectorAll('.tpl-tile').forEach(b => {
    const on = b.dataset.key === CAP.template;
    b.setAttribute('aria-checked', String(on)); b.tabIndex = on ? 0 : -1;
  });
  renderSwatches();
  capState = ''; updateOverlay(true);
  syncPlaceUI();
  if (typeof schedulePreview === 'function') schedulePreview();
}
// Where the caption sits (0-1 across and down). Before any dragging it's the template's own spot.
function capPlace(){
  if (CAP.x != null) return {x: CAP.x, y: CAP.y};
  const portrait = S.format !== 'horizontal';
  return {x: .5, y: {top: portrait ? .24 : .13, middle: .5}[CAP.position] ?? (portrait ? .76 : .87)};
}
function syncPlaceUI(){
  const {x, y} = capPlace(), pct = Math.round(capScale() * 100);
  setFancy($('posX'), Math.round(x * 100), Math.round(x * 100) + '%', $('posXOut'));
  setFancy($('posY'), Math.round(y * 100), Math.round(y * 100) + '%', $('posYOut'));
  setFancy($('capSize'), pct, pct + '%', $('capSizeOut'));
  const pad = $('posPad');
  pad.classList.toggle('wide', S.format === 'horizontal');
  pad.style.setProperty('--x', x); pad.style.setProperty('--y', y); pad.style.setProperty('--s', capScale());
  pad.setAttribute('aria-valuetext', `${Math.round(x * 100)}% across, ${Math.round(y * 100)}% down`);
  $('resetPlace').hidden = CAP.x == null && CAP.scale == null;
}
function setFancy(inp, v, label, out){
  inp.value = v; out.textContent = label;
  inp.style.setProperty('--p', ((v - inp.min) / (inp.max - inp.min) * 100) + '%');
}
function movePlace(x, y, save){
  CAP.x = Math.min(Math.max(x, 0), 1); CAP.y = Math.min(Math.max(y, 0), 1);
  capState = ''; updateOverlay(true); syncPlaceUI();
  if (save) capChanged();
}
document.querySelectorAll('.seg[data-opt]').forEach(g => g.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  CAP[g.dataset.opt] = b.dataset.v;
  if (g.dataset.opt === 'position'){ CAP.x = CAP.y = null; }
  saveCap();
}));
$('capSize').oninput = () => { CAP.scale = +$('capSize').value / 100; capState = ''; updateOverlay(true); syncPlaceUI(); };
$('posX').oninput = () => movePlace(+$('posX').value / 100, capPlace().y);
$('posY').oninput = () => movePlace(capPlace().x, +$('posY').value / 100);
['capSize', 'posX', 'posY'].forEach(id => $(id).onchange = () => capChanged());
$('resetPlace').onclick = () => { CAP.x = CAP.y = CAP.scale = null; CAP.position = 'bottom'; CAP.size = 'medium'; saveCap(); toast('Caption back to its default spot and size'); };
// The pad: a small copy of the frame. Drag the dot anywhere; it clicks into the dots at top, centre and bottom.
(() => {
  const pad = $('posPad');
  let on = false;
  const at = (e, save) => {
    const r = pad.getBoundingClientRect();
    let x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
    if (!e.altKey){
      if (Math.abs(x - .5) < .05) x = .5;
      for (const d of pad.querySelectorAll('.pad-dots i')) if (Math.abs(y - +d.dataset.y) < .04 && x === .5) y = +d.dataset.y;
    }
    movePlace(x, y, save);
  };
  pad.addEventListener('pointerdown', e => { on = true; pad.setPointerCapture(e.pointerId); pad.classList.add('active'); at(e); });
  pad.addEventListener('pointermove', e => { if (on) at(e); });
  const end = e => { if (!on) return; on = false; pad.classList.remove('active'); at(e, true); };
  pad.addEventListener('pointerup', end); pad.addEventListener('pointercancel', () => { on = false; pad.classList.remove('active'); });
  pad.addEventListener('keydown', e => {
    const k = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[e.key]; if (!k) return;
    e.preventDefault(); e.stopPropagation();
    const p = capPlace(), step = e.shiftKey ? .1 : .01;
    movePlace(p.x + k[0] * step, p.y + k[1] * step, true);
  });
})();

// ----- place and size the caption by hand, right on the video -----
function placeFrame(){
  const f = $('capFrame'), b = $('capLayer').querySelector('.cl-block');
  if ($('editor').hidden || !b){ if (!CAPDRAG) f.hidden = true; return; }
  const pr = player.getBoundingClientRect(), r = b.getBoundingClientRect(), pad = 6, m = 8;   // m: handles stay on screen
  const x0 = Math.max(r.left - pr.left - pad, m), y0 = Math.max(r.top - pr.top - pad, m);
  const x1 = Math.min(r.right - pr.left + pad, pr.width - m), y1 = Math.min(r.bottom - pr.top + pad, pr.height - m);
  Object.assign(f.style, {left: x0 + 'px', top: y0 + 'px', width: Math.max(x1 - x0, 20) + 'px', height: Math.max(y1 - y0, 20) + 'px'});
  f.hidden = false;
}
var CAPDRAG = null, justDragged = false;   // var: placeFrame can run before this line
function blockCentre(){
  const b = $('capLayer').querySelector('.cl-block'), pr = player.getBoundingClientRect();
  if (!b) return null;
  const r = b.getBoundingClientRect();
  return {x: (r.left + r.width / 2 - pr.left) / pr.width, y: (r.top + r.height / 2 - pr.top) / pr.height, r, pr};
}
player.addEventListener('pointerdown', e => {
  if ($('editor').hidden || e.button !== 0) return;
  const handle = e.target.closest('.cap-frame i'), onCap = e.target.closest('.cl-block, .cap-frame');
  if (!onCap) return;
  const c = blockCentre(); if (!c) return;
  e.preventDefault(); e.stopPropagation();
  CAPDRAG = {kind: handle ? 'size' : 'move', x0: e.clientX, y0: e.clientY, cx: c.x, cy: c.y, scale: capScale(),
             dist: Math.hypot(e.clientX - (c.r.left + c.r.width / 2), e.clientY - (c.r.top + c.r.height / 2)) || 1,
             mid: [c.r.left + c.r.width / 2, c.r.top + c.r.height / 2], moved: false};
  player.setPointerCapture(e.pointerId);
  player.classList.add('placing');
});
player.addEventListener('pointermove', e => {
  const d = CAPDRAG; if (!d) return;
  if (!d.moved && Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 3) return;
  d.moved = true;
  const pr = player.getBoundingClientRect();
  if (d.kind === 'move'){
    let x = d.cx + (e.clientX - d.x0) / pr.width, y = d.cy + (e.clientY - d.y0) / pr.height;
    const snapX = !e.altKey && Math.abs(x - .5) < .02, snapY = !e.altKey && Math.abs(y - .5) < .02;
    if (snapX) x = .5; if (snapY) y = .5;
    $('guideV').hidden = !snapX; $('guideH').hidden = !snapY;
    CAP.x = Math.min(Math.max(x, 0), 1); CAP.y = Math.min(Math.max(y, 0), 1);
    $('capTip').textContent = `${Math.round(CAP.x * 100)}% · ${Math.round(CAP.y * 100)}%`;
  } else {
    if (CAP.x == null){ CAP.x = d.cx; CAP.y = d.cy; }        // keep it where it is while it grows
    const dist = Math.hypot(e.clientX - d.mid[0], e.clientY - d.mid[1]);
    CAP.scale = Math.min(Math.max(d.scale * dist / d.dist, .4), 2.5);
    $('capTip').textContent = Math.round(CAP.scale * 100) + '%';
  }
  capState = ''; updateOverlay(true);
  syncPlaceUI();
});
const endCapDrag = () => {
  const d = CAPDRAG; if (!d) return;
  CAPDRAG = null; player.classList.remove('placing');
  $('guideV').hidden = $('guideH').hidden = true; $('capTip').textContent = '';
  if (d.moved){ justDragged = true; setTimeout(() => justDragged = false, 0); saveCap(); }
};
player.addEventListener('pointerup', endCapDrag);
player.addEventListener('pointercancel', endCapDrag);
video.addEventListener('loadedmetadata', () => applyCaptionStyle());
window.addEventListener('resize', () => updateOverlay(true));

// Gallery: every tile plays a live sample of its template.
const SAMPLE = 'Aaj hum baat karenge 90% creators ki sabse badi galti'.split(' ');
const SAMPLE_CUE = {start: 0, end: SAMPLE.length * .42, text: SAMPLE.join(' '), wt: SAMPLE.map((_, k) => [k * .42, k * .42 + .38])};
$('tplRow').replaceChildren(...LOOKS.order.map(key => [key, LOOKS.templates[key]]).map(([key, t]) => {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'tpl-tile'; b.dataset.key = key; b.setAttribute('role', 'radio');
  b.setAttribute('aria-label', `${t.name}: ${t.desc}`);
  b.innerHTML = '<span class="tpl-stage"><span class="capl"></span></span><span class="tpl-name"></span>';
  b.querySelector('.tpl-name').textContent = t.name;
  return b;
}));
$('tplRow').onclick = e => {
  const b = e.target.closest('.tpl-tile'); if (!b) return;
  if (CAP.template !== b.dataset.key){ CAP.template = b.dataset.key; CAP.accent = null; saveCap(); }
};
$('tplRow').onkeydown = e => {
  if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
  const tiles = [...$('tplRow').children], i = tiles.findIndex(b => b.dataset.key === CAP.template);
  const next = tiles[(i + (e.key === 'ArrowRight' ? 1 : -1) + tiles.length) % tiles.length];
  e.preventDefault(); next.click(); next.focus();
};
const tileState = new Map();
function animateTiles(){
  if (document.hidden || $('editor').hidden || $('paneTpl').hidden) return;
  const t = (performance.now() / 1000) % (SAMPLE_CUE.end + .8);
  $('tplRow').querySelectorAll('.tpl-tile').forEach(b => {
    const key = b.dataset.key, tpl = CaptionLook.resolve(key, key === CAP.template ? CAP : {});
    tpl.words = Math.min(tpl.words || 4, 4);   // thumbnails are small: fewer words, bigger text
    const time = Math.min(t, SAMPLE_CUE.end - .01), st = CaptionLook.at(SAMPLE_CUE, time, tpl);
    const sig = `${st.key}|${key === CAP.template ? CAP.accent + CAP.font : ''}`, prev = tileState.get(key) || '';
    if (sig === prev) return;
    tileState.set(key, sig);
    const layer = b.querySelector('.capl'), w = layer.clientWidth, h = layer.clientHeight;
    CaptionLook.draw(layer, {tpl, words: st.page, active: st.active, position: 'bottom',
                             newPage: prev.split(':')[0] !== st.key.split(':')[0], em: Math.max(CaptionLook.emFor(w, h, tpl) * (w > h ? 2.3 : 1.5), 8.5), landscape: w > h});
  });
}
setInterval(animateTiles, 90);

// Accent colour: the template's own colour first, then presets, then any colour.
const PRESETS = ['#A6F24D', '#FFE81F', '#F7931E', '#FF4D6D', '#5B6CFF', '#1E8DEB', '#43FF6E', '#FFFFFF'];
function accentDefault(tpl){
  const f = tpl.accent; if (!f) return null;
  const v = f.includes('.') ? (tpl[f.split('.')[0]] || {})[f.split('.')[1]] : tpl[f];
  return v ? v.slice(0, 7).toUpperCase() : null;
}
function renderSwatches(){
  const tpl = LOOKS.templates[CAP.template], def = accentDefault(tpl);
  $('accentGrp').hidden = !def;
  if (!def) return;
  const cur = (CAP.accent || def).toUpperCase();
  const list = [def, ...PRESETS.filter(c => c !== def)].slice(0, 8);
  const btns = list.map((c, k) => {
    const b = Object.assign(document.createElement('button'), {type: 'button', className: 'swatch', title: k ? c : `${c} (template default)`});
    b.style.background = c; b.dataset.c = c; b.setAttribute('aria-label', k ? `Colour ${c}` : 'Template colour');
    b.setAttribute('aria-pressed', String(c === cur));
    return b;
  });
  const custom = Object.assign(document.createElement('label'), {className: 'swatch custom', title: 'Any colour'});
  const inp = Object.assign(document.createElement('input'), {type: 'color', value: cur.toLowerCase()});
  inp.setAttribute('aria-label', 'Pick any colour');
  inp.oninput = () => { CAP.accent = inp.value.toUpperCase(); capChanged(); capState = ''; updateOverlay(true); tileState.clear(); };
  inp.onchange = saveCap;
  custom.setAttribute('aria-pressed', String(!list.includes(cur)));
  custom.append(inp);
  $('swatches').replaceChildren(...btns, custom);
}
$('swatches').onclick = e => {
  const b = e.target.closest('button.swatch'); if (!b) return;
  CAP.accent = b.dataset.c === accentDefault(LOOKS.templates[CAP.template]) ? null : b.dataset.c; saveCap(); tileState.clear();
};

// ---------- font library ----------
const FONT_BY_KEY = Object.fromEntries(FONTS.fonts.map(f => [f.key, f]));
const fontOf = k => FONT_BY_KEY[k] || null;
const DEVA = /[\u0900-\u097F]/;
const hindiCaptions = () => S.cues.some(c => DEVA.test(c.text));
// Same rule as render.py: a font without Hindi letters falls back to the style's font for Hindi captions.
const loadFont = f => CaptionLook.loadFont(f.key);
let fontFilter = 'all';
function fontSample(){
  const c = S.cues.find(c => c.text.trim());
  const words = c ? c.text.trim().split(/\s+/).slice(0, 3).join(' ') : 'Aaj ka video';
  return LOOKS.templates[CAP.template].upper ? words.toUpperCase() : words;
}
const tileObserver = 'IntersectionObserver' in window ? new IntersectionObserver(entries => entries.forEach(e => {
  if (e.isIntersecting){ loadFont(fontOf(e.target.dataset.key)); tileObserver.unobserve(e.target); }
}), {root: $('fontGrid'), rootMargin: '200px'}) : null;
function renderFonts(){
  const q = $('fontFind').value.trim().toLowerCase(), hindi = hindiCaptions(), sample = fontSample();
  $('fontSummary').textContent = `${FONTS.fonts.length} fonts, ${FONTS.fonts.filter(f => f.hindi).length} of them write Hindi. Free for commercial use.`;
  const own = fontOf(LOOKS.templates[CAP.template].font);
  const list = [{...own, key: '', fontKey: own.key, label: `${own.label} (template font)`},
                ...FONTS.fonts].filter(f =>
    (!q || f.label.toLowerCase().includes(q)) &&
    (fontFilter === 'all' || (fontFilter === 'hindi_ok' ? f.hindi : f.group === fontFilter)));
  const grid = $('fontGrid');
  tileObserver?.disconnect();
  grid.replaceChildren(...list.map(f => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'font-tile'; b.dataset.key = f.key;
    b.setAttribute('aria-pressed', String((CAP.font || '') === f.key));
    const blocked = hindi && !f.hindi;
    if (blocked){ b.setAttribute('aria-disabled', 'true'); b.title = 'This font has English letters only, so it can\'t write these Hindi captions'; }
    const sm = document.createElement('span'); sm.className = 'sample'; sm.textContent = sample;
    sm.style.fontFamily = `'F-${f.fontKey || f.key}', sans-serif`;
    sm.style.setProperty('--k', f.scale);
    const meta = document.createElement('span'); meta.className = 'meta';
    meta.append(Object.assign(document.createElement('span'), {textContent: f.label}));
    if (f.hindi) meta.append(Object.assign(document.createElement('span'), {className: 'tag', textContent: 'हिंदी'}));
    b.append(sm, meta);
    if (!f.key) CaptionLook.loadFont(f.fontKey);
    else if (tileObserver) tileObserver.observe(b); else loadFont(f);
    return b;
  }));
  if (!list.length) grid.append(Object.assign(document.createElement('p'), {className: 'hint font-empty', textContent: 'No font matches that search.'}));
}
// "Hindi" lists every font that can write Hindi script, not only the ones designed for it.
const {hindi: _h, ...FONT_GROUPS} = FONTS.groups;
const FONT_CHIPS = {all: 'All', hindi_ok: 'Hindi', ...FONT_GROUPS};
$('fontChips').replaceChildren(...Object.entries(FONT_CHIPS).map(([k, label]) => {
  const b = Object.assign(document.createElement('button'), {type: 'button', textContent: label});
  b.dataset.k = k; b.setAttribute('aria-pressed', String(k === fontFilter));
  if (k === 'added') b.hidden = !FONTS.fonts.some(f => f.group === 'added');   // shown once you add one
  return b;
}));
$('fontChips').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  fontFilter = b.dataset.k;
  $('fontChips').querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  renderFonts();
};
$('fontFind').oninput = renderFonts;
$('fontGrid').onclick = e => {
  const b = e.target.closest('.font-tile'); if (!b) return;
  if (b.getAttribute('aria-disabled') === 'true') return toast('This font has English letters only. Pick one marked हिंदी for Hindi captions.');
  CAP.font = b.dataset.key || null; capChanged(); applyCaptionStyle();
  $('fontDlg').close();
};
$('fontBtn').onclick = () => { showMatch(false); $('fontFind').value = ''; renderFonts(); $('fontDlg').showModal(); $('fontFind').focus(); };
$('fontClose').onclick = () => $('fontDlg').close();
$('fontDlg').addEventListener('click', e => { if (e.target === $('fontDlg')) $('fontDlg').close(); });

// ---------- match a font from a picture ----------
const crop = {x0: 0, y0: 0, x1: 1, y1: 1, drag: null};   // fractions of the picture
function showMatch(on){
  $('matchPanel').hidden = !on;
  $('fontGrid').hidden = on;
  $('fontFind').closest('.font-tools').hidden = on;
  if (on && $('matchStage').hidden) $('matchDrop').focus();
}
function useFontEntry(f){            // a font that just joined the library (added from Google Fonts)
  if (!FONT_BY_KEY[f.key]){ FONTS.fonts.push(f); FONT_BY_KEY[f.key] = f; CaptionLook.init({fonts: FONTS, looks: LOOKS}); }
  $('fontChips').querySelector('[data-k="added"]').hidden = false;
}
function pickFont(key){
  if (typeof pickFontForScope === 'function' && pickFontForScope(key)){ $('fontDlg').close(); return; }
  const f = fontOf(key);
  if (f && hindiCaptions() && !f.hindi) return toast('This font has English letters only. Pick one marked हिंदी for Hindi captions.');
  CAP.font = key; capChanged(); applyCaptionStyle();
  $('fontDlg').close();
}
function loadMatchPicture(file){
  if (!file || !file.type.startsWith('image/')) return toast('That isn\'t a picture. Use a PNG or JPG.');
  const url = URL.createObjectURL(file);
  $('matchImg').onload = () => URL.revokeObjectURL(url);
  $('matchImg').src = url;
  Object.assign(crop, {x0: 0, y0: 0, x1: 1, y1: 1}); $('cropBox').hidden = true;
  $('matchDrop').hidden = true; $('matchStage').hidden = false;
  $('matchText').value = ''; $('matchNote').textContent = ''; $('matchResults').replaceChildren(); $('matchExact').hidden = true;
  $('matchGo').focus();
}
$('matchBtn').onclick = () => showMatch(true);
$('matchBack').onclick = () => { showMatch(false); renderFonts(); $('fontFind').focus(); };
$('matchDrop').onclick = () => $('matchFile').click();
$('matchClear').onclick = () => {          // back to an empty drop area, ready for a new picture
  $('matchFile').value = ''; $('matchImg').removeAttribute('src');
  $('matchStage').hidden = true; $('matchExact').hidden = true; $('matchDrop').hidden = false;
  $('matchText').value = ''; $('matchNote').textContent = ''; $('matchNote').classList.remove('err');
  $('matchResults').replaceChildren();
  $('matchDrop').focus();
};
$('matchFile').onchange = () => loadMatchPicture($('matchFile').files[0]);
['dragenter', 'dragover'].forEach(ev => $('matchDrop').addEventListener(ev, e => { e.preventDefault(); $('matchDrop').classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => $('matchDrop').addEventListener(ev, e => { e.preventDefault(); $('matchDrop').classList.remove('over'); }));
$('matchDrop').addEventListener('drop', e => loadMatchPicture(e.dataTransfer.files[0]));
document.addEventListener('paste', e => {
  if (!$('fontDlg').open || $('matchPanel').hidden) return;
  const file = [...(e.clipboardData?.files || [])].find(f => f.type.startsWith('image/'));
  if (file){ e.preventDefault(); loadMatchPicture(file); }
});

// Drag a box around the text.
function cropAt(e){
  const r = $('matchImg').getBoundingClientRect();
  return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
}
function drawCrop(){
  const box = $('cropBox'), whole = crop.x1 - crop.x0 > 0.98 && crop.y1 - crop.y0 > 0.98;
  box.hidden = whole;
  Object.assign(box.style, {left: crop.x0 * 100 + '%', top: crop.y0 * 100 + '%',
    width: (crop.x1 - crop.x0) * 100 + '%', height: (crop.y1 - crop.y0) * 100 + '%'});
}
$('cropWrap').addEventListener('pointerdown', e => {
  if (e.target.closest('#matchClear')) return;      // the X, not the start of a box
  $('cropWrap').setPointerCapture(e.pointerId);
  crop.drag = cropAt(e); [crop.x0, crop.y0] = crop.drag; [crop.x1, crop.y1] = crop.drag; drawCrop();
});
$('cropWrap').addEventListener('pointermove', e => {
  if (!crop.drag) return;
  const [x, y] = cropAt(e), [sx, sy] = crop.drag;
  Object.assign(crop, {x0: Math.min(x, sx), x1: Math.max(x, sx), y0: Math.min(y, sy), y1: Math.max(y, sy)}); drawCrop();
});
$('cropWrap').addEventListener('pointerup', () => {
  crop.drag = null;
  if (crop.x1 - crop.x0 < 0.03 || crop.y1 - crop.y0 < 0.03) Object.assign(crop, {x0: 0, y0: 0, x1: 1, y1: 1});  // a click: whole picture
  drawCrop();
});
function croppedPicture(){
  const img = $('matchImg'), W = img.naturalWidth, H = img.naturalHeight;
  const w = Math.round((crop.x1 - crop.x0) * W), h = Math.round((crop.y1 - crop.y0) * H);
  const k = Math.min(1, 1600 / Math.max(w, h));
  const c = Object.assign(document.createElement('canvas'), {width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k))});
  c.getContext('2d').drawImage(img, crop.x0 * W, crop.y0 * H, w, h, 0, 0, c.width, c.height);
  return c.toDataURL('image/png');
}

function matchTile(r, i, text){
  const b = document.createElement('div');
  b.className = 'font-tile'; b.tabIndex = 0; b.setAttribute('role', 'button');
  const sm = document.createElement('span'); sm.className = 'sample'; sm.textContent = text;
  const meta = document.createElement('span'); meta.className = 'meta';
  meta.append(Object.assign(document.createElement('span'), {textContent: r.label}));
  if (i === 0) meta.append(Object.assign(document.createElement('span'), {className: 'best', textContent: 'Best match'}));
  if (r.source === 'library'){
    const f = fontOf(r.key);
    sm.style.fontFamily = `'F-${r.key}', sans-serif`; sm.style.setProperty('--k', f.scale);
    loadFont(f);
    if (f.hindi) meta.append(Object.assign(document.createElement('span'), {className: 'tag', textContent: 'हिंदी'}));
    b.dataset.key = r.key;
  } else {
    const fam = `T-${r.family.replace(/\W/g, '')}-${r.weight}`;
    sm.style.fontFamily = `'${fam}', sans-serif`; sm.classList.add('loading');
    new FontFace(fam, `url(/fonts/try/${encodeURIComponent(r.file)})`).load()
      .then(face => { document.fonts.add(face); sm.classList.remove('loading'); }).catch(() => sm.classList.remove('loading'));
    meta.append(Object.assign(document.createElement('span'), {className: 'tag g', textContent: 'Google Fonts'}));
    const add = Object.assign(document.createElement('button'), {type: 'button', className: 'btn sm primary add', textContent: 'Add & use'});
    add.dataset.family = r.family; add.dataset.weight = r.weight;
    b.append(sm, meta, add);
    return b;
  }
  b.append(sm, meta);
  return b;
}
$('matchGo').onclick = async () => {
  if (!$('matchImg').naturalWidth) return;
  const go = $('matchGo'), note = $('matchNote');
  go.disabled = true; go.textContent = 'Finding…';
  note.classList.remove('err'); note.textContent = 'Reading the picture and comparing fonts…';
  try {
    const res = await fetch('/fonts/match', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({image: croppedPicture(), text: $('matchText').value})});
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || 'Something went wrong');
    $('matchText').value = d.text;
    const google = d.results.some(r => r.source === 'google');
    note.textContent = d.results.length
      ? `Closest first, from your fonts and all of Google Fonts.${google ? ' Ones marked Google Fonts are free: add one with a click.' : ''} Wrong text? Fix it above and try again.`
      : 'No font came close. Try a tighter box around one line.';
    if (d.indexing) note.textContent += ` Still preparing the full Google Fonts search (${d.indexing.done} of ${d.indexing.total || '…'} fonts), so for now only likely candidates were checked. Try again in a few minutes for the full search.`;
    $('exactName').textContent = d.exact; $('matchExact').hidden = !d.exact;
    const sample = d.text.split('\n')[0].slice(0, 40);
    $('matchResults').replaceChildren(...d.results.map((r, i) => matchTile(r, i, sample)));
  } catch (err){
    note.classList.add('err'); note.textContent = err.message;
  } finally {
    go.disabled = false; go.textContent = 'Find this font';
  }
};
$('matchText').addEventListener('keydown', e => { if (e.key === 'Enter') $('matchGo').click(); });
// A font file the user owns (e.g. a paid font): only they can see and use it.
$('uploadFontBtn').onclick = $('exactUpload').onclick = () => { $('uploadFont').value = ''; $('uploadFont').click(); };
$('uploadFont').onchange = async () => {
  const file = $('uploadFont').files[0]; if (!file) return;
  const body = new FormData(); body.append('file', file);
  toast(`Adding ${file.name}…`);
  try {
    const res = await fetch('/fonts/upload', {method: 'POST', body});
    const d = await res.json();
    if (!res.ok) throw new Error(d.error || 'Couldn\'t add that font');
    useFontEntry(d.font);
    toast(`${d.font.label} added to your fonts`);
    pickFont(d.font.key);
  } catch (err){ toast(err.message); }
};
$('matchResults').addEventListener('click', async e => {
  const add = e.target.closest('button.add');
  if (add){
    add.disabled = true; add.textContent = 'Adding…';
    try {
      const res = await fetch('/fonts/add', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({family: add.dataset.family, weight: +add.dataset.weight})});
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || 'Couldn\'t add that font');
      useFontEntry(d.font);
      toast(`${d.font.label} added to your fonts`);
      pickFont(d.font.key);
    } catch (err){ toast(err.message); add.disabled = false; add.textContent = 'Add & use'; }
    return;
  }
  const tile = e.target.closest('.font-tile[data-key]');
  if (tile) pickFont(tile.dataset.key);
});
$('matchResults').addEventListener('keydown', e => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.font-tile[data-key]')){ e.preventDefault(); pickFont(e.target.dataset.key); }
});
useFormat('vertical');

let exportPoll = null;
function resetExport(){
  clearInterval(exportPoll); exportPoll = null;
  $('exportLabel').textContent = 'Export video'; $('exportBar').hidden = true; $('exportFill').style.width = '0';
  $('exportBtn').disabled = false;
}
$('exportBtn').onclick = async () => {
  if (!S.pid) return toast('Generate captions first');
  if (S.editing >= 0) commitEdit(true);
  const base = `/projects/${S.pid}/export`;
  if (exportPoll){                                   // second click = cancel
    fetch(base + '/cancel', {method: 'POST'}).catch(() => {});
    resetExport(); return toast('Export cancelled');
  }
  PJ.dirty = true; await saveNow();                  // export exactly what's on screen
  let r;
  try { r = await fetch(base, {method: 'POST'}); }
  catch { return toast('Could not reach the server. Is app.py still running?'); }
  if (!r.ok){ const e = await r.json().catch(() => ({})); return toast(e.error || 'Export failed'); }
  $('exportLabel').textContent = 'Exporting… 0%'; $('exportBar').hidden = false;
  const pid = S.pid;
  exportPoll = setInterval(async () => {
    let s; try { s = await (await fetch(base + '/status')).json(); } catch { return; }
    if (S.pid !== pid) return resetExport();
    if (s.status === 'running'){
      const p = Math.round((s.progress || 0) * 100);
      $('exportLabel').textContent = `Exporting… ${p}% (click to cancel)`; $('exportFill').style.width = p + '%';
      return;
    }
    resetExport();
    if (s.status === 'done'){
      const a = document.createElement('a'); a.href = base + '/file'; a.click();
      toast('Video exported with captions');
    } else if (s.status === 'error') toast(s.error || 'Export failed', {label: 'OK', run: () => {}});
  }, 1000);
};
if (CTX.local) fetch('/info').then(r => r.json()).then(d => { $('engine').textContent = `Speech engine: ${d.device}`; }).catch(() => {});

// ---------- account, plans and payments (website mode) ----------
let ACC = null;
const mins = sec => sec >= 60 ? `${Math.floor(sec / 60)} min` : `${Math.round(sec)} s`;
const rupees = paise => '₹' + (paise / 100).toLocaleString('en-IN');
async function loadAccount(){
  if (CTX.local) return;
  let r;
  try { r = await fetch('/account'); } catch { return; }
  if (r.status === 401) return location.assign('/');
  ACC = await r.json();
  $('usage').hidden = false;
  $('planPill').textContent = ACC.plan_name;
  $('minutesLeft').textContent = `${mins(ACC.remaining_seconds)} left`;
  $('usage').classList.toggle('low', ACC.remaining_seconds < 60);
  $('upgradeBtn').hidden = ACC.plan !== 'free';
  if (S.cues.length) updateStatus();
  $('acctName').textContent = ACC.name || 'Your account'; $('acctEmail').textContent = ACC.email || '';
  $('avatarInitial').textContent = (ACC.name || ACC.email || '?').trim().charAt(0).toUpperCase();
  if (ACC.picture){ $('avatar').src = ACC.picture; $('avatar').hidden = false; $('avatarInitial').hidden = true; }
  syncFooter();
}

let PLANS = null;
async function openPlans(){
  if (CTX.local) return;
  if (!PLANS){ try { PLANS = await (await fetch('/billing/plans')).json(); } catch { return toast('Could not load plans'); } }
  await loadAccount();
  const until = ACC.plan_until ? ` until ${new Date(ACC.plan_until * 1000).toLocaleDateString('en-IN', {day: 'numeric', month: 'short'})}` : '';
  $('plansSummary').textContent = `You're on ${ACC.plan_name}${until} · ${mins(ACC.remaining_seconds)} left this month`;
  const grid = $('planGrid'); grid.innerHTML = '';
  const buyable = {creator: 'creator_30d', pro: 'pro_30d'};
  ['free', 'creator', 'pro'].map(k => [k, PLANS.plans[k]]).forEach(([key, p]) => {
    const card = document.createElement('div'); card.className = 'plan' + (ACC.plan === key ? ' current' : '');
    const h = document.createElement('h3'); h.textContent = p.name;
    const price = document.createElement('div'); price.className = 'price';
    price.textContent = p.price ? rupees(p.price) : '₹0';
    const per = document.createElement('small'); per.textContent = p.price ? ' / 30 days' : ' forever'; price.append(per);
    const ul = document.createElement('ul');
    [`${p.minutes} minutes of video a month`, `Videos up to ${p.max_seconds / 60} min long`,
     p.watermark ? 'Small watermark on video exports' : 'No watermark',
     'All 11 caption templates and 74 fonts, SRT and VTT', 'Learns your words as you edit'].forEach(t => {
      const li = document.createElement('li'); li.textContent = t; ul.append(li); });
    const btn = document.createElement('button'); btn.type = 'button';
    if (ACC.plan === key){ btn.className = 'btn'; btn.textContent = key === 'free' ? 'Current plan' : 'Add 30 days'; btn.disabled = key === 'free'; }
    else { btn.className = 'btn' + (key === 'creator' ? ' primary' : ''); btn.textContent = key === 'free' ? 'Free' : `Get ${p.name}`; btn.disabled = key === 'free'; }
    if (buyable[key]) btn.onclick = () => buy(buyable[key]);
    card.append(h, price, ul, btn); grid.append(card);
  });
  const t = PLANS.products.topup_30, top = $('topup'); top.innerHTML = '';
  const label = document.createElement('span'); label.textContent = `Need a few more minutes? ${t.minutes} extra minutes for ${rupees(t.amount)}, valid on any plan.`;
  const tb = document.createElement('button'); tb.type = 'button'; tb.className = 'btn sm'; tb.textContent = 'Add minutes'; tb.onclick = () => buy('topup_30');
  top.append(label, tb);
  if (!$('plansDlg').open) $('plansDlg').showModal();
}

function loadRazorpay(){
  return window.Razorpay ? Promise.resolve() : new Promise((ok, bad) => {
    const sc = document.createElement('script'); sc.src = 'https://checkout.razorpay.com/v1/checkout.js';
    sc.onload = ok; sc.onerror = () => bad(new Error('Could not load Razorpay')); document.head.append(sc);
  });
}
async function buy(product){
  if (!PLANS.payments) return toast('Payments are not set up on this server yet.');
  let order;
  try {
    const r = await fetch('/billing/order', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({product})});
    order = await r.json();
    if (!r.ok) return toast(order.error || 'Could not start the payment');
    if (order.demo){
      $('plansDlg').close();
      if (!confirm(`DEMO checkout\n\n${order.description}: ${rupees(order.amount)}\n\nSimulate a successful payment? No money is charged.`))
        return toast('Payment cancelled (demo)');
      const p = await fetch('/billing/demo-pay', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({order_id: order.order_id})});
      if (!p.ok) return toast('Demo payment failed');
      await loadAccount(); return toast('Payment received (demo). Thank you!');
    }
    await loadRazorpay();
  } catch { return toast('Could not start the payment. Check your connection.'); }
  $('plansDlg').close();
  const rzp = new Razorpay({
    key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency,
    name: order.name, description: order.description, prefill: order.prefill,
    theme: {color: getComputedStyle(document.documentElement).getPropertyValue('--accent-strong').trim() || '#6a5af9'},
    handler: async resp => {
      try {
        const r = await fetch('/billing/verify', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(resp)});
        const d = await r.json();
        if (!r.ok) return toast(d.error || 'Payment could not be verified');
        await loadAccount(); toast('Payment received. Thank you!');
      } catch { toast('Payment done; refresh in a minute to see it.'); }
    },
  });
  rzp.on('payment.failed', e => toast(e.error?.description || 'Payment failed. No money was taken.'));
  rzp.open();
}

if (!CTX.local){
  $('upgradeBtn').onclick = openPlans; $('usage').onclick = openPlans;
  $('plansClose').onclick = () => $('plansDlg').close();
  $('plansDlg').addEventListener('click', e => { if (e.target === $('plansDlg')) $('plansDlg').close(); });
  const acctBtn = $('acctBtn'), acctMenu = $('acctMenu');
  const closeAcct = () => { acctMenu.hidden = true; acctBtn.setAttribute('aria-expanded', 'false'); };
  acctBtn.onclick = e => { e.stopPropagation(); const open = acctMenu.hidden; acctMenu.hidden = !open; acctBtn.setAttribute('aria-expanded', String(open)); if (open) $('plansItem').focus(); };
  acctMenu.addEventListener('keydown', e => { if (e.key === 'Escape'){ closeAcct(); acctBtn.focus(); } });
  document.addEventListener('click', e => { if (!e.target.closest('#acctMenu')) closeAcct(); });
  $('plansItem').onclick = () => { closeAcct(); openPlans(); };
  $('logoutItem').onclick = async () => { await fetch('/auth/logout', {method: 'POST'}).catch(() => {}); location.assign('/'); };
  loadAccount().then(() => {
    // Arriving from a "Get Creator / Pro" button on the landing page opens the plans straight away.
    if (new URLSearchParams(location.search).has('plans')){ history.replaceState(null, '', '/app'); openPlans(); }
  });
}
function syncToVideo(){
  if (S.cues.length){
    const i = cueAt(clock.currentTime);
    if (i !== S.current) setCurrent(i);
    lightWord();
  }
  updateOverlay();   // word-level: which word is being spoken changes within a subtitle
  if (!$('editor').hidden){
    placeHead(); previewTick();
    $('tNow').textContent = fineClock(clock.currentTime);
  }
}
const fineClock = s => {
  s = Math.max(0, s || 0);
  const m = Math.floor(s / 60), sec = (s % 60).toFixed(1).padStart(4, '0');
  return `${String(m).padStart(2, '0')}:${sec}`;
};
function seekTo(i, play){
  const c = S.cues[i]; if (!c) return;
  if (S.playable){
    clock.currentTime = c.start + 0.001;
    if (play) clock.play().catch(() => {});
  }
  setCurrent(i, true);
  if (!$('editor').hidden){ placeHead(); followHead(); }
}
let raf = 0;
const loop = () => {
  syncToVideo();
  if (!$('editor').hidden) followHead();
  raf = clock.paused ? 0 : requestAnimationFrame(loop);
};
clock.addEventListener('play', () => { if (!raf) raf = requestAnimationFrame(loop); syncPlayBtn(); });
clock.addEventListener('pause', syncPlayBtn);
clock.addEventListener('seeked', syncToVideo);
clock.addEventListener('timeupdate', () => { if (!raf) syncToVideo(); });
video.addEventListener('loadedmetadata', () => { $('tDur').textContent = fineClock(clock.duration || video.duration); });
clock.addEventListener('volumechange', () => {
  $('muteIco').innerHTML = `<use href="#i-${clock.muted ? 'mute' : 'vol'}"/>`;
  $('muteBtn').setAttribute('aria-label', clock.muted ? 'Unmute' : 'Mute');
});

// ----- the editor's own player controls -----
function syncPlayBtn(){
  $('playIco').innerHTML = `<use href="#i-${clock.paused ? 'play' : 'pause'}"/>`;
  $('playBtn').setAttribute('aria-label', clock.paused ? 'Play' : 'Pause');
}
const togglePlay = () => { if (!S.playable) return; clock.paused ? clock.play().catch(() => {}) : clock.pause(); };
$('playBtn').onclick = togglePlay;
$('muteBtn').onclick = () => { clock.muted = !clock.muted; };
// Full screen enlarges the whole stage; the player inside keeps the video's shape, so the
// captions (drawn on a canvas the size of the player) always sit exactly on the picture.
$('fsBtn').onclick = () => {
  const box = $('stageBox');
  if (document.fullscreenElement) document.exitFullscreen();
  else (box.requestFullscreen || box.webkitRequestFullscreen)?.call(box);
};
document.addEventListener('fullscreenchange', () => setTimeout(() => {
  updateOverlay(true); if (typeof resizeAss === 'function'){ resizeAss(); drawHits(true); }
}, 60));
player.addEventListener('click', e => { if (!$('editor').hidden && !justDragged && !e.target.closest('.cl-block, .cap-frame')) togglePlay(); });
$('speedSeg').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  clock.playbackRate = +b.dataset.v;
  $('speedSeg').querySelectorAll('button').forEach(o => o.setAttribute('aria-pressed', String(o === b)));
};
$('safeBtn').onclick = () => {
  const on = $('safeZone').hidden;
  $('safeZone').hidden = !on; $('safeBtn').setAttribute('aria-pressed', String(on));
};
new ResizeObserver(() => updateOverlay(true)).observe(player);

// ----- right panel: Templates / Text -----
function sideTab(text){
  $('sideTpl').setAttribute('aria-selected', String(!text)); $('sideTpl').tabIndex = text ? -1 : 0;
  $('sideText').setAttribute('aria-selected', String(text)); $('sideText').tabIndex = text ? 0 : -1;
  $('paneTpl').hidden = text; $('paneText').hidden = !text;
  if (!text) tileState.clear();
}
$('sideTpl').onclick = () => sideTab(false);
$('sideText').onclick = () => sideTab(true);

$('autoScroll').onclick = () => {
  S.autoScroll = !S.autoScroll;
  $('autoScroll').setAttribute('aria-checked', S.autoScroll);
  if (S.autoScroll && S.current >= 0) scrollToRow($('cues').children[S.current]);
};

// Native text track only shows in native fullscreen (iPhone), where the overlay can't follow.
function refreshTrack(){
  if (!video.textTracks || !window.VTTCue) return;
  if (!S.track){ S.track = video.addTextTrack('subtitles', 'Subtitles'); S.track.mode = 'hidden'; }
  [...(S.track.cues || [])].forEach(c => S.track.removeCue(c));
  S.cues.forEach(c => S.track.addCue(new VTTCue(c.start, c.end, c.text)));
}
const setFs = on => S.track && (S.track.mode = on ? 'showing' : 'hidden');
video.addEventListener('webkitbeginfullscreen', () => setFs(true));
video.addEventListener('webkitendfullscreen', () => setFs(false));

// ---------- export ----------
const ts = (s, sep) => {
  const ms = Math.round(s * 1000), h = Math.floor(ms / 3.6e6), m = Math.floor(ms % 3.6e6 / 6e4),
        sec = Math.floor(ms % 6e4 / 1000), r = ms % 1000, p = (n, l = 2) => String(n).padStart(l, '0');
  return `${p(h)}:${p(m)}:${p(sec)}${sep}${p(r, 3)}`;
};
const build = {
  srt: () => S.cues.map((c, i) => `${i + 1}\n${ts(c.start, ',')} --> ${ts(c.end, ',')}\n${c.text}\n`).join('\n'),
  vtt: () => 'WEBVTT\n\n' + S.cues.map(c => `${ts(c.start, '.')} --> ${ts(c.end, '.')}\n${c.text}\n`).join('\n'),
  txt: () => S.cues.map(c => c.text).join('\n'),
};
function download(fmt){
  if (fmt === 'ass'){                      // built by the server: every style, position and animation
    PJ.dirty = true; saveNow().then(() => { const a = document.createElement('a'); a.href = `/projects/${S.pid}/subtitles.ass`; a.click(); });
    return;
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([build[fmt]()], {type: 'text/plain;charset=utf-8'}));
  a.download = `${S.baseName}_${S.mode}.${fmt}`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast(`${fmt.toUpperCase()} downloaded`);
}

const dlBtn = $('dlBtn'), dlMenu = $('dlMenu'), items = () => [...dlMenu.querySelectorAll('[role=menuitem]')];
function openMenu(focusIdx = 0){
  dlMenu.hidden = false; dlBtn.setAttribute('aria-expanded', 'true');
  items()[focusIdx]?.focus();
}
function closeMenu(refocus){
  if (dlMenu.hidden) return;
  dlMenu.hidden = true; dlBtn.setAttribute('aria-expanded', 'false');
  if (refocus) dlBtn.focus();
}
dlBtn.onclick = () => dlMenu.hidden ? openMenu() : closeMenu();
dlBtn.addEventListener('keydown', e => {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp'){ e.preventDefault(); openMenu(e.key === 'ArrowUp' ? items().length - 1 : 0); }
});
dlMenu.addEventListener('keydown', e => {
  const list = items(), i = list.indexOf(document.activeElement);
  if (e.key === 'ArrowDown'){ e.preventDefault(); list[(i + 1) % list.length].focus(); }
  else if (e.key === 'ArrowUp'){ e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
  else if (e.key === 'Home'){ e.preventDefault(); list[0].focus(); }
  else if (e.key === 'End'){ e.preventDefault(); list[list.length - 1].focus(); }
  else if (e.key === 'Escape'){ e.preventDefault(); e.stopPropagation(); closeMenu(true); }
  else if (e.key === 'Tab') closeMenu();
});
dlMenu.querySelectorAll('[data-fmt]').forEach(b => b.onclick = () => { closeMenu(true); download(b.dataset.fmt); });
document.addEventListener('click', e => { if (!e.target.closest('.menu-wrap')) closeMenu(); });

$('copyBtn').onclick = async () => {
  closeMenu(true);
  try { await navigator.clipboard.writeText(build.srt()); toast('Copied'); }
  catch { toast('Copy failed — your browser blocked clipboard access'); }
};

// ---------- keyboard shortcuts ----------
document.addEventListener('keydown', e => {
  if (e.defaultPrevented || !S.file) return;
  const t = e.target, typing = t.closest('input, textarea, select, [contenteditable=true]');
  const inEditor = !$('editor').hidden;
  if (inEditor && (e.metaKey || e.ctrlKey) && !e.altKey){
    const k = e.key.toLowerCase();
    if (k === 'z' && !typing){ e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (k === 'y' && !typing){ e.preventDefault(); redo(); return; }
    if (k === 'f'){ e.preventDefault(); showFind(true); return; }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey || typing || t.closest('[role=menu], video, dialog')) return;
  if (e.key === ' '){
    // Space on ordinary buttons keeps its normal meaning; inside the list it plays/pauses.
    if (t.closest('button') && !t.closest('.cues, .ed-stage, .tl')) return;
    if (!S.playable) return;
    e.preventDefault(); togglePlay();
  } else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && S.cues.length){
    e.preventDefault();
    const cur = S.sel >= 0 ? S.sel : S.current, dir = e.key === 'ArrowDown' ? 1 : -1;
    let next = cur < 0 ? (dir > 0 ? 0 : S.cues.length - 1) : cur + dir;
    const rows = $('cues').children;
    while (rows[next]?.hidden) next += dir;            // skip lines hidden by search
    if (next >= 0 && next < S.cues.length){ if (inEditor) select(next, false); seekTo(next, false); }
  } else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && inEditor && S.playable){
    e.preventDefault();
    clock.currentTime = Math.min(Math.max(clock.currentTime + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 5 : 1), 0), dur());
    followHead();
  } else if ((e.key === 'e' || e.key === 'E' || (e.key === 'Enter' && !t.closest('button, a'))) && S.cues.length){
    const i = S.sel >= 0 ? S.sel : S.current >= 0 ? S.current : 0;
    e.preventDefault(); startEdit(i);
  } else if (!inEditor){
    return;
  } else if ((e.key === 's' || e.key === 'S') && S.sel >= 0 && !S.selClip){ e.preventDefault(); $('splitBtn').click(); }   // a caption line is picked: split the line
  else if (e.key === 's' || e.key === 'S'){ e.preventDefault(); splitClipAt(clock.currentTime); }                  // else cut the video here
  else if (e.key === 'i' || e.key === 'I'){ e.preventDefault(); markIn(); }
  else if (e.key === 'o' || e.key === 'O'){ e.preventDefault(); markOut(); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && CUT.range){ e.preventDefault(); removeRange(CUT.range.t0, CUT.range.t1); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && e.shiftKey && (S.selWords?.size || S.sel >= 0)){ e.preventDefault(); removeTextFromVideo(); }
  else if (e.key === 'm' || e.key === 'M'){ e.preventDefault(); $('mergeBtn').click(); }
  else if (e.key === 'n' || e.key === 'N'){ e.preventDefault(); addCue(); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && S.selClip){ e.preventDefault(); deleteClip(S.selClip, e.altKey); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && S.selSuper){ e.preventDefault(); deleteSuper(S.selSuper); }
  else if ((e.key === 'Delete' || e.key === 'Backspace') && S.sel >= 0){ e.preventDefault(); deleteCue(S.sel); }
  else if (e.key === 't' || e.key === 'T'){ e.preventDefault(); addSuper(); }
  else if (e.key === '=' || e.key === '+'){ e.preventDefault(); setZoom(TL.pps * 1.4); }
  else if (e.key === '-' || e.key === '_'){ e.preventDefault(); setZoom(TL.pps / 1.4); }
  else if (e.key === 'Escape'){ if (CUT.range) clearRange(); else clearSelection(); }
});

// Buttons activate on Space keyup; stop that when Space was used for play/pause.
document.addEventListener('keyup', e => {
  if (e.key === ' ' && e.target.closest?.('.cues button, .ed-stage button, .tl button')) e.preventDefault();
});
window.addEventListener('beforeunload', e => { if (S.cues.length && H.past.length){ e.preventDefault(); e.returnValue = ''; } });

syncFooter();
