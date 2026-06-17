/* ============================================================
   dashboard.js  —  Health Tracker Dashboard v2
   ============================================================ */

const CSV_PATH = 'Health_Tracker_Master.csv';

let allRows   = [];
let dateIndex = 0;
let charts    = {};

// ── HELPERS ───────────────────────────────────────────────────
const $  = id => document.getElementById(id);
const n  = (v, d = 0) => { const x = parseFloat(v); return isNaN(x) ? null : parseFloat(x.toFixed(d)); };
const fmt = (v, d = 0, fb = '—') => { const x = n(v, d); return x === null ? fb : x.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}); };
const pct = (v, d = 1) => { const x = n(v, d); return x === null ? '—' : x + '%'; };
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ── COLORS ────────────────────────────────────────────────────
function recoveryColor(s) {
  return s >= 67 ? '#1fd67a' : s >= 33 ? '#f0c93a' : '#e84d4d';
}
function fillColor(ratio, invert = false) {
  if (invert) return ratio > 1 ? '#e84d4d' : ratio > 0.8 ? '#f0c93a' : '#1fd67a';
  return ratio >= 1 ? '#1fd67a' : ratio >= 0.5 ? '#f0c93a' : '#e84d4d';
}
function badgeClass(sig) {
  const m = {
    'PEAK':'badge-green','OPTIMAL':'badge-green','READY':'badge-blue',
    'MODERATE':'badge-yellow','REST':'badge-red',
    'UNDER-FUELED':'badge-orange','ON TARGET':'badge-green','OVER-FUELED':'badge-red',
    'WORSENING':'badge-red','IMPROVING':'badge-green','STABLE':'badge-blue',
    'OK':'badge-green','MONITOR':'badge-yellow','HIGH':'badge-red',
    'ADAPTING':'badge-green','MAINTAINING':'badge-blue','OVERREACHING':'badge-red',
    'DECLINING':'badge-red','SLIGHT DECLINE':'badge-yellow','SLIGHT IMPROVEMENT':'badge-green',
  };
  return m[sig] || 'badge-blue';
}

// ── BADGE HTML ────────────────────────────────────────────────
function badgeHTML(text, cls) {
  if (!text) return '';
  return `<span class="badge ${cls||badgeClass(text)}"><span class="badge-dot"></span>${text}</span>`;
}

// ── GAUGE ─────────────────────────────────────────────────────
function setGauge(id, value, max, color) {
  const el = $(id); if (!el) return;
  const circ = parseFloat(el.getAttribute('stroke-dasharray'));
  el.style.strokeDashoffset = circ * (1 - clamp(value / max, 0, 1));
  el.style.stroke = color;
}

// ── FILL BAR HTML ─────────────────────────────────────────────
function fillBarHTML(name, actual, goal, unit = '', invert = false, d = 0) {
  if (actual == null || goal == null || goal === 0) {
    return `<div>
      <div class="fill-bar-header">
        <span class="fill-bar-name">${name}</span>
        <span class="fill-bar-nums muted">No data</span>
      </div>
      <div class="fill-bar-track"><div class="fill-bar-fill" style="width:0%;background:var(--bg4)"></div></div>
    </div>`;
  }
  const ratio   = actual / goal;
  const display = clamp(ratio, 0, 1) * 100;
  const color   = fillColor(ratio, invert);
  const pctTxt  = Math.round(ratio * 100) + '%';
  const overTxt = ratio > 1
    ? ` <span style="color:${invert?'var(--red)':'var(--green)'}">+${fmt(actual-goal,d)}${unit} over</span>`
    : '';
  return `<div>
    <div class="fill-bar-header">
      <span class="fill-bar-name">${name}</span>
      <span class="fill-bar-nums"><span>${fmt(actual,d)}${unit}</span> / ${fmt(goal,d)}${unit} · ${pctTxt}${overTxt}</span>
    </div>
    <div class="fill-bar-track" style="background:${color}20">
      <div class="fill-bar-fill" style="width:${display}%;background:${color}"></div>
    </div>
  </div>`;
}

// ── CHART DEFAULTS ────────────────────────────────────────────
Chart.defaults.color          = '#404c5a';
Chart.defaults.borderColor    = '#1f2630';
Chart.defaults.font.family    = "'DM Sans', system-ui, sans-serif";
Chart.defaults.font.size      = 10;

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

const baseScales = {
  x: { ticks:{ maxTicksLimit:5, font:{size:9}, color:'#404c5a' }, grid:{ color:'#1f263044' } },
  y: { ticks:{ font:{size:9}, color:'#404c5a' }, grid:{ color:'#1f263044' } }
};

// ── COACHING ENGINE ───────────────────────────────────────────
function buildCoaching(row) {
  const recovery   = n(row.recovery_score);
  const signal     = row.readiness_signal || '';
  const sleepDebt  = n(row.sleep_debt_7day_rolling_hrs);
  const debtTrend  = row.sleep_debt_trend || '';
  const otRisk     = row.sr_overtraining_risk || '';
  const adaptation = row.sr_adaptation_trend || '';
  const fueling    = row.eb_fueling_status || '';
  const cvTraj     = row.cv_fitness_trajectory || '';
  const calIn      = n(row.calories_actual);
  const calBurned  = n(row.total_calories_kcal);

  let icon = '💡', headline = '', detail = '', tags = [];

  if (otRisk === 'HIGH' || (adaptation === 'OVERREACHING' && recovery != null && recovery < 33)) {
    icon = '🚨';
    headline = 'Signs of overtraining detected. Rest is not optional today.';
    detail = `Recovery is ${recovery||'—'} and your strain-to-recovery ratio indicates overreaching. Pushing through today risks injury and prolonged fatigue. Active recovery only — walking, stretching, or light mobility work.`;
    tags = ['REST DAY','HIGH RISK'];
  } else if (sleepDebt != null && sleepDebt > 15 && debtTrend === 'WORSENING') {
    icon = '😴';
    headline = `${fmt(sleepDebt,1)} hours of accumulated sleep debt and still rising.`;
    detail = `Chronic sleep debt suppresses HRV, elevates cortisol, and impairs muscle recovery. Before any other optimization — nutrition, training load, supplements — you need to close this debt. Aim for 8–9 hours tonight.`;
    tags = ['SLEEP PRIORITY','RECOVERY FOCUS'];
  } else if (fueling === 'UNDER-FUELED' && calIn != null && calBurned != null) {
    const deficit = calBurned - calIn;
    icon = '⚠️';
    headline = `${fmt(deficit)} calories under-fueled vs what you burned today.`;
    detail = `Under-fueling while training suppresses recovery and adaptation. Your body cannot repair muscle tissue, regulate hormones, or improve fitness without adequate fuel. Prioritize protein and complex carbohydrates.`;
    tags = ['FUEL UP','NUTRITION ACTION'];
  } else if (signal === 'PEAK' || (recovery != null && recovery >= 80 && adaptation !== 'OVERREACHING')) {
    icon = '⚡';
    headline = `Recovery is ${signal||'strong'} — this is your window to push hard.`;
    detail = `Your HRV and resting heart rate are signaling high readiness. If training is on the agenda, today is the day. High-intensity work, PR attempts, or long endurance sessions are all supported. Fuel well before and after.`;
    tags = ['HIGH READINESS','TRAIN HARD'];
    if (sleepDebt != null && sleepDebt > 10) {
      detail += ` Note: sleep debt is still elevated at ${fmt(sleepDebt,1)} hours — prioritize sleep tonight even on a strong performance day.`;
      tags.push('WATCH SLEEP DEBT');
    }
  } else if (signal === 'REST' || (recovery != null && recovery < 33)) {
    icon = '🛌';
    headline = `Low recovery (${recovery||'—'}). Protect today's energy.`;
    detail = `Your body is not ready for high-intensity output. Keep any training aerobic and low-strain. Focus on sleep quality tonight, hydration, and hitting your nutrition targets.`;
    tags = ['LOW READINESS','LIGHT ACTIVITY'];
  } else if (cvTraj === 'DECLINING' || cvTraj === 'SLIGHT DECLINE') {
    icon = '📉';
    headline = `Cardiovascular fitness trending ${cvTraj.toLowerCase()}.`;
    detail = `Your 30-day HRV and RHR trends indicate your aerobic base is softening. Zone 2 cardio 3–4x per week is the most evidence-backed intervention. Consistency is the fix.`;
    tags = ['CV TREND','AEROBIC WORK'];
  } else {
    icon = '✅';
    headline = `Moderate readiness (${recovery||'—'}). Controlled intensity today.`;
    detail = `Signals are in the moderate range — not a peak day but not a rest day either. Moderate aerobic work, technique-focused training, or accessory lifts are well-suited. Hit nutrition targets and prioritize sleep.`;
    tags = ['MODERATE DAY','CONTROLLED EFFORT'];
  }
  if (adaptation === 'ADAPTING') tags.push('ADAPTING');
  if (otRisk === 'MONITOR' && !tags.includes('HIGH RISK')) tags.push('MONITOR LOAD');
  return { icon, headline, detail, tags };
}

// ── RENDER DAY ────────────────────────────────────────────────
function renderDay(row) {
  if (!row) return;

  // ── NAV BADGES ───────────────────────────────────────────────
  const recov = n(row.recovery_score);
  const recBadge = recov != null
    ? `<span class="badge" style="color:${recoveryColor(recov)};background:${recoveryColor(recov)}18;border-color:${recoveryColor(recov)}40">
        <span class="badge-dot"></span>${recov} Recovery</span>` : '';
  $('topnav-badges').innerHTML = recBadge + [
    row.readiness_signal,
    row.eb_fueling_status,
    row.sleep_debt_trend ? 'Sleep ' + row.sleep_debt_trend : '',
    row.cv_fitness_trajectory,
  ].filter(Boolean).map(v => badgeHTML(v)).join('');

  // ── CALORIE HERO ─────────────────────────────────────────────
  const calIn     = n(row.calories_actual);
  const calBurned = n(row.total_calories_kcal);
  const calGoal   = n(row.calories_goal);
  const bmr       = n(row.bmr_estimated_kcal);
  const eb7Avg    = n(row.eb_7day_avg_calories);

  $('cal-in-num').textContent = calIn != null ? fmt(calIn) : '—';
  $('cal-in-num').style.color = calIn != null && calGoal && calIn >= calGoal ? 'var(--green)' : 'var(--text)';
  $('cal-in-goal').textContent = calGoal ? 'Goal: ' + fmt(calGoal) + ' kcal' : 'Goal: —';
  $('cal-burned-num').textContent = calBurned != null ? fmt(calBurned) : '—';
  $('cal-burned-sub').textContent = bmr ? 'BMR: ' + fmt(bmr) + ' kcal' : 'BMR: —';

  if (calIn != null && calBurned != null) {
    const net = calIn - calBurned;
    const surplus = net > 0;
    const c = surplus ? 'var(--green)' : 'var(--orange)';
    $('net-result').textContent = (surplus?'+':'') + fmt(net);
    $('net-result').style.cssText = `color:${c};border-color:${surplus?'var(--green-border)':'var(--orange-border)'};background:${surplus?'var(--green-bg)':'var(--orange-bg)'}`;
    $('net-words').textContent = surplus ? 'SURPLUS' : 'DEFICIT';
    $('net-words').style.color = c;
  } else {
    $('net-result').textContent = '—';
    $('net-words').textContent = 'No meal data';
    $('net-words').style.color = 'var(--text3)';
  }

  if (calIn != null && calGoal) {
    const r = calIn / calGoal;
    $('cal-in-bar').style.width   = clamp(r,0,1)*100+'%';
    $('cal-in-bar').style.background = fillColor(r);
    $('cal-bar-nums').innerHTML = `<span>${fmt(calIn)}</span> / ${fmt(calGoal)} kcal`;
  } else {
    $('cal-bar-nums').textContent = 'No data';
  }

  if (calBurned != null && eb7Avg) {
    const r = calBurned / eb7Avg;
    $('eb7-bar').style.width = clamp(r,0,1)*100+'%';
    $('eb7-nums').innerHTML = `<span>${fmt(calBurned)}</span> / ${fmt(eb7Avg)} kcal 7d avg`;
  } else {
    $('eb7-nums').textContent = 'No data';
  }

  // ── MEAL DONUT ───────────────────────────────────────────────
  destroyChart('mealDonut');
  const mVals   = [n(row.cal_by_meal_breakfast_actual)||0, n(row.cal_by_meal_lunch_actual)||0, n(row.cal_by_meal_dinner_actual)||0, n(row.cal_by_meal_snack_actual)||0];
  const mLabels = ['Breakfast','Lunch','Dinner','Snack'];
  const mColors = ['#4a94e8','#e87a3a','#28c4c4','#9470e8'];
  const mTotal  = mVals.reduce((a,b)=>a+b,0);
  $('meal-legend').innerHTML = mLabels.map((l,i)=>
    `<div class="legend-item"><div class="legend-dot" style="background:${mColors[i]}"></div>${l}: ${fmt(mVals[i])} kcal</div>`
  ).join('');
  charts.mealDonut = new Chart($('meal-donut'),{
    type:'doughnut',
    data:{ labels:mLabels, datasets:[{ data:mTotal>0?mVals:[1,0,0,0], backgroundColor:mColors, borderWidth:0, hoverOffset:4 }] },
    options:{
      responsive:true, maintainAspectRatio:false, cutout:'70%',
      plugins:{
        legend:{display:false},
        tooltip:{ callbacks:{ label: ctx => mTotal>0 ? ` ${ctx.label}: ${fmt(ctx.raw)} kcal (${Math.round(ctx.raw/mTotal*100)}%)` : ' No data' } }
      }
    }
  });

  // ── RECOVERY GAUGE ───────────────────────────────────────────
  if (recov != null) {
    $('recovery-num').textContent = recov;
    $('recovery-num').style.color = recoveryColor(recov);
    setGauge('gauge-track', recov, 100, recoveryColor(recov));
  } else {
    $('recovery-num').textContent = '—';
  }
  $('hrv-val').textContent  = row.hrv_rmssd_ms       ? fmt(row.hrv_rmssd_ms,1)+' ms'   : '—';
  $('rhr-val').textContent  = row.resting_heart_rate  ? fmt(row.resting_heart_rate)+' bpm' : '—';
  $('spo2-val').textContent = row.spo2_pct            ? pct(row.spo2_pct)               : '—';
  $('temp-val').textContent = row.skin_temp_celsius    ? fmt(row.skin_temp_celsius,1)+'°C' : '—';

  // ── SLEEP ────────────────────────────────────────────────────
  const lightH = n(row.light_sleep_hrs)||0;
  const swsH   = n(row.slow_wave_sleep_hrs)||0;
  const remH   = n(row.rem_sleep_hrs)||0;
  const awakeH = n(row.time_awake_min) ? n(row.time_awake_min)/60 : 0;
  const sleptTotal = lightH + swsH + remH;
  $('sleep-total').textContent  = sleptTotal > 0 ? fmt(sleptTotal,1) : '—';
  $('sleep-needed').textContent = row.sleep_needed_total_hrs ? fmt(row.sleep_needed_total_hrs,1) : '—';

  const sColors = {Light:'#4a94e8',SWS:'#28c4c4',REM:'#9470e8',Awake:'#2a3340'};
  const sSegs   = [{label:'Light',val:lightH},{label:'SWS',val:swsH},{label:'REM',val:remH},{label:'Awake',val:awakeH}];
  const sBasis  = sleptTotal + awakeH || 1;
  $('sleep-stack').innerHTML = sSegs.map(s=>
    `<div class="sleep-seg" style="width:${(s.val/sBasis*100).toFixed(1)}%;background:${sColors[s.label]}"></div>`
  ).join('');
  $('sleep-legend').innerHTML = sSegs.filter(s=>s.val>0).map(s=>
    `<div class="legend-item"><div class="legend-dot" style="background:${sColors[s.label]}"></div>${s.label}: ${fmt(s.val,1)}h</div>`
  ).join('');

  const spPct = n(row.sleep_performance_pct);
  $('sleep-perf').innerHTML   = spPct != null ? `<span style="color:${fillColor(spPct/100)}">${pct(spPct,0)}</span>` : '—';
  $('sleep-eff').textContent   = row.sleep_efficiency_pct  ? pct(row.sleep_efficiency_pct,0)  : '—';
  $('sleep-cons').textContent  = row.sleep_consistency_pct ? pct(row.sleep_consistency_pct,0) : '—';
  $('sleep-cycles').textContent= row.sleep_cycles ? row.sleep_cycles : '—';

  // ── SLEEP DEBT ───────────────────────────────────────────────
  const debt7d   = n(row.sleep_debt_7day_rolling_hrs);
  const debtLast = n(row.sleep_debt_last_night_hrs);
  if (debt7d != null) {
    $('sleep-debt-7d').textContent = fmt(debt7d,1);
    $('sleep-debt-7d').style.color = debt7d > 15 ? 'var(--red)' : debt7d > 7 ? 'var(--yellow)' : 'var(--green)';
  } else {
    $('sleep-debt-7d').textContent = '—';
  }
  if (debtLast != null) {
    $('sleep-debt-last-nums').innerHTML = `<span>${fmt(debtLast,1)} hrs</span>`;
    $('sleep-debt-bar').style.width      = clamp(debtLast/4,0,1)*100+'%';
    $('sleep-debt-bar').style.background = debtLast > 2 ? 'var(--red)' : 'var(--yellow)';
  } else {
    $('sleep-debt-last-nums').textContent = '—';
  }
  const dt = row.sleep_debt_trend || '—';
  $('debt-trend').textContent = dt;
  $('debt-trend').style.color = dt==='IMPROVING' ? 'var(--green)' : dt==='WORSENING' ? 'var(--red)' : 'var(--text3)';
  $('debt-repay').textContent = row.sleep_debt_days_to_repayment || '—';

  // ── STRAIN ───────────────────────────────────────────────────
  const strain = n(row.day_strain);
  $('strain-num').textContent = strain != null ? fmt(strain,1) : '—';
  if (strain != null) {
    $('strain-bar').style.width      = clamp(strain/21,0,1)*100+'%';
    $('strain-bar').style.background = strain>=14 ? 'var(--red)' : strain>=8 ? 'var(--orange)' : 'var(--blue)';
  }
  $('workout-count').textContent = row.workout_count || '0';
  $('workout-dur').textContent   = row.workout_total_duration_min ? fmt(row.workout_total_duration_min)+' min' : '—';
  $('avg-hr').textContent        = row.day_avg_heart_rate  ? fmt(row.day_avg_heart_rate)+' bpm'  : '—';
  $('max-hr').textContent        = row.day_max_heart_rate  ? fmt(row.day_max_heart_rate)+' bpm'  : '—';

  // ── OVERTRAINING ─────────────────────────────────────────────
  const otRisk = row.sr_overtraining_risk || '';
  $('ot-risk-val').textContent = otRisk || '—';
  $('ot-risk-val').style.color = otRisk==='OK' ? 'var(--green)' : otRisk==='MONITOR' ? 'var(--yellow)' : otRisk==='HIGH' ? 'var(--red)' : 'var(--text)';
  $('ot-adaptation').className = 'badge ' + badgeClass(row.sr_adaptation_trend||'');
  $('ot-adaptation').innerHTML = `<span class="badge-dot"></span>${row.sr_adaptation_trend||'—'}`;
  const riskMap = {OK:0,MONITOR:1,HIGH:2};
  const rl = riskMap[otRisk] ?? -1;
  $('risk-ok').className  = 'risk-seg'+(rl>=0?' active-ok':'');
  $('risk-mon').className = 'risk-seg'+(rl>=1?' active-monitor':'');
  $('risk-hi').className  = 'risk-seg'+(rl>=2?' active-high':'');
  $('sr-strain').textContent    = row.sr_7day_avg_strain   ? fmt(row.sr_7day_avg_strain,1)   : '—';
  $('sr-recovery').textContent  = row.sr_7day_avg_recovery ? fmt(row.sr_7day_avg_recovery,1) : '—';
  $('sr-ratio').textContent     = row.sr_ratio             ? fmt(row.sr_ratio,3)              : '—';
  $('readiness-3d').textContent = row.readiness_3day_avg_strain ? fmt(row.readiness_3day_avg_strain,1) : '—';

  // ── READINESS GAUGE ──────────────────────────────────────────
  const rdns = n(row.readiness_composite_score);
  if (rdns != null) {
    $('readiness-num').textContent = rdns;
    $('readiness-num').style.color = recoveryColor(rdns);
    setGauge('readiness-track', rdns, 100, recoveryColor(rdns));
  } else {
    $('readiness-num').textContent = '—';
  }
  const hbp = n(row.readiness_hrv_vs_baseline_pct);
  const rbp = n(row.readiness_rhr_vs_baseline_pct);
  $('hrv-baseline').textContent = hbp!=null ? (hbp>0?'+':'')+fmt(hbp,1)+'%' : '—';
  $('hrv-baseline').style.color = hbp!=null ? (hbp>=0?'var(--green)':'var(--red)') : '';
  $('rhr-baseline').textContent = rbp!=null ? (rbp>0?'+':'')+fmt(rbp,1)+'%' : '—';
  $('rhr-baseline').style.color = rbp!=null ? (rbp<=0?'var(--green)':'var(--red)') : '';
  $('readiness-signal').textContent = row.readiness_signal || '—';

  // ── COACHING ─────────────────────────────────────────────────
  const c = buildCoaching(row);
  $('coaching-icon').textContent    = c.icon;
  $('coaching-headline').textContent = c.headline;
  $('coaching-detail').textContent   = c.detail;
  $('coaching-tags').innerHTML = c.tags.map(t=>`<span class="coaching-tag ${badgeClass(t)}">${t}</span>`).join('');

  // ── MACROS ───────────────────────────────────────────────────
  $('macro-bars').innerHTML = [
    fillBarHTML('Total Fat',          n(row.macro_total_fat_actual),   n(row.macro_total_fat_goal),   'g', false, 1),
    fillBarHTML('Total Carbohydrates',n(row.macro_total_carbs_actual), n(row.macro_total_carbs_goal), 'g', false, 1),
    fillBarHTML('Protein',            n(row.macro_protein_actual),     n(row.macro_protein_goal),     'g', false, 1),
  ].join('');

  destroyChart('macroDonut');
  const macVals   = [n(row.macro_total_fat_actual)||0, n(row.macro_total_carbs_actual)||0, n(row.macro_protein_actual)||0];
  const macLabels = ['Fat','Carbs','Protein'];
  const macColors = ['#e87a3a','#4a94e8','#1fd67a'];
  const macTotal  = macVals.reduce((a,b)=>a+b,0);
  $('macro-legend').innerHTML = macLabels.map((l,i)=>
    `<div class="legend-item"><div class="legend-dot" style="background:${macColors[i]}"></div>${l}: ${fmt(macVals[i],1)}g${macTotal>0?' ('+Math.round(macVals[i]/macTotal*100)+'%)':''}</div>`
  ).join('');
  charts.macroDonut = new Chart($('macro-donut'),{
    type:'doughnut',
    data:{ labels:macLabels, datasets:[{ data:macTotal>0?macVals:[1,1,1], backgroundColor:macColors, borderWidth:0, hoverOffset:4 }] },
    options:{
      responsive:true, maintainAspectRatio:false, cutout:'70%',
      plugins:{
        legend:{display:false},
        tooltip:{ callbacks:{ label: ctx => macTotal>0 ? ` ${ctx.label}: ${fmt(ctx.raw,1)}g (${Math.round(ctx.raw/macTotal*100)}%)` : ' No data' } }
      }
    }
  });

  // ── MICROS ───────────────────────────────────────────────────
  const micros = [
    {name:'Sodium',        a:n(row.micro_sodium_actual),            g:n(row.micro_sodium_goal),            unit:'mg', inv:true},
    {name:'Potassium',     a:n(row.micro_potassium_actual),          g:n(row.micro_potassium_goal),          unit:'mg'},
    {name:'Dietary Fiber', a:n(row.micro_dietary_fiber_actual),      g:n(row.micro_dietary_fiber_goal),      unit:'g', d:1},
    {name:'Sugars',        a:n(row.micro_sugars_actual),             g:n(row.micro_sugars_goal),             unit:'g', inv:true, d:1},
    {name:'Vitamin A',     a:n(row.micro_vitamin_a_mcg_rae_actual),  g:n(row.micro_vitamin_a_mcg_rae_goal),  unit:'mcg'},
    {name:'Vitamin C',     a:n(row.micro_vitamin_c_mg_actual),       g:n(row.micro_vitamin_c_mg_goal),       unit:'mg'},
    {name:'Vitamin D',     a:n(row.micro_vitamin_d_mcg_actual),      g:n(row.micro_vitamin_d_mcg_goal),      unit:'mcg', d:1},
    {name:'Calcium',       a:n(row.micro_calcium_mg_actual),         g:n(row.micro_calcium_mg_goal),         unit:'mg'},
    {name:'Iron',          a:n(row.micro_iron_mg_actual),            g:n(row.micro_iron_mg_goal),            unit:'mg', d:1},
  ];
  $('micro-bars').innerHTML = micros.map(m => fillBarHTML(m.name, m.a, m.g, m.unit, m.inv||false, m.d||0)).join('');

  // ── CV FITNESS ───────────────────────────────────────────────
  const cvTraj = row.cv_fitness_trajectory || '—';
  $('cv-trajectory').textContent = cvTraj;
  $('cv-trajectory').style.color = cvTraj.includes('IMPROV') ? 'var(--green)' : cvTraj.includes('DECLIN') ? 'var(--red)' : 'var(--yellow)';
  $('cv-hrv').textContent = row.cv_30day_avg_hrv ? fmt(row.cv_30day_avg_hrv,1)+' ms'  : '—';
  $('cv-rhr').textContent = row.cv_30day_avg_rhr ? fmt(row.cv_30day_avg_rhr,1)+' bpm' : '—';
  const htp = n(row.cv_hrv_trend_vs_prior30_pct);
  const rtp = n(row.cv_rhr_trend_vs_prior30_pct);
  $('cv-hrv-trend').innerHTML = htp!=null ? `<span class="${htp>=0?'trend-up':'trend-down'}">${htp>=0?'▲':'▼'} ${Math.abs(htp)}% vs prior 30d</span>` : '—';
  $('cv-rhr-trend').innerHTML = rtp!=null ? `<span class="${rtp<=0?'trend-up':'trend-down'}">${rtp<=0?'▲':'▼'} ${Math.abs(rtp)}% vs prior 30d</span>` : '—';

  // ── FUELING ──────────────────────────────────────────────────
  $('cal-per-strain').textContent = row.eb_cal_per_strain_point ? fmt(row.eb_cal_per_strain_point) : '—';
  $('eb7-avg').textContent  = row.eb_7day_avg_calories        ? fmt(row.eb_7day_avg_calories)+' kcal'       : '—';
  $('eb-maint').textContent = row.eb_maintenance_target_kcal  ? fmt(row.eb_maintenance_target_kcal)+' kcal' : '—';
  const vsAvg = n(row.eb_today_vs_7day_avg_kcal);
  $('eb-vs-avg').textContent = vsAvg!=null ? (vsAvg>0?'+':'')+fmt(vsAvg)+' kcal' : '—';
  $('eb-vs-avg').style.color = vsAvg!=null ? (vsAvg>=0?'var(--green)':'var(--red)') : '';
  $('eb-status').textContent = row.eb_fueling_status || '—';
  $('eb-status').style.color = row.eb_fueling_status==='ON TARGET' ? 'var(--green)' : row.eb_fueling_status==='UNDER-FUELED' ? 'var(--orange)' : 'var(--red)';

  // ── TREND CHARTS ─────────────────────────────────────────────
  buildTrends();
}

// ── TREND & MINI CHARTS ───────────────────────────────────────
function buildTrends() {
  const window30 = allRows.slice(dateIndex, dateIndex + 30).reverse();
  const labels   = window30.map(r => (r.date||'').slice(5));
  const get      = f => window30.map(r => n(r[f]));

  // Recovery
  destroyChart('tRec');
  charts.tRec = new Chart($('trend-recovery'),{
    type:'line',
    data:{ labels, datasets:[{ data:get('recovery_score'), borderColor:'#1fd67a', backgroundColor:'transparent', borderWidth:1.5, pointRadius:2, tension:0.3, spanGaps:true }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}, scales:{ x:{...baseScales.x}, y:{...baseScales.y,min:0,max:100} } }
  });

  // HRV
  destroyChart('tHRV');
  charts.tHRV = new Chart($('trend-hrv'),{
    type:'line',
    data:{ labels, datasets:[
      { data:get('hrv_rmssd_ms'),     borderColor:'#9470e8', backgroundColor:'transparent', borderWidth:1.5, pointRadius:2, tension:0.3, spanGaps:true },
      { data:get('cv_30day_avg_hrv'), borderColor:'#9470e840', backgroundColor:'transparent', borderWidth:1, borderDash:[4,4], pointRadius:0, tension:0, spanGaps:true },
    ]},
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}, scales:{ x:{...baseScales.x}, y:{...baseScales.y} } }
  });

  // Sleep
  destroyChart('tSleep');
  charts.tSleep = new Chart($('trend-sleep'),{
    type:'line',
    data:{ labels, datasets:[{ data:get('sleep_performance_pct'), borderColor:'#4a94e8', backgroundColor:'transparent', borderWidth:1.5, pointRadius:2, tension:0.3, spanGaps:true }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}, scales:{ x:{...baseScales.x}, y:{...baseScales.y,min:0,max:100} } }
  });

  // Calories in vs burned
  destroyChart('tCal');
  charts.tCal = new Chart($('trend-calories'),{
    type:'line',
    data:{ labels, datasets:[
      { label:'In',     data:get('calories_actual'),    borderColor:'#1fd67a', backgroundColor:'transparent', borderWidth:1.5, pointRadius:2, tension:0.3, spanGaps:true },
      { label:'Burned', data:get('total_calories_kcal'),borderColor:'#e87a3a', backgroundColor:'transparent', borderWidth:1.5, pointRadius:2, tension:0.3, spanGaps:true },
    ]},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display:true, position:'bottom', labels:{ boxWidth:8, font:{size:9}, color:'#7a8694', padding:6 } }, tooltip:{mode:'index',intersect:false} },
      scales:{ x:{...baseScales.x}, y:{...baseScales.y} }
    }
  });

  // Strain bars
  destroyChart('tStrain');
  charts.tStrain = new Chart($('trend-strain'),{
    type:'bar',
    data:{ labels, datasets:[{ data:get('day_strain'), backgroundColor: window30.map(r=>{ const s=n(r.day_strain); return s>=14?'#e84d4d99':s>=8?'#e87a3a99':'#4a94e899'; }), borderWidth:0 }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}, scales:{ x:{...baseScales.x,grid:{display:false}}, y:{...baseScales.y,min:0,max:21} } }
  });

  // HRV mini chart
  destroyChart('hrvMini');
  charts.hrvMini = new Chart($('hrv-chart'),{
    type:'line',
    data:{ labels, datasets:[{ data:get('hrv_rmssd_ms'), borderColor:'#9470e8', backgroundColor:'#9470e812', borderWidth:1.5, pointRadius:0, tension:0.4, fill:true, spanGaps:true }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}, scales:{ x:{...baseScales.x,ticks:{maxTicksLimit:4}}, y:{...baseScales.y} } }
  });

  // Energy balance 14d bars
  destroyChart('ebMini');
  const eb14   = allRows.slice(dateIndex, dateIndex+14).reverse();
  const ebLabs = eb14.map(r=>(r.date||'').slice(5));
  charts.ebMini = new Chart($('eb-chart'),{
    type:'bar',
    data:{ labels:ebLabs, datasets:[
      { label:'In',     data:eb14.map(r=>n(r.calories_actual)),     backgroundColor:'#1fd67a66', borderWidth:0 },
      { label:'Burned', data:eb14.map(r=>n(r.total_calories_kcal)), backgroundColor:'#e87a3a66', borderWidth:0 },
    ]},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{ display:true, position:'bottom', labels:{ boxWidth:8, font:{size:9}, color:'#7a8694', padding:6 } }, tooltip:{mode:'index',intersect:false} },
      scales:{ x:{...baseScales.x,grid:{display:false}}, y:{...baseScales.y} }
    }
  });
}

// ── DATE NAV ──────────────────────────────────────────────────
function updateDate() {
  const row = allRows[dateIndex];
  if (!row) return;
  $('current-date').textContent = row.date || '—';
  $('prev-day').disabled = dateIndex >= allRows.length - 1;
  $('next-day').disabled = dateIndex <= 0;
  renderDay(row);
}
$('prev-day').addEventListener('click', () => { if (dateIndex < allRows.length-1) { dateIndex++; updateDate(); } });
$('next-day').addEventListener('click', () => { if (dateIndex > 0)               { dateIndex--; updateDate(); } });

// ── LOAD CSV ──────────────────────────────────────────────────
function showError(msg) {
  $('loading').style.display = 'none';
  $('error-msg').style.display = 'flex';
  if (msg) $('error-detail').textContent = msg;
}

Papa.parse(CSV_PATH,{
  download: true,
  header: true,
  skipEmptyLines: true,
  complete(results) {
    if (!results.data || results.data.length === 0) {
      showError('CSV file is empty or could not be parsed.');
      return;
    }
    const seen = new Set();
    allRows = results.data.filter(r => {
      const d = r.date;
      if (!d || seen.has(d)) return false;
      seen.add(d); return true;
    });
    allRows.sort((a,b) => (b.date||'').localeCompare(a.date||''));
    $('loading').style.display = 'none';
    $('app').style.display = 'block';
    dateIndex = 0;
    updateDate();
  },
  error(err) {
    showError('Failed to load Health_Tracker_Master.csv: ' + err.message);
  }
});
