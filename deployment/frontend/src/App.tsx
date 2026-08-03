import{useEffect,useMemo,useState}from'react';
import{Activity,AlertTriangle,ArrowRight,Bot,Check,CloudLightning,Cpu,Database,Gauge,GitBranch,History,Map,Plane,ShieldCheck,Ticket,Users,Wrench,X}from'lucide-react';
import{api,ApiError}from'./api';
import type{Audit,Disruption,FleetAircraft,Flight,Recovery}from'./types';
import{useScenario}from'./scenario';
import type{Scenario}from'./scenario';
import RouteWorkspace from'./RouteWorkspace';
import SolverWorkspace from'./SolverWorkspace';
import Tier3Workspace from'./Tier3Workspace';
import DataHealthWorkspace from'./DataHealthWorkspace';
import CrewWorkspace from'./CrewWorkspace';
import FleetWorkspace from'./FleetWorkspace';
import AirportView from'./AirportView';
import PassengersWorkspace from'./PassengersWorkspace';
import AgentWorkspace from'./AgentWorkspace';
import{LogoMark}from'./Logo';

type Route='overview'|'agent'|'datahealth'|'disruptions'|'crew'|'flights'|'aircraft'|'routes'|'passengers'|'tiers'|'tier1'|'tier2'|'tier3'|'decisions'|'deployment'|'audit';
const navGroups:[string,[Route,string,any,boolean?][]][]=[
 ['Monitor',[['overview','Overview',Activity],['datahealth','Data Health',Database],['disruptions','Disruptions',CloudLightning]]],
 ['Operate',[['crew','Crew Recovery',Users],['flights','Flights',Plane],['aircraft','Aircraft',Wrench],['passengers','Passengers',Ticket],['routes','Planned Routes',Map]]],
 ['Solve',[['agent','Recovery Agent',Bot],['tiers','Solver Tiers',GitBranch],['tier1','Tier 1 · Legal',Gauge,true],['tier2','Tier 2 · Optimize',Cpu,true],['tier3','Tier 3 · Human',Users,true]]],
 ['Govern',[['decisions','Decisions',ShieldCheck],['deployment','Deployment',ArrowRight],['audit','Audit',History]]],
];
const fallbackDisruption:Disruption={id:'DSP-DEL-0726',severity:'critical',title:'Delhi low-visibility departure restrictions',summary:'Dense fog is cascading crew, aircraft and passenger dependencies across the India network.',source:'IMD / Delhi ATC',confidence:.96,started_at:'2026-07-31T00:28:00Z',deadline:'2026-07-31T02:10:00Z',partitions:['DEL','BOM','BLR','HYD'],affected_flights:['AI421','6E203','UK945','AI807','6E531'],illegal_crews:2,blocked_aircraft:2,passengers:958,status:'active'};
const fallbackFlight:Flight={id:'AI421',origin:'DEL',destination:'BOM',aircraft:{registration:'VT-EXA',type:'A321',status:'blocked'},gate:'T3-42',proposed_gate:'T3-46',crew:{id:'IC-184',status:'illegal',duty_remaining:'-00:38',qualifications:['A321']},passengers:186,connections:42,delay:92,state:'recovery_pending',tier:'tier1',risk:'critical'};
const flightIds=['AI421','6E203','UK945','AI807','6E531'];
// The flight API is the immutable disruption snapshot. Operational workspaces
// overlay the acknowledged post-deployment projection; Audit keeps the before state.
export const operationalDelay=(flight:Flight,deployed:boolean)=>deployed?Math.max(5,Math.round(flight.delay*.2)):flight.delay;

function Badge({children,tone='neutral'}:{children:any;tone?:string}){return <span className={`badge ${tone}`}>{children}</span>}
function PageHead({eyebrow,title,detail,actions}:{eyebrow:string;title:string;detail:string;actions?:any}){return <header className="page-head"><div><span>{eyebrow}</span><h1>{title}</h1><p>{detail}</p></div><div className="page-actions">{actions}</div></header>}
function Table({headers,rows,onRow}:{headers:string[];rows:any[][];onRow?:(row:any[])=>void}){return <div className="table-wrap"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i} className={onRow?'clickable':''} onClick={()=>onRow?.(row)}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>}
function TopBar(){
 const[now,setNow]=useState(()=>new Date());
 const[healthy,setHealthy]=useState<boolean|null>(null);
 useEffect(()=>{
  const clock=setInterval(()=>setNow(new Date()),1000);
  const check=()=>api.health().then(h=>setHealthy(h.status==='live')).catch(()=>setHealthy(false));
  check();const poll=setInterval(check,60000);
  return()=>{clearInterval(clock);clearInterval(poll)};
 },[]);
 return <div className="topbar status-only">
  <div className="tb-right">
   <span className={`sys ${healthy===null?'':healthy?'ok':'bad'}`}><i/>{healthy===null?'Checking…':healthy?'System healthy':'Backend unreachable'}</span>
   <span className="clock tabular">{now.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Kolkata',hour12:false})} IST</span>
   <span className="avatar" title="Operations scheduler">OPS</span>
  </div>
 </div>;
}

function Overview({d,scenario,fleet,flights,setFlight,go,deployed}:{d:Disruption;scenario:Scenario;fleet:FleetAircraft[];flights:Flight[];setFlight:(f:Flight)=>void;go:(r:Route)=>void;deployed:boolean}){
 const s=scenario.stats;const pct=Math.round((s.total?s.resolved/s.total:0)*100);const allDone=s.total>0&&s.open===0&&s.escalated===0;
 const blocked=deployed?0:fleet.filter(a=>a.status==='blocked').length;
 const sorted=[...flights].sort((a,b)=>b.delay-a.delay);
 const started=new Date(d.started_at),deadline=new Date(d.deadline);
 const fmt=(x:Date)=>x.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Kolkata',hour12:false});
 const timeline:[string,string,'done'|'current'|'pending'][]=[
  ['03:15','Dense fog forecast issued','done'],
  [fmt(started),'Fog below CAT III — departures metered','done'],
  [fmt(deadline),'Recovery deadline set','done'],
  ['now',`Crew recovery ${s.resolved}/${s.total}`,allDone?'done':'current'],
  ['','Recovery plan ready',allDone?'current':'pending'],
 ];
 return <>
  <section className="prio-banner">
   <div className="prio-left"><Badge tone={deployed?'success':'danger'}>{deployed?'DEPLOYED · RECOVERED':'PRIORITY 1'}</Badge><h1>{deployed?'Recovery deployed — network stabilized':d.title}</h1><p>{deployed?'Crew, aircraft, gate and passenger actions acknowledged. Operational views now show the recovered projection.':d.summary}</p></div>
   <div className="prio-kpis">
    <div><strong>{flights.length}</strong><span>Flights affected</span><small>{d.partitions.join(' · ')}</small></div>
    <div><strong>{d.passengers.toLocaleString('en-IN')}</strong><span>Passengers</span><small className={deployed||s.paxResolved?'good':''}>{deployed?`${d.passengers.toLocaleString('en-IN')} protected`:s.paxResolved?`↓ ${s.paxResolved.toLocaleString('en-IN')} protected`:'exposure building'}</small></div>
    <div><strong className={deployed||!s.open?'good':'bad'}>{deployed?0:s.open+s.escalated}</strong><span>Illegal crews</span><small>{deployed?'all assignments legal':`${s.resolved} resolved`}</small></div>
    <div><strong className={blocked?'warn':'good'}>{blocked}</strong><span>Aircraft blocked</span><small>{fleet.filter(a=>a.status==='available'||a.status==='ready').length} spares ready</small></div>
   </div>
  </section>
  <div className="guided">
   <aside className="card gcol"><header className="rowbetween"><h2>{deployed?'Recovered flights':'Affected flights'}</h2><span className="muted small">{flights.length} {deployed?'deployed':'by impact'}</span></header>
    {sorted.map(f=>{const imp=deployed?'recovered':f.delay>=60?'high':f.delay>=45?'moderate':'low';const c=scenario.cases.find(x=>x.flight===f.id);const delay=operationalDelay(f,deployed);
     return <button key={f.id} className="fl-row" onClick={()=>{if(c&&c.status!=='resolved')go('crew');else{setFlight(f);go('routes')}}}>
      <span className={`badge ${imp==='recovered'?'success':imp==='high'?'danger':imp==='moderate'?'warning':'neutral'}`}>{imp.toUpperCase()}</span>
      <div><strong>{f.id} <span className="muted">{f.origin} → {f.destination}</span></strong><small>{f.aircraft.type} · Gate {deployed?f.proposed_gate:f.gate} · Pax {f.passengers}{c?` · ${c.status==='resolved'?`crew ${c.replacementId}`:c.status==='escalated'?'Tier 3':'crew action'}`:''}</small></div>
      <span className={`delay-chip ${deployed?'recovered':''}`}>+{delay}m</span>
     </button>;})}
   </aside>
   <section className="card gcol center"><header className="rowbetween"><h2>DEL operational view</h2><span className="muted small">Indira Gandhi Intl · IST</span></header>
    <AirportView flights={flights} cases={scenario.cases} deployed={deployed} onSelect={f=>{setFlight(f);go('routes')}}/>
    <div className="ev-timeline" role="list" aria-label="Event timeline">{timeline.map(([t,label,st],i)=><div key={i} className={`ev ${st}`} role="listitem"><span className="ev-dot"/><small>{t}</small><span>{label}</span></div>)}</div>
   </section>
   <aside className="card gcol reco"><header className="rowbetween"><h2>Recommended recovery</h2><Badge tone="danger">P1</Badge></header>
    <h3 className="reco-h">{allDone?'All pairings legal — plan assembled':`Clear ${s.open+s.escalated} illegal pairings, protect ${d.passengers.toLocaleString('en-IN')} passengers`}</h3>
    <p className="muted small">Reassign from the standby roster; each option is validated by the legality engine. Cases without a legal option escalate to Tier 3.</p>
    <div className="outcome"><span className="o-label">Outcome</span>
     <div className={`o-line ${s.resolved?'ok':''}`}>{s.resolved?<Check/>:<span className="o-dot"/>}<span>{s.resolved}/{s.total} crew pairings legalized</span></div>
     <div className={`o-line ${s.paxResolved?'ok':''}`}>{s.paxResolved?<Check/>:<span className="o-dot"/>}<span>{s.paxResolved.toLocaleString('en-IN')} passengers protected</span></div>
     <div className={`o-line ${s.escalated?'warn':''}`}>{s.escalated?<AlertTriangle/>:<span className="o-dot"/>}<span>{s.escalated} case(s) in supervisor review</span></div>
     <div className={`o-line ${deployed?'ok':'info'}`}>{deployed?<Check/>:<span className="o-dot"/>}<span>{deployed?'Blocked aircraft released to recovered rotations':`${blocked} aircraft awaiting LVP release`}</span></div>
    </div>
    {allDone
     ?<button className="primary wide cta" onClick={()=>go('decisions')}>Review recovery plan</button>
     :<button className="primary wide cta" onClick={()=>go(s.open?'crew':'tier3')}>{s.open?'Work recovery cases':'Open Tier 3 queue'}</button>}
    <div className="reco-progress"><div style={{width:`${deployed?100:pct}%`}}/></div>
    <p className="muted small center-t">{deployed?'100% deployed · acknowledgements complete':`${pct}% recovered · ${s.open} open · ${s.escalated} in review`}</p>
   </aside>
  </div>
 </>;
}

function Disruptions({d,flights,deployed,go}:{d:Disruption;flights:Flight[];deployed:boolean;go:(r:Route)=>void}){
 const totalPax=flights.reduce((s,f)=>s+f.passengers,0),illegal=deployed?0:flights.filter(f=>f.crew.status==='illegal').length,blocked=deployed?0:flights.filter(f=>f.aircraft.status==='blocked').length,totalDelay=flights.reduce((s,f)=>s+operationalDelay(f,deployed),0);
 const statusTone=(s:string)=>s==='illegal'?'danger':s==='legal'?'success':'warning';
 const riskTone=(r:string)=>r==='critical'?'danger':r==='high'?'warning':r==='medium'?'cyan':'success';
 return <>
  <PageHead eyebrow={`DISRUPTION ${d.id}`} title={deployed?'Recovery deployed':d.title} detail={deployed?'Historical disruption context with the acknowledged recovered projection.':d.summary} actions={<button className="primary" onClick={()=>go(deployed?'deployment':'crew')}>{deployed?'View deployment':'Work crew recovery'}</button>}/>
  <div className="kpis">{([['Affected flights',flights.length,'in scenario'],['Illegal crews',illegal,'need action'],['Blocked aircraft',blocked,'on ground'],['Passengers',totalPax.toLocaleString('en-IN'),'exposed'],['Cumulative delay',`${totalDelay}m`,'across flights'],['Partitions',d.partitions.length,d.partitions.join(', ')]] as [string,any,string][]).map(([k,v,sub])=><div className="kpi" key={k}><span>{k}</span><strong>{v}</strong><small>{sub}</small></div>)}</div>
  <div className="fact-strip">{[['Source',d.source],['Confidence',`${Math.round(d.confidence*100)}%`],['Started',new Date(d.started_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})],['Recovery deadline',new Date(d.deadline).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})],['Authority','Scheduler']].map(x=><span key={x[0]}>{x[0]}<b>{x[1]}</b></span>)}</div>
  <section className="card"><header className="rowbetween"><h2>{deployed?'Recovered flights':'Affected flights'}</h2><Badge tone={deployed?'success':'warning'}>{deployed?'DEPLOYED':`${illegal} need crew action`}</Badge></header><Table headers={['Flight','Route','Aircraft','Crew','Crew status','Pax','Delay','Risk']} rows={flights.map(f=>[f.id,`${f.origin} → ${f.destination}`,`${f.aircraft.type} · ${f.aircraft.registration}`,f.crew.id,<span className={`badge ${deployed?'success':statusTone(f.crew.status)}`}>{deployed?'LEGAL':f.crew.status.toUpperCase()}</span>,f.passengers,`${operationalDelay(f,deployed)}m`,<span className={`badge ${deployed?'success':riskTone(f.risk)}`}>{deployed?'RECOVERED':f.risk.toUpperCase()}</span>])} onRow={()=>go(deployed?'deployment':'crew')}/></section>
  <section className="card"><header className="rowbetween"><h2>Passenger connections at risk</h2><Badge tone="warning">{flights.reduce((s,f)=>s+f.connections,0)} connecting</Badge></header>
   <p className="muted small" style={{margin:'0 0 12px'}}>Connecting passengers exposed to a missed onward flight if departures slip. A legal on-time recovery protects them.</p>
   <div className="pax-grid">{flights.map(f=>{const atRisk=!deployed&&f.delay>=60;const pct=Math.min(100,Math.round((f.connections/f.passengers)*100*2.4));return <div className="pax-card" key={f.id}><div className="pf"><b>{f.id}</b><span className={`badge ${atRisk?'danger':'success'}`}>{deployed?'PROTECTED':atRisk?'AT RISK':'BUFFERED'}</span></div><div className={`pax-bar ${atRisk?'risk':''}`}><span style={{width:`${pct}%`}}/></div><div className="pax-meta"><span>{f.connections} connecting</span><span>of {f.passengers} pax</span></div><p className="muted small" style={{margin:'8px 0 0'}}>{deployed?`Recovered at +${operationalDelay(f,true)}m · connections protected`:atRisk?`+${f.delay}m delay threatens ~${f.connections} onward connections`:`${f.delay}m within the connection buffer`}</p></div>})}</div></section>
 </>;
}


// The backend flight record carries the *incumbent* crew and never changes — it
// is the disruption as reported. Recovery decisions live in the scenario, so the
// crew column has to overlay them, and must not claim a flight is legal before
// the plan has actually been deployed.
function crewCell(f:Flight,scenario:Scenario,deployed:boolean){
 const c=scenario.cases.find(x=>x.flight===f.id);
 if(!c||c.status==='open')return{crew:f.crew.id,label:f.crew.status.toUpperCase(),tone:f.crew.status==='illegal'?'danger':f.crew.status==='legal'?'success':'warning'};
 if(c.status==='escalated')return{crew:f.crew.id,label:'HUMAN REVIEW',tone:'warning'};
 const crew=c.replacementId?`${f.crew.id} → ${c.replacementId}`:f.crew.id;
 return deployed
  ?{crew,label:'LEGAL',tone:'success'}
  :{crew,label:'CLEARED · PENDING DEPLOY',tone:'cyan'};
}

export function Flights({flights,scenario,deployed,setFlight,go}:{flights:Flight[];scenario:Scenario;deployed:boolean;setFlight:(f:Flight)=>void;go:(r:Route)=>void}){
 return <><PageHead eyebrow="FLIGHT OPERATIONS" title="Network flights" detail="Every affected flight with its aircraft, crew and movement record. The crew column reflects the current recovery plan; a flight only reads LEGAL once that plan is deployed."/>
  <section className="card"><Table headers={['Flight','Route','Aircraft','Tail','Crew','Crew status','Gate','Pax','Delay']} rows={flights.map(f=>{const s=crewCell(f,scenario,deployed);return[f.id,`${f.origin} → ${f.destination}`,f.aircraft.type,f.aircraft.registration,s.crew,<span className={`badge ${s.tone}`}>{s.label}</span>,deployed?f.proposed_gate:`${f.gate}${f.proposed_gate!==f.gate?` → ${f.proposed_gate}`:''}`,f.passengers,deployed?<span className="badge success">RECOVERED · +{operationalDelay(f,true)}m</span>:`${f.delay}m`]})} onRow={r=>{const f=flights.find(x=>x.id===r[0]);if(f){setFlight(f);go('routes')}}}/></section>
  {flights.length===0&&<section className="empty"><Plane/><h2>Loading flights…</h2></section>}</>;
}

function Decisions({scenario,recovery,run,choose,busy,go}:{scenario:Scenario;recovery:Recovery|null;run:()=>void;choose:(id:string)=>void;busy:boolean;go:(r:Route)=>void}){
 const s=scenario.stats;const resolved=scenario.cases.filter(c=>c.status==='resolved');
 return <>
  <PageHead eyebrow="RECOVERY DECISIONS" title="Recovery plan & candidate comparison" detail="The plan assembled from your crew decisions, plus solver-generated candidates with full provenance." actions={<button className="primary" disabled={busy||s.resolved===0} onClick={run}>{recovery?'Re-generate plan':'Generate recovery plan'}</button>}/>
  {s.escalated>0&&<section className="card action-card"><div><h2><Users/> Human review required</h2><p className="muted">{s.escalated} case{s.escalated===1?' is':'s are'} pending an operator decision after the Agent run. Resolve the Tier 3 queue before finalizing the plan.</p></div><button className="primary" onClick={()=>go('tier3')}>Open human review queue</button></section>}
  <section className="card"><header className="rowbetween"><h2>Plan being assembled</h2><Badge tone={s.open===0&&s.escalated===0&&s.total>0?'success':'warning'}>{s.resolved}/{s.total} CASES RESOLVED</Badge></header>
   {resolved.length===0?<p className="muted">No decisions yet — resolve crew cases in Crew Recovery first, then generate the plan.</p>
   :<div className="plan-lines">{resolved.map(c=><div key={c.flight} className="plan-line"><span className="badge success"><Check/></span><b>{c.flight}</b><span>{c.incumbentId} → <b>{c.replacementId}</b> ({c.replacementName})</span><span className={`badge ${c.resolvedVia==='override'?'warning':'cyan'}`}>{c.resolvedVia==='override'?'SUPERVISOR OVERRIDE':'LEGAL REASSIGNMENT'}</span></div>)}</div>}
   {(s.open>0||s.escalated>0)&&<p className="muted small">{s.open>0?`${s.open} case(s) still open in Crew Recovery. `:''}{s.escalated>0?`${s.escalated} case(s) awaiting Tier 3 supervisor decision. `:''}<button className="linklike" onClick={()=>go(s.open>0?'crew':'tier3')}>Resolve them →</button></p>}
  </section>
  {!recovery?<section className="empty"><ShieldCheck/><h2>No solver candidates yet</h2><p>Generate the recovery plan to produce versioned, comparable candidates from the solver.</p></section>
  :<div className="candidate-grid">{recovery.candidates.map(c=><article className="candidate" key={c.id}><header><Badge tone={c.recommended?'cyan':'neutral'}>{c.tier?.toUpperCase()||'SOLVER'}</Badge><strong>{c.id}</strong></header><h2>{c.name}</h2><div className="score">{Math.round(c.coverage*100)}%<span>coverage</span></div><div className="candidate-metrics"><span>Flights<b>{c.flights_recovered}</b></span><span>Pax<b>{c.passengers_recovered}</b></span><span>Risk<b>{c.risk}</b></span></div><div className="explain"><strong>Evidence</strong><p>{c.changes.join('. ')}</p><small>{c.ruleset_version||'Ruleset unavailable'} · state v{c.state_version||recovery.state_version}</small></div><button className={recovery.selected_candidate_id===c.id?'':'primary'} disabled={busy} onClick={()=>choose(c.id)}>{recovery.selected_candidate_id===c.id?'✓ Selected':'Select plan'}</button></article>)}</div>}
 </>;
}

export function ackClass(status:string){const s=(status||'').toLowerCase();
 // Order matters: 'nack' contains 'ack', so failures and partials are classified before positives.
 if(s.includes('partial'))return'part';
 if(['nack','fail','error','reject'].some(k=>s.includes(k)))return'bad';
 if(['ack','deployed','complete','success','confirmed'].some(k=>s.includes(k)))return'ok';
 return'wait'}
export function Deployment({recovery,approvalReason,setApprovalReason,authorize,deployNow,validate,busy}:{recovery:Recovery|null;approvalReason:string;setApprovalReason:(v:string)=>void;authorize:(reason:string)=>void;deployNow:()=>void;validate?:()=>void;busy:boolean}){
 if(!recovery)return <><PageHead eyebrow="APPROVAL & DEPLOYMENT" title="Authorize & deploy the recovery plan" detail="Three separate authorities: scheduler proposes, duty manager approves, controller deploys."/><section className="empty"><ArrowRight/><h2>No recovery in progress</h2><p>Resolve crew cases and generate a plan on Decisions first, then return here to authorize it.</p></section></>;
 const r=recovery;const approved=(r.approvals?.length||0)>0;const deployed=!!(r.simulated||r.deployed);const acks=r.acknowledgements||[];
 const okC=acks.filter(a=>ackClass(a.status)==='ok').length,failC=acks.length-okC;
 const steps:[string,string,'done'|'current'|'blocked'|'pending'][]=[
  ['Propose & validate','Scheduler',r.validated?'done':(r.selected_candidate_id?'current':'pending')],
  ['Approve','Duty manager',approved?'done':(r.validated?'current':'pending')],
  ['Deploy','Controller',deployed?'done':(approved?'current':'blocked')],
 ];
 return <>
  <PageHead eyebrow="APPROVAL & DEPLOYMENT" title="Authorize & deploy the recovery plan" detail="Separation of duties — a scheduler proposes, a duty manager approves, a controller deploys."/>
  <div className="authority">{steps.map(([label,who,st],i)=><div key={label} className={`auth-step ${st}`}><span className="auth-n">{st==='done'?<Check/>:i+1}</span><div><strong>{label}</strong><small>{who}</small></div></div>)}</div>
  {!r.validated
   ?<section className="card action-card"><div><h2>Validate the plan</h2><p className="muted">Run the DGCA-oriented legality checks on the selected candidate before it can be approved.</p>{!r.selected_candidate_id&&<p className="muted small">Select a candidate on Decisions first.</p>}</div><button className="primary" disabled={busy||!r.selected_candidate_id} onClick={validate}>Run legality validation</button></section>
   :!approved
   ?<section className="card action-card"><div><h2><ShieldCheck/> Duty-manager approval</h2><p className="muted">Approval authorizes the validated plan — this is separate from publication.</p><label className="field"><span>Approval note</span><input value={approvalReason} onChange={e=>setApprovalReason(e.target.value)} placeholder="e.g. Reviewed — legal and operationally sound"/></label></div><button className="primary" disabled={busy||approvalReason.trim().length<3} onClick={()=>authorize(approvalReason.trim())}>Authorize as duty manager</button></section>
   :!deployed
   ?<section className="card action-card"><div><h2><ArrowRight/> Controller deployment</h2><p className="muted">Approved{r.approvals?.[0]?.reason?` — "${r.approvals[0].reason}"`:''}. Execute the deployment: commands are sent to the carrier adapters and acknowledged per resource.</p></div><button className="primary" disabled={busy} onClick={deployNow}>Execute deployment</button></section>
   :<section className="card"><header><h2><ArrowRight/> Deployment result</h2><Badge tone={r.deployment_status==='partial'?'warning':'success'}>{(r.deployment_status||'complete').toUpperCase()}</Badge></header>
     <div className="fact-strip"><span>Acknowledged<b>{okC}</b></span><span>Needs attention<b>{failC}</b></span><span>Commands<b>{acks.length}</b></span><span>Ref<b>{r.deployment_id?.slice(0,14)||'—'}</b></span></div>
     <div className="ack-grid">{acks.map((a,i)=><div key={i} className={`ack ${ackClass(a.status)}`}><span className="res">{a.resource}</span><span className="st">{a.status.replaceAll('_',' ').toUpperCase()}</span>{a.detail&&<span className="muted small">{a.detail}</span>}</div>)}</div>
     {r.deployment_status==='partial'&&<div className="banner-warn"><AlertTriangle/> <span>Partial deployment — {failC} command(s) require retry or compensation. Partial state never auto-completes.</span></div>}
    </section>}
 </>;
}
function AuditPage({items}:{items:Audit[]}){return <><PageHead eyebrow="AUDIT TRAIL" title="Recovery audit trail" detail="Chronological record of every recovery action with actor, correlation and ruleset version."/><section className="card"><Table headers={['Timestamp','Action','Actor','Recovery','Detail','Ruleset']} rows={items.map(a=>[new Date(a.timestamp).toLocaleString(),a.action.replaceAll('_',' '),a.operator,a.recovery_id,a.detail,a.ruleset_version])}/>{!items.length&&<p>No recovery actions recorded yet.</p>}</section></>}

// Truthful, work-preserving messaging for mutation failures. A 409 never discards
// the operator's context: we keep the current recovery selection and refresh the
// authoritative state so the action can be retried against the current version.
export function describeFailure(error:unknown,recovery:Recovery|null,setRecovery:(r:Recovery)=>void):string{
 if(error instanceof ApiError){
  // A hold conflict is not a stale version: retrying cannot fix it, so say what
  // is actually blocked instead of sending the operator round a futile loop.
  if(error.isResourceConflict){const held=error.heldResources;const crew=held.filter(r=>r.startsWith('crew:')).length;
   return `Blocked: ${held.length} resource(s) are reserved by another recovery${crew?` (${crew} crew)`:''}. Re-generate the plan to supersede it.`}
  if(error.isStale){if(recovery)api.recovery(recovery.id).then(setRecovery).catch(()=>{});return `Plan advanced to state v${error.stateVersion??'?'} elsewhere. Your selection is preserved — review the refreshed state and retry.`}
  if(error.isValidation)return `Backend rejected the request: ${error.ruleViolations.length} rule finding(s). No candidate was approved.`;
  if(error.isPermission)return 'Not authorized for this action. Approval and deployment require stepped-up authentication.';
  return error.correlationId?`${error.message} (correlation ${error.correlationId})`:error.message;
 }
 return error instanceof Error?error.message:'Action failed';
}

export default function App(){
 const routeFromHash=()=>((location.hash.slice(2)||'overview') as Route);
 const[route,setRoute]=useState<Route>(routeFromHash),[d,setD]=useState(fallbackDisruption),[flight,setFlight]=useState(fallbackFlight),[flights,setFlights]=useState<Flight[]>([]),[fleet,setFleet]=useState<FleetAircraft[]>([]),[recovery,setRecovery]=useState<Recovery|null>(null),[audit,setAudit]=useState<Audit[]>([]),[busy,setBusy]=useState(false),[notice,setNotice]=useState(''),[approvalReason,setApprovalReason]=useState('');
 const scenario=useScenario();
 useEffect(()=>{const onHash=()=>setRoute(routeFromHash());addEventListener('hashchange',onHash);api.disruptions().then(x=>x.items[0]&&setD(x.items[0])).catch(()=>{});Promise.all(flightIds.map(id=>api.flight(id).catch(()=>null))).then(fs=>{const ok=fs.filter((f):f is Flight=>!!f);setFlights(ok);if(ok[0])setFlight(ok[0])});api.aircraft().then(x=>setFleet(x.items)).catch(()=>{});api.audit().then(x=>setAudit(x.items)).catch(()=>{});return()=>removeEventListener('hashchange',onHash)},[]);
 const go=(next:Route)=>{location.hash=`/${next}`};
 const finishWork=(next:Recovery,message:string)=>{setRecovery(next);setNotice(message);api.audit().then(x=>setAudit(x.items))};
 const work=async(fn:()=>Promise<{recovery:Recovery}>,message:string,onSuccess?:(r:Recovery)=>void)=>{setBusy(true);try{const result=await fn();finishWork(result.recovery,message);onSuccess?.(result.recovery)}catch(error){setNotice(describeFailure(error,recovery,setRecovery))}finally{setBusy(false)}};
 // Refresh and retry a stale mutation once, preserving the operator's selected
 // candidate and approval note instead of forcing a confusing second click.
 const recoveryWork=async(action:(current:Recovery)=>Promise<{recovery:Recovery}>,message:string,onSuccess?:(r:Recovery)=>void)=>{if(!recovery)return;setBusy(true);try{let current=recovery,result;try{result=await action(current)}catch(error){if(!(error instanceof ApiError)||!error.isStale)throw error;current=await api.recovery(recovery.id);setRecovery(current);result=await action(current)}finishWork(result.recovery,message);onSuccess?.(result.recovery)}catch(error){setNotice(describeFailure(error,recovery,setRecovery))}finally{setBusy(false)}};
 const run=()=>work(()=>api.createRecovery(d.id),'Candidate plans generated');
 const choose=(id:string)=>recoveryWork(r=>api.decide(r.id,r.state_version,id),'Candidate selected — continue with legality validation',()=>go('deployment'));
 const validatePlan=()=>recoveryWork(r=>api.validate(r.id,r.state_version,r.selected_candidate_id||undefined),'Legality checks completed');
 // Governance actions elevate to the required demo role for the single privileged
 // call, then return the session to the scheduler so the rest of the app keeps working.
 const asRole=async<T,>(role:string,fn:()=>Promise<T>):Promise<T>=>{await api.login('ops','sky2026',role);try{return await fn()}finally{await api.login('ops','sky2026','scheduler-demo').catch(()=>{})}};
 const authorize=(reason:string)=>recoveryWork(r=>asRole('duty-manager',()=>api.approve(r.id,r.state_version,reason)),'Plan approved by duty manager');
 const deployNow=()=>recoveryWork(r=>asRole('deployment-controller',()=>api.simulateDeployment(r.id,r.state_version)),'Deployment executed — acknowledgements received');
 const page=useMemo(()=>{switch(route){case'overview':return <Overview d={d} scenario={scenario} fleet={fleet} flights={flights} setFlight={setFlight} go={go} deployed={!!(recovery?.simulated||recovery?.deployed)}/>;case'agent':return <AgentWorkspace scenario={scenario} go={go}/>;case'datahealth':return <DataHealthWorkspace/>;case'disruptions':return <Disruptions d={d} flights={flights} deployed={!!(recovery?.simulated||recovery?.deployed)} go={go}/>;case'crew':return <CrewWorkspace scenario={scenario} go={go}/>;case'flights':return <Flights flights={flights} scenario={scenario} deployed={!!(recovery?.simulated||recovery?.deployed)} setFlight={setFlight} go={go}/>;case'aircraft':return <FleetWorkspace deployed={!!(recovery?.simulated||recovery?.deployed)} onOpenFlight={id=>api.flight(id).then(f=>{setFlight(f);go('routes')})}/>;case'passengers':return <PassengersWorkspace flights={flights} scenario={scenario} deployed={!!(recovery?.simulated||recovery?.deployed)} go={go}/>;case'routes':return <RouteWorkspace flight={flight} onFlight={setFlight}/>;case'tiers':return <SolverWorkspace onOpen={go}/>;case'tier1':case'tier2':return <SolverWorkspace selected={route} onOpen={go}/>;case'tier3':return <Tier3Workspace scenario={scenario} go={go}/>;case'decisions':return <Decisions scenario={scenario} recovery={recovery} run={run} choose={choose} busy={busy} go={go}/>;case'deployment':return <Deployment recovery={recovery} approvalReason={approvalReason} setApprovalReason={setApprovalReason} authorize={authorize} deployNow={deployNow} validate={validatePlan} busy={busy}/>;case'audit':return <AuditPage items={audit}/>}},[route,d,flight,flights,fleet,recovery,audit,busy,approvalReason,scenario]);
 return <main className="app-shell"><aside className="sidebar"><div className="logo"><LogoMark size={30}/><div className="logo-word">SKYSOLVER<small>KINETIC</small></div></div><nav aria-label="Primary">{navGroups.map(([group,items])=><div key={group} className="nav-group"><span className="nav-label">{group}</span>{items.map(([id,label,Icon,sub])=><button key={id} className={`${route===id||(id==='tiers'&&['tier1','tier2','tier3'].includes(route))?'active':''}${sub?' sub':''}`} aria-current={route===id?'page':undefined} onClick={()=>go(id)}><Icon/>{label}{id==='tier3'&&scenario.stats.escalated>0&&<span className="nav-count" aria-label={`${scenario.stats.escalated} pending human review`}>{scenario.stats.escalated}</span>}</button>)}</div>)}</nav></aside><section className="main"><TopBar/><div className="content">{page}</div></section>{notice&&<div className="toast"><ShieldCheck/>{notice}<button onClick={()=>setNotice('')}><X/></button></div>}</main>
}
