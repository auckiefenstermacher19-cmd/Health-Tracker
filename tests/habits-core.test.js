'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../habits-core.js');

// The fixture is pinned to LF in .gitattributes; strip CR anyway so a checkout
// with autocrlf cannot break the byte-identical round-trip test.
const FIX = fs.readFileSync(path.join(__dirname, 'fixtures', 'habits-sample.csv'), 'utf8').replace(/\r\n/g, '\n');
const DEFS = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'habits', 'definitions.json'), 'utf8'));

test('parse then serialize is byte-identical on the real file', () => {
  const p = core.parseCSV(FIX);
  assert.equal(core.serializeCSV(p.header, p.rows), FIX);
});

test('parse handles quoted commas and doubled quotes', () => {
  const p = core.parseCSV('a,b\n"x, y","say ""hi"""\n');
  assert.deepEqual(p.rows[0], { a: 'x, y', b: 'say "hi"' });
  assert.equal(core.serializeCSV(p.header, p.rows), 'a,b\n"x, y","say ""hi"""\n');
});

test('a field with an embedded newline round-trips byte-identically', () => {
  const csv = 'date,note\n2026-09-11,"line one\nline two"\n';
  const p = core.parseCSV(csv);
  assert.equal(p.rows[0].note, 'line one\nline two');
  assert.equal(p.rows.length, 1, 'the newline inside quotes is not a record break');
  assert.equal(core.serializeCSV(p.header, p.rows), csv);
});

test('serialize uses LF, trailing newline, no quoting when not needed', () => {
  assert.equal(core.serializeCSV(['a', 'b'], [{ a: '1', b: '' }]), 'a,b\n1,\n');
});

test('upsertDay creates a sorted row with day_of_week and logged_at', () => {
  const p = core.parseCSV('date,day_of_week,made_bed,teeth,logged_at,note\n2026-09-12,Saturday,yes,,,\n');
  const out = core.upsertDay(p, '2026-09-11', { made_bed: 'yes', teeth: 'no' }, '2026-09-11T22:10:00-04:00');
  assert.equal(out.rows.length, 2);
  assert.deepEqual(out.rows[0], { date: '2026-09-11', day_of_week: 'Friday', made_bed: 'yes', teeth: 'no', logged_at: '2026-09-11T22:10:00-04:00', note: '' });
  assert.equal(out.rows[1].date, '2026-09-12');
  assert.equal(p.rows.length, 1, 'input not mutated');
});

test('upsertDay updates only the given keys and can clear one', () => {
  const p = core.parseCSV('date,day_of_week,made_bed,teeth,slept_7h,logged_at,note\n2026-09-11,Friday,yes,yes,no,old,keep me\n');
  const out = core.upsertDay(p, '2026-09-11', { teeth: '' }, 'new');
  assert.deepEqual(out.rows[0], { date: '2026-09-11', day_of_week: 'Friday', made_bed: 'yes', teeth: '', slept_7h: 'no', logged_at: 'new', note: 'keep me' });
});

test('upsertDay refuses unknown columns', () => {
  const p = core.parseCSV('date,day_of_week,logged_at,note\n');
  assert.throws(() => core.upsertDay(p, '2026-09-11', { nope: 'yes' }, 'x'), /unknown column/);
});

test('phoneHabits are the eleven in order, derivedHabits exclude self and retired', () => {
  const ids = core.phoneHabits(DEFS).map(h => h.id);
  assert.deepEqual(ids, ['made_bed', 'morning_vitamins', 'shower', 'teeth', 'night_vitamins', 'no_junk', 'no_fap', 'read_fiction', 'read_nonfiction', 'devices_off_9pm', 'screentime']);
  const d = core.derivedHabits(DEFS).map(h => h.id);
  assert.ok(d.includes('slept_7h') && d.includes('water') && d.includes('workout') && d.includes('calories_on_target'));
  assert.ok(!d.includes('shower_teeth') && !d.includes('made_bed'));
  // water and workout are source 'self' so the GTD Year tab can tick them;
  // auto_source is what puts them on the automatic list here.
  assert.equal(DEFS.habits.find(h => h.id === 'water').source, 'self');
  assert.equal(DEFS.habits.find(h => h.id === 'workout').source, 'self');
  assert.ok(!ids.includes('water') && !ids.includes('workout'));
});

test('phoneHabits skips a weekly habit even when it carries a phone_order', () => {
  const synthetic = {
    habits: [
      { id: 'made_bed', source: 'self', phone_order: 1 },
      { id: 'clean_sink', source: 'self', phone_order: 2, cadence: 'weekly' },
      { id: 'water', source: 'self', auto_source: 'water_dashboard', phone_order: 3 },
    ],
  };
  assert.deepEqual(core.phoneHabits(synthetic).map(h => h.id), ['made_bed']);
  assert.deepEqual(core.derivedHabits(synthetic).map(h => h.id), ['water']);
});

test('date helpers are device-local and formatted for humans', () => {
  const d = new Date(2026, 8, 11, 22, 10, 0);            // local time
  assert.equal(core.todayLocal(d), '2026-09-11');
  assert.match(core.localISO(d), /^2026-09-11T22:10:00[+-]\d\d:\d\d$/);
  assert.equal(core.dayOfWeek('2026-09-11'), 'Friday');
  assert.equal(core.formatDateLong('2026-09-11'), 'September 11');
  assert.equal(core.formatLoggedAt('2026-09-11T22:10:00-04:00'), '10:10 pm');
  assert.equal(core.draftKey('2026-09-11'), 'habits_draft_2026-09-11');
});
