import{AlertTriangle,Check,ShieldCheck}from'lucide-react';
import{checkLegality}from'./scenario';
import type{Scenario}from'./scenario';

export default function Tier3Workspace({scenario,go}:{scenario:Scenario;go:(r:'crew')=>void}){
 const{cases,availableFor,overrideAssign,reassign,reopen}=scenario;
 const escalated=cases.filter(c=>c.status==='escalated');
 return <>
  <header className="page-head"><div><span>TIER 3 · HUMAN-ASSISTED RECOVERY</span><h1>Supervisor decision queue</h1><p>Cases with no legal automated option. A supervisor may assign a legal crew, or accept a documented override for the residual risk.</p></div><div className="page-actions"><span className="badge purple">{escalated.length} in queue</span></div></header>
  {escalated.length===0
   ?<section className="empty"><ShieldCheck/><h2>Human review queue is clear</h2><p>Cases escalate here from Crew Recovery when automation cannot resolve them. Nothing currently requires supervisor intervention.</p><button className="primary" onClick={()=>go('crew')}>Go to Crew Recovery</button></section>
   :escalated.map(c=>{
    const ranked=availableFor(c).filter(cr=>cr.qualifications.includes(c.requiredQual)).map(cr=>({crew:cr,...checkLegality(cr,c)})).sort((a,b)=>Number(b.legal)-Number(a.legal)||(a.crew.base===c.origin?-1:1));
    return <section className="card" key={c.flight}>
     <header className="rowbetween"><div><span className="badge purple">TIER 3</span> <strong>{c.flight} · {c.origin} → {c.destination}</strong></div><span className="badge danger">{c.aircraft} · needs {c.requiredQual}</span></header>
     <p className="muted">{c.incumbentName} ({c.incumbentId}) is illegal on {c.flight}. No standby {c.requiredQual} crew clears every legality check at {c.origin} — supervisor decision required. {c.passengers} passengers exposed.</p>
     {ranked.length===0&&<p className="muted">No {c.requiredQual}-rated crew in the standby pool — options are a deadhead positioning (not modelled) or cancellation.</p>}
     <div className="t3-options">{ranked.map(({crew,legal,qualified,positioned,rested,violations},i)=><article className={`t3opt ${legal?'ok':''}`} key={crew.id}><header><span className="badge">RANK {i+1}</span><strong>{crew.name} · {crew.id}</strong>{legal?<span className="badge success">LEGAL</span>:<span className="badge warning">RESIDUAL RISK</span>}</header><p className="muted small">{crew.rank} · base {crew.base} · {crew.qualifications.join('/')} · rest {crew.rest_hours}h · seniority {crew.seniority}</p><div className="verdict"><span className={`chk ${qualified?'ok':'bad'}`}>Qualified</span><span className={`chk ${positioned?'ok':'bad'}`}>At origin</span><span className={`chk ${rested?'ok':'bad'}`}>Rested</span></div>{!legal&&<p className="muted small">Residual risk: {violations.join(' · ')}</p>}<div className="page-actions">{legal?<button className="primary" onClick={()=>reassign(c.flight,crew)}><Check/> Assign {crew.id}</button>:<button className="primary" onClick={()=>overrideAssign(c.flight,crew)}><AlertTriangle/> Accept override</button>}</div></article>)}</div>
     <div className="page-actions"><button onClick={()=>reopen(c.flight)}>Return to Crew Recovery</button></div>
    </section>;
   })}
 </>;
}
