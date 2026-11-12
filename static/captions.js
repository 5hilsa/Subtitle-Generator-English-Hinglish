/* Caption templates in the browser: the live preview of what render.py exports.
   Same rules as looks.py (pages, lines, key words) and render.py (sizes, colours,
   boxes), so the preview matches the burned-in video. Keep the three in step.

   CaptionLook.init({fonts, looks})          once, with the catalogues from the server
   CaptionLook.pages(words, maxWords)        words: [{text, start, end}]
   CaptionLook.draw(root, opts)              draws one page into `root` (see draw below)
   CaptionLook.at(cue, time, tpl)            {page, active, first, key} for a cue at a time */
(function(){
  'use strict';
  const DEVA = /[ऀ-ॿ]/, PUNCT = /[,.?!;:।]$/;
  const LIGHT = new Set(['poppins', 'lora_medium', 'inter_semibold', 'kaushan']);
  let FONT = {}, LOOKS = {templates: {}, default: 'hustle', stop: []}, STOP = new Set();
  const loaded = new Set();

  function init({fonts, looks}){
    FONT = Object.fromEntries(fonts.fonts.map(f => [f.key, f]));
    LOOKS = looks; STOP = new Set(looks.stop);
  }
  function loadFont(key){
    const f = FONT[key];
    if (!f || loaded.has(key)) return;
    loaded.add(key);
    new FontFace(`F-${key}`, `url(/fonts/${encodeURIComponent(f.file)})`).load()
      .then(face => { document.fonts.add(face); }).catch(() => loaded.delete(key));
  }
  const family = key => `'F-${key}', 'Poppins', sans-serif`;

  // ---- shared rules (mirror looks.py) ----
  function pages(words, max){
    if (!max) return words.length ? [words] : [];
    const out = []; let cur = [];
    for (const w of words){
      if (cur.length && w.start - cur[cur.length - 1].end > 0.6){ out.push(cur); cur = []; }
      cur.push(w);
      if (cur.length >= max || (cur.length >= 2 && PUNCT.test(w.text))){ out.push(cur); cur = []; }
    }
    if (cur.length) out.push(cur);
    return out;
  }
  function splitLines(texts, tpl){
    const n = texts.length, all = [...Array(n).keys()];
    if (n < 2 || (tpl.lines || 1) < 2) return [all];
    if (tpl.split === 'half'){ const k = Math.ceil(n / 2); return [all.slice(0, k), all.slice(k)]; }
    const len = a => a.reduce((s, t) => s + t.length, 0) + Math.max(0, a.length - 1);
    if (len(texts) <= (tpl.chars || 24)) return [all];
    let best = Infinity, bk = 1;
    for (let k = 1; k < n; k++){
      const m = Math.max(len(texts.slice(0, k)), len(texts.slice(k)));
      if (m < best){ best = m; bk = k; }
    }
    return [all.slice(0, bk), all.slice(bk)];
  }
  function emphasis(texts, tpl){
    const e = tpl.emphasis, out = {};
    if (!e || !Object.keys(e).length) return out;
    let key = -1, keyLen = 4;
    texts.forEach((t, i) => {
      const bare = t.toLowerCase().replace(/[^\p{L}\p{N}%]/gu, '');
      if (/\d/.test(bare)) out[i] = e.num;
      else if (!STOP.has(bare) && bare.length > keyLen){ key = i; keyLen = bare.length; }
    });
    if (key >= 0) out[key] = e.key;
    return out;
  }
  function withAccent(tpl, accent){
    tpl = {...tpl, line2: {...(tpl.line2 || {})}, emphasis: {...(tpl.emphasis || {})}};
    const f = tpl.accent;
    if (f && accent && /^#[0-9a-f]{6}$/i.test(accent)){
      if (f.includes('.')){ const [a, b] = f.split('.'); tpl[a][b] = accent; }
      else { const old = tpl[f] || ''; tpl[f] = accent + (old.length === 9 ? old.slice(7) : ''); }
    }
    return tpl;
  }
  /** The template after the user's choices: accent colour and font. */
  function resolve(key, {accent, font} = {}){
    let tpl = withAccent(LOOKS.templates[key] || LOOKS.templates[LOOKS.default], accent);
    tpl.scale = 1;
    if (font && FONT[font]){
      tpl.scale = FONT[font].scale / FONT[tpl.font].scale;
      tpl.font = font;
      if (tpl.line2.font) tpl.line2.font = font;
    }
    return tpl;
  }

  // ---- timing ----
  function wordTimes(cue, n, texts){
    if (cue.wt && cue.wt.length === n)
      return cue.wt.map(([s, e]) => { s = Math.max(s, cue.start); e = Math.min(e, cue.end); return [s, Math.max(e, s + .05)]; });
    const total = texts.reduce((a, w) => a + w.length, 0) || 1, span = cue.end - cue.start;
    let t = cue.start;
    return texts.map(w => { const d = span * w.length / total, r = [t, t + d]; t += d; return r; });
  }
  /** Which page and word of `cue` is on screen at `time`. */
  function at(cue, time, tpl){
    const texts = cue.text.split(/\s+/).filter(Boolean);
    if (!texts.length) return null;
    const times = wordTimes(cue, texts.length, texts);
    const words = texts.map((t, i) => ({text: t, start: times[i][0], end: times[i][1], i}));
    const groups = pages(words, tpl.words || 0);
    let gi = groups.length - 1;
    for (let g = 1; g < groups.length; g++) if (time < groups[g][0].start){ gi = g - 1; break; }
    const page = groups[gi];
    const stateful = !!(tpl.upcoming || tpl.active || tpl.active_box || tpl.spoken_box || tpl.active_scale);
    let active = null;
    if (stateful){
      active = 0;
      for (let k = 1; k < page.length; k++) if (time >= page[k].start) active = k;
    }
    return {page: page.map(w => w.text), active, pageKey: `${gi}`, key: `${gi}:${active}`};
  }

  // ---- drawing ----
  const rgba = hex => {
    const h = hex.replace('#', ''), a = h.length === 8 ? parseInt(h.slice(6), 16) / 255 : 1;
    return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${+a.toFixed(3)})`;
  };
  function fontFor(text, key){
    if (DEVA.test(text) && FONT[key] && !FONT[key].hindi) return LIGHT.has(key) ? 'poppins' : 'poppins_xb';
    return key;
  }

  /** Draws one page of a caption into `root` (an absolutely positioned layer over the video).
   *  opts: {tpl, words (texts), active (index or null), em (px), position, newPage (bool: animate in)} */
  function draw(root, {tpl, words, active, em, position = 'bottom', newPage = false, landscape = false}){
    const hide = tpl.upcoming === 'hide';
    const visible = hide && active != null ? active + 1 : words.length;
    const lines = splitLines(words, tpl), styledTwo = tpl.split === 'half' && lines.length === 2;
    const emph = emphasis(words, tpl), l2 = tpl.line2 || {};
    const block = document.createElement('div');
    block.className = 'cl-block';
    const margin = landscape ? 8 : 20;
    Object.assign(block.style, {
      position: 'absolute', fontSize: em + 'px', lineHeight: '1.18', whiteSpace: 'nowrap',
      textAlign: tpl.align === 'left' ? 'left' : 'center', letterSpacing: (tpl.spacing || 0) + 'em',
    });
    if (tpl.align === 'left') block.style.left = '8%';
    else { block.style.left = '50%'; block.style.translate = '-50% 0'; }
    if (position === 'top') block.style.top = margin + '%';
    else if (position === 'middle'){ block.style.top = '50%'; block.style.translate = (tpl.align === 'left' ? '0' : '-50%') + ' -50%'; }
    else block.style.bottom = margin + '%';
    if (tpl.page_box){
      Object.assign(block.style, {background: rgba(tpl.page_box), padding: '.05em .45em', borderRadius: '.3em'});
    }
    const shadow = (glow, inBox) => {
      const s = [];
      if (glow) s.push(`0 0 .14em ${rgba(glow + 'B0')}`, `0 0 .4em ${rgba(glow + '90')}`);
      if (inBox) return s.join(',') || 'none';
      if (tpl.shadow === 'hard') s.push(`0 .06em 0 #000`);
      if (tpl.shadow === 'soft') s.push(`0 .06em .22em rgba(0,0,0,.45)`);
      return s.join(',') || 'none';
    };
    lines.forEach((idx, li) => {
      const styled = styledTwo && li === 1;
      const line = document.createElement('div');
      const key = styled && l2.font ? l2.font : tpl.font;
      const upper = styled && 'upper' in l2 ? l2.upper : tpl.upper;
      if (styled && l2.size) line.style.fontSize = l2.size + 'em';
      let shown = 0;
      idx.forEach((j, n) => {
        const st = active == null ? 'spoken' : j < active ? 'spoken' : j === active ? 'active' : 'upcoming';
        if (j >= visible) return;
        const text = upper ? words[j].toUpperCase() : words[j];
        if (shown++){
          const sp = document.createElement('span');
          sp.textContent = '\u00a0';
          Object.assign(sp.style, {display: 'inline-block', fontFamily: family(key)});
          if (tpl.spoken_box && j <= (active ?? -1)) sp.style.background = rgba(tpl.spoken_box);
          if (tpl.active_scale) sp.style.marginLeft = ((tpl.active_scale - 1) * 1.2) + 'em';
          line.append(sp);
        }
        const w = document.createElement('span');
        w.textContent = text;
        const fk = fontFor(text, key); loadFont(fk);
        if (DEVA.test(text)) w.style.letterSpacing = '0';   // spacing breaks up Hindi letter joins
        let col = styled && l2.color ? l2.color : tpl.color;
        if (emph[j] && st !== 'upcoming') col = emph[j];
        if (st === 'active' && tpl.active) col = tpl.active;
        if (st === 'upcoming' && tpl.upcoming && !hide) col = tpl.upcoming;
        const inBox = (tpl.active_box && st === 'active') || (tpl.spoken_box && st !== 'upcoming');
        if (inBox && tpl.box_text) col = tpl.box_text;
        const glow = styled ? ('glow' in l2 ? l2.glow : tpl.glow) : tpl.glow;
        Object.assign(w.style, {
          fontFamily: family(fk), color: rgba(col), display: 'inline-block',
          textShadow: shadow(glow, inBox), paintOrder: 'stroke fill',
          WebkitTextStroke: tpl.outline ? `${tpl.outline * 2}em ${rgba(tpl.outline_color || '#000000')}` : '',
        });
        if (tpl.active_box && st === 'active')
          Object.assign(w.style, {background: rgba(tpl.active_box), borderRadius: '.22em', padding: '0 .18em', margin: '0 -.18em'});
        if (tpl.spoken_box && st !== 'upcoming')
          Object.assign(w.style, {background: rgba(tpl.spoken_box), borderRadius: '.1em', padding: '0 .12em', margin: '0 -.12em'});
        if (st === 'active' && tpl.active_scale) w.style.transform = `scale(${tpl.active_scale})`;
        if (hide && st === 'active') w.className = 'cl-in';
        line.append(w);
      });
      block.append(line);
    });
    if (newPage && tpl.pop) block.classList.add('cl-pop');
    if (newPage && tpl.fade) block.classList.add('cl-fade');
    root.replaceChildren(block);
    // Shrink to fit 84% of the frame, like the export.
    const max = root.clientWidth * .84, wd = block.scrollWidth;
    if (wd > max && wd > 0) block.style.fontSize = (em * max / wd) + 'px';
    return block;
  }

  // Animations for pop-in, fade and reveal; injected once.
  const css = document.createElement('style');
  css.textContent = `
@keyframes cl-pop{0%{scale:.7}55%{scale:1.08}100%{scale:1}}
@keyframes cl-fade{from{opacity:0}to{opacity:1}}
@keyframes cl-in{from{opacity:0;transform:translateY(.15em)}to{opacity:1;transform:none}}
.cl-pop{animation:cl-pop .17s ease-out both}
.cl-fade{animation:cl-fade .18s ease-out both}
.cl-in{animation:cl-in .16s ease-out both}
@media (prefers-reduced-motion:reduce){.cl-pop,.cl-fade,.cl-in{animation:none}}`;
  document.head.append(css);

  /** Text size in px for a frame of size w x h (same formula as render.py). */
  const emFor = (w, h, tpl, size = 1) => Math.min(w, h) * (h > w ? .075 : .06) * tpl.size * size * (tpl.scale || 1);

  window.CaptionLook = {init, loadFont, pages, splitLines, emphasis, resolve, at, draw, emFor,
                        get templates(){ return LOOKS.templates; }, get order(){ return LOOKS.order; }, get defaultKey(){ return LOOKS.default; }};
})();
