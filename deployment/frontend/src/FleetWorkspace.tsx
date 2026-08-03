import{useEffect,useState}from'react';
import{AlertTriangle,Plane,RefreshCw,Wrench}from'lucide-react';
import{api}from'./api';
import type{FleetAircraft}from'./types';

const tone=(s:string):'danger'|'warning'|'success'=>{const x=(s||'').toLowerCase();if(x.includes('block')||x.includes('maint')||x.includes('aog'))return'danger';if(x.includes('inbound'))return'warning';return'success'};

export default function FleetWorkspace({deployed=false,onOpenFlight}:{deployed?:boolean;onOpenFlight?:(id:string)=>void}){
 const[fleet,setFleet]=useState<FleetAircraft[]|null>(null),[error,setError]=useState('');
 const load=()=>{setError('');api.aircraft().then(r=>setFleet(r.items)).catch(e=>setError(e.message))};
 useEffect(load,[]);
 if(error)return <section className="empty"><AlertTriangle/><h2>Fleet unavailable</h2><p>{error}</p><button onClick={load}><RefreshCw/> Retry</button></section>;
 if(!fleet)return <section className="empty" role="status" aria-live="polite"><RefreshCw className="spin"/><h2>Loading fleet</h2></section>;
 const projected=fleet.map(a=>deployed&&a.status==='blocked'?{...a,status:'ready',gate:a.gate,next_available:'Released · recovered rotation'}:a);
 const blocked=projected.filter(a=>tone(a.status)==='danger').length,available=projected.filter(a=>a.status==='available'||a.status==='ready').length;
 return <>
  <header className="page-head"><div><span>AIRCRAFT · FLEET</span><h1>{deployed?'Recovered fleet status':'Fleet status'}</h1><p>{deployed?'Acknowledged aircraft projection after recovery deployment. Maintenance restrictions remain authoritative.':'Availability across the disrupted network — blocked tails, inbound aircraft and ready spares.'}</p></div><div className="page-actions">{blocked>0&&<span className="badge danger">{blocked} blocked</span>}<span className="badge success">{available} available</span><button onClick={load}><RefreshCw/> Refresh</button></div></header>
  {deployed&&<div className="banner-ok"><Plane/> <span>Recovery deployed — LVP-blocked tails released to their acknowledged rotations. Maintenance aircraft remain unavailable.</span></div>}
  <div className="fleet-grid">{projected.map(a=><article key={a.registration} className={`fleet-card ${tone(a.status)}`}><header><span className="reg"><Plane/> {a.registration}</span><span className={`badge ${tone(a.status)}`}>{a.status.toUpperCase()}</span></header><div className="fleet-type">{a.type}</div><dl><dt>Location</dt><dd>{a.location} · {a.gate}</dd><dt>Assignment</dt><dd>{a.assigned_flight?<button className="linklike" onClick={()=>a.assigned_flight&&onOpenFlight?.(a.assigned_flight)}>{a.assigned_flight}</button>:'Unassigned spare'}</dd><dt>Availability</dt><dd>{a.next_available}</dd></dl>{tone(a.status)==='danger'&&a.status!=='blocked'&&<p className="muted small"><Wrench/> Not dispatchable</p>}</article>)}</div>
 </>;
}
