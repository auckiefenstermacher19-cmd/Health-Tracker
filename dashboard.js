/* ============================================================
   dashboard.js  —  Health Tracker Dashboard
   Reads Health_Tracker_Master.csv, renders all panels.
   ============================================================ */

// ── CONFIG ────────────────────────────────────────────────────
const CSV_PATH = 'Health_Tracker_Master.csv';

// ── STATE ─────────────────────────────────────────────────────
let allRows   = [];
let dateIndex = 0;
let charts    = {};

// ── HELPERS ───────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const n = (v, decimals = 0) => {
  const num = parseFloat(v);
  return isNaN(num) ? null : parseFloat(num.toFixed(decimals));
};
const fmt = (v, decimals = 0, fallback = '—') => {
  const num = n(v, decimals);
  return num === null ? fallback : num.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
};
const pct = v => {
  const num = n(v, 1);
  return num === null ? '—' : num + '%';
};
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ── COLOR HELPERS ─────────────────────────────────────────────
function recoveryColor(score) {
  if (score >= 67) return '#22c97a';
  if (score >= 33) return '#f5c842';
  return '#f04f4f';
}
function badgeClass(signal) {
  const map = {
    'PEAK':'green','OPTIMAL':'green','READY':'blue','MODERATE':'yellow',
    'REST':'red','UNDER-FUELED':'orange','ON TARGET':'green','OVER-FUELED':'red',
    'WORSENING':'red','IMPROVING':'green','STABLE':'blue',
    'OK':'green','MONITOR':'yellow','HIGH':'red',
    'ADAPTING':'green','MAINTAINING':'blue','OVERREACHING':'red',
    'IMPROVING':'green','DECLINING':'red','SLIGHT DECLINE':'yellow',
  };
  return 'badge-' + (map[signal] || 'blue');
}

function fillColor(pctVal, invert = false) {
  // invert=true means over-goal is BAD (sodium, sugars)
  if (invert) {
    if (pctVal > 1)   return '#f04f4f';
    if (pctVal > 0.8) return '#f5c842';
    return '#22c97a';
  }
  if (pctVal >= 1)   return '#22c97a';
  if (pctVal >= 0.5) return '#f5c842';
  return '#f04f4f';
}

// ── GAUGE ─────────────────────────────────────────────────────
function setGauge(trackId, value, max, color) {
  const el = $(trackId);
  if (!el) return;
  const circumference = parseFloat(el.getAttribute('stroke-dasharray'));
  const pctVal = clamp(value / max, 0, 1);
  el.style.strokeDashoffset = circumference * (1 - pctVal);
  el.style.stroke = color;
}

// ── FILL BAR ──────────────────────────────────────────────────
function setFillBar(barId, actual, goal, invert = false) {
  const el = $(barId);
  if (!el || goal == null || goal === 0) return;
  const pctVal = actual / goal;
  const displayPct = clamp(pctVal, 0, 1.5) * 100 / 1.5; // scale to 150% max
  el.style.width = clamp(displayPct, 0, 100) + '%';
  el.style.background = fillColor(pctVal, invert);
}

// ── BUILD FILL BAR HTML ───────────────────────────────────────
function fillBarHTML(name, actual, goal, unit = '', invert = false, decimals = 0) {
  if (actual == null || goal == null) {
    return `<div class="fill-bar-item">
      <div class="fill-bar-header">
        <span class="fill-bar-name">${name}</span>
        <span class="fill-bar-nums muted">No data</span>
      </div>
      <div class="fill-bar-track"><div class="fill-bar-fill" style="width:0%;background:var(--bg3)"></div></div>
    </div>`;
  }
  const pctVal  = goal > 0 ? actual / goal : 0;
  const display = clamp(pctVal, 0, 1) * 100;
  const color   = fillColor(pctVal, invert);
  const pctText = Math.round(pctVal * 100) + '%';
  const overText = pctVal > 1
    ? `<span style="color:${invert ? '#f04f4f' : '#22c97a'}"> +${fmt(actual - goal, decimals)}${unit} over</span>`
    : '';

  return `<div class="fill-bar-item">
    <div class="fill-bar-header">
      <span class="fill-bar-name">${name}</span>
      <span class="fill-bar-nums"><span>${fmt(actual, decimals)}${unit}</span> / ${fmt(goal, decimals)}${unit} · ${pctText}${overText}</span>
    </div>
    <div class="fill-bar-track" style="background:${color}22">
      <div class="fill-bar-fill" style="width:${display}%;background:${color}"></div>
    </div>
  </div>`;
}

// ── BADGE HTML ────────────────────────────────────────────────
function badgeHTML(text, cls) {
  if (!text) return '';
  return `<span class="badge ${cls || badgeClass(text)}">
    <span class="badge-dot" style="background:currentColor"></span>${text}
  </span>`;
}

// ── CHART DEFAULTS ────────────────────────────────────────────
Chart.defaults.color = '#505a68';
Chart.defaults.borderColor = '#232830';
Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";

function destroyChart(key) {
  if (charts[key]) { charts[key].destroy(); delete charts[key]; }
}

function lineChartOpts(label, color, data, labels, fillArea = false) {
  return {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label,
        data,
        borderColor: color,
        backgroundColor: fillArea ? color + '22' : 'transparent',
        borderWidth: 2,
        pointRadius: data.length > 20 ? 0 : 3,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: fillArea,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 6, font: { size: 10 } }, grid: { color: '#23283044' } },
        y: { ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
    }
  };
}

// ── COACHING ENGINE ───────────────────────────────────────────
function buildCoaching(row) {
  const recovery   = n(row.recovery_score);
  const signal     = row.readiness_signal || '';
  const strain     = n(row.day_strain);
  const sleepDebt  = n(row.sleep_debt_7day_rolling_hrs);
  const debtTrend  = row.sleep_debt_trend || '';
  const otRisk     = row.sr_overtraining_risk || '';
  const adaptation = row.sr_adaptation_trend || '';
  const fueling    = row.eb_fueling_status || '';
  const cvTraj     = row.cv_fitness_trajectory || '';
  const calIn      = n(row.calories_actual);
  const calBurned  = n(row.total_calories_kcal);

  let icon = '💡';
  let headline = '';
  let detail = '';
  let tags = [];

  // Priority cascade — most urgent signal wins headline
  if (otRisk === 'HIGH' || (adaptation === 'OVERREACHING' && recovery < 33)) {
    icon = '🚨';
    headline = 'Your body is showing signs of overtraining. Rest is not optional today.';
    detail = `Your recovery is ${recovery || '—'} and your strain-to-recovery ratio indicates overreaching. Pushing through today risks injury and prolonged fatigue. Prioritize active recovery — walk, stretch, or light mobility work only.`;
    tags = ['REST DAY', 'HIGH RISK'];
  } else if (sleepDebt > 15 && debtTrend === 'WORSENING') {
    icon = '😴';
    headline = `You're carrying ${fmt(sleepDebt, 1)} hours of sleep debt and it's getting worse.`;
    detail = `Chronic sleep debt suppresses HRV, elevates cortisol, and impairs muscle recovery. Before any other optimization — nutrition, training load, supplements — you need to close this debt. Aim for 8–9 hours tonight. This is your highest-leverage health action.`;
    tags = ['SLEEP PRIORITY', 'RECOVERY FOCUS'];
  } else if (fueling === 'UNDER-FUELED' && calIn != null && calBurned != null) {
    const deficit = calBurned - calIn;
    icon = '⚠️';
    headline = `You're ${fmt(deficit)} calories under-fueled relative to what you burned.`;
    detail = `Under-fueling while training suppresses recovery and adaptation. Your body cannot repair muscle tissue, regulate hormones, or improve fitness without adequate fuel. Hit your calorie target today — prioritize protein and complex carbohydrates.`;
    tags = ['FUEL UP', 'NUTRITION ACTION'];
  } else if (signal === 'PEAK' || (recovery >= 80 && adaptation !== 'OVERREACHING')) {
    icon = '⚡';
    headline = `Recovery is ${signal || 'strong'} — this is your window to push.`;
    detail = `Your HRV and resting heart rate are signaling high readiness. If training is on the agenda, today is the day to go hard. High-intensity work, PR attempts, or long endurance sessions are all supported by your current state. Fuel well before and after.`;
    tags = ['HIGH READINESS', 'TRAIN HARD'];
    if (sleepDebt > 10) {
      detail += ` One note: your sleep debt is still elevated at ${fmt(sleepDebt, 1)} hours — make tonight's sleep a priority even on a strong performance day.`;
      tags.push('WATCH SLEEP DEBT');
    }
  } else if (signal === 'REST' || recovery < 33) {
    icon = '🛌';
    headline = `Low recovery day (${recovery || '—'}). Protect today's energy.`;
    detail = `Your body is not ready for high-intensity output. If you must train, keep it aerobic and low-strain. Focus on sleep quality tonight, hydration, and hitting your nutrition targets. HRV should rebound if you respect the signal.`;
    tags = ['LOW READINESS', 'LIGHT ACTIVITY'];
  } else if (cvTraj === 'DECLINING' || cvTraj === 'SLIGHT DECLINE') {
    icon = '📉';
    headline = `Cardiovascular fitness is trending ${cvTraj.toLowerCase()}. Consistency is the fix.`;
    detail = `Your 30-day HRV and RHR trends indicate your aerobic base is softening. This is a slow-moving signal — it won't flip overnight — but it responds directly to consistent aerobic training and adequate recovery. Zone 2 cardio 3–4x per week is the most evidence-backed intervention.`;
    tags = ['CV TREND', 'AEROBIC WORK'];
  } else {
    icon = '✅';
    headline = `Moderate readiness (${recovery || '—'}). Train at controlled intensity today.`;
    detail = `Your signals are in the moderate range — not a peak performance day but not a rest day either. Moderate aerobic work, technique-focused training, or accessory lifts are well-suited. Hit your nutrition targets and prioritize sleep for a stronger tomorrow.`;
    tags = ['MODERATE DAY', 'CONTROLLED EFFORT'];
  }

  if (adaptation === 'ADAPTING') tags.push('ADAPTING');
  if (otRisk === 'MONITOR' && !tags.includes('HIGH RISK')) tags.push('MONITOR LOAD');

  return { icon, headline, detail, tags };
}

// ── RENDER SINGLE DAY ─────────────────────────────────────────
function renderDay(row, allRowsSorted) {
  if (!row) return;

  // ── TOP BADGES ──────────────────────────────────────────────
  const badges = [
    { label: row.recovery_score ? fmt(row.recovery_score) + ' Recovery' : 'Recovery N/A', val: row.readiness_signal || 'N/A' },
  ];
  const badgesHTML = [
    row.recovery_score   ? badgeHTML(fmt(row.recovery_score) + ' Recovery', badgeClass('PEAK')) : '',
    row.readiness_signal ? badgeHTML(row.readiness_signal) : '',
    row.eb_fueling_status ? badgeHTML(row.eb_fueling_status) : '',
    row.sleep_debt_trend  ? badgeHTML('Sleep Debt ' + row.sleep_debt_trend) : '',
    row.cv_fitness_trajectory ? badgeHTML(row.cv_fitness_trajectory) : '',
  ].filter(Boolean).join('');
  // override recovery badge color
  const recScore = n(row.recovery_score);
  const recBadge = recScore != null
    ? `<span class="badge" style="color:${recoveryColor(recScore)};background:${recoveryColor(recScore)}22;border-color:${recoveryColor(recScore)}44">
        <span class="badge-dot" style="background:currentColor"></span>${recScore} Recovery
       </span>` : '';
  $('topnav-badges').innerHTML = recBadge + [
    row.readiness_signal, row.eb_fueling_status,
    row.sleep_debt_trend ? 'Sleep ' + row.sleep_debt_trend : '',
    row.cv_fitness_trajectory
  ].filter(Boolean).map(v => badgeHTML(v)).join('');

  // ── ENERGY BALANCE / CALORIE HERO ───────────────────────────
  const calIn     = n(row.calories_actual);
  const calBurned = n(row.total_calories_kcal);
  const calGoal   = n(row.calories_goal);
  const bmr       = n(row.bmr_estimated_kcal);
  const eb7Avg    = n(row.eb_7day_avg_calories);

  if (calIn != null) {
    $('cal-in-num').textContent = fmt(calIn);
    $('cal-in-num').className = 'cal-side-num ' + (calGoal && calIn >= calGoal ? 'green' : '');
  } else {
    $('cal-in-num').textContent = '—';
    $('cal-in-num').className = 'cal-side-num muted';
  }
  $('cal-in-goal').textContent = calGoal ? 'Goal: ' + fmt(calGoal) + ' kcal' : 'Goal: —';

  if (calBurned != null) {
    $('cal-burned-num').textContent = fmt(calBurned);
  } else {
    $('cal-burned-num').textContent = '—';
  }
  $('cal-burned-sub').textContent = bmr ? 'BMR: ' + fmt(bmr) + ' kcal' : 'BMR: —';

  if (calIn != null && calBurned != null) {
    const net = calIn - calBurned;
    const surplus = net > 0;
    $('net-result').textContent = (surplus ? '+' : '') + fmt(net);
    $('net-result').style.color = surplus ? 'var(--green)' : 'var(--orange)';
    $('net-result').style.borderColor = surplus ? 'rgba(34,201,122,0.4)' : 'rgba(240,124,58,0.4)';
    $('net-result').style.background = surplus ? 'rgba(34,201,122,0.08)' : 'rgba(240,124,58,0.08)';
    $('net-words').textContent = surplus ? 'SURPLUS' : 'DEFICIT';
    $('net-words').style.color = surplus ? 'var(--green)' : 'var(--orange)';
  } else {
    $('net-result').textContent = '—';
    $('net-words').textContent = 'No meal data';
    $('net-words').style.color = 'var(--text3)';
  }

  // Calorie fill bars
  if (calIn != null && calGoal) {
    const pct = calIn / calGoal;
    $('cal-in-bar').style.width = clamp(pct * 100, 0, 100) + '%';
    $('cal-in-bar').style.background = fillColor(pct);
    $('cal-bar-nums').innerHTML = `<span>${fmt(calIn)}</span> / ${fmt(calGoal)} kcal`;
  }
  if (calBurned != null && eb7Avg) {
    const pct = calBurned / eb7Avg;
    $('eb7-bar').style.width = clamp(pct * 100, 0, 100) + '%';
    $('eb7-nums').innerHTML = `<span>${fmt(calBurned)}</span> / ${fmt(eb7Avg)} kcal 7d avg`;
  }

  // ── MEAL DONUT ──────────────────────────────────────────────
  destroyChart('mealDonut');
  const mealData = [
    n(row.cal_by_meal_breakfast_actual) || 0,
    n(row.cal_by_meal_lunch_actual) || 0,
    n(row.cal_by_meal_dinner_actual) || 0,
    n(row.cal_by_meal_snack_actual) || 0,
  ];
  const mealLabels = ['Breakfast', 'Lunch', 'Dinner', 'Snack'];
  const mealColors = ['#4f9cf0', '#f07c3a', '#2dcbcb', '#9b72f0'];
  const mealTotal = mealData.reduce((a, b) => a + b, 0);
  $('meal-legend').innerHTML = mealLabels.map((l, i) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${mealColors[i]}"></div>${l}: ${fmt(mealData[i])} kcal</div>`
  ).join('');
  charts.mealDonut = new Chart($('meal-donut'), {
    type: 'doughnut',
    data: {
      labels: mealLabels,
      datasets: [{ data: mealTotal > 0 ? mealData : [1,0,0,0], backgroundColor: mealColors, borderWidth: 0, hoverOffset: 6 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              if (mealTotal === 0) return ' No data';
              return ` ${ctx.label}: ${fmt(ctx.raw)} kcal (${Math.round(ctx.raw/mealTotal*100)}%)`;
            }
          }
        }
      }
    }
  });

  // ── RECOVERY GAUGE ──────────────────────────────────────────
  const recov = n(row.recovery_score);
  if (recov != null) {
    $('recovery-num').textContent = recov;
    $('recovery-num').style.color = recoveryColor(recov);
    setGauge('gauge-track', recov, 100, recoveryColor(recov));
  } else {
    $('recovery-num').textContent = '—';
  }
  $('hrv-val').textContent  = row.hrv_rmssd_ms ? fmt(row.hrv_rmssd_ms, 1) + ' ms' : '—';
  $('rhr-val').textContent  = row.resting_heart_rate ? fmt(row.resting_heart_rate) + ' bpm' : '—';
  $('spo2-val').textContent = row.spo2_pct ? pct(row.spo2_pct) : '—';
  $('temp-val').textContent = row.skin_temp_celsius ? fmt(row.skin_temp_celsius, 1) + '°C' : '—';

  // ── SLEEP BREAKDOWN ──────────────────────────────────────────
  const lightH = n(row.light_sleep_hrs) || 0;
  const swsH   = n(row.slow_wave_sleep_hrs) || 0;
  const remH   = n(row.rem_sleep_hrs) || 0;
  const awakeH = n(row.time_awake_min) ? n(row.time_awake_min) / 60 : 0;
  const totalSlept = lightH + swsH + remH;
  const sleepNeeded = n(row.sleep_needed_total_hrs);
  $('sleep-total').textContent  = totalSlept > 0 ? fmt(totalSlept, 1) : '—';
  $('sleep-needed').textContent = sleepNeeded ? fmt(sleepNeeded, 1) : '—';

  const sleepColors = { Light: '#4f9cf0', SWS: '#2dcbcb', REM: '#9b72f0', Awake: '#505a68' };
  const sleepSegs = [
    { label: 'Light', val: lightH },
    { label: 'SWS', val: swsH },
    { label: 'REM', val: remH },
    { label: 'Awake', val: awakeH },
  ];
  const sleepBasis = totalSlept + awakeH || 1;
  $('sleep-stack').innerHTML = sleepSegs.map(s =>
    `<div class="sleep-seg" style="width:${(s.val/sleepBasis*100).toFixed(1)}%;background:${sleepColors[s.label]}"></div>`
  ).join('');
  $('sleep-legend').innerHTML = sleepSegs.map(s =>
    `<div class="legend-item"><div class="legend-dot" style="background:${sleepColors[s.label]}"></div>${s.label}: ${fmt(s.val, 1)}h</div>`
  ).join('');

  $('sleep-perf').innerHTML  = row.sleep_performance_pct ? `<span style="color:${fillColor((n(row.sleep_performance_pct)||0)/100)}">${pct(row.sleep_performance_pct)}</span>` : '—';
  $('sleep-eff').textContent  = row.sleep_efficiency_pct  ? pct(row.sleep_efficiency_pct)  : '—';
  $('sleep-cons').textContent = row.sleep_consistency_pct ? pct(row.sleep_consistency_pct) : '—';
  $('sleep-cycles').textContent = row.sleep_cycles ? row.sleep_cycles : '—';

  // ── SLEEP DEBT ───────────────────────────────────────────────
  const debt7d = n(row.sleep_debt_7day_rolling_hrs);
  const debtLast = n(row.sleep_debt_last_night_hrs);
  if (debt7d != null) {
    $('sleep-debt-7d').textContent = fmt(debt7d, 1);
    $('sleep-debt-7d').style.color = debt7d > 15 ? 'var(--red)' : debt7d > 7 ? 'var(--yellow)' : 'var(--green)';
  }
  $('sleep-debt-last-nums').innerHTML = debtLast != null ? `<span>${fmt(debtLast, 1)} hrs</span>` : '—';
  if (debtLast != null) {
    const pctDebt = clamp(debtLast / 4, 0, 1); // 4hrs max reference
    $('sleep-debt-bar').style.width = pctDebt * 100 + '%';
    $('sleep-debt-bar').style.background = debtLast > 2 ? 'var(--red)' : 'var(--yellow)';
  }
  const debtTrend = row.sleep_debt_trend || '—';
  $('debt-trend').textContent = debtTrend;
  $('debt-trend').style.color = debtTrend === 'IMPROVING' ? 'var(--green)' : debtTrend === 'WORSENING' ? 'var(--red)' : 'var(--text3)';
  $('debt-repay').textContent = row.sleep_debt_days_to_repayment || '—';

  // ── STRAIN & WORKOUTS ────────────────────────────────────────
  const strain = n(row.day_strain);
  $('strain-num').textContent = strain != null ? fmt(strain, 1) : '—';
  if (strain != null) {
    $('strain-bar').style.width = clamp(strain / 21 * 100, 0, 100) + '%';
    $('strain-bar').style.background = strain >= 14 ? 'var(--red)' : strain >= 8 ? 'var(--orange)' : 'var(--blue)';
  }
  $('workout-count').textContent = row.workout_count || '0';
  $('workout-dur').textContent = row.workout_total_duration_min ? fmt(row.workout_total_duration_min) + ' min' : '—';
  $('avg-hr').textContent = row.day_avg_heart_rate ? fmt(row.day_avg_heart_rate) + ' bpm' : '—';
  $('max-hr').textContent = row.day_max_heart_rate ? fmt(row.day_max_heart_rate) + ' bpm' : '—';

  // ── OVERTRAINING ─────────────────────────────────────────────
  const otRisk = row.sr_overtraining_risk || '';
  $('ot-risk-val').textContent = otRisk || '—';
  $('ot-risk-val').style.color = otRisk === 'OK' ? 'var(--green)' : otRisk === 'MONITOR' ? 'var(--yellow)' : otRisk === 'HIGH' ? 'var(--red)' : 'var(--text)';
  $('ot-adaptation').className = 'badge ' + badgeClass(row.sr_adaptation_trend || '');
  $('ot-adaptation').innerHTML = `<span class="badge-dot" style="background:currentColor"></span>${row.sr_adaptation_trend || '—'}`;
  const riskMap = { OK: 0, MONITOR: 1, HIGH: 2 };
  const riskLevel = riskMap[otRisk] ?? -1;
  $('risk-ok').className  = 'risk-seg' + (riskLevel >= 0 ? ' active-ok' : '');
  $('risk-mon').className = 'risk-seg' + (riskLevel >= 1 ? ' active-monitor' : '');
  $('risk-hi').className  = 'risk-seg' + (riskLevel >= 2 ? ' active-high' : '');
  $('sr-strain').textContent   = row.sr_7day_avg_strain   ? fmt(row.sr_7day_avg_strain, 1)   : '—';
  $('sr-recovery').textContent = row.sr_7day_avg_recovery ? fmt(row.sr_7day_avg_recovery, 1) : '—';
  $('sr-ratio').textContent    = row.sr_ratio             ? fmt(row.sr_ratio, 3)              : '—';
  $('readiness-3d').textContent = row.readiness_3day_avg_strain ? fmt(row.readiness_3day_avg_strain, 1) : '—';

  // ── READINESS GAUGE ──────────────────────────────────────────
  const readiness = n(row.readiness_composite_score);
  if (readiness != null) {
    $('readiness-num').textContent = readiness;
    $('readiness-num').style.color = recoveryColor(readiness);
    setGauge('readiness-track', readiness, 100, recoveryColor(readiness));
  }
  const hbPct = n(row.readiness_hrv_vs_baseline_pct);
  const rbPct = n(row.readiness_rhr_vs_baseline_pct);
  $('hrv-baseline').textContent   = hbPct != null ? (hbPct > 0 ? '+' : '') + fmt(hbPct, 1) + '%' : '—';
  $('hrv-baseline').style.color   = hbPct != null ? (hbPct >= 0 ? 'var(--green)' : 'var(--red)') : '';
  $('rhr-baseline').textContent   = rbPct != null ? (rbPct > 0 ? '+' : '') + fmt(rbPct, 1) + '%' : '—';
  $('rhr-baseline').style.color   = rbPct != null ? (rbPct <= 0 ? 'var(--green)' : 'var(--red)') : ''; // lower RHR = good
  $('readiness-signal').textContent = row.readiness_signal || '—';
  $('readiness-signal').style.color = 'var(--text)';

  // ── COACHING CARD ────────────────────────────────────────────
  const coaching = buildCoaching(row);
  $('coaching-icon').textContent = coaching.icon;
  $('coaching-headline').textContent = coaching.headline;
  $('coaching-detail').textContent = coaching.detail;
  $('coaching-tags').innerHTML = coaching.tags.map(t =>
    `<span class="coaching-tag ${badgeClass(t)}">${t}</span>`
  ).join('');

  // ── MACROS ───────────────────────────────────────────────────
  const macroFatA   = n(row.macro_total_fat_actual);
  const macroFatG   = n(row.macro_total_fat_goal);
  const macroCarbA  = n(row.macro_total_carbs_actual);
  const macroCarbG  = n(row.macro_total_carbs_goal);
  const macroProtA  = n(row.macro_protein_actual);
  const macroProtG  = n(row.macro_protein_goal);
  $('macro-bars').innerHTML = [
    fillBarHTML('Total Fat',        macroFatA,  macroFatG,  'g', false, 1),
    fillBarHTML('Total Carbohydrates', macroCarbA, macroCarbG, 'g', false, 1),
    fillBarHTML('Protein',          macroProtA, macroProtG, 'g', false, 1),
  ].join('');

  // Macro donut
  destroyChart('macroDonut');
  const macroVals = [macroFatA || 0, macroCarbA || 0, macroProtA || 0];
  const macroLabels = ['Fat', 'Carbs', 'Protein'];
  const macroColors = ['#f07c3a', '#4f9cf0', '#22c97a'];
  const macroTotal = macroVals.reduce((a, b) => a + b, 0);
  $('macro-legend').innerHTML = macroLabels.map((l, i) =>
    `<div class="legend-item"><div class="legend-dot" style="background:${macroColors[i]}"></div>${l}: ${fmt(macroVals[i], 1)}g${macroTotal > 0 ? ' ('+Math.round(macroVals[i]/macroTotal*100)+'%)' : ''}</div>`
  ).join('');
  charts.macroDonut = new Chart($('macro-donut'), {
    type: 'doughnut',
    data: {
      labels: macroLabels,
      datasets: [{ data: macroTotal > 0 ? macroVals : [1,1,1], backgroundColor: macroColors, borderWidth: 0, hoverOffset: 6 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '68%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => macroTotal > 0
              ? ` ${ctx.label}: ${fmt(ctx.raw, 1)}g (${Math.round(ctx.raw/macroTotal*100)}%)`
              : ' No data'
          }
        }
      }
    }
  });

  // ── MICROS ───────────────────────────────────────────────────
  const micros = [
    { name: 'Sodium',        actual: n(row.micro_sodium_actual),             goal: n(row.micro_sodium_goal),             unit: 'mg', invert: true },
    { name: 'Potassium',     actual: n(row.micro_potassium_actual),           goal: n(row.micro_potassium_goal),           unit: 'mg' },
    { name: 'Dietary Fiber', actual: n(row.micro_dietary_fiber_actual),       goal: n(row.micro_dietary_fiber_goal),       unit: 'g'  },
    { name: 'Sugars',        actual: n(row.micro_sugars_actual),              goal: n(row.micro_sugars_goal),              unit: 'g', invert: true },
    { name: 'Vitamin A',     actual: n(row.micro_vitamin_a_mcg_rae_actual),   goal: n(row.micro_vitamin_a_mcg_rae_goal),   unit: 'mcg' },
    { name: 'Vitamin C',     actual: n(row.micro_vitamin_c_mg_actual),        goal: n(row.micro_vitamin_c_mg_goal),        unit: 'mg' },
    { name: 'Vitamin D',     actual: n(row.micro_vitamin_d_mcg_actual),       goal: n(row.micro_vitamin_d_mcg_goal),       unit: 'mcg' },
    { name: 'Calcium',       actual: n(row.micro_calcium_mg_actual),          goal: n(row.micro_calcium_mg_goal),          unit: 'mg' },
    { name: 'Iron',          actual: n(row.micro_iron_mg_actual),             goal: n(row.micro_iron_mg_goal),             unit: 'mg' },
  ];
  $('micro-bars').innerHTML = micros.map(m =>
    fillBarHTML(m.name, m.actual, m.goal, m.unit, m.invert || false, m.unit === 'g' ? 1 : 0)
  ).join('');

  // ── CV FITNESS ───────────────────────────────────────────────
  const cvTraj = row.cv_fitness_trajectory || '—';
  $('cv-trajectory').textContent = cvTraj;
  $('cv-trajectory').style.color = cvTraj.includes('IMPROV') ? 'var(--green)' : cvTraj.includes('DECLIN') ? 'var(--red)' : 'var(--yellow)';
  $('cv-hrv').textContent = row.cv_30day_avg_hrv ? fmt(row.cv_30day_avg_hrv, 1) + ' ms' : '—';
  $('cv-rhr').textContent = row.cv_30day_avg_rhr ? fmt(row.cv_30day_avg_rhr, 1) + ' bpm' : '—';
  const hrvTrendPct = n(row.cv_hrv_trend_vs_prior30_pct);
  const rhrTrendPct = n(row.cv_rhr_trend_vs_prior30_pct);
  $('cv-hrv-trend').innerHTML = hrvTrendPct != null
    ? `<span class="${hrvTrendPct >= 0 ? 'trend-up' : 'trend-down'}">${hrvTrendPct >= 0 ? '▲' : '▼'} ${Math.abs(hrvTrendPct)}% vs prior 30d</span>`
    : '—';
  $('cv-rhr-trend').innerHTML = rhrTrendPct != null
    ? `<span class="${rhrTrendPct <= 0 ? 'trend-up' : 'trend-down'}">${rhrTrendPct <= 0 ? '▲' : '▼'} ${Math.abs(rhrTrendPct)}% vs prior 30d</span>`
    : '—';

  // ── FUELING EFFICIENCY ───────────────────────────────────────
  $('cal-per-strain').textContent = row.eb_cal_per_strain_point ? fmt(row.eb_cal_per_strain_point) : '—';
  $('eb7-avg').textContent  = row.eb_7day_avg_calories        ? fmt(row.eb_7day_avg_calories) + ' kcal' : '—';
  $('eb-maint').textContent = row.eb_maintenance_target_kcal  ? fmt(row.eb_maintenance_target_kcal) + ' kcal' : '—';
  const vsAvg = n(row.eb_today_vs_7day_avg_kcal);
  $('eb-vs-avg').textContent = vsAvg != null ? (vsAvg > 0 ? '+' : '') + fmt(vsAvg) + ' kcal' : '—';
  $('eb-vs-avg').style.color = vsAvg != null ? (vsAvg >= 0 ? 'var(--green)' : 'var(--red)') : '';
  $('eb-status').textContent = row.eb_fueling_status || '—';
  $('eb-status').style.color = row.eb_fueling_status === 'ON TARGET' ? 'var(--green)' : row.eb_fueling_status === 'UNDER-FUELED' ? 'var(--orange)' : 'var(--red)';

  // ── TREND CHARTS (last 30 days from selected date) ───────────
  buildTrends(allRowsSorted, dateIndex);
}

// ── TREND CHARTS ─────────────────────────────────────────────
function buildTrends(sorted, fromIdx) {
  // sorted = newest-first, so slice from fromIdx and reverse for chronological
  const window30 = sorted.slice(fromIdx, fromIdx + 30).reverse();
  const labels = window30.map(r => {
    const d = r.date || '';
    return d.slice(5); // MM-DD
  });

  const makeData = field => window30.map(r => n(r[field]));

  // Recovery
  destroyChart('trendRec');
  charts.trendRec = new Chart($('trend-recovery'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: makeData('recovery_score'),
        borderColor: '#22c97a', backgroundColor: 'transparent',
        borderWidth: 2, pointRadius: 2, tension: 0.3,
        spanGaps: true,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { color: '#23283044' } },
        y: { min: 0, max: 100, ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
    }
  });

  // HRV + 30d avg overlay
  destroyChart('trendHRV');
  const hrvData = makeData('hrv_rmssd_ms');
  const avg30 = window30.map(r => n(r['cv_30day_avg_hrv']));
  charts.trendHRV = new Chart($('trend-hrv'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'HRV', data: hrvData, borderColor: '#9b72f0', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 2, tension: 0.3, spanGaps: true },
        { label: '30d Avg', data: avg30, borderColor: '#9b72f044', backgroundColor: 'transparent', borderWidth: 1.5, borderDash: [4,4], pointRadius: 0, tension: 0, spanGaps: true },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { color: '#23283044' } },
        y: { ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
    }
  });

  // Sleep
  destroyChart('trendSleep');
  charts.trendSleep = new Chart($('trend-sleep'), {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: makeData('sleep_performance_pct'),
        borderColor: '#4f9cf0', backgroundColor: 'transparent',
        borderWidth: 2, pointRadius: 2, tension: 0.3, spanGaps: true
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { color: '#23283044' } },
        y: { min: 0, max: 100, ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
    }
  });

  // Calories in vs burned
  destroyChart('trendCal');
  charts.trendCal = new Chart($('trend-calories'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Intake', data: makeData('calories_actual'), borderColor: '#22c97a', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 2, tension: 0.3, spanGaps: true },
        { label: 'Burned', data: makeData('total_calories_kcal'), borderColor: '#f07c3a', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 2, tension: 0.3, spanGaps: true },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 }, color: '#8892a0' } },
        tooltip: { mode: 'index', intersect: false }
      },
      scales: {
        x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { color: '#23283044' } },
        y: { ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
    }
  });

  // Strain bar
  destroyChart('trendStrain');
  charts.trendStrain = new Chart($('trend-strain'), {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: makeData('day_strain'),
        backgroundColor: window30.map(r => {
          const s = n(r.day_strain);
          return s >= 14 ? '#f04f4f88' : s >= 8 ? '#f07c3a88' : '#4f9cf088';
        }),
        borderWidth: 0,
        spanGaps: true,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { display: false } },
        y: { min: 0, max: 21, ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
    }
  });

  // HRV mini trend (CV card)
  destroyChart('hrvMini');
  charts.hrvMini = new Chart($('hrv-chart'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'HRV', data: hrvData, borderColor: '#9b72f0', backgroundColor: '#9b72f011', borderWidth: 2, pointRadius: 0, tension: 0.4, fill: true, spanGaps: true },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
      scales: {
        x: { ticks: { maxTicksLimit: 4, font: { size: 9 } }, grid: { color: '#23283022' } },
        y: { ticks: { font: { size: 9 } }, grid: { color: '#23283022' } }
      }
    }
  });

  // Energy Balance mini chart (last 14 days)
  destroyChart('ebMini');
  const eb14 = sorted.slice(fromIdx, fromIdx + 14).reverse();
  const ebLabels = eb14.map(r => (r.date || '').slice(5));
  charts.ebMini = new Chart($('eb-chart'), {
    type: 'bar',
    data: {
      labels: ebLabels,
      datasets: [
        {
          label: 'In',
          data: eb14.map(r => n(r.calories_actual)),
          backgroundColor: '#22c97a88',
          borderWidth: 0,
          spanGaps: true,
        },
        {
          label: 'Burned',
          data: eb14.map(r => n(r.total_calories_kcal)),
          backgroundColor: '#f07c3a88',
          borderWidth: 0,
          spanGaps: true,
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: true, position: 'bottom', labels: { boxWidth: 10, font: { size: 10 }, color: '#8892a0' } },
        tooltip: { mode: 'index', intersect: false }
      },
      scales: {
        x: { ticks: { maxTicksLimit: 5, font: { size: 10 } }, grid: { display: false } },
        y: { ticks: { font: { size: 10 } }, grid: { color: '#23283044' } }
      }
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
  renderDay(row, allRows);
}

$('prev-day').addEventListener('click', () => {
  if (dateIndex < allRows.length - 1) { dateIndex++; updateDate(); }
});
$('next-day').addEventListener('click', () => {
  if (dateIndex > 0) { dateIndex--; updateDate(); }
});

// ── LOAD CSV ──────────────────────────────────────────────────
function showError(msg) {
  $('loading').style.display = 'none';
  const el = $('error-msg');
  el.style.display = 'flex';
  if (msg) $('error-detail').textContent = msg;
}

Papa.parse(CSV_PATH, {
  download: true,
  header: true,
  skipEmptyLines: true,
  complete(results) {
    if (!results.data || results.data.length === 0) {
      showError('The CSV file was empty or could not be parsed. Make sure Health_Tracker_Master.csv is present.');
      return;
    }

    // Deduplicate by date (keep first occurrence = newest because CSV is newest-first)
    const seen = new Set();
    allRows = results.data.filter(r => {
      const d = r.date || r['date'];
      if (!d || seen.has(d)) return false;
      seen.add(d);
      return true;
    });

    // Sort newest first
    allRows.sort((a, b) => (b.date || '').localeCompare(a.date || ''));

    $('loading').style.display = 'none';
    $('app').style.display = 'block';

    dateIndex = 0;
    updateDate();
  },
  error(err) {
    showError('Failed to load Health_Tracker_Master.csv: ' + err.message + '. If running locally, you must serve this from a web server (not file://).');
  }
});
