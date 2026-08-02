import{useEffect,useState}from'react';
import{AlertTriangle,Check,RefreshCw,UserCheck}from'lucide-react';
import{api}from'./api';
import type{CrewRosterEntry,Flight,ReassignmentPreview,Recovery}from'./types';

const MIN_REST=10;

export default function CrewWorkspace({recovery,onSolve,busy}:{recovery:Recovery|null;onSolve:()=>void;busy:boolean}){
 const[roster,setRoster]=useState<CrewRosterEntry[]|null>(null),[error,setError]=useState(''),[sel,setSel]=useState<CrewRosterEntry|null>(null),[flight,setFlight]=useState<Flight|null>(null),[previews,setPreviews]=useState<Record<string,ReassignmentPreview>>({}),[checking,setChecking]=useState(false);
 const spares=(items:CrewRosterEntry[])=>items.filter(c=>!c.assigned_flight);
 const select=(c:CrewRosterEntry,items:CrewRosterEntry[])=>{
  setSel(c);setPreviews({});setFlight(null);
  if(!c.assigned_flight)return;
  api.flight(c.assigned_flight).then(setFlight).catch(()=>{});
  setChecking(true);
  Promise.all(spares(items).map(cd=>api.reassignmentPreview(c.assigned_flight!,cd.id).then(p=>[cd.id,p] as const).catch(()=>null)))
   .then(rs=>{const m:Record<string,ReassignmentPreview>={};rs.forEach(x=>{if(x)m[x[0]]=x[1]});setPreviews(m)})
   .finally(()=>setChecking(false));
 };
 const load=()=>{setError('');api.crew().then(r=>{setRoster(r.items);const first=r.items.find(c=>c.status==='illegal');if(first)select(first,r.items)}).catch(e=>setError(e.message))};
 useEffect(load,[]);
 if(error)return <section className="empty"><AlertTriangle/><h2>Crew roster unavailable</h2><p>{error}</p><button onClick={load}><RefreshCw/> Retry</button></section>;
 if(!roster)return <section className="empty" role="status" aria-live="polite"><RefreshCw className="spin"/><h2>Loading crew roster</h2></section>;
 const cases=roster.filter(c=>c.status==='illegal'),spare=spares(roster),legalCount=Object.values(previews).filter(p=>p.legal).length;
 return <>
  <header className="page-head"><div><span>CREW RECOVERY</span><h1>Reassign crew to clear illegal pairings</h1><p>Pick a replacement from the roster — each option is checked live against the DGCA-oriented legality engine.</p></div><div className="page-actions"><span className="badge danger">{cases.length} illegal</span><button onClick={load}><RefreshCw/> Refresh roster</button></div></header>
  <div className="crew3">
   <aside className="card"><h2>Cases needing action</h2>{cases.map(c=><button key={c.id} className={`caserow ${sel?.id===c.id?'active':''}`} onClick={()=>select(c,roster)}><span className="badge danger">ILLEGAL</span><div><strong>{c.assigned_flight} · {c.name}</strong><small>{c.id} · {c.qualifications.join('/')} · duty {c.duty_remaining}</small></div></button>)}{cases.length===0&&<p className="muted">No illegal pairings in this scenario.</p>}</aside>
   <section className="card"><h2>Current pairing</h2>{sel?<div className="pairing"><span className="badge danger">ILLEGAL</span><h3>{sel.assigned_flight}{flight?` · ${flight.origin} → ${flight.destination}`:''}</h3><p className="muted">{flight?`${flight.aircraft.type} · ${flight.aircraft.registration} · Gate ${flight.gate}`:'Loading flight…'}</p><dl className="pairing-dl"><dt>Crew</dt><dd>{sel.name} · {sel.id}</dd><dt>Rank</dt><dd>{sel.rank}</dd><dt>Qualified</dt><dd>{sel.qualifications.join(', ')}</dd><dt>Duty remaining</dt><dd>{sel.duty_remaining}</dd><dt>Rest</dt><dd className={sel.rest_hours<MIN_REST?'bad-text':''}>{sel.rest_hours}h (min {MIN_REST}h)</dd></dl>{sel.rest_hours<MIN_REST&&<p className="muted">Below the minimum rest period — this pairing is illegal until the crew is replaced.</p>}</div>:<p className="muted">Select a case.</p>}</section>
   <aside className="card"><header className="rowbetween"><h2>Replacement crew</h2>{checking?<span className="badge">checking…</span>:<span className="badge success">{legalCount} legal</span>}</header>{spare.map(cd=>{const p=previews[cd.id];const legal=p?.legal;return <div key={cd.id} className={`crewopt ${p?(legal?'ok':'bad'):''}`}><div className="crewopt-head"><strong>{cd.name}</strong><span className="muted small">{cd.id} · {cd.rank} · base {cd.base} · {cd.qualifications.join('/')} · rest {cd.rest_hours}h · {cd.status}</span></div>{p?<><div className="verdict">{legal?<span className="badge success"><Check/> LEGAL</span>:<span className="badge danger"><AlertTriangle/> ILLEGAL</span>}<span className={`chk ${p.checks.qualified?'ok':'bad'}`}>Qualified</span><span className={`chk ${p.checks.positioned_at_origin?'ok':'bad'}`}>At origin</span><span className={`chk ${p.checks.rest_ok?'ok':'bad'}`}>Rested</span></div>{!legal&&<p className="muted small">{p.rule_violations.map(v=>v.message).join(' · ')}</p>}{legal&&<button className="primary wide" disabled={busy} onClick={onSolve}><UserCheck/> Assign &amp; build recovery plan</button>}</>:<span className="muted small">Awaiting check…</span>}</div>})}</aside>
  </div>
  {recovery&&<div className="scenario-strip"><span className="dot" aria-hidden="true"/><strong>Recovery plan generated</strong><span>Compare candidates on Decisions — each is validated by the legality engine before it can be approved.</span></div>}
 </>;
}
