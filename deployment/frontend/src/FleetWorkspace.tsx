import{useEffect,useState}from'react';
import{AlertTriangle,Plane,RefreshCw,Wrench}from'lucide-react';
import{api}from'./api';
import type{FleetAircraft}from'./types';

const tone=(s:string):'danger'|'warning'|'success'=>{const x=(s||'').toLowerCase();if(x.includes('block')||x.includes('maint')||x.includes('aog'))return'danger';if(x.includes('inbound'))return'warning';return'success'};

export default function FleetWorkspace({onOpenFlight}:{onOpenFlight?:(id:string)=>void}){
 const[fleet,setFleet]=useState<FleetAircraft[]|null>(null),[error,setError]=useState('');
 const load=()=>{setError('');api.aircraft().then(r=>setFleet(r.items)).catch(e=>setError(e.message))};
 useEffect(load,[]);
 if(error)return <section className="empty"><AlertTriangle/><h2>Fleet unavailable</h2><p>{error}</p><button onClick={load}><RefreshCw/> Retry</button></section>;
 if(!fleet)return <section className="empty" role="status" aria-live="polite"><RefreshCw className="spin"/><h2>Loading fleet</h2></section>;
 const blocked=fleet.filter(a=>tone(a.status)==='danger').length,available=fleet.filter(a=>a.status==='available'||a.status==='ready').length;
 return <>
  <header className="page-head"><div><span>AIRCRAFT · FLEET</span><h1>Fleet status</h1><p>Availability across the disrupted network — blocked tails, inbound aircraft and ready spares.</p></div><div className="page-actions"><span className="badge danger">{blocked} blocked</span><span className="badge success">{available} available</span><button onClick={load}><RefreshCw/> Refresh</button></div></header>
  <div className="fleet-grid">{fleet.map(a=><article key={a.registration} className={`fleet-card ${tone(a.status)}`}><header><span className="reg"><Plane/> {a.registration}</span><span className={`badge ${tone(a.status)}`}>{a.status.toUpperCase()}</span></header><div className="fleet-type">{a.type}</div><dl><dt>Location</dt><dd>{a.location} · {a.gate}</dd><dt>Assignment</dt><dd>{a.assigned_flight?<button className="linklike" onClick={()=>a.assigned_flight&&onOpenFlight?.(a.assigned_flight)}>{a.assigned_flight}</button>:'Unassigned spare'}</dd><dt>Availability</dt><dd>{a.next_available}</dd></dl>{tone(a.status)==='danger'&&a.status!=='blocked'&&<p className="muted small"><Wrench/> Not dispatchable</p>}</article>)}</div>
 </>;
}
