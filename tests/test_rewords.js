// Editing a caption's text keeps word timing and style.   node tests/test_rewords.js
'use strict';
const fs = require('fs'), path = require('path'), assert = require('assert');
const src = fs.readFileSync(path.join(__dirname, '../static/editor/model.js'), 'utf8');
const end = src.indexOf('// ---------- the project document');
global.S = {nextId: 100};
eval(src.slice(0, end) + '\nglobal.Cue = Cue;');

const cue = () => new Cue({t0: 0, t1: 3, words: [
  {id: 'a', t0: 0, t1: .5, text: 'roz'}, {id: 'b', t0: .5, t1: 1, text: '200'},
  {id: 'c', t0: 1, t1: 1.6, text: 'coins', o: {color: '#FFE81F'}}, {id: 'd', t0: 1.6, t1: 2.2, text: 'klem'},
  {id: 'e', t0: 2.2, t1: 3, text: 'karo'}]});

// a fix keeps the replaced word's time and id
let c = cue(); c.text = 'roz 200 coins claim karo';
assert.deepStrictEqual(c.words.map(w => [w.id, w.t0, w.t1]), [['a', 0, .5], ['b', .5, 1], ['c', 1, 1.6], ['d', 1.6, 2.2], ['e', 2.2, 3]]);
assert.strictEqual(c.words[2].o.color, '#FFE81F');

// an inserted word shares the neighbour's time, nothing else moves
c = cue(); c.text = 'roz 200 coins abhi klem karo';
assert.deepStrictEqual(c.words.filter(w => w.text !== 'abhi' && w.text !== 'coins').map(w => [w.text, w.t0, w.t1]),
  [['roz', 0, .5], ['200', .5, 1], ['klem', 1.6, 2.2], ['karo', 2.2, 3]]);
const abhi = c.words.find(w => w.text === 'abhi');
assert.ok(abhi.t0 >= 1 && abhi.t1 <= 1.6 + 1e-9, 'inserted word sits between coins and klem');

// one word split into two shares its time
c = cue(); c.text = 'roz 200 coins kl em karo';
const kl = c.words.find(w => w.text === 'kl'), em = c.words.find(w => w.text === 'em');
assert.strictEqual(kl.t0, 1.6); assert.ok(Math.abs(em.t1 - 2.2) < 1e-6);

// deleting keeps the rest exactly
c = cue(); c.text = 'roz coins karo';
assert.deepStrictEqual(c.words.map(w => w.id), ['a', 'c', 'e']);
console.log('rewords: all good');
