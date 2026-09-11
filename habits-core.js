/* habits-core.js — pure logic for habits.html. No DOM, no fetch.
   Loaded by a <script> tag in the page and by node --test. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.HabitsCore = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function parseCSV(text) {
    const rows = [];
    let field = '', record = [], inQ = false, i = 0;
    const s = text.replace(/\r\n/g, '\n');
    while (i < s.length) {
      const c = s[i];
      if (inQ) {
        if (c === '"') { if (s[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
        else field += c;
      } else if (c === '"') inQ = true;
      else if (c === ',') { record.push(field); field = ''; }
      else if (c === '\n') { record.push(field); rows.push(record); record = []; field = ''; }
      else field += c;
      i++;
    }
    if (field.length || record.length) { record.push(field); rows.push(record); }
    const header = rows.shift() || [];
    return {
      header,
      rows: rows.filter(r => r.length > 1 || r[0] !== '').map(r => {
        const o = {};
        header.forEach((h, k) => { o[h] = r[k] === undefined ? '' : r[k]; });
        return o;
      })
    };
  }

  function quote(v) {
    v = v == null ? '' : String(v);
    return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  function serializeCSV(header, rows) {
    const lines = [header.map(quote).join(',')];
    rows.forEach(r => lines.push(header.map(h => quote(r[h])).join(',')));
    return lines.join('\n') + '\n';
  }

  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  function parts(dateStr) { const [y, m, d] = dateStr.split('-').map(Number); return { y, m, d }; }
  function dayOfWeek(dateStr) { const p = parts(dateStr); return DAYS[new Date(p.y, p.m - 1, p.d).getDay()]; }
  function formatDateLong(dateStr) { const p = parts(dateStr); return MONTHS[p.m - 1] + ' ' + p.d; }

  function upsertDay(parsed, dateStr, values, loggedAt) {
    const header = parsed.header.slice();
    Object.keys(values).forEach(k => { if (!header.includes(k)) throw new Error('unknown column: ' + k); });
    const rows = parsed.rows.map(r => Object.assign({}, r));
    let row = rows.find(r => r.date === dateStr);
    if (!row) {
      row = {}; header.forEach(h => { row[h] = ''; });
      row.date = dateStr; row.day_of_week = dayOfWeek(dateStr);
      rows.push(row);
    }
    Object.keys(values).forEach(k => { row[k] = values[k] == null ? '' : String(values[k]); });
    if (header.includes('logged_at')) row.logged_at = loggedAt;
    rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    return { header, rows };
  }

  function phoneHabits(defs) {
    return defs.habits
      .filter(h => typeof h.phone_order === 'number' && h.active !== false && h.source === 'self' && h.cadence !== 'weekly')
      .sort((a, b) => a.phone_order - b.phone_order);
  }
  function derivedHabits(defs) { return defs.habits.filter(h => h.source !== 'self' && h.active !== false); }

  const pad = n => String(n).padStart(2, '0');
  function todayLocal(now) { now = now || new Date(); return now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()); }
  function localISO(now) {
    now = now || new Date();
    const off = -now.getTimezoneOffset(), sign = off >= 0 ? '+' : '-', a = Math.abs(off);
    return todayLocal(now) + 'T' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds()) + sign + pad(Math.floor(a / 60)) + ':' + pad(a % 60);
  }
  function formatLoggedAt(iso) {
    const m = /T(\d\d):(\d\d)/.exec(iso || '');
    if (!m) return '';
    let h = Number(m[1]); const ap = h >= 12 ? 'pm' : 'am'; h = h % 12 || 12;
    return h + ':' + m[2] + ' ' + ap;
  }
  function draftKey(dateStr) { return 'habits_draft_' + dateStr; }

  return { parseCSV, serializeCSV, upsertDay, dayOfWeek, phoneHabits, derivedHabits, todayLocal, localISO, formatDateLong, formatLoggedAt, draftKey };
}));
