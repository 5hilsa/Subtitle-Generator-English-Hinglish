// Cutting, speed and transitions in the editor's model, run without a browser:
//   node tests/test_cut.js
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
const ROOT = path.join(__dirname, '..');
const el = () => ({hidden: false, children: [], style: {}, dataset: {}, classList: {add(){}, remove(){}, toggle(){}}, append(){}, replaceChildren(){}, addEventListener(){}, querySelector(){ return null; }});
const toasts = [];
const ctx = {
  console, performance, EventTarget, Event, addEventListener(){}, setTimeout, clearTimeout, requestAnimationFrame: () => 0, cancelAnimationFrame(){},
  document: {querySelector: () => null, createElement: el}, window: {},
  $: () => el(), tlContent: el(), TL: {pps: 50},
  S: {cues: [], hidden: [], supers: [], selWords: new Set(), sel: -1, nextId: 100},
  toast: m => toasts.push(m), pushHistory(){ ctx.pushes++; }, pushes: 0,
  tlRender(){}, edited(){}, updateStatus(){}, inspectorSync(){}, renderCues(){}, followHead(){}, setScope(){},
  refreshWordMarks(){}, select(i){ ctx.S.sel = i; }, fine: s => s.toFixed(2), sideTab(){}, drawHits(){}, schedulePreview(){},
  begin(){}, done(){}, undo(){}, snapTo: t => [t, null], showSnap(){}, timeAt: () => 0, placeHead(){},
};
ctx.dur = () => ctx.tlDuration();
vm.createContext(ctx);
const src = ['player.js', 'model.js', 'clips.js', 'cut.js'].map(f => fs.readFileSync(path.join(ROOT, 'static/editor', f), 'utf8')).join('\n;\n');
vm.runInContext(src + '\n;edited = () => {};\nthis.api = {PJ, clock, wrapCue, relinkCaptions, removeRange, setClipSpeed, textRanges, removeTextFromVideo, clipTransitions, clipLen, clipEnd, toTL, toAsset, CUT};', ctx);
const A = ctx.api;
const eq = (a, b) => assert.deepStrictEqual(JSON.parse(JSON.stringify(a)), b);   // values from the sandbox's realm

const words = (list) => list.map(([t, t0, t1], k) => ({id: 'w' + t + k, text: t, t0, t1}));
function fresh(){
  A.PJ.doc = {id: 'p', canvas: {w: 1080, h: 1920}, assets: [{id: 'a1', w: 1080, h: 1920, duration: 10, audio: true}],
    tracks: [{id: 'v1', kind: 'video', name: 'Video 1', clips: [{id: 'c1', asset: 'a1', in: 0, out: 10, at: 0}]},
             {id: 's', kind: 'subtitle', groups: []}]};
  ctx.S.cues = [
    {id: 'g1', asset: 'a1', t0: 0.5, t1: 3, words: words([['one', .5, 1], ['two', 1.2, 1.8], ['three', 2.2, 3]])},
    {id: 'g2', asset: 'a1', t0: 5, t1: 6, words: words([['four', 5, 5.4], ['five', 5.5, 6]])},
  ].map(A.wrapCue);
  ctx.S.hidden = []; ctx.S.supers = [{id: 'x1', t0: 7, t1: 8, words: []}]; ctx.S.sel = -1; ctx.S.selWords = new Set();
  A.relinkCaptions();
}
const clips = () => A.PJ.doc.tracks[0].clips.map(c => [c.in, c.out, c.at, c.speed || 1]);
const lines = () => ctx.S.cues.map(c => [c.text, +c.start.toFixed(2), +c.end.toFixed(2)]);

// remove a section in the middle: the clip splits, what follows moves up, captions follow
fresh();
assert.strictEqual(+A.removeRange(1.5, 2.5).toFixed(3), 1);
eq(clips(), [[0, 1.5, 0, 1], [2.5, 10, 1.5, 1]]);
eq(lines(), [['one', 0.5, 1.5], ['three', 1.5, 2], ['four five', 4, 5]]);   // "two" sat across the cut: the line split at it
eq([ctx.S.supers[0].t0, ctx.S.supers[0].t1], [6, 7]);
assert.strictEqual(A.clock.currentTime, 1.5);

// speed: 2x halves the clip, captions land at the right moments, later clips move up
fresh();
A.PJ.doc.tracks[0].clips = [{id: 'c1', asset: 'a1', in: 0, out: 4, at: 0}, {id: 'c2', asset: 'a1', in: 4, out: 10, at: 4}];
A.relinkCaptions();
ctx.S.selClip = {id: 'c1'};
A.setClipSpeed(2);
eq(clips(), [[0, 4, 0, 2], [4, 10, 2, 1]]);
eq(lines()[0], ['one two three', 0.25, 1.5]);
eq(lines()[1], ['four five', 3, 4]);
eq(ctx.S.cues[0].wt[1], [0.6, 0.9]);
ctx.S.cues[0].wt = [[0.25, 0.5], [0.6, 0.9], [1, 1.5]];             // retiming in timeline time writes file time
eq([ctx.S.cues[0].words[2].t0, ctx.S.cues[0].words[2].t1], [2, 3]);
ctx.S.selClip = null;

// cut by text: picked words become one stretch with a little air, the gap closes
fresh();
ctx.S.selWords = new Set([ctx.S.cues[0].words[1].id]);              // "two" (1.2-1.8)
eq(A.textRanges().map(r => r.map(x => +x.toFixed(2))), [[1.16, 1.84]]);
ctx.S.selWords = new Set([ctx.S.cues[0].words[1].id, ctx.S.cues[0].words[2].id]);   // "two three"
eq(A.textRanges().map(r => r.map(x => +x.toFixed(2))), [[1.16, 3]]);
ctx.pushes = 0;
A.removeTextFromVideo();
assert.strictEqual(ctx.pushes, 1);                                   // one undo step
eq(lines(), [['one', 0.5, 1.16], ['four five', 3.16, 4.16]]);   // the line ends at the cut
// a whole line, picked with no words
fresh(); ctx.S.sel = 1;
A.removeTextFromVideo();
eq(clips(), [[0, 5, 0, 1], [6, 10, 5, 1]]);

// transitions: only between clips that touch, capped by their length
fresh();
const t = A.PJ.doc.tracks[0];
t.clips = [{id: 'c1', asset: 'a1', in: 0, out: 1, at: 0}, {id: 'c2', asset: 'a1', in: 3, out: 8, at: 1, trans: {type: 'cross', d: 2}},
           {id: 'c3', asset: 'a1', in: 8, out: 10, at: 7, trans: {type: 'dip', d: .5}}];
const tr = A.clipTransitions(t);
eq(Object.keys(tr), ['c2']);                     // c3 doesn't touch c2 (gap at 6-7)
assert.strictEqual(tr.c2.d, 0.5);                                     // half of c1's 1 s

console.log('cut tests ok');
