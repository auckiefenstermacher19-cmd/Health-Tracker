/* ============================================================
   dashboard.js  —  Health Tracker Dashboard v3
   ============================================================ */

const CSV_PATH = 'Health_Tracker_Master.csv?' + Date.now();
let allRows = [], dateIndex = 0, charts = {};
let calOpen = false, calViewYear = new Date().getFullYear(), calViewMonth = new Date().getMonth();

const $  = id => document.getElementById(id);
const n  = (v,d=0) => { const x=parseFloat(v); return isNaN(x)?null:parseFloat(x.toFixed(d)); };
const fmt = (v,d=0,fb='—') => { const x=n(v,d); return x===null?fb:x.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}); };
const pct = (v,d=1) => { const x=n(v,d); return x===null?'—':x+'%'; };
const clamp = (v,lo,hi) => Math.min(hi,Math.max(lo,v));

function recoveryColor(s) { return s>=67?'#1fd67a':s>=33?'#f0c93a':'#e84d4d'; }
function fillColor(r,inv=false) {
  if(inv) return r>1?'#e84d4d':r>0.8?'#f0c93a':'#1fd67a';
  return r>=1?'#1fd67a':r>=0.5?'#f0c93a':'#e84d4d';
}
function badgeClass(sig) {
  const m={'PEAK':'badge-green','OPTIMAL':'badge-green','READY':'badge-blue','MODERATE':'badge-yellow',
    'REST':'badge-red','UNDER-FUELED':'badge-orange','ON TARGET':'badge-green','OVER-FUELED':'badge-red',
    'WORSENING':'badge-red','IMPROVING':'badge-green','STABLE':'badge-blue',
    'OK':'badge-green','MONITOR':'badge-yellow','HIGH':'badge-red',
    'ADAPTING':'badge-green','MAINTAINING':'badge-blue','OVERREACHING':'badge-red',
    'DECLINING':'badge-red','SLIGHT DECLINE':'badge-yellow','SLIGHT IMPROVEMENT':'badge-green'};
  return m[sig]||'badge-blue';
}
function badgeHTML(text,cls) {
  if(!text) return '';
  return `<span class="badge ${cls||badgeClass(text)}"><span class="badge-dot"></span>${text}</span>`;
}
function setGauge(id,value,max,color) {
  const el=$(id); if(!el) return;
  const c=parseFloat(el.getAttribute('stroke-dasharray'));
  el.style.strokeDashoffset=c*(1-clamp(value/max,0,1));
  el.style.stroke=color;
}
function fillBarHTML(name,actual,goal,unit='',inv=false,d=0) {
  if(actual==null||goal==null||goal===0) return `<div>
    <div class="fill-bar-header"><span class="fill-bar-name">${name}</span><span class="fill-bar-nums muted">No data</span></div>
    <div class="fill-bar-track"><div class="fill-bar-fill" style="width:0%;background:var(--bg4)"></div></div></div>`;
  const ratio=actual/goal, display=clamp(ratio,0,1)*100, color=fillColor(ratio,inv);
  const pctTxt=Math.round(ratio*100)+'%';
  const overTxt=ratio>1?` <span style="color:${inv?'var(--red)':'var(--green)'}">+${fmt(actual-goal,d)}${unit} over</span>`:'';
  return `<div>
    <div class="fill-bar-header"><span class="fill-bar-name">${name}</span>
    <span class="fill-bar-nums"><span>${fmt(actual,d)}${unit}</span> / ${fmt(goal,d)}${unit} · ${pctTxt}${overTxt}</span></div>
    <div class="fill-bar-track" style="background:${color}20"><div class="fill-bar-fill" style="width:${display}%;background:${color}"></div></div></div>`;
}

Chart.defaults.color='#404c5a'; Chart.defaults.borderColor='#1f2630';
Chart.defaults.font.family="'DM Sans',system-ui,sans-serif"; Chart.defaults.font.size=10;
function destroyChart(k) { if(charts[k]){charts[k].destroy();delete charts[k];} }
const bx = { ticks:{maxTicksLimit:5,font:{size:9},color:'#404c5a'}, grid:{color:'#1f263044'} };
const by = { ticks:{font:{size:9},color:'#404c5a'}, grid:{color:'#1f263044'} };

// ── KEY METRICS ────────────────────────────────────────────────
function keyMetricDesc(label, value, row) {
  switch(label) {
    case 'Recovery':
      const rs = n(row.recovery_score);
      if(rs==null) return 'No recovery data for this date.';
      if(rs>=67) return `<strong>${rs}/100</strong> — Your body is well-recovered. HRV and resting heart rate are in a healthy range. Good day to push hard.`;
      if(rs>=33) return `<strong>${rs}/100</strong> — Moderate recovery. Train at controlled intensity and prioritize sleep tonight.`;
      return `<strong>${rs}/100</strong> — Low recovery. Your nervous system is stressed. Rest or light movement only today.`;
    case 'Readiness':
      const sig = row.readiness_signal || '';
      const descs = {
        'PEAK':     'Your nervous system is primed for peak performance. This is your window to train hard or attempt a PR.',
        'OPTIMAL':  'Strong readiness — conditions are favorable for quality training.',
        'READY':    'Your body is ready for normal training. Stick to your planned session.',
        'MODERATE': 'Mixed signals — some stress indicators present. Train at moderate intensity.',
        'REST':     'Your body is signaling a need for recovery. Avoid high-intensity training today.'
      };
      return descs[sig] || 'Composite score of HRV, resting HR, and recent strain vs recovery balance.';
    case 'Fueling':
      const fs = row.eb_fueling_status || '';
      if(fs==='UNDER-FUELED') return 'You burned significantly more calories than you consumed. Under-fueling impairs muscle repair, hormone regulation, and next-day recovery.';
      if(fs==='ON TARGET')    return 'Calorie intake is well-matched to what you burned. Your body has the fuel it needs to recover and adapt.';
      if(fs==='OVER-FUELED')  return 'Calorie intake exceeded what you burned today. This creates a surplus — beneficial for muscle building, less so for fat loss goals.';
      return 'Relationship between calories consumed and calories burned today.';
    case 'Sleep Debt':
      const dt = row.sleep_debt_trend || '';
      const d7 = n(row.sleep_debt_7day_rolling_hrs);
      if(dt==='WORSENING') return `<strong>${fmt(d7,1)} hrs</strong> accumulated and rising. Chronic sleep debt suppresses HRV, raises cortisol, and impairs recovery. Prioritize 8–9 hrs tonight.`;
      if(dt==='IMPROVING') return `<strong>${fmt(d7,1)} hrs</strong> accumulated but trending down. Keep prioritizing sleep — you're moving in the right direction.`;
      return `<strong>${fmt(d7,1)} hrs</strong> of sleep owed to your body over the last 7 days. Sleep debt compounds and must be repaid to restore full recovery capacity.`;
    case 'CV Fitness':
      const cv = row.cv_fitness_trajectory || '';
      if(cv==='DECLINING')      return 'Your 30-day HRV is falling and resting HR is rising. Aerobic base is weakening. Zone 2 cardio 3–4x per week is the most effective fix.';
      if(cv==='SLIGHT DECLINE') return 'Early signs of cardiovascular softening. Consistent aerobic work will reverse this trend before it becomes significant.';
      if(cv.includes('IMPROV')) return 'Your cardiovascular fitness is trending in the right direction. HRV rising and RHR falling are signs your aerobic base is strengthening.';
      return '30-day trend of HRV and resting heart rate — the most reliable long-term indicators of cardiovascular health.';
    default: return '';
  }
}

function renderKeyMetrics(row) {
  const recov = n(row.recovery_score);
  const metrics = [
    { label:'Recovery',  badge: recov!=null ? `<span class="badge" style="color:${recoveryColor(recov)};background:${recoveryColor(recov)}18;border-color:${recoveryColor(recov)}40"><span class="badge-dot"></span>${recov}</span>` : badgeHTML('No Data','badge-blue') },
    { label:'Readiness', badge: row.readiness_signal      ? badgeHTML(row.readiness_signal)      : badgeHTML('No Data','badge-blue') },
    { label:'Fueling',   badge: row.eb_fueling_status     ? badgeHTML(row.eb_fueling_status)     : badgeHTML('No Data','badge-blue') },
    { label:'Sleep Debt',badge: row.sleep_debt_trend      ? badgeHTML('Sleep '+row.sleep_debt_trend) : badgeHTML('No Data','badge-blue') },
    { label:'CV Fitness',badge: row.cv_fitness_trajectory ? badgeHTML(row.cv_fitness_trajectory) : badgeHTML('No Data','badge-blue') },
  ];
  $('key-metrics-grid').innerHTML = metrics.map(m => `
    <div class="km-item">
      <div class="km-top"><span class="km-label">${m.label}</span>${m.badge}</div>
      <div class="km-desc">${keyMetricDesc(m.label, null, row)}</div>
    </div>`).join('');
}

// ── COACHING ENGINE ────────────────────────────────────────────
function buildCoaching(row) {
  const recovery=n(row.recovery_score), signal=row.readiness_signal||'';
  const sleepDebt=n(row.sleep_debt_7day_rolling_hrs), debtTrend=row.sleep_debt_trend||'';
  const otRisk=row.sr_overtraining_risk||'', adaptation=row.sr_adaptation_trend||'';
  const fueling=row.eb_fueling_status||'', cvTraj=row.cv_fitness_trajectory||'';
  const calIn=n(row.calories_actual), calBurned=n(row.total_calories_kcal);
  let icon='💡', headline='', detail='', tags=[];
  if(otRisk==='HIGH'||(adaptation==='OVERREACHING'&&recovery!=null&&recovery<33)) {
    icon='🚨'; headline='Signs of overtraining detected. Rest is not optional today.';
    detail=`Recovery is ${recovery||'—'} and your strain-to-recovery ratio indicates overreaching. Active recovery only — walking, stretching, or light mobility work.`;
    tags=['REST DAY','HIGH RISK'];
  } else if(sleepDebt!=null&&sleepDebt>15&&debtTrend==='WORSENING') {
    icon='😴'; headline=`${fmt(sleepDebt,1)} hours of accumulated sleep debt and still rising.`;
    detail=`Chronic sleep debt suppresses HRV, elevates cortisol, and impairs muscle recovery. Aim for 8–9 hours tonight.`;
    tags=['SLEEP PRIORITY','RECOVERY FOCUS'];
  } else if(fueling==='UNDER-FUELED'&&calIn!=null&&calBurned!=null) {
    const deficit=calBurned-calIn; icon='⚠️';
    headline=`${fmt(deficit)} calories under-fueled vs what you burned today.`;
    detail=`Under-fueling while training suppresses recovery and adaptation. Prioritize protein and complex carbohydrates.`;
    tags=['FUEL UP','NUTRITION ACTION'];
  } else if(signal==='PEAK'||(recovery!=null&&recovery>=80&&adaptation!=='OVERREACHING')) {
    icon='⚡'; headline=`Recovery is ${signal||'strong'} — this is your window to push hard.`;
    detail=`Your HRV and resting heart rate are signaling high readiness. High-intensity work, PR attempts, or long endurance sessions are all supported. Fuel well before and after.`;
    tags=['HIGH READINESS','TRAIN HARD'];
    if(sleepDebt!=null&&sleepDebt>10) { detail+=` Note: sleep debt is still elevated at ${fmt(sleepDebt,1)} hours — prioritize sleep tonight.`; tags.push('WATCH SLEEP DEBT'); }
  } else if(signal==='REST'||(recovery!=null&&recovery<33)) {
    icon='🛌'; headline=`Low recovery (${recovery||'—'}). Protect today's energy.`;
    detail=`Keep any training aerobic and low-strain. Focus on sleep quality tonight, hydration, and hitting your nutrition targets.`;
    tags=['LOW READINESS','LIGHT ACTIVITY'];
  } else if(cvTraj==='DECLINING'||cvTraj==='SLIGHT DECLINE') {
    icon='📉'; headline=`Cardiovascular fitness trending ${cvTraj.toLowerCase()}.`;
    detail=`Zone 2 cardio 3–4x per week is the most evidence-backed intervention. Consistency is the fix.`;
    tags=['CV TREND','AEROBIC WORK'];
  } else {
    icon='✅'; headline=`Moderate readiness (${recovery||'—'}). Controlled intensity today.`;
    detail=`Not a peak day but not a rest day. Moderate aerobic work or technique-focused training. Hit nutrition targets and prioritize sleep.`;
    tags=['MODERATE DAY','CONTROLLED EFFORT'];
  }
  if(adaptation==='ADAPTING') tags.push('ADAPTING');
  if(otRisk==='MONITOR'&&!tags.includes('HIGH RISK')) tags.push('MONITOR LOAD');
  return {icon,headline,detail,tags};
}

// ── RENDER DAY ─────────────────────────────────────────────────
function renderDay(row) {
  if(!row) return;
  renderKeyMetrics(row);

  const calIn=n(row.calories_actual), calBurned=n(row.total_calories_kcal);
  const calGoal=n(row.calories_goal), bmr=n(row.bmr_estimated_kcal), eb7Avg=n(row.eb_7day_avg_calories);
  $('cal-in-num').textContent=calIn!=null?fmt(calIn):'—';
  $('cal-in-num').style.color=calIn!=null&&calGoal&&calIn>=calGoal?'var(--green)':'var(--text)';
  $('cal-in-goal').textContent=calGoal?'Goal: '+fmt(calGoal)+' kcal':'Goal: —';
  $('cal-burned-num').textContent=calBurned!=null?fmt(calBurned):'—';
  $('cal-burned-sub').textContent=bmr?'BMR: '+fmt(bmr)+' kcal':'BMR: —';
  if(calIn!=null&&calBurned!=null) {
    const net=calIn-calBurned, surplus=net>0, c=surplus?'var(--green)':'var(--orange)';
    $('net-result').textContent=(surplus?'+':'')+fmt(net);
    $('net-result').style.cssText=`color:${c};border-color:${surplus?'var(--green-border)':'var(--orange-border)'};background:${surplus?'var(--green-bg)':'var(--orange-bg)'}`;
    $('net-words').textContent=surplus?'SURPLUS':'DEFICIT';
    $('net-words').style.color=c;
  } else { $('net-result').textContent='—'; $('net-words').textContent='No meal data'; $('net-words').style.color='var(--text3)'; }
  if(calIn!=null&&calGoal) { const r=calIn/calGoal; $('cal-in-bar').style.width=clamp(r,0,1)*100+'%'; $('cal-in-bar').style.background=fillColor(r); $('cal-bar-nums').innerHTML=`<span>${fmt(calIn)}</span> / ${fmt(calGoal)} kcal`; } else { $('cal-bar-nums').textContent='No data'; }
  if(calBurned!=null&&eb7Avg) { const r=calBurned/eb7Avg; $('eb7-bar').style.width=clamp(r,0,1)*100+'%'; $('eb7-nums').innerHTML=`<span>${fmt(calBurned)}</span> / ${fmt(eb7Avg)} kcal 7d avg`; } else { $('eb7-nums').textContent='No data'; }

  destroyChart('mealDonut');
  const mV=[n(row.cal_by_meal_breakfast_actual)||0,n(row.cal_by_meal_lunch_actual)||0,n(row.cal_by_meal_dinner_actual)||0,n(row.cal_by_meal_snack_actual)||0];
  const mL=['Breakfast','Lunch','Dinner','Snack'],mC=['#4a94e8','#e87a3a','#28c4c4','#9470e8'],mT=mV.reduce((a,b)=>a+b,0);
  $('meal-legend').innerHTML=mL.map((l,i)=>`<div class="legend-item"><div class="legend-dot" style="background:${mC[i]}"></div>${l}: ${fmt(mV[i])} kcal</div>`).join('');
  charts.mealDonut=new Chart($('meal-donut'),{type:'doughnut',data:{labels:mL,datasets:[{data:mT>0?mV:[1,0,0,0],backgroundColor:mC,borderWidth:0,hoverOffset:4}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%',plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>mT>0?` ${ctx.label}: ${fmt(ctx.raw)} kcal (${Math.round(ctx.raw/mT*100)}%)`:'No data'}}}}});

  const recov=n(row.recovery_score);
  if(recov!=null){$('recovery-num').textContent=recov;$('recovery-num').style.color=recoveryColor(recov);setGauge('gauge-track',recov,100,recoveryColor(recov));}
  else $('recovery-num').textContent='—';
  $('hrv-val').textContent=row.hrv_rmssd_ms?fmt(row.hrv_rmssd_ms,1)+' ms':'—';
  $('rhr-val').textContent=row.resting_heart_rate?fmt(row.resting_heart_rate)+' bpm':'—';
  $('spo2-val').textContent=row.spo2_pct?pct(row.spo2_pct):'—';
  $('temp-val').textContent=row.skin_temp_celsius?fmt(row.skin_temp_celsius,1)+'°C':'—';

  const lH=n(row.light_sleep_hrs)||0,swsH=n(row.slow_wave_sleep_hrs)||0,remH=n(row.rem_sleep_hrs)||0;
  const awH=n(row.time_awake_min)?n(row.time_awake_min)/60:0,slT=lH+swsH+remH;
  $('sleep-total').textContent=slT>0?fmt(slT,1):'—';
  $('sleep-needed').textContent=row.sleep_needed_total_hrs?fmt(row.sleep_needed_total_hrs,1):'—';
  const sC={Light:'#4a94e8',SWS:'#28c4c4',REM:'#9470e8',Awake:'#2a3340'};
  const sS=[{label:'Light',val:lH},{label:'SWS',val:swsH},{label:'REM',val:remH},{label:'Awake',val:awH}];
  const sB=slT+awH||1;
  $('sleep-stack').innerHTML=sS.map(s=>`<div class="sleep-seg" style="width:${(s.val/sB*100).toFixed(1)}%;background:${sC[s.label]}"></div>`).join('');
  $('sleep-legend').innerHTML=sS.filter(s=>s.val>0).map(s=>`<div class="legend-item"><div class="legend-dot" style="background:${sC[s.label]}"></div>${s.label}: ${fmt(s.val,1)}h</div>`).join('');
  const sp=n(row.sleep_performance_pct);
  $('sleep-perf').innerHTML=sp!=null?`<span style="color:${fillColor(sp/100)}">${pct(sp,0)}</span>`:'—';
  $('sleep-eff').textContent=row.sleep_efficiency_pct?pct(row.sleep_efficiency_pct,0):'—';
  $('sleep-cons').textContent=row.sleep_consistency_pct?pct(row.sleep_consistency_pct,0):'—';
  $('sleep-cycles').textContent=row.sleep_cycles||'—';

  const d7=n(row.sleep_debt_7day_rolling_hrs),dL=n(row.sleep_debt_last_night_hrs);
  if(d7!=null){$('sleep-debt-7d').textContent=fmt(d7,1);$('sleep-debt-7d').style.color=d7>15?'var(--red)':d7>7?'var(--yellow)':'var(--green)';}
  else $('sleep-debt-7d').textContent='—';
  if(dL!=null){$('sleep-debt-last-nums').innerHTML=`<span>${fmt(dL,1)} hrs</span>`;$('sleep-debt-bar').style.width=clamp(dL/4,0,1)*100+'%';$('sleep-debt-bar').style.background=dL>2?'var(--red)':'var(--yellow)';}
  else $('sleep-debt-last-nums').textContent='—';
  const dt=row.sleep_debt_trend||'—';
  $('debt-trend').textContent=dt; $('debt-trend').style.color=dt==='IMPROVING'?'var(--green)':dt==='WORSENING'?'var(--red)':'var(--text3)';
  $('debt-repay').textContent=row.sleep_debt_days_to_repayment||'—';

  const strain=n(row.day_strain);
  $('strain-num').textContent=strain!=null?fmt(strain,1):'—';
  if(strain!=null){$('strain-bar').style.width=clamp(strain/21,0,1)*100+'%';$('strain-bar').style.background=strain>=14?'var(--red)':strain>=8?'var(--orange)':'var(--blue)';}
  $('workout-count').textContent=row.workout_count||'0';
  $('workout-dur').textContent=row.workout_total_duration_min?fmt(row.workout_total_duration_min)+' min':'—';
  $('avg-hr').textContent=row.day_avg_heart_rate?fmt(row.day_avg_heart_rate)+' bpm':'—';
  $('max-hr').textContent=row.day_max_heart_rate?fmt(row.day_max_heart_rate)+' bpm':'—';

  const ot=row.sr_overtraining_risk||'';
  $('ot-risk-val').textContent=ot||'—'; $('ot-risk-val').style.color=ot==='OK'?'var(--green)':ot==='MONITOR'?'var(--yellow)':ot==='HIGH'?'var(--red)':'var(--text)';
  $('ot-adaptation').className='badge '+badgeClass(row.sr_adaptation_trend||'');
  $('ot-adaptation').innerHTML=`<span class="badge-dot"></span>${row.sr_adaptation_trend||'—'}`;
  const rm={OK:0,MONITOR:1,HIGH:2},rl=rm[ot]??-1;
  $('risk-ok').className='risk-seg'+(rl>=0?' active-ok':'');
  $('risk-mon').className='risk-seg'+(rl>=1?' active-monitor':'');
  $('risk-hi').className='risk-seg'+(rl>=2?' active-high':'');
  $('sr-strain').textContent=row.sr_7day_avg_strain?fmt(row.sr_7day_avg_strain,1):'—';
  $('sr-recovery').textContent=row.sr_7day_avg_recovery?fmt(row.sr_7day_avg_recovery,1):'—';
  $('sr-ratio').textContent=row.sr_ratio?fmt(row.sr_ratio,3):'—';
  $('readiness-3d').textContent=row.readiness_3day_avg_strain?fmt(row.readiness_3day_avg_strain,1):'—';

  const rd=n(row.readiness_composite_score);
  if(rd!=null){$('readiness-num').textContent=rd;$('readiness-num').style.color=recoveryColor(rd);setGauge('readiness-track',rd,100,recoveryColor(rd));}
  else $('readiness-num').textContent='—';
  const hb=n(row.readiness_hrv_vs_baseline_pct),rb=n(row.readiness_rhr_vs_baseline_pct);
  $('hrv-baseline').textContent=hb!=null?(hb>0?'+':'')+fmt(hb,1)+'%':'—'; $('hrv-baseline').style.color=hb!=null?(hb>=0?'var(--green)':'var(--red)'):'';
  $('rhr-baseline').textContent=rb!=null?(rb>0?'+':'')+fmt(rb,1)+'%':'—'; $('rhr-baseline').style.color=rb!=null?(rb<=0?'var(--green)':'var(--red)'):'';
  $('readiness-signal').textContent=row.readiness_signal||'—';

  const c=buildCoaching(row);
  $('coaching-icon').textContent=c.icon; $('coaching-headline').textContent=c.headline;
  $('coaching-detail').textContent=c.detail;
  $('coaching-tags').innerHTML=c.tags.map(t=>`<span class="coaching-tag ${badgeClass(t)}">${t}</span>`).join('');

  $('macro-bars').innerHTML=[
    fillBarHTML('Total Fat',n(row.macro_total_fat_actual),n(row.macro_total_fat_goal),'g',false,1),
    fillBarHTML('Total Carbohydrates',n(row.macro_total_carbs_actual),n(row.macro_total_carbs_goal),'g',false,1),
    fillBarHTML('Protein',n(row.macro_protein_actual),n(row.macro_protein_goal),'g',false,1),
  ].join('');

  destroyChart('macroDonut');
  const macV=[n(row.macro_total_fat_actual)||0,n(row.macro_total_carbs_actual)||0,n(row.macro_protein_actual)||0];
  const macL=['Fat','Carbs','Protein'],macC=['#e87a3a','#4a94e8','#1fd67a'],macT=macV.reduce((a,b)=>a+b,0);
  $('macro-legend').innerHTML=macL.map((l,i)=>`<div class="legend-item"><div class="legend-dot" style="background:${macC[i]}"></div>${l}: ${fmt(macV[i],1)}g${macT>0?' ('+Math.round(macV[i]/macT*100)+'%)':''}</div>`).join('');
  charts.macroDonut=new Chart($('macro-donut'),{type:'doughnut',data:{labels:macL,datasets:[{data:macT>0?macV:[1,1,1],backgroundColor:macC,borderWidth:0,hoverOffset:4}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%',plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>macT>0?` ${ctx.label}: ${fmt(ctx.raw,1)}g (${Math.round(ctx.raw/macT*100)}%)`:'No data'}}}}});

  const micros=[
    {name:'Sodium',a:n(row.micro_sodium_actual),g:n(row.micro_sodium_goal),unit:'mg',inv:true},
    {name:'Potassium',a:n(row.micro_potassium_actual),g:n(row.micro_potassium_goal),unit:'mg'},
    {name:'Dietary Fiber',a:n(row.micro_dietary_fiber_actual),g:n(row.micro_dietary_fiber_goal),unit:'g',d:1},
    {name:'Sugars',a:n(row.micro_sugars_actual),g:n(row.micro_sugars_goal),unit:'g',inv:true,d:1},
    {name:'Vitamin A',a:n(row.micro_vitamin_a_mcg_rae_actual),g:n(row.micro_vitamin_a_mcg_rae_goal),unit:'mcg'},
    {name:'Vitamin C',a:n(row.micro_vitamin_c_mg_actual),g:n(row.micro_vitamin_c_mg_goal),unit:'mg'},
    {name:'Vitamin D',a:n(row.micro_vitamin_d_mcg_actual),g:n(row.micro_vitamin_d_mcg_goal),unit:'mcg',d:1},
    {name:'Calcium',a:n(row.micro_calcium_mg_actual),g:n(row.micro_calcium_mg_goal),unit:'mg'},
    {name:'Iron',a:n(row.micro_iron_mg_actual),g:n(row.micro_iron_mg_goal),unit:'mg',d:1},
  ];
  $('micro-bars').innerHTML=micros.map(m=>fillBarHTML(m.name,m.a,m.g,m.unit,m.inv||false,m.d||0)).join('');

  const cv=row.cv_fitness_trajectory||'—';
  $('cv-trajectory').textContent=cv; $('cv-trajectory').style.color=cv.includes('IMPROV')?'var(--green)':cv.includes('DECLIN')?'var(--red)':'var(--yellow)';
  $('cv-hrv').textContent=row.cv_30day_avg_hrv?fmt(row.cv_30day_avg_hrv,1)+' ms':'—';
  $('cv-rhr').textContent=row.cv_30day_avg_rhr?fmt(row.cv_30day_avg_rhr,1)+' bpm':'—';
  const ht=n(row.cv_hrv_trend_vs_prior30_pct),rt=n(row.cv_rhr_trend_vs_prior30_pct);
  $('cv-hrv-trend').innerHTML=ht!=null?`<span class="${ht>=0?'trend-up':'trend-down'}">${ht>=0?'▲':'▼'} ${Math.abs(ht)}% vs prior 30d</span>`:'—';
  $('cv-rhr-trend').innerHTML=rt!=null?`<span class="${rt<=0?'trend-up':'trend-down'}">${rt<=0?'▲':'▼'} ${Math.abs(rt)}% vs prior 30d</span>`:'—';

  $('cal-per-strain').textContent=row.eb_cal_per_strain_point?fmt(row.eb_cal_per_strain_point):'—';
  $('eb7-avg').textContent=row.eb_7day_avg_calories?fmt(row.eb_7day_avg_calories)+' kcal':'—';
  $('eb-maint').textContent=row.eb_maintenance_target_kcal?fmt(row.eb_maintenance_target_kcal)+' kcal':'—';
  const va=n(row.eb_today_vs_7day_avg_kcal);
  $('eb-vs-avg').textContent=va!=null?(va>0?'+':'')+fmt(va)+' kcal':'—'; $('eb-vs-avg').style.color=va!=null?(va>=0?'var(--green)':'var(--red)'):'';
  $('eb-status').textContent=row.eb_fueling_status||'—';
  $('eb-status').style.color=row.eb_fueling_status==='ON TARGET'?'var(--green)':row.eb_fueling_status==='UNDER-FUELED'?'var(--orange)':'var(--red)';

  buildTrends();
}

// ── TREND & MINI CHARTS ────────────────────────────────────────
function buildTrends() {
  const w30=allRows.slice(dateIndex,dateIndex+30).reverse();
  const labels=w30.map(r=>(r.date||'').slice(5));
  const get=f=>w30.map(r=>n(r[f]));

  destroyChart('tRec');
  charts.tRec=new Chart($('trend-recovery'),{type:'line',data:{labels,datasets:[{data:get('recovery_score'),borderColor:'#1fd67a',backgroundColor:'transparent',borderWidth:1.5,pointRadius:2,tension:0.3,spanGaps:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx},y:{...by,min:0,max:100}}}});

  destroyChart('tHRV');
  charts.tHRV=new Chart($('trend-hrv'),{type:'line',data:{labels,datasets:[{data:get('hrv_rmssd_ms'),borderColor:'#9470e8',backgroundColor:'transparent',borderWidth:1.5,pointRadius:2,tension:0.3,spanGaps:true},{data:get('cv_30day_avg_hrv'),borderColor:'#9470e840',backgroundColor:'transparent',borderWidth:1,borderDash:[4,4],pointRadius:0,tension:0,spanGaps:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx},y:{...by}}}});

  destroyChart('tSleep');
  charts.tSleep=new Chart($('trend-sleep'),{type:'line',data:{labels,datasets:[{data:get('sleep_performance_pct'),borderColor:'#4a94e8',backgroundColor:'transparent',borderWidth:1.5,pointRadius:2,tension:0.3,spanGaps:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx},y:{...by,min:0,max:100}}}});

  destroyChart('tCal');
  charts.tCal=new Chart($('trend-calories'),{type:'line',data:{labels,datasets:[{label:'In',data:get('calories_actual'),borderColor:'#1fd67a',backgroundColor:'transparent',borderWidth:1.5,pointRadius:2,tension:0.3,spanGaps:true},{label:'Burned',data:get('total_calories_kcal'),borderColor:'#e87a3a',backgroundColor:'transparent',borderWidth:1.5,pointRadius:2,tension:0.3,spanGaps:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,position:'bottom',labels:{boxWidth:8,font:{size:9},color:'#7a8694',padding:6}},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx},y:{...by}}}});

  destroyChart('tStrain');
  charts.tStrain=new Chart($('trend-strain'),{type:'bar',data:{labels,datasets:[{data:get('day_strain'),backgroundColor:w30.map(r=>{const s=n(r.day_strain);return s>=14?'#e84d4d99':s>=8?'#e87a3a99':'#4a94e899';}),borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx,grid:{display:false}},y:{...by,min:0,max:21}}}});

  destroyChart('hrvMini');
  charts.hrvMini=new Chart($('hrv-chart'),{type:'line',data:{labels,datasets:[{data:get('hrv_rmssd_ms'),borderColor:'#9470e8',backgroundColor:'#9470e812',borderWidth:1.5,pointRadius:0,tension:0.4,fill:true,spanGaps:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx,ticks:{maxTicksLimit:4}},y:{...by}}}});

  destroyChart('ebMini');
  const eb14=allRows.slice(dateIndex,dateIndex+14).reverse();
  const ebL=eb14.map(r=>(r.date||'').slice(5));
  charts.ebMini=new Chart($('eb-chart'),{type:'bar',data:{labels:ebL,datasets:[{label:'In',data:eb14.map(r=>n(r.calories_actual)),backgroundColor:'#1fd67a66',borderWidth:0},{label:'Burned',data:eb14.map(r=>n(r.total_calories_kcal)),backgroundColor:'#e87a3a66',borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,position:'bottom',labels:{boxWidth:8,font:{size:9},color:'#7a8694',padding:6}},tooltip:{mode:'index',intersect:false}},scales:{x:{...bx,grid:{display:false}},y:{...by}}}});
}

// ── DATE NAV ───────────────────────────────────────────────────
function updateDate() {
  const row=allRows[dateIndex]; if(!row) return;
  $('current-date').textContent=row.date||'—';
  $('prev-day').disabled=dateIndex>=allRows.length-1;
  $('next-day').disabled=dateIndex<=0;
  renderDay(row);
}
$('prev-day').addEventListener('click',()=>{if(dateIndex<allRows.length-1){dateIndex++;updateDate();}});
$('next-day').addEventListener('click',()=>{if(dateIndex>0){dateIndex--;updateDate();}});

// ── CALENDAR ───────────────────────────────────────────────────
function openCalendar() {
  const row=allRows[dateIndex];
  if(row&&row.date){const d=new Date(row.date+'T00:00:00');calViewYear=d.getFullYear();calViewMonth=d.getMonth();}
  renderCalendar(); $('cal-dropdown').classList.add('open'); calOpen=true;
}
function closeCalendar() { $('cal-dropdown').classList.remove('open'); calOpen=false; }
function renderCalendar() {
  const mN=['January','February','March','April','May','June','July','August','September','October','November','December'];
  $('cal-month-label').textContent=mN[calViewMonth]+' '+calViewYear;
  const dateset=new Set(allRows.map(r=>r.date));
  const sel=allRows[dateIndex]?allRows[dateIndex].date:'';
  const today=new Date().toISOString().slice(0,10);
  const firstDay=new Date(calViewYear,calViewMonth,1).getDay();
  const daysInMonth=new Date(calViewYear,calViewMonth+1,0).getDate();
  const grid=$('cal-grid'); grid.innerHTML='';
  ['Su','Mo','Tu','We','Th','Fr','Sa'].forEach(d=>{const el=document.createElement('div');el.className='cal-day-label';el.textContent=d;grid.appendChild(el);});
  for(let i=0;i<firstDay;i++){const el=document.createElement('div');el.className='cal-day empty';grid.appendChild(el);}
  for(let day=1;day<=daysInMonth;day++){
    const ds=calViewYear+'-'+String(calViewMonth+1).padStart(2,'0')+'-'+String(day).padStart(2,'0');
    const el=document.createElement('div'); el.textContent=day;
    const hasData=dateset.has(ds),isSel=ds===sel,isToday=ds===today;
    let cls='cal-day';
    if(isSel) cls+=' selected'; else if(hasData) cls+=' has-data'; else cls+=' no-data';
    if(isToday&&!isSel) cls+=' today';
    el.className=cls;
    if(hasData){el.addEventListener('click',()=>{const idx=allRows.findIndex(r=>r.date===ds);if(idx!==-1){dateIndex=idx;updateDate();closeCalendar();}});}
    grid.appendChild(el);
  }
}
$('current-date').addEventListener('click',e=>{e.stopPropagation();calOpen?closeCalendar():openCalendar();});
$('cal-prev-month').addEventListener('click',e=>{e.stopPropagation();calViewMonth--;if(calViewMonth<0){calViewMonth=11;calViewYear--;}renderCalendar();});
$('cal-next-month').addEventListener('click',e=>{e.stopPropagation();calViewMonth++;if(calViewMonth>11){calViewMonth=0;calViewYear++;}renderCalendar();});
document.addEventListener('click',e=>{if(calOpen&&!$('cal-dropdown').contains(e.target))closeCalendar();});
$('cal-dropdown').addEventListener('click',e=>e.stopPropagation());

// ── LOAD CSV ───────────────────────────────────────────────────
function showError(msg){$('loading').style.display='none';$('error-msg').style.display='flex';if(msg)$('error-detail').textContent=msg;}
Papa.parse(CSV_PATH,{
  download:true,header:true,skipEmptyLines:true,
  complete(results){
    if(!results.data||results.data.length===0){showError('CSV file is empty or could not be parsed.');return;}
    const seen=new Set();
    allRows=results.data.filter(r=>{const d=r.date;if(!d||seen.has(d))return false;seen.add(d);return true;});
    allRows.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
    $('loading').style.display='none'; $('app').style.display='block';
    dateIndex=0; updateDate();
  },
  error(err){showError('Failed to load Health_Tracker_Master.csv: '+err.message);}
});
