import{useEffect,useMemo,useState}from'react';
import{Activity,AlertTriangle,ArrowRight,Check,CloudLightning,Cpu,Database,Gauge,GitBranch,History,Map,Plane,ShieldCheck,Users,Wrench,X}from'lucide-react';
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

type Route='overview'|'datahealth'|'disruptions'|'crew'|'flights'|'aircraft'|'routes'|'tiers'|'tier1'|'tier2'|'tier3'|'decisions'|'deployment'|'audit';
const nav:[Route,string,any,boolean?][]=[['overview','Overview',Activity],['datahealth','Data Health',Database],['disruptions','Disruptions',CloudLightning],['crew','Crew Recovery',Users],['flights','Flights',Plane],['aircraft','Aircraft',Wrench],['routes','Planned Routes',Map],['tiers','Solver Tiers',GitBranch],['tier1','Tier 1 · Legal',Gauge,true],['tier2','Tier 2 · Optimize',Cpu,true],['tier3','Tier 3 · Human',Users,true],['decisions','Decisions',ShieldCheck],['deployment','Deployment',ArrowRight],['audit','Audit',History]];
const fallbackDisruption:Disruption={id:'DSP-DEL-0726',severity:'critical',title:'Delhi low-visibility departure restrictions',summary:'Dense fog is cascading crew, aircraft and passenger dependencies across the India network.',source:'IMD / Delhi ATC',confidence:.96,started_at:'2026-07-31T00:28:00Z',deadline:'2026-07-31T02:10:00Z',partitions:['DEL','BOM','BLR','HYD'],affected_flights:['AI421','6E203','UK945','AI807','6E531'],illegal_crews:2,blocked_aircraft:2,passengers:958,status:'active'};
const fallbackFlight:Flight={id:'AI421',origin:'DEL',destination:'BOM',aircraft:{registration:'VT-EXA',type:'A321',status:'blocked'},gate:'T3-42',proposed_gate:'T3-46',crew:{id:'IC-184',status:'illegal',duty_remaining:'-00:38',qualifications:['A321']},passengers:186,connections:42,delay:92,state:'recovery_pending',tier:'tier1',risk:'critical'};
const flightIds=['AI421','6E203','UK945','AI807','6E531'];

function Badge({children,tone='neutral'}:{children:any;tone?:string}){return <span className={`badge ${tone}`}>{children}</span>}
function PageHead({eyebrow,title,detail,actions}:{eyebrow:string;title:string;detail:string;actions?:any}){return <header className="page-head"><div><span>{eyebrow}</span><h1>{title}</h1><p>{detail}</p></div><div className="page-actions">{actions}</div></header>}
function Table({headers,rows,onRow}:{headers:string[];rows:any[][];onRow?:(row:any[])=>void}){return <div className="table-wrap"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i} className={onRow?'clickable':''} onClick={()=>onRow?.(row)}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>}
function Provenance(){return <div className="scenario-strip"><span className="dot" aria-hidden="true"/><strong>Synthetic scenario data</strong><span>SkySolver crew-recovery prototype · DGCA-oriented ruleset · not a live carrier feed</span></div>}

function Overview({d,scenario,fleet,go}:{d:Disruption;scenario:Scenario;fleet:FleetAircraft[];go:(r:Route)=>void}){
 const s=scenario.stats;const pct=Math.round((s.total?s.resolved/s.total:0)*100);
 const blocked=fleet.filter(a=>['blocked','maintenance','inbound'].includes(a.status)).length;
 const tiles:[string,any,string,string][]=[['Open crew cases',s.open,s.open?'danger':'success','illegal pairings'],['Resolved',s.resolved,'success','legal reassignments'],['Human review',s.escalated,s.escalated?'purple':'neutral','Tier 3 queue'],['Recovery',`${pct}%`,pct===100?'success':'warning',`${s.resolved}/${s.total} cases`],['Passengers exposed',d.passengers.toLocaleString('en-IN'),'neutral','across affected flights'],['Aircraft blocked',blocked,blocked?'warning':'success',`${fleet.length} in fleet`]];
 return <>
  <PageHead eyebrow="NETWORK BRIEFING" title="India crew-recovery control" detail="Live status of the active disruption, crew recovery progress and pending decisions." actions={<button className="primary" onClick={()=>go('crew')}>Open recovery worklist</button>}/>
  <div className="kpis">{tiles.map(([k,v,tone,sub])=><div className={`kpi ${tone}`} key={k}><span>{k}</span><strong>{v}</strong><small>{sub}</small></div>)}</div>
  <div className="progressbar big"><div className="progressbar-fill" style={{width:`${pct}%`}}/><span>{s.resolved} of {s.total} crew cases resolved{s.escalated?` · ${s.escalated} in human review`:''}</span></div>
  <div className="overview-grid">
   <section className="card urgent"><header><div><Badge tone="danger">P1 · {d.severity.toUpperCase()}</Badge><h2>{d.title}</h2></div></header><p>{d.summary}</p><div className="fact-strip small">{[['Source',d.source],['Confidence',`${Math.round(d.confidence*100)}%`],['Partitions',d.partitions.join(', ')]].map(x=><span key={x[0]}>{x[0]}<b>{x[1]}</b></span>)}</div><button onClick={()=>go('disruptions')}>Inspect disruption</button></section>
   <section className="card"><header className="rowbetween"><h2>Recovery cases</h2><button className="linklike" onClick={()=>go('crew')}>Work cases →</button></header><div className="mini-cases">{scenario.cases.map(c=><div key={c.flight} className="mini-case"><span className={`dotstatus ${c.status}`}/><b>{c.flight}</b><span className="muted small">{c.origin}→{c.destination} · {c.aircraft}</span><span className={`badge ${c.status==='resolved'?'success':c.status==='escalated'?'purple':'danger'}`}>{c.status==='resolved'?`✓ ${c.replacementId}`:c.status==='escalated'?'TIER 3':'OPEN'}</span></div>)}{scenario.cases.length===0&&<p className="muted">Loading cases…</p>}</div></section>
  </div>
 </>;
}

function Disruptions({d,flights,go}:{d:Disruption;flights:Flight[];go:(r:Route)=>void}){
 const totalPax=flights.reduce((s,f)=>s+f.passengers,0),illegal=flights.filter(f=>f.crew.status==='illegal').length,blocked=flights.filter(f=>f.aircraft.status==='blocked').length,totalDelay=flights.reduce((s,f)=>s+f.delay,0);
 const statusTone=(s:string)=>s==='illegal'?'danger':s==='legal'?'success':'warning';
 const riskTone=(r:string)=>r==='critical'?'danger':r==='high'?'warning':r==='medium'?'cyan':'success';
 return <>
  <PageHead eyebrow={`DISRUPTION ${d.id}`} title={d.title} detail={d.summary} actions={<button className="primary" onClick={()=>go('crew')}>Work crew recovery</button>}/>
  <div className="kpis">{([['Affected flights',flights.length,'in scenario'],['Illegal crews',illegal,'need action'],['Blocked aircraft',blocked,'on ground'],['Passengers',totalPax.toLocaleString('en-IN'),'exposed'],['Cumulative delay',`${totalDelay}m`,'across flights'],['Partitions',d.partitions.length,d.partitions.join(', ')]] as [string,any,string][]).map(([k,v,sub])=><div className="kpi" key={k}><span>{k}</span><strong>{v}</strong><small>{sub}</small></div>)}</div>
  <div className="fact-strip">{[['Source',d.source],['Confidence',`${Math.round(d.confidence*100)}%`],['Started',new Date(d.started_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})],['Recovery deadline',new Date(d.deadline).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})],['Authority','Scheduler']].map(x=><span key={x[0]}>{x[0]}<b>{x[1]}</b></span>)}</div>
  <section className="card"><header className="rowbetween"><h2>Affected flights</h2><Badge tone="warning">{illegal} need crew action</Badge></header><Table headers={['Flight','Route','Aircraft','Crew','Crew status','Pax','Delay','Risk']} rows={flights.map(f=>[f.id,`${f.origin} → ${f.destination}`,`${f.aircraft.type} · ${f.aircraft.registration}`,f.crew.id,<span className={`badge ${statusTone(f.crew.status)}`}>{f.crew.status.toUpperCase()}</span>,f.passengers,`${f.delay}m`,<span className={`badge ${riskTone(f.risk)}`}>{f.risk.toUpperCase()}</span>])} onRow={()=>go('crew')}/></section>
 </>;
}


function Flights({flights,setFlight,go}:{flights:Flight[];setFlight:(f:Flight)=>void;go:(r:Route)=>void}){
 const statusTone=(s:string)=>s==='illegal'?'danger':s==='legal'?'success':'warning';
 return <><PageHead eyebrow="FLIGHT OPERATIONS" title="Network flights" detail="Every affected flight with its aircraft, crew and movement record. Select a flight to inspect its route."/>
  <section className="card"><Table headers={['Flight','Route','Aircraft','Tail','Crew','Crew status','Gate','Pax','Delay']} rows={flights.map(f=>[f.id,`${f.origin} → ${f.destination}`,f.aircraft.type,f.aircraft.registration,f.crew.id,<span className={`badge ${statusTone(f.crew.status)}`}>{f.crew.status.toUpperCase()}</span>,`${f.gate}${f.proposed_gate!==f.gate?` → ${f.proposed_gate}`:''}`,f.passengers,`${f.delay}m`])} onRow={r=>{const f=flights.find(x=>x.id===r[0]);if(f){setFlight(f);go('routes')}}}/></section>
  {flights.length===0&&<section className="empty"><Plane/><h2>Loading flights…</h2></section>}</>;
}

function Decisions({scenario,recovery,run,choose,busy,go}:{scenario:Scenario;recovery:Recovery|null;run:()=>void;choose:(id:string)=>void;busy:boolean;go:(r:Route)=>void}){
 const s=scenario.stats;const resolved=scenario.cases.filter(c=>c.status==='resolved');
 return <>
  <PageHead eyebrow="RECOVERY DECISIONS" title="Recovery plan & candidate comparison" detail="The plan assembled from your crew decisions, plus solver-generated candidates with full provenance." actions={<button className="primary" disabled={busy||s.resolved===0} onClick={run}>{recovery?'Re-generate plan':'Generate recovery plan'}</button>}/>
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
export function Deployment({recovery,approvalReason,setApprovalReason,approve,deploy,validate,busy}:{recovery:Recovery|null;approvalReason:string;setApprovalReason:(v:string)=>void;approve:(reason:string)=>void;deploy:()=>void;validate?:()=>void;busy:boolean}){
 if(!recovery)return <><PageHead eyebrow="APPROVAL & DEPLOYMENT" title="Approval and publication are separate authorities" detail="Scheduler proposes and validates; a duty manager approves; an authorized controller publishes."/><section className="empty"><ArrowRight/><h2>No recovery in progress</h2><p>Start a recovery and select a candidate before approval or deployment.</p></section></>;
 const r=recovery;const selected=r.candidates.find(c=>c.id===r.selected_candidate_id)||null;const jf=selected?.joint_feasibility;const approved=(r.approvals?.length||0)>0;const acks=r.acknowledgements||[];
 const steps:[string,'done'|'blocked'|'current'|'pending',string][]=[['Candidate selected',r.selected_candidate_id?'done':(r.candidates.length?'current':'pending'),r.selected_candidate_id||'Not selected'],['Legality validated',r.validated?'done':(r.selected_candidate_id?'current':'pending'),r.validated?'Certificate issued':'Not validated'],['Joint feasibility',jf?.deployable?'done':'blocked',jf?jf.status.replaceAll('_',' '):'Not evaluated'],['Duty-manager approval',approved?'done':'blocked',approved?'Approved':'Requires approve permission'],['Controller deployment',r.deployed?'done':'blocked',r.deployed?'Deployed':'Requires deploy permission']];
 return <>
  <PageHead eyebrow="APPROVAL & DEPLOYMENT" title="Approval and publication are separate authorities" detail="Scheduler proposes and validates; a duty manager approves; an authorized controller publishes. Carrier writes remain disabled." actions={<Badge tone={r.carrier_writes_enabled?'warning':'danger'}>{r.carrier_writes_enabled?'CARRIER WRITES ENABLED':'CARRIER WRITES DISABLED'}</Badge>}/>
  <div className="step-flow" role="list" aria-label="Recovery lifecycle">{steps.map(([label,st,detail])=><div key={label} className={`step ${st}`} role="listitem"><span className="s-label">{label}</span><span className="s-state">{st==='done'?<Check/>:st==='blocked'?<AlertTriangle/>:null} {detail}</span></div>)}</div>
  <section className="card"><header><h2><ShieldCheck/> Approval — duty manager</h2><Badge tone={approved?'success':'neutral'}>{approved?'APPROVED':'NOT APPROVED'}</Badge></header>
   <p className="muted">Approval authorizes the validated plan; it is <b>not</b> publication. A scheduler may request it, but only an APPROVE-permission user can grant it. The backend enforces this and rejects an unauthorized attempt — the UI does not simulate approval.</p>
   <label className="field"><span>Approval reason</span><input value={approvalReason} onChange={e=>setApprovalReason(e.target.value)} placeholder="Reason (min 3 chars), recorded on the approval" aria-label="Approval reason"/></label>
   <div className="page-actions"><button className="primary" disabled={busy||!r.validated||approvalReason.trim().length<3} onClick={()=>approve(approvalReason.trim())}>Submit for approval</button></div>
   {!r.validated&&(r.selected_candidate_id?<div className="page-actions"><button disabled={busy} onClick={validate}>Run legality validation first</button></div>:<p className="muted small">Select a candidate plan on Decisions first.</p>)}
   {r.approvals?.map((a,i)=><p key={i} className="muted small"><Check/> {a.role||'approver'} · {a.reason} {a.at?`· ${new Date(a.at).toLocaleString()}`:''}</p>)}
  </section>
  <section className="card"><header><h2><ArrowRight/> Deployment — authorized controller</h2><Badge tone={r.deployed?'success':'danger'}>{r.deployed?'DEPLOYED':'NOT DEPLOYED'}</Badge></header>
   <p className="muted">Publication sends commands to carrier systems. It requires prior approval, evaluated joint feasibility and DEPLOY permission. The scheduler role cannot deploy; the backend returns a permission error rather than a fake acknowledgement.</p>
   {jf&&!jf.deployable&&<div className="provenance" role="alert"><AlertTriangle/><span><strong>Joint feasibility not satisfied — deployment blocked</strong><small>{jf.findings.map(f=>f.message).join('; ')||jf.status}</small></span></div>}
   <div className="page-actions"><button disabled={busy||!approved||!jf?.deployable} onClick={deploy}>Publish to carrier systems</button></div>
   <h3 className="muted">Per-resource acknowledgements</h3>
   {acks.length===0
     ?<p className="muted small">No deployment issued — there are no ACK / NACK / timeout / partial acknowledgements to display. Nothing here is fabricated.</p>
     :<div className="ack-grid">{acks.map((a,i)=><div key={i} className={`ack ${ackClass(a.status)}`}><span className="res">{a.resource}</span><span className="st">{a.status.toUpperCase()}</span>{a.detail&&<span className="muted small">{a.detail}</span>}{a.target_reference&&<span className="muted small">ref {a.target_reference}</span>}</div>)}</div>}
   <p className="muted small">Retry and compensation become available per command only when a deployment record reports that command retryable or compensatable. No deployment record exists here, so neither is offered.</p>
  </section>
 </>;
}
function AuditPage({items}:{items:Audit[]}){return <><PageHead eyebrow="AUDIT TRAIL" title="Recovery audit trail" detail="Chronological record of every recovery action with actor, correlation and ruleset version. This prototype uses an in-memory ledger; production uses immutable external storage."/><section className="card"><Table headers={['Timestamp','Action','Actor','Recovery','Detail','Ruleset']} rows={items.map(a=>[new Date(a.timestamp).toLocaleString(),a.action.replaceAll('_',' '),a.operator,a.recovery_id,a.detail,a.ruleset_version])}/>{!items.length&&<p>No recovery actions recorded yet.</p>}</section></>}

// Truthful, work-preserving messaging for mutation failures. A 409 never discards
// the operator's context: we keep the current recovery selection and refresh the
// authoritative state so the action can be retried against the current version.
export function describeFailure(error:unknown,recovery:Recovery|null,setRecovery:(r:Recovery)=>void):string{
 if(error instanceof ApiError){
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
 const work=async(fn:()=>Promise<{recovery:Recovery}>,message:string)=>{setBusy(true);try{const result=await fn();setRecovery(result.recovery);setNotice(message);api.audit().then(x=>setAudit(x.items))}catch(error){setNotice(describeFailure(error,recovery,setRecovery))}finally{setBusy(false)}};
 const run=()=>work(()=>api.createRecovery(d.id),'Candidate plans generated');
 const choose=(id:string)=>recovery&&work(()=>api.decide(recovery.id,recovery.state_version,id),'Candidate plan selected');
 const validatePlan=()=>recovery?.selected_candidate_id&&work(()=>api.validate(recovery.id,recovery.state_version,recovery.selected_candidate_id||undefined),'Legality checks completed');
 const submitApproval=(reason:string)=>recovery&&work(()=>api.approve(recovery.id,recovery.state_version,reason),'Approval request submitted');
 const deployPlan=()=>recovery&&work(()=>api.deploy(recovery.id,recovery.state_version),'Deployment requested');
 const page=useMemo(()=>{switch(route){case'overview':return <Overview d={d} scenario={scenario} fleet={fleet} go={go}/>;case'datahealth':return <DataHealthWorkspace/>;case'disruptions':return <Disruptions d={d} flights={flights} go={go}/>;case'crew':return <CrewWorkspace scenario={scenario} go={go}/>;case'flights':return <Flights flights={flights} setFlight={setFlight} go={go}/>;case'aircraft':return <FleetWorkspace onOpenFlight={id=>api.flight(id).then(f=>{setFlight(f);go('routes')})}/>;case'routes':return <RouteWorkspace flight={flight} onFlight={setFlight}/>;case'tiers':return <SolverWorkspace onOpen={go}/>;case'tier1':case'tier2':return <SolverWorkspace selected={route} onOpen={go}/>;case'tier3':return <Tier3Workspace scenario={scenario} go={go}/>;case'decisions':return <Decisions scenario={scenario} recovery={recovery} run={run} choose={choose} busy={busy} go={go}/>;case'deployment':return <Deployment recovery={recovery} approvalReason={approvalReason} setApprovalReason={setApprovalReason} approve={submitApproval} deploy={deployPlan} validate={validatePlan} busy={busy}/>;case'audit':return <AuditPage items={audit}/>}},[route,d,flight,flights,fleet,recovery,audit,busy,approvalReason,scenario]);
 return <main className="app-shell"><aside className="sidebar"><div className="logo"><span><Plane/></span><div>SKYSOLVER<small>Crew recovery · India</small></div></div><nav aria-label="Primary">{nav.map(([id,label,Icon,sub])=><button key={id} className={`${route===id||(id==='tiers'&&['tier1','tier2','tier3'].includes(route))?'active':''}${sub?' sub':''}`} aria-current={route===id?'page':undefined} onClick={()=>go(id)}><Icon/>{label}</button>)}</nav><div className="side-foot"><Badge tone="cyan">PROTOTYPE</Badge><span>Synthetic scenario</span><small>DGCA-oriented ruleset</small></div></aside><section className="main"><Provenance/><div className="content">{page}</div></section>{notice&&<div className="toast"><ShieldCheck/>{notice}<button onClick={()=>setNotice('')}><X/></button></div>}</main>
}
