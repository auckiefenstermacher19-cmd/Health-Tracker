/* ============================================================
   dashboard.js — Health Tracker · v5 "Cinematic" (full parity)
   Bento/WHOOP presentation + motion over the complete v4 engine.
   ============================================================ */

const CSV_BASE = 'Health_Tracker_Master.csv';
let allRows = [], dateIndex = 0, charts = {}, firstRender = true;
let calOpen = false, calViewYear = new Date().getFullYear(), calViewMonth = new Date().getMonth();
const reduceMotion = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

const $  = id => document.getElementById(id);
const n  = (v,d=0) => { const x=parseFloat(v); return isNaN(x)?null:parseFloat(x.toFixed(d)); };
const fmt = (v,d=0,fb='—') => { const x=n(v,d); return x===null?fb:x.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d}); };
const pct = (v,d=0) => { const x=n(v,d); return x===null?'—':x+'%'; };
const clamp = (v,lo,hi) => Math.min(hi,Math.max(lo,v));
function fmtHHMM(h){ if(h==null||isNaN(h))return '—'; const t=Math.round(Math.abs(h)*60),H=Math.floor(t/60),M=t%60; if(H===0)return M+'m'; if(M===0)return H+'h'; return H+'h '+M+'m'; }
function recoveryColor(s){ return s>=67?'#00e69a':s>=33?'#ffcb47':'#ff4d63'; }
function fillColor(r,inv=false){ if(inv)return r>1?'#ff4d63':r>0.8?'#ffcb47':'#00e69a'; return r>=1?'#00e69a':r>=0.5?'#ffcb47':'#ff4d63'; }
function rowHasWhoop(r){ return !!((r.recovery_score&&r.recovery_score.trim())||(r.resting_heart_rate&&r.resting_heart_rate.trim())); }
function newestWhoopDate(){ const r=allRows.find(rowHasWhoop); return r?r.date:null; }
function daysOld(d){ const t=new Date().toISOString().slice(0,10); return Math.round((new Date(t+'T00:00:00')-new Date(d+'T00:00:00'))/86400000); }

const BADGE={ 'PEAK':'#00e69a','OPTIMAL':'#00e69a','READY':'#4fa3ff','MODERATE':'#ffcb47','REST':'#ff4d63',
  'UNDER-FUELED':'#ff7a3c','ON TARGET':'#00e69a','OVER-FUELED':'#ff4d63','WORSENING':'#ff4d63','IMPROVING':'#00e69a',
  'STABLE':'#4fa3ff','OK':'#00e69a','MONITOR':'#ffcb47','HIGH':'#ff4d63','ADAPTING':'#00e69a','MAINTAINING':'#4fa3ff',
  'OVERREACHING':'#ff4d63','DECLINING':'#ff4d63','SLIGHT DECLINE':'#ffcb47','SLIGHT IMPROVEMENT':'#00e69a' };
function badgeColor(sig){ return BADGE[sig]||'#8b95a8'; }
function chip(text){ if(!text) return ''; const c=badgeColor(text); return `<span class="chip" style="color:${c};border-color:${c}44;background:${c}18">${text}</span>`; }
function setGauge(id,value,max,color){ const el=$(id); if(!el)return; const c=parseFloat(el.getAttribute('stroke-dasharray')); el.style.stroke=color;
  const off=c*(1-clamp(value/max,0,1)); if(reduceMotion) el.style.strokeDashoffset=off; else requestAnimationFrame(()=>{ el.style.strokeDashoffset=off; }); }
function fillBarHTML(name,actual,goal,unit='',inv=false,d=0){
  if(actual==null||goal==null||goal===0) return `<div class="fb"><div class="fb-h"><span>${name}</span><span class="fb-n">No data</span></div><div class="bar"><i style="width:0"></i></div></div>`;
  const ratio=actual/goal, disp=clamp(ratio,0,1)*100, color=fillColor(ratio,inv), pctTxt=Math.round(ratio*100)+'%';
  const over=ratio>1?` <span style="color:${inv?'#ff4d63':'#00e69a'}">+${fmt(actual-goal,d)}${unit}</span>`:'';
  return `<div class="fb"><div class="fb-h"><span>${name}</span><span class="fb-n"><b>${fmt(actual,d)}</b>/${fmt(goal,d)}${unit} · ${pctTxt}${over}</span></div><div class="bar"><i data-w="${disp}" style="width:0;background:${color}"></i></div></div>`;
}

/* ── KEY METRICS ────────────────────────────────────────────── */
function keyMetricDesc(label,row){
  switch(label){
    case 'Recovery':{ const rs=n(row.recovery_score); if(rs==null)return 'No recovery data for this date.';
      if(rs>=67)return `<b>${rs}/100</b> — Well recovered. Good day to push hard in training.`;
      if(rs>=33)return `<b>${rs}/100</b> — Moderate recovery. Train at controlled intensity.`;
      return `<b>${rs}/100</b> — Low recovery. Rest or light movement only today.`; }
    case 'Readiness':{ const d={'PEAK':'Nervous system primed. This is your window to train hard or attempt a PR.','OPTIMAL':'Strong readiness — conditions are favorable for quality training.','READY':'Ready for normal training. Stick to your planned session.','MODERATE':'Mixed signals. Train at moderate intensity today.','REST':'Body signaling need for recovery. Avoid high-intensity training.'};
      return d[row.readiness_signal||'']||'Composite of HRV, resting HR, and recent strain vs recovery.'; }
    case 'Fueling':{ const fs=row.eb_fueling_status||''; if(fs==='UNDER-FUELED')return 'You burned more than you ate. Under-fueling impairs muscle repair and next-day recovery.';
      if(fs==='ON TARGET')return 'Intake matched your burn. Your body has the fuel it needs to recover and adapt.';
      if(fs==='OVER-FUELED')return 'Ate more than you burned — caloric surplus. Good for muscle building, less for fat loss.';
      return 'Relationship between calories eaten and calories burned today.'; }
    case 'Sleep Debt':{ const dt=row.sleep_debt_trend||'',d7=n(row.sleep_debt_7day_rolling_hrs);
      if(dt==='WORSENING')return `<b>${fmt(d7,1)} hrs</b> owed and rising. Suppresses HRV and recovery. Prioritize 8–9 hrs tonight.`;
      if(dt==='IMPROVING')return `<b>${fmt(d7,1)} hrs</b> owed but trending down. Keep prioritizing sleep.`;
      return `<b>${fmt(d7,1)} hrs</b> of sleep owed over the last 7 days. Must be repaid to restore full recovery.`; }
    case 'CV Fitness':{ const cv=row.cv_fitness_trajectory||''; if(cv==='DECLINING')return 'HRV falling, RHR rising. Aerobic base weakening. Zone 2 cardio 3–4x/week is the fix.';
      if(cv==='SLIGHT DECLINE')return 'Early cardiovascular softening. Consistent aerobic work will reverse this.';
      if(cv.includes('IMPROV'))return 'HRV rising, RHR falling — your aerobic base is strengthening. Keep going.';
      return '30-day HRV and resting HR trends — the most reliable long-term health indicators.'; }
    default:return '';
  }
}
function renderKeyMetrics(row){
  const recov=n(row.recovery_score);
  const m=[
    {l:'Recovery',b:recov!=null?chip(String(recov)):chip('No Data')},
    {l:'Readiness',b:chip(row.readiness_signal||'No Data')},
    {l:'Fueling',b:chip(row.eb_fueling_status||'No Data')},
    {l:'Sleep Debt',b:chip(row.sleep_debt_trend||'No Data')},
    {l:'CV Fitness',b:chip(row.cv_fitness_trajectory||'No Data')},
  ];
  $('key-metrics-grid').innerHTML=m.map(x=>`<div class="km"><div class="km-top"><span class="km-l">${x.l}</span>${x.b}</div><div class="km-d">${keyMetricDesc(x.l,row)}</div></div>`).join('');
}

/* ── COACHING (verbatim v4) ─────────────────────────────────── */
function buildCoaching(row){
  const recovery=n(row.recovery_score), signal=row.readiness_signal||'';
  const sleepDebt=n(row.sleep_debt_7day_rolling_hrs), debtTrend=row.sleep_debt_trend||'';
  const otRisk=row.sr_overtraining_risk||'', adaptation=row.sr_adaptation_trend||'';
  const fueling=row.eb_fueling_status||'', cvTraj=row.cv_fitness_trajectory||'';
  const calIn=n(row.calories_actual), calBurned=n(row.total_calories_kcal);
  let icon='💡', headline='', detail='', tags=[];
  if(otRisk==='HIGH'||(adaptation==='OVERREACHING'&&recovery!=null&&recovery<33)){
    icon='🚨'; headline='Signs of overtraining detected. Rest is not optional today.';
    detail=`Recovery is ${recovery||'—'} and your strain-to-recovery ratio indicates overreaching. Active recovery only — walking, stretching, or light mobility work.`; tags=['REST DAY','HIGH RISK'];
  } else if(sleepDebt!=null&&sleepDebt>15&&debtTrend==='WORSENING'){
    icon='😴'; headline=`${fmt(sleepDebt,1)} hours of accumulated sleep debt and still rising.`;
    detail='Chronic sleep debt suppresses HRV, elevates cortisol, and impairs muscle recovery. Aim for 8–9 hours tonight. This is your highest-leverage health action right now.'; tags=['SLEEP PRIORITY','RECOVERY FOCUS'];
  } else if(fueling==='UNDER-FUELED'&&calIn!=null&&calBurned!=null){
    const deficit=calBurned-calIn; icon='⚠️';
    headline=`${fmt(deficit)} calories under-fueled vs what you burned today.`;
    detail='Under-fueling while training suppresses recovery and adaptation. Your body cannot repair muscle tissue without adequate fuel. Hit your calorie target — prioritize protein and complex carbs.'; tags=['FUEL UP','NUTRITION ACTION'];
  } else if(signal==='PEAK'||(recovery!=null&&recovery>=80&&adaptation!=='OVERREACHING')){
    icon='⚡'; headline=`Recovery is ${signal||'strong'} — this is your window to push hard.`;
    detail='HRV and resting HR are signaling high readiness. High-intensity work, PR attempts, or long endurance sessions are all supported today. Fuel well before and after.'; tags=['HIGH READINESS','TRAIN HARD'];
    if(sleepDebt!=null&&sleepDebt>10){detail+=` Note: sleep debt is still elevated at ${fmt(sleepDebt,1)} hours — prioritize sleep tonight.`; tags.push('WATCH SLEEP DEBT');}
  } else if(signal==='REST'||(recovery!=null&&recovery<33)){
    icon='🛌'; headline=`Low recovery (${recovery||'—'}). Protect today's energy.`;
    detail='Keep any training aerobic and low-strain. Focus on sleep quality tonight, hydration, and hitting your nutrition targets.'; tags=['LOW READINESS','LIGHT ACTIVITY'];
  } else if(cvTraj==='DECLINING'||cvTraj==='SLIGHT DECLINE'){
    icon='📉'; headline=`Cardiovascular fitness trending ${cvTraj.toLowerCase()}.`;
    detail='Your 30-day HRV and RHR trends indicate your aerobic base is softening. Zone 2 cardio 3–4x per week is the most evidence-backed intervention.'; tags=['CV TREND','AEROBIC WORK'];
  } else {
    icon='✅'; headline=`Moderate readiness (${recovery||'—'}). Controlled intensity today.`;
    detail='Not a peak day but not a rest day. Moderate aerobic work or technique-focused training. Hit nutrition targets and prioritize sleep.'; tags=['MODERATE DAY','CONTROLLED EFFORT'];
  }
  if(adaptation==='ADAPTING') tags.push('ADAPTING');
  if(otRisk==='MONITOR'&&!tags.includes('HIGH RISK')) tags.push('MONITOR LOAD');
  return {icon,headline,detail,tags};
}
const cIc=(c,p)=>`<svg viewBox="0 0 24 24" width="20" height="20" fill="none" style="stroke:${c}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const COACH_ICONS={
  '💡':cIc('#8b95a8','<path d="M9 18h6M10 22h4M12 2a7 7 0 00-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0012 2z"/>'),
  '🚨':cIc('#ff4d63','<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/>'),
  '😴':cIc('#a480ff','<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>'),
  '⚠️':cIc('#ff7a3c','<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>'),
  '⚡':cIc('#00e69a','<path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"/>'),
  '🛌':cIc('#4fa3ff','<path d="M2 16h20M2 16v4M22 16v4M4 16v-4a2 2 0 012-2h12a2 2 0 012 2v4M7 10V8h4v2"/>'),
  '📉':cIc('#ffcb47','<path d="M3 7l6 6 4-4 8 8"/><path d="M21 17v-5m0 5h-5"/>'),
  '✅':cIc('#00e69a','<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>'),
};

/* ── MOTION ─────────────────────────────────────────────────── */
function countUp(el,to,dur,dec){
  if(!el) return;
  if(to==null){ el.textContent='—'; return; }
  const finalTxt=dec?to.toFixed(dec):Math.round(to).toLocaleString();
  if(reduceMotion){ el.textContent=finalTxt; return; }
  let s=null;
  requestAnimationFrame(function step(ts){ if(!s)s=ts; const p=Math.min((ts-s)/dur,1),e=1-Math.pow(1-p,3),val=to*e;
    el.textContent=dec?val.toFixed(dec):Math.round(val).toLocaleString(); if(p<1)requestAnimationFrame(step); });
  setTimeout(()=>{ el.textContent=finalTxt; }, dur+150);
}
function paintBars(sel){ requestAnimationFrame(()=>document.querySelectorAll(sel).forEach(i=>{ if(i.dataset.w!=null) i.style.width=i.dataset.w+'%'; })); }

/* ── CHARTS ─────────────────────────────────────────────────── */
Chart.defaults.color='#4f5a6d'; Chart.defaults.borderColor='#1c2431';
Chart.defaults.font.family="'Inter',system-ui,sans-serif"; Chart.defaults.font.size=11;
if(reduceMotion) Chart.defaults.animation=false;
function destroyChart(k){ if(charts[k]){charts[k].destroy();delete charts[k];} }
const fillGrad=color=>context=>{const c=context.chart,a=c.chartArea;if(!a)return color+'00';const g=c.ctx.createLinearGradient(0,a.top,0,a.bottom);g.addColorStop(0,color+'33');g.addColorStop(1,color+'00');return g;};
const lastDot=data=>{let l=-1;for(let i=0;i<data.length;i++)if(data[i]!=null&&!isNaN(data[i]))l=i;return c=>c.dataIndex===l?4:0;};
const bx={ticks:{maxTicksLimit:6,font:{size:10},color:'#4f5a6d'},grid:{color:'#1c243155'}};
const by={ticks:{font:{size:10},color:'#4f5a6d'},grid:{color:'#1c243155'}};
function lineDS(data,color,fill,label){ return {label,data,borderColor:color,backgroundColor:fill?fillGrad(color):'transparent',fill:!!fill,borderWidth:2,pointRadius:lastDot(data),pointBackgroundColor:color,pointHoverRadius:4,tension:0.35,spanGaps:true}; }

function renderCharts(){
  const w30=allRows.slice(dateIndex,dateIndex+30).reverse();
  const labels=w30.map(r=>(r.date||'').slice(5));
  const get=f=>w30.map(r=>n(r[f]));
  const cur=allRows[dateIndex];
  const noLeg={responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}};
  const botLeg={responsive:true,maintainAspectRatio:false,plugins:{legend:{display:true,position:'bottom',labels:{boxWidth:10,font:{size:10},color:'#7a8694',padding:8}},tooltip:{mode:'index',intersect:false}}};

  const recData=get('recovery_score'), curRec=n(cur.recovery_score);
  $('rec-chart-now').textContent=curRec!=null?curRec:'—'; $('rec-chart-now').style.color=curRec!=null?recoveryColor(curRec):'#8b95a8';
  destroyChart('tRec'); charts.tRec=new Chart($('trend-recovery'),{type:'line',data:{labels,datasets:[Object.assign(lineDS(recData,'#00e69a',true),{borderWidth:2.5})]},options:Object.assign({},noLeg,{scales:{x:{...bx},y:{...by,min:0,max:100}}})});

  const hrvData=get('hrv_rmssd_ms');
  $('hrv-now').textContent=n(cur.hrv_rmssd_ms)!=null?fmt(cur.hrv_rmssd_ms,0):'—';
  $('hrv-avg-sub').textContent=cur.cv_30day_avg_hrv?'30-day avg '+fmt(cur.cv_30day_avg_hrv,0)+' ms':'';
  destroyChart('tHRV'); charts.tHRV=new Chart($('hrv-chart'),{type:'line',data:{labels,datasets:[
    Object.assign(lineDS(hrvData,'#a480ff',true),{tension:0.4}),
    {label:'30d avg',data:get('cv_30day_avg_hrv'),borderColor:'#a480ff55',backgroundColor:'transparent',borderWidth:1.5,borderDash:[5,4],pointRadius:0,tension:0,spanGaps:true}
  ]},options:Object.assign({},noLeg,{scales:{x:{...bx,ticks:{maxTicksLimit:4}},y:{...by}}})});

  destroyChart('tSleep'); charts.tSleep=new Chart($('trend-sleep'),{type:'line',data:{labels,datasets:[lineDS(get('sleep_performance_pct'),'#4fa3ff',true)]},options:Object.assign({},noLeg,{scales:{x:{...bx},y:{...by,min:0,max:100}}})});

  destroyChart('tCal'); charts.tCal=new Chart($('trend-calories'),{type:'line',data:{labels,datasets:[lineDS(get('calories_actual'),'#00e69a',false,'Calories In'),lineDS(get('total_calories_kcal'),'#ff7a3c',false,'Calories Burned')]},options:Object.assign({},botLeg,{scales:{x:{...bx},y:{...by}}})});

  destroyChart('tStrain'); charts.tStrain=new Chart($('trend-strain'),{type:'bar',data:{labels,datasets:[{data:get('day_strain'),backgroundColor:w30.map(r=>{const s=n(r.day_strain);return s>=14?'#ff4d63cc':s>=8?'#ff7a3ccc':'#4fa3ffcc';}),borderWidth:0}]},options:Object.assign({},noLeg,{scales:{x:{...bx,grid:{display:false}},y:{...by,min:0,max:21}}})});

  // Energy balance 14d
  const eb14=allRows.slice(dateIndex,dateIndex+14).reverse(), ebL=eb14.map(r=>(r.date||'').slice(5));
  destroyChart('ebMini'); charts.ebMini=new Chart($('eb-chart'),{type:'bar',data:{labels:ebL,datasets:[
    {label:'In',data:eb14.map(r=>n(r.calories_actual)),backgroundColor:'#00e69a77',borderWidth:0},
    {label:'Burned',data:eb14.map(r=>n(r.total_calories_kcal)),backgroundColor:'#ff7a3c77',borderWidth:0}
  ]},options:Object.assign({},botLeg,{scales:{x:{...bx,grid:{display:false}},y:{...by}}})});

  // Meal donut
  const mV=[n(cur.cal_by_meal_breakfast_actual)||0,n(cur.cal_by_meal_lunch_actual)||0,n(cur.cal_by_meal_dinner_actual)||0,n(cur.cal_by_meal_snack_actual)||0];
  const mL=['Breakfast','Lunch','Dinner','Snack'],mC=['#4fa3ff','#ff7a3c','#2fd7d7','#a480ff'],mT=mV.reduce((a,b)=>a+b,0);
  $('meal-legend').innerHTML=mL.map((l,i)=>`<span><i class="ld" style="background:${mC[i]}"></i>${l} ${fmt(mV[i])}</span>`).join('');
  destroyChart('mealDonut'); charts.mealDonut=new Chart($('meal-donut'),{type:'doughnut',data:{labels:mL,datasets:[{data:mT>0?mV:[1,0,0,0],backgroundColor:mC,borderWidth:0,hoverOffset:5}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>mT>0?` ${c.label}: ${fmt(c.raw)} kcal`:'No data'}}}}});

  // Macro donut
  const macV=[n(cur.macro_total_fat_actual)||0,n(cur.macro_total_carbs_actual)||0,n(cur.macro_protein_actual)||0];
  const macL=['Fat','Carbs','Protein'],macC=['#ff7a3c','#4fa3ff','#00e69a'],macT=macV.reduce((a,b)=>a+b,0);
  $('macro-legend').innerHTML=macL.map((l,i)=>`<span><i class="ld" style="background:${macC[i]}"></i>${l} ${fmt(macV[i],0)}g</span>`).join('');
  destroyChart('macroDonut'); charts.macroDonut=new Chart($('macro-donut'),{type:'doughnut',data:{labels:macL,datasets:[{data:macT>0?macV:[1,1,1],backgroundColor:macC,borderWidth:0,hoverOffset:5}]},options:{responsive:true,maintainAspectRatio:false,cutout:'70%',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>macT>0?` ${c.label}: ${fmt(c.raw,1)}g`:'No data'}}}}});
}

/* ── RENDER DAY ─────────────────────────────────────────────── */
function renderDay(row){
  if(!row) return;

  // Hero recovery ring
  const rec=n(row.recovery_score), recColor=rec!=null?recoveryColor(rec):'#8b95a8';
  const ring=$('recRing');
  if(ring){ const C=540, off=rec!=null?C*(1-clamp(rec/100,0,1)):C; ring.style.stroke=recColor; if(reduceMotion)ring.style.strokeDashoffset=off; else requestAnimationFrame(()=>{ring.style.strokeDashoffset=off;}); }
  $('recNum').style.color=recColor; countUp($('recNum'),rec,1400);
  $('recRingWrap').style.filter=rec!=null?`drop-shadow(0 0 26px ${recColor}30)`:'none';
  $('rec-verdict').textContent = rec==null?'No WHOOP data for this day — nutrition below is current.':(rec>=67?'Well recovered. Green light to push hard today.':rec>=33?'Moderate recovery. Train at controlled intensity.':'Low recovery. Rest or light movement only today.');
  $('hrv-val').textContent=row.hrv_rmssd_ms?fmt(row.hrv_rmssd_ms,1)+' ms':'—';
  $('rhr-val').textContent=row.resting_heart_rate?fmt(row.resting_heart_rate)+' bpm':'—';
  $('spo2-val').textContent=row.spo2_pct?pct(row.spo2_pct):'—';
  $('temp-val').textContent=row.skin_temp_celsius?fmt(row.skin_temp_celsius,1)+'°':'—';

  // Strain tile + detail
  const strain=n(row.day_strain);
  countUp($('strainNum'),strain,1200,1);
  const sb=$('strainBar'); if(strain!=null){ sb.style.background=strain>=14?'#ff4d63':strain>=8?'#ff7a3c':'#4fa3ff'; sb.dataset.w=clamp(strain/21,0,1)*100; sb.style.width='0'; } else sb.style.width='0%';
  $('strain-sub').textContent=(row.workout_count||'0')+' workouts · '+(row.workout_total_duration_min?fmtHHMM(n(row.workout_total_duration_min)/60):'—');
  $('strain-max').textContent=row.day_max_heart_rate?fmt(row.day_max_heart_rate)+' max':'';
  $('workout-count').textContent=row.workout_count||'0';
  $('workout-dur').textContent=row.workout_total_duration_min?fmt(row.workout_total_duration_min)+' min':'—';
  $('avg-hr').textContent=row.day_avg_heart_rate?fmt(row.day_avg_heart_rate)+' bpm':'—';
  $('max-hr').textContent=row.day_max_heart_rate?fmt(row.day_max_heart_rate)+' bpm':'—';

  // Sleep tile + detail
  const sp=n(row.sleep_performance_pct);
  $('sleepNum').style.color=sp!=null?fillColor(sp/100):'#8b95a8'; countUp($('sleepNum'),sp,1200);
  const lH=n(row.light_sleep_hrs,4),swsH=n(row.slow_wave_sleep_hrs,4),remH=n(row.rem_sleep_hrs,4),awMin=n(row.time_awake_min),awH=awMin!=null?awMin/60:null,slT=(lH||0)+(swsH||0)+(remH||0);
  $('sleep-sub').textContent=(slT>0?fmtHHMM(slT):'—')+' slept · '+(row.sleep_needed_total_hrs?fmtHHMM(n(row.sleep_needed_total_hrs,4)):'—')+' need';
  const d7=n(row.sleep_debt_7day_rolling_hrs), sdChip=$('sleep-debt-chip'); if(d7!=null){sdChip.textContent='Debt '+fmt(d7,0)+'h';sdChip.style.display='';}else sdChip.style.display='none';
  $('sleep-total').textContent=slT>0?fmtHHMM(slT):'—';
  $('sleep-needed').textContent=row.sleep_needed_total_hrs?fmtHHMM(n(row.sleep_needed_total_hrs,4)):'—';
  const sC={Light:'#4fa3ff',SWS:'#2fd7d7',REM:'#a480ff',Awake:'#232c3a'};
  const sS=[{l:'Light',v:lH},{l:'SWS',v:swsH},{l:'REM',v:remH},{l:'Awake',v:awH}], sBase=slT+(awH||0)||1;
  $('sleep-stack').innerHTML=sS.map(s=>`<i data-w="${((s.v||0)/sBase*100).toFixed(1)}" style="width:0;background:${sC[s.l]}"></i>`).join('');
  $('sleep-legend').innerHTML=sS.filter(s=>s.v!=null&&s.v>0).map(s=>`<span><i class="ld" style="background:${sC[s.l]}"></i>${s.l==='SWS'?'Deep':s.l} ${fmtHHMM(s.v)}</span>`).join('');
  $('sleep-perf').innerHTML=sp!=null?`<span style="color:${fillColor(sp/100)}">${pct(sp)}</span>`:'—';
  $('sleep-eff').textContent=row.sleep_efficiency_pct?pct(row.sleep_efficiency_pct):'—';
  $('sleep-cons').textContent=row.sleep_consistency_pct?pct(row.sleep_consistency_pct):'—';
  $('sleep-cycles').textContent=row.sleep_cycles||'—';

  // Sleep debt panel
  const dL=n(row.sleep_debt_last_night_hrs), repay=n(row.sleep_debt_days_to_repayment), dt=row.sleep_debt_trend||'—';
  if(d7!=null){$('sleep-debt-7d').textContent=fmt(d7,1);$('sleep-debt-7d').style.color=d7>15?'#ff4d63':d7>7?'#ffcb47':'#00e69a';}else $('sleep-debt-7d').textContent='—';
  $('sleep-debt-last').textContent=dL!=null?fmt(dL,1)+'h':'—';
  $('debt-trend').textContent=dt; $('debt-trend').style.color=dt==='IMPROVING'?'#00e69a':dt==='WORSENING'?'#ff4d63':'#8b95a8';
  $('debt-repay').textContent=repay!=null?repay+' nights':'—';
  let ex=''; if(d7!=null&&repay!=null){ ex=`Carrying <b>${fmt(d7,1)} hours</b> of debt. `; ex+=dt==='WORSENING'?'It is <b>increasing</b> — sleeping less than needed. ':dt==='IMPROVING'?'It is <b>decreasing</b> — recent sleep beat your need. ':'Holding <b>steady</b>. '; ex+=`At +1 hr/night, ~<b>${repay} nights</b> to repay. Aim for ${fmt((n(row.sleep_needed_total_hrs)||8)+1,1)} hrs tonight.`; }
  else if(d7!=null) ex=`Carrying <b>${fmt(d7,1)} hours</b> of accumulated sleep debt. Sleep more than you need each night to repay it.`;
  else ex='Sleep debt data not available for this date.';
  $('debt-explain-text').innerHTML=ex;

  // Readiness
  const rd=n(row.readiness_composite_score); $('readyNum').style.color=rd!=null?recoveryColor(rd):'#8b95a8'; countUp($('readyNum'),rd,1200);
  $('ready-chip').textContent=row.readiness_signal||'—';
  const hb=n(row.readiness_hrv_vs_baseline_pct),rb=n(row.readiness_rhr_vs_baseline_pct);
  const rp=[]; if(hb!=null)rp.push('HRV '+(hb>0?'+':'')+fmt(hb,0)+'%'); if(rb!=null)rp.push('RHR '+(rb>0?'+':'')+fmt(rb,0)+'%');
  $('ready-sub').textContent=rp.length?rp.join(' · ')+' vs base':'vs baseline';
  $('readiness-signal').textContent=row.readiness_signal||'—';
  $('hrv-baseline').textContent=hb!=null?(hb>0?'+':'')+fmt(hb,1)+'%':'—'; $('hrv-baseline').style.color=hb!=null?(hb>=0?'#00e69a':'#ff4d63'):'';
  $('rhr-baseline').textContent=rb!=null?(rb>0?'+':'')+fmt(rb,1)+'%':'—'; $('rhr-baseline').style.color=rb!=null?(rb<=0?'#00e69a':'#ff4d63'):'';
  $('readiness-3d').textContent=row.readiness_3day_avg_strain?fmt(row.readiness_3day_avg_strain,1):'—';

  // Overtraining
  const ot=row.sr_overtraining_risk||'';
  $('ot-risk-val').textContent=ot||'—'; $('ot-risk-val').style.color=ot==='OK'?'#00e69a':ot==='MONITOR'?'#ffcb47':ot==='HIGH'?'#ff4d63':'#eef2f8';
  $('ot-adaptation').innerHTML=chip(row.sr_adaptation_trend||'—');
  const rm={OK:0,MONITOR:1,HIGH:2}, rl=rm[ot]??-1;
  $('risk-ok').className='rseg'+(rl>=0?' on-ok':''); $('risk-mon').className='rseg'+(rl>=1?' on-mon':''); $('risk-hi').className='rseg'+(rl>=2?' on-hi':'');
  $('sr-strain').textContent=row.sr_7day_avg_strain?fmt(row.sr_7day_avg_strain,1):'—';
  $('sr-recovery').textContent=row.sr_7day_avg_recovery?fmt(row.sr_7day_avg_recovery,1):'—';
  $('sr-ratio').textContent=row.sr_ratio?fmt(row.sr_ratio,3):'—';
  $('sr-adaptation-cell').textContent=row.sr_adaptation_trend||'—';

  // Energy net tile
  const calIn=n(row.calories_actual),calBurned=n(row.total_calories_kcal),calGoal=n(row.calories_goal),bmr=n(row.bmr_estimated_kcal),eb7Avg=n(row.eb_7day_avg_calories);
  $('fuel-chip').textContent=row.eb_fueling_status||'—';
  if(calIn!=null&&calBurned!=null){ const net=calIn-calBurned,surplus=net>0,col=surplus?'#00e69a':'#ff4d63';
    $('net-sign').textContent=surplus?'+':'−'; $('net-sign').style.color=col; countUp($('netNum'),Math.abs(net),1300); $('netNum').style.color=col;
    $('fuel-sub').textContent=fmt(calIn)+' in · '+fmt(calBurned)+' burned';
  } else { $('net-sign').textContent=''; $('netNum').textContent='—'; $('netNum').style.color='#8b95a8'; $('fuel-sub').textContent='No meal data logged'; }

  // Calorie hero panel
  $('cal-in-num').textContent=calIn!=null?fmt(calIn):'—'; $('cal-in-num').style.color=calIn!=null&&calGoal&&calIn>=calGoal?'#00e69a':'#eef2f8';
  $('cal-in-goal').textContent=calGoal?'Goal '+fmt(calGoal)+' kcal':'Goal —';
  $('cal-burned-num').textContent=calBurned!=null?fmt(calBurned):'—';
  $('cal-burned-sub').textContent=bmr?'BMR '+fmt(bmr)+' kcal':'BMR —';
  if(calIn!=null&&calBurned!=null){ const net=calIn-calBurned,surplus=net>0,col=surplus?'#00e69a':'#ff7a3c';
    $('net-result').textContent=(surplus?'+':'')+fmt(net); $('net-result').style.cssText=`color:${col};border-color:${col}44;background:${col}18`;
    $('net-words').textContent=surplus?'SURPLUS':'DEFICIT'; $('net-words').style.color=col;
  } else { $('net-result').textContent='—'; $('net-words').textContent='No meal data'; $('net-words').style.color='#4f5a6d'; }
  if(calIn!=null&&calGoal){ const r=calIn/calGoal; const b=$('cal-in-bar'); b.dataset.w=clamp(r,0,1)*100; b.style.width='0'; b.style.background=fillColor(r); $('cal-bar-nums').innerHTML=`<b>${fmt(calIn)}</b> / ${fmt(calGoal)} kcal`; } else $('cal-bar-nums').textContent='No data';
  if(calBurned!=null&&eb7Avg){ const r=calBurned/eb7Avg; const b=$('eb7-bar'); b.dataset.w=clamp(r,0,1)*100; b.style.width='0'; $('eb7-nums').innerHTML=`<b>${fmt(calBurned)}</b> / ${fmt(eb7Avg)} 7d avg`; } else $('eb7-nums').textContent='No data';

  // Fueling detail
  const fs=row.eb_fueling_status||'—';
  $('eb-status').textContent=fs; $('eb-status').style.color=fs==='ON TARGET'?'#00e69a':fs==='UNDER-FUELED'?'#ff7a3c':fs==='OVER-FUELED'?'#ff4d63':'#eef2f8';
  $('eb-status-desc').textContent=fs==='UNDER-FUELED'?'Burned more than consumed — body drew on reserves':fs==='ON TARGET'?'Intake matched expenditure — well balanced':fs==='OVER-FUELED'?'Consumed more than burned — caloric surplus':'—';
  $('eb7-avg').textContent=eb7Avg?fmt(eb7Avg)+' kcal':'—';
  $('eb-maint').textContent=row.eb_maintenance_target_kcal?fmt(row.eb_maintenance_target_kcal)+' kcal':'—';
  const va=n(row.eb_today_vs_7day_avg_kcal); $('eb-vs-avg').textContent=va!=null?(va>0?'+':'')+fmt(va)+' kcal':'—'; $('eb-vs-avg').style.color=va!=null?(va>=0?'#00e69a':'#ff4d63'):'';
  $('cal-per-strain').textContent=row.eb_cal_per_strain_point?fmt(row.eb_cal_per_strain_point)+' kcal':'—';

  // Macros bars
  $('macro-bars').innerHTML=[
    fillBarHTML('Protein',n(row.macro_protein_actual),n(row.macro_protein_goal),'g',false,0),
    fillBarHTML('Carbohydrates',n(row.macro_total_carbs_actual),n(row.macro_total_carbs_goal),'g',false,0),
    fillBarHTML('Fat',n(row.macro_total_fat_actual),n(row.macro_total_fat_goal),'g',false,0),
  ].join('');

  // Micros
  const micros=[
    ['Sodium',n(row.micro_sodium_actual),n(row.micro_sodium_goal),'mg',true,0],
    ['Potassium',n(row.micro_potassium_actual),n(row.micro_potassium_goal),'mg',false,0],
    ['Fiber',n(row.micro_dietary_fiber_actual),n(row.micro_dietary_fiber_goal),'g',false,1],
    ['Sugars',n(row.micro_sugars_actual),n(row.micro_sugars_goal),'g',true,1],
    ['Vitamin A',n(row.micro_vitamin_a_mcg_rae_actual),n(row.micro_vitamin_a_mcg_rae_goal),'mcg',false,0],
    ['Vitamin C',n(row.micro_vitamin_c_mg_actual),n(row.micro_vitamin_c_mg_goal),'mg',false,0],
    ['Vitamin D',n(row.micro_vitamin_d_mcg_actual),n(row.micro_vitamin_d_mcg_goal),'mcg',false,1],
    ['Calcium',n(row.micro_calcium_mg_actual),n(row.micro_calcium_mg_goal),'mg',false,0],
    ['Iron',n(row.micro_iron_mg_actual),n(row.micro_iron_mg_goal),'mg',false,1],
  ];
  $('micro-bars').innerHTML=micros.map(m=>fillBarHTML(m[0],m[1],m[2],m[3],m[4],m[5])).join('');

  // CV fitness
  const cv=row.cv_fitness_trajectory||'—';
  $('cv-trajectory').textContent=cv; $('cv-trajectory').style.color=cv.includes('IMPROV')?'#00e69a':cv.includes('DECLIN')?'#ff4d63':'#ffcb47';
  const cvD={'IMPROVING':'HRV trending up, RHR trending down — cardiovascular fitness strengthening.','SLIGHT IMPROVEMENT':'Early positive signs — HRV and RHR moving the right way.','STABLE':'Holding steady — consistent training maintaining your base.','SLIGHT DECLINE':'Early warning — HRV softening slightly. More aerobic work reverses this.','DECLINING':'HRV falling, RHR rising. Aerobic base weakening. Prioritize Zone 2 cardio 3–4x/week.'};
  $('cv-traj-desc').textContent=cvD[cv]||'';
  $('cv-hrv').textContent=row.cv_30day_avg_hrv?fmt(row.cv_30day_avg_hrv,1)+' ms':'—';
  $('cv-rhr').textContent=row.cv_30day_avg_rhr?fmt(row.cv_30day_avg_rhr,1)+' bpm':'—';
  const ht=n(row.cv_hrv_trend_vs_prior30_pct),rt=n(row.cv_rhr_trend_vs_prior30_pct);
  $('cv-hrv-trend').innerHTML=ht!=null?`<span style="color:${ht>=0?'#00e69a':'#ff4d63'}">${ht>=0?'▲':'▼'} ${Math.abs(ht)}% vs prior 30d</span>`:'—';
  $('cv-rhr-trend').innerHTML=rt!=null?`<span style="color:${rt<=0?'#00e69a':'#ff4d63'}">${rt>=0?'▲':'▼'} ${Math.abs(rt)}% vs prior 30d</span>`:'—';

  // Coaching + key metrics
  const c=buildCoaching(row);
  $('coaching-icon').innerHTML=COACH_ICONS[c.icon]||COACH_ICONS['💡'];
  $('coaching-headline').textContent=c.headline; $('coaching-detail').textContent=c.detail;
  $('coaching-tags').innerHTML=c.tags.map(t=>`<span class="tag">${t}</span>`).join('');
  renderKeyMetrics(row);

  const note=$('no-whoop-note'); if(note){ if(rowHasWhoop(row))note.style.display='none'; else {note.style.display='';note.textContent='No WHOOP data for this day. Nutrition metrics below are current.';} }

  renderCharts();
  paintBars('#sleep-stack > i, .bar > i');

  if(firstRender){ document.querySelectorAll('.tile').forEach((t,i)=>{ if(!reduceMotion)t.style.animationDelay=(0.04+i*0.04)+'s'; t.classList.add('reveal'); }); firstRender=false; }
}

/* ── DATE NAV ───────────────────────────────────────────────── */
function updateDate(){ const row=allRows[dateIndex]; if(!row)return; $('current-date').textContent=(row.date||'—').replace(/-/g,'·'); $('prev-day').disabled=dateIndex>=allRows.length-1; $('next-day').disabled=dateIndex<=0; renderDay(row); }
$('prev-day').addEventListener('click',()=>{ if(dateIndex<allRows.length-1){dateIndex++;updateDate();} });
$('next-day').addEventListener('click',()=>{ if(dateIndex>0){dateIndex--;updateDate();} });

/* ── CALENDAR (verbatim v4) ─────────────────────────────────── */
function openCalendar(){ const row=allRows[dateIndex]; if(row&&row.date){const d=new Date(row.date+'T00:00:00');calViewYear=d.getFullYear();calViewMonth=d.getMonth();} renderCalendar(); $('cal-dropdown').classList.add('open'); calOpen=true; }
function closeCalendar(){ $('cal-dropdown').classList.remove('open'); calOpen=false; }
function renderCalendar(){
  const mN=['January','February','March','April','May','June','July','August','September','October','November','December'];
  $('cal-month-label').textContent=mN[calViewMonth]+' '+calViewYear;
  const dateset=new Set(allRows.map(r=>r.date)), sel=allRows[dateIndex]?allRows[dateIndex].date:'', today=new Date().toISOString().slice(0,10);
  const firstDay=new Date(calViewYear,calViewMonth,1).getDay(), daysInMonth=new Date(calViewYear,calViewMonth+1,0).getDate();
  const grid=$('cal-grid'); grid.innerHTML='';
  ['Su','Mo','Tu','We','Th','Fr','Sa'].forEach(d=>{const el=document.createElement('div');el.className='cal-day-label';el.textContent=d;grid.appendChild(el);});
  for(let i=0;i<firstDay;i++){const el=document.createElement('div');el.className='cal-day empty';grid.appendChild(el);}
  for(let day=1;day<=daysInMonth;day++){
    const ds=calViewYear+'-'+String(calViewMonth+1).padStart(2,'0')+'-'+String(day).padStart(2,'0');
    const el=document.createElement('div'); el.textContent=day;
    const hasData=dateset.has(ds),isSel=ds===sel,isToday=ds===today;
    let cls='cal-day'; if(isSel)cls+=' selected'; else if(hasData)cls+=' has-data'; else cls+=' no-data'; if(isToday&&!isSel)cls+=' today'; el.className=cls;
    if(hasData) el.addEventListener('click',()=>{ const idx=allRows.findIndex(r=>r.date===ds); if(idx!==-1){dateIndex=idx;updateDate();closeCalendar();} });
    grid.appendChild(el);
  }
}
$('current-date').addEventListener('click',e=>{e.stopPropagation();calOpen?closeCalendar():openCalendar();});
$('cal-prev-month').addEventListener('click',e=>{e.stopPropagation();calViewMonth--;if(calViewMonth<0){calViewMonth=11;calViewYear--;}renderCalendar();});
$('cal-next-month').addEventListener('click',e=>{e.stopPropagation();calViewMonth++;if(calViewMonth>11){calViewMonth=0;calViewYear++;}renderCalendar();});
document.addEventListener('click',e=>{ if(calOpen&&!$('cal-dropdown').contains(e.target)&&e.target!==$('current-date')) closeCalendar(); });
$('cal-dropdown').addEventListener('click',e=>e.stopPropagation());

/* ── FRESHNESS (verbatim v4) ────────────────────────────────── */
function updateFreshness(){
  const el=$('data-freshness'), newest=allRows.length?allRows[0].date:null;
  if(el){ if(!newest)el.textContent=''; else { const a=daysOld(newest); if(a>2){el.className='data-freshness stale';el.textContent='Data may be stale — newest '+newest+' ('+a+'d old)';}else{el.className='data-freshness';el.textContent='Data as of '+newest;} } }
  const wel=$('whoop-freshness'); if(wel){ const w=newestWhoopDate(); if(!w)wel.textContent=''; else { const a=daysOld(w); if(a>2){wel.className='whoop-freshness stale';wel.innerHTML='<i></i>WHOOP '+w+' ('+a+'d ago)';}else{wel.className='whoop-freshness';wel.innerHTML='<i></i>WHOOP synced '+w;} } }
}

/* ── LOAD (verbatim v4) ─────────────────────────────────────── */
function showError(msg){ $('loading').style.display='none'; $('error-msg').style.display='flex'; if(msg)$('error-detail').textContent=msg; }
function loadData(){
  Papa.parse(CSV_BASE+'?t='+Date.now(),{ download:true,header:true,skipEmptyLines:true,
    complete(results){
      if(!results.data||results.data.length===0){ showError('CSV file is empty or could not be parsed.'); return; }
      const prevDate=allRows[dateIndex]?allRows[dateIndex].date:null, seen=new Set();
      allRows=results.data.filter(r=>{const d=r.date;if(!d||seen.has(d))return false;seen.add(d);return true;});
      allRows.sort((a,b)=>(b.date||'').localeCompare(a.date||''));
      $('loading').style.display='none'; $('app').style.display='block';
      const keep=prevDate?allRows.findIndex(r=>r.date===prevDate):-1; dateIndex=keep>=0?keep:0;
      updateDate(); updateFreshness();
    },
    error(err){ showError('Failed to load Health_Tracker_Master.csv: '+err.message); }
  });
}
loadData();
document.addEventListener('visibilitychange',()=>{ if(document.visibilityState==='visible') loadData(); });
setInterval(loadData, 15*60*1000);
