import{useEffect,useState}from'react';
import{AlertTriangle,Check,RefreshCw,UserCheck,Users}from'lucide-react';
import{checkLegality}from'./scenario';
import type{Scenario}from'./scenario';

export default function CrewWorkspace({scenario,go}:{scenario:Scenario;go:(r:'tier3'|'decisions')=>void}){
 const{loading,error,cases,availableFor,reassign,escalate,reset,stats}=scenario;
 const open=cases.filter(c=>c.status==='open');
 const[selFlight,setSelFlight]=useState<string|null>(null);
 useEffect(()=>{if((!selFlight||!open.find(c=>c.flight===selFlight))&&open.length)setSelFlight(open[0].flight);if(open.length===0)setSelFlight(null);},[cases]);// eslint-disable-line
 if(error)return <section className="empty"><AlertTriangle/><h2>Crew roster unavailable</h2><p>{error}</p><button onClick={reset}><RefreshCw/> Retry</button></section>;
 if(loading)return <section className="empty" role="status" aria-live="polite"><RefreshCw className="spin"/><h2>Loading crew roster</h2></section>;
 const sel=cases.find(c=>c.flight===selFlight)||null;
 const cands=sel?availableFor(sel).map(c=>({crew:c,...checkLegality(c,sel)})).sort((a,b)=>Number(b.legal)-Number(a.legal)||a.crew.rest_hours-b.crew.rest_hours):[];
 const legalCands=cands.filter(c=>c.legal);
 const resolved=cases.filter(c=>c.status==='resolved'),escalated=cases.filter(c=>c.status==='escalated');
 return <>
  <header className="page-head"><div><span>CREW RECOVERY · PRIMARY WORKSPACE</span><h1>Clear illegal crew pairings</h1><p>Reassign a legal replacement, or escalate to human review when none exists. Every option is checked against the DGCA-oriented legality engine.</p></div><div className="page-actions"><button onClick={reset}><RefreshCw/> Reset scenario</button></div></header>
  <div className="progressbar"><div className="progressbar-fill" style={{width:`${Math.round((stats.resolved/(stats.total||1))*100)}%`}}/><span>{stats.resolved} of {stats.total} resolved · {stats.escalated} in human review · {stats.open} open</span></div>
  {stats.open===0&&stats.escalated===0&&stats.total>0&&<div className="banner-ok"><Check/> <span>All crew pairings are legal — recovery plan ready.</span><button className="linklike" onClick={()=>go('decisions')}>View recovery plan →</button></div>}
  <div className="crew3">
   <aside className="card"><h2>Cases <span className="badge danger">{stats.open}</span></h2>
    {open.map(c=><button key={c.flight} className={`caserow ${selFlight===c.flight?'active':''}`} onClick={()=>setSelFlight(c.flight)}><span className="badge danger">ILLEGAL</span><div><strong>{c.flight} · {c.origin}→{c.destination}</strong><small>{c.aircraft} · {c.incumbentName} · rest breach</small></div></button>)}
    {open.length===0&&<p className="muted">No open cases.</p>}
    {resolved.length>0&&<><h2 className="mt">Resolved <span className="badge success">{stats.resolved}</span></h2>{resolved.map(c=><div key={c.flight} className="caserow done"><span className="badge success"><Check/></span><div><strong>{c.flight} · {c.replacementName}</strong><small>{c.resolvedVia==='override'?'Human override':'Reassigned'} · {c.incumbentId} released</small></div></div>)}</>}
    {escalated.length>0&&<><h2 className="mt">Human review <span className="badge purple">{stats.escalated}</span></h2>{escalated.map(c=><button key={c.flight} className="caserow" onClick={()=>go('tier3')}><span className="badge purple">TIER 3</span><div><strong>{c.flight}</strong><small>No legal option — open Tier 3 →</small></div></button>)}</>}
   </aside>
   <section className="card"><h2>Current pairing</h2>{sel?<div className="pairing"><span className="badge danger">ILLEGAL</span><h3>{sel.flight} · {sel.origin} → {sel.destination}</h3><p className="muted">{sel.aircraft} · Gate {sel.gate} · {sel.passengers} passengers</p><dl className="pairing-dl"><dt>Rostered crew</dt><dd>{sel.incumbentName} · {sel.incumbentId}</dd><dt>Type rating</dt><dd>{sel.requiredQual}</dd><dt>Legality</dt><dd className="bad-text">Below minimum rest — pairing illegal</dd></dl><p className="muted">Legal replacements available: <b>{legalCands.length}</b>.{legalCands.length===0&&' No standby crew clears every check for this flight.'}</p>{legalCands.length===0&&<button className="primary wide" onClick={()=>escalate(sel.flight)}><Users/> Escalate to human review (Tier 3)</button>}</div>:<p className="muted">Select a case — or every case is handled.</p>}</section>
   <aside className="card"><header className="rowbetween"><h2>Replacement crew</h2>{sel&&<span className="badge success">{legalCands.length} legal</span>}</header>{!sel?<p className="muted">Nothing to reassign.</p>:cands.map(({crew,legal,qualified,positioned,rested,violations})=><div key={crew.id} className={`crewopt ${legal?'ok':'bad'}`}><div className="crewopt-head"><strong>{crew.name}</strong><span className="muted small">{crew.id} · {crew.rank} · base {crew.base} · {crew.qualifications.join('/')} · rest {crew.rest_hours}h · {crew.status}</span></div><div className="verdict">{legal?<span className="badge success"><Check/> LEGAL</span>:<span className="badge danger"><AlertTriangle/> ILLEGAL</span>}<span className={`chk ${qualified?'ok':'bad'}`}>Qualified</span><span className={`chk ${positioned?'ok':'bad'}`}>At origin</span><span className={`chk ${rested?'ok':'bad'}`}>Rested</span></div>{!legal&&<p className="muted small">{violations.join(' · ')}</p>}{legal&&<button className="primary wide" onClick={()=>reassign(sel.flight,crew)}><UserCheck/> Reassign {crew.id} &amp; clear</button>}</div>)}</aside>
  </div>
 </>;
}
