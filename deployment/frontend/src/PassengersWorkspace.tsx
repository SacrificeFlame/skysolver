import{useMemo}from'react';
import{AlertTriangle,ArrowRight,Check}from'lucide-react';
import type{Flight}from'./types';
import type{Scenario}from'./scenario';

// Synthetic onward-flight options used to reaccommodate misconnecting passengers.
const NEXT_FLIGHT:Record<string,string>={BOM:'AI-665 · 12:40',DEL:'6E-2119 · 12:10',HYD:'UK-846 · 13:05',CCU:'AI-770 · 13:30',BLR:'6E-509 · 12:55',MAA:'AI-539 · 13:20'};

type Row=Flight&{atRisk:number;status:'reaccommodated'|'at_risk'|'protected_pending'|'on_time';resolved:boolean};

export default function PassengersWorkspace({flights,scenario,deployed,go}:{flights:Flight[];scenario:Scenario;deployed:boolean;go:(r:'crew'|'deployment')=>void}){
 const rows=useMemo<Row[]>(()=>flights.map(f=>{
  const resolved=scenario.cases.find(c=>c.flight===f.id)?.status==='resolved';
  const atRisk=f.delay>=60?f.connections:f.delay>=45?Math.round(f.connections*0.4):0;
  const status:Row['status']=deployed&&atRisk>0?'reaccommodated':atRisk===0?'on_time':resolved?'protected_pending':'at_risk';
  return{...f,atRisk,status,resolved};
 }),[flights,scenario.cases,deployed]);
 const total=flights.reduce((s,f)=>s+f.passengers,0);
 const connecting=flights.reduce((s,f)=>s+f.connections,0);
 const atRiskTotal=rows.reduce((s,r)=>s+r.atRisk,0);
 const reaccommodated=deployed?atRiskTotal:0;
 const queue=rows.filter(r=>r.atRisk>0);
 const tone=(s:Row['status'])=>s==='reaccommodated'?'success':s==='at_risk'?'danger':s==='protected_pending'?'warning':'neutral';
 const label=(s:Row['status'])=>s==='reaccommodated'?'REACCOMMODATED':s==='at_risk'?'AT RISK':s==='protected_pending'?'REBOOKING':'ON TIME';
 return <>
  <header className="page-head"><div><span>PASSENGER RECOVERY</span><h1>Passenger impact &amp; reaccommodation</h1><p>Connecting passengers exposed to a missed onward flight, and how the recovery protects them.</p></div><div className="page-actions">{deployed?<span className="badge success"><Check/> {reaccommodated} reaccommodated</span>:atRiskTotal>0?<span className="badge danger">{atRiskTotal} at risk</span>:<span className="badge success">All buffered</span>}</div></header>
  <div className="kpis">{([['Passengers',total.toLocaleString('en-IN'),'across affected flights'],['Connecting',connecting.toLocaleString('en-IN'),'onward journeys'],['Misconnection risk',atRiskTotal,deployed?'now protected':'if departures slip'],['Reaccommodated',deployed?reaccommodated:0,deployed?'rebooked onward':'pending deployment'],['Protection',`${connecting?Math.round(((connecting-atRiskTotal+reaccommodated)/connecting)*100):100}%`,'of connections held']] as [string,any,string][]).map(([k,v,sub])=><div className={`kpi ${k==='Misconnection risk'&&atRiskTotal&&!deployed?'danger':k==='Reaccommodated'&&deployed?'success':''}`} key={k}><span>{k}</span><strong>{v}</strong><small>{sub}</small></div>)}</div>
  {!deployed&&atRiskTotal>0&&<div className="dh-note"><AlertTriangle/><span><b>{atRiskTotal} connecting passengers</b> risk missing their onward flight while departures are delayed. Resolve the crew cases and deploy the recovery to rebook them automatically.</span></div>}
  {deployed&&<div className="banner-ok"><Check/> <span>Recovery deployed — {reaccommodated} connecting passengers reaccommodated onto protected onward flights.</span></div>}
  <section className="card"><header className="rowbetween"><h2>Passenger load by flight</h2><span className="muted small">{flights.length} flights</span></header>
   <div className="table-wrap"><table><thead><tr><th>Flight</th><th>Route</th><th>Passengers</th><th>Connecting</th><th>At risk</th><th>Delay</th><th>Status</th></tr></thead><tbody>{rows.map(r=><tr key={r.id}><td><b>{r.id}</b></td><td>{r.origin} → {r.destination}</td><td>{r.passengers}</td><td>{r.connections}</td><td className={r.atRisk?'bad-text':''}>{r.atRisk||'—'}</td><td>{r.delay}m</td><td><span className={`badge ${tone(r.status)}`}>{label(r.status)}</span></td></tr>)}</tbody></table></div>
  </section>
  <section className="card"><header className="rowbetween"><h2>Reaccommodation queue</h2><span className={`badge ${deployed?'success':queue.length?'warning':'success'}`}>{deployed?'COMPLETE':queue.length?`${queue.length} flights`:'CLEAR'}</span></header>
   {queue.length===0?<p className="muted small">No connecting passengers at risk — every onward journey is within its connection buffer.</p>
   :<div className="pax-grid">{queue.map(r=><div key={r.id} className={`pax-card ${deployed?'':''}`}><div className="pf"><b>{r.id} · {r.destination}</b><span className={`badge ${deployed?'success':'warning'}`}>{deployed?'DONE':'PENDING'}</span></div><p className="muted small" style={{margin:'2px 0 8px'}}>{r.atRisk} passengers connecting at {r.destination}</p><div className="reacc"><ArrowRight/><span>{deployed?'Rebooked to':'Proposed onward'} <b>{NEXT_FLIGHT[r.destination]||'next available service'}</b></span></div></div>)}</div>}
   {!deployed&&queue.length>0&&<div className="page-actions" style={{marginTop:'12px'}}><button onClick={()=>go('crew')}>Resolve crew cases</button><button className="primary" onClick={()=>go('deployment')}>Go to deployment <ArrowRight/></button></div>}
  </section>
 </>;
}
