import{useCallback,useEffect,useRef,useState}from'react';
import{AlertTriangle,ArrowRight,Bot,Check,ChevronRight,Cpu,Eye,Gavel,Lock,Play,Search,ShieldCheck,X}from'lucide-react';
import{api,ApiError}from'./api';
import type{AgentRun,AgentStep,AgentToolset}from'./types';
import type{Scenario}from'./scenario';

type Planner='deterministic'|'gemini'|'openai';

const PLANNERS:[Planner,string,string][]=[
 ['gemini','Gemini','LLM chooses the actions'],
 ['deterministic','Deterministic','Constraint heuristic, no API key'],
];

// Phase presentation. The loop is perceive -> plan -> act -> observe -> escalate;
// the icon and tone make the shape of the run legible at a glance.
const PHASE:Record<AgentStep['phase'],{label:string;Icon:any}>={
 perceive:{label:'PERCEIVE',Icon:Eye},
 plan:{label:'PLAN',Icon:Search},
 act:{label:'ACT',Icon:Cpu},
 observe:{label:'OBSERVE',Icon:Eye},
 escalate:{label:'ESCALATE',Icon:Gavel},
};

function stepTone(step:AgentStep):string{
 if(!step.ok)return'warning';
 if(step.phase==='escalate')return'danger';
 if(step.tool==='commit_reassignment')return'success';
 if(step.tool==='preview_reassignment')return step.observation.data?.legal?'success':'danger';
 return'neutral';
}

function violationCodes(step:AgentStep):string[]{
 const list=step.observation.data?.rule_violations;
 return Array.isArray(list)?list.map((v:any)=>v.code):[];
}

type Applied={resolved:number;escalated:number;unknown:string[]};

export default function AgentWorkspace({scenario,go}:{scenario:Scenario;go:(r:'crew'|'tier3'|'decisions'|'audit')=>void}){
 const [planner,setPlanner]=useState<Planner>('gemini');
 const [run,setRun]=useState<AgentRun|null>(null);
 const [tools,setTools]=useState<AgentToolset|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const [revealed,setRevealed]=useState(0);
 const [showTools,setShowTools]=useState(false);
 const [applied,setApplied]=useState<Applied|null>(null);
 const timers=useRef<number[]>([]);

 useEffect(()=>{api.agentTools().then(setTools).catch(()=>setTools(null))},[]);
 // Clear any pending reveal timers if the component unmounts mid-animation.
 useEffect(()=>()=>{timers.current.forEach(clearTimeout)},[]);

 // The agent's plan is only useful if it lands in the same recovery state a
 // manual decision would. Without this the Decisions page still sees zero
 // resolved cases and refuses to generate a plan.
 const applyToRecovery=useCallback((result:AgentRun):Applied=>{
  let resolved=0,escalated=0;const unknown:string[]=[];
  for(const a of result.resolved){
   const crew=scenario.roster.find(c=>c.id===a.crew_id);
   if(crew){scenario.reassign(a.flight_id,crew);resolved++}
   else unknown.push(`${a.flight_id} (${a.crew_id})`);
  }
  for(const e of result.escalated){scenario.escalate(e.flight_id);escalated++}
  return{resolved,escalated,unknown};
 },[scenario]);

 const start=useCallback(async()=>{
  timers.current.forEach(clearTimeout);timers.current=[];
  setBusy(true);setError('');setRun(null);setRevealed(0);setApplied(null);
  try{
   const result=await api.agentRun(planner);
   setRun(result);
   setApplied(applyToRecovery(result));
   // Step the trace out rather than dumping it: the sequence of decisions is
   // the point, and an operator needs to be able to follow it.
   result.trace.steps.forEach((_,i)=>{
    timers.current.push(window.setTimeout(()=>setRevealed(i+1),i*260));
   });
  }catch(e){
   const err=e as ApiError;
   setError(err?.message||'The agent could not be started.');
  }finally{setBusy(false)}
 },[planner,applyToRecovery]);

 const steps=run?run.trace.steps.slice(0,revealed):[];
 const complete=!!run&&revealed>=run.trace.steps.length;
 const degraded=!!run&&run.notes.length>0;

 return <>
  <header className="page-head">
   <div>
    <span>RECOVERY AGENT</span>
    <h1>Autonomous crew recovery</h1>
    <p>The agent decides what to try. The FAR117/DGCA rules engine decides what is allowed — every reassignment below was cleared by the engine before it entered the plan.</p>
   </div>
   <div className="page-actions">
    {run&&<span className={`badge ${degraded?'warning':'success'}`}>{run.planner}</span>}
    <button className="primary" onClick={start} disabled={busy}><Play/> {busy?'Running…':run?'Run again':'Run agent'}</button>
   </div>
  </header>

  <div className="agent-controls">
   <span className="muted small">Planner</span>
   {PLANNERS.map(([id,label,detail])=>
    <button key={id} className={`agent-pick ${planner===id?'on':''}`} onClick={()=>setPlanner(id)} disabled={busy} aria-pressed={planner===id}>
     <b>{label}</b><small>{detail}</small>
    </button>
   )}
   <button className="agent-pick ghost" onClick={()=>setShowTools(v=>!v)} aria-expanded={showTools}>
    <b><Lock/> Guardrails</b><small>{showTools?'Hide':'What the agent may do'}</small>
   </button>
  </div>

  {showTools&&tools&&<section className="card agent-guards">
   <header className="rowbetween"><h2>Enforced in code, not in a prompt</h2><span className="muted small">{tools.items.length} tools</span></header>
   <ul className="guard-list">{tools.guarantees.map(g=><li key={g}><ShieldCheck/><span>{g}</span></li>)}</ul>
   <div className="tool-grid">{tools.items.map(t=>
    <div key={t.name} className="tool-chip"><code>{t.name}</code><small>{t.description}</small></div>
   )}</div>
  </section>}

  {error&&<div className="dh-note"><AlertTriangle/><span>{error}</span></div>}

  {!run&&!busy&&!error&&<section className="card agent-idle">
   <Bot/>
   <div>
    <h2>No run yet</h2>
    <p className="muted small">Start the agent to work the open crew legality cases. It reads the disruption, shortlists type-rated replacements, asks the rules engine to rule on each one, and escalates anything it cannot resolve legally.</p>
   </div>
  </section>}

  {run&&<>
   <div className="kpis">
    {([['Resolved',run.summary.resolved,'legal reassignments'],
       ['Escalated',run.summary.escalated,'sent to a scheduler'],
       ['Unresolved',run.summary.unresolved,'left open'],
       ['Tool calls',run.summary.tool_calls,'decisions taken'],
       ['Elapsed',`${run.summary.elapsed_s}s`,'end to end']] as [string,any,string][])
     .map(([k,v,sub])=><div className={`kpi ${k==='Resolved'&&run.summary.resolved?'success':k==='Escalated'&&run.summary.escalated?'warning':k==='Unresolved'&&run.summary.unresolved?'danger':''}`} key={k}>
      <span>{k}</span><strong>{v}</strong><small>{sub}</small>
     </div>)}
   </div>

   {degraded&&<div className="dh-note"><AlertTriangle/><span>
    <b>Ran on the {run.planner} planner.</b> {run.notes.join(' ')} The recovery plan is identical either way — the legality decisions come from the rules engine, not the model.
   </span></div>}

   {applied&&applied.escalated>0&&<div className="agent-review-alert" role="alert">
    <Gavel/><div><strong>{applied.escalated} item{applied.escalated===1?'':'s'} pending human review</strong><span>The agent reached its authority boundary. An operator must review the unresolved case in Tier 3 before the plan can proceed.</span></div>
    <button className="primary" onClick={()=>go('tier3')}>Review now <ArrowRight/></button>
   </div>}

   <section className="card">
    <header className="rowbetween">
     <h2>Decision trace</h2>
     <span className="muted small">{steps.length} of {run.trace.steps.length} steps{complete?'':' …'}</span>
    </header>
    <ol className="agent-trace">
     {steps.map(step=>{
      const {label,Icon}=PHASE[step.phase];
      const codes=violationCodes(step);
      return <li key={step.index} className={`agent-step ${stepTone(step)}`}>
       <div className="as-rail"><span className="as-index">{step.index}</span></div>
       <div className="as-body">
        <div className="as-head">
         <span className="as-phase"><Icon/> {label}</span>
         <code className="as-tool">{step.tool}</code>
         {Object.entries(step.tool_input).filter(([k])=>k!=='reason'&&k!=='rationale').map(([k,v])=>
          <span key={k} className="as-arg">{k}=<b>{String(v)}</b></span>)}
         {step.duration_ms>0&&<span className="as-ms">{step.duration_ms}ms</span>}
        </div>
        <p className="as-why">{step.rationale}</p>
        <p className={`as-out ${stepTone(step)}`}>
         {step.ok?<ChevronRight/>:<X/>}
         <span>{step.outcome}</span>
        </p>
        {codes.length>0&&<div className="as-codes">{codes.map(c=><span key={c} className="badge danger">{c}</span>)}</div>}
       </div>
      </li>;
     })}
    </ol>
   </section>

   {complete&&<>
    <section className="card">
     <header className="rowbetween"><h2>Recovery plan</h2>
      <span className={`badge ${run.summary.unresolved?'danger':'success'}`}>{run.summary.unresolved?'INCOMPLETE':'ALL CASES SETTLED'}</span>
     </header>
     {run.resolved.length===0&&run.escalated.length===0&&<p className="muted small">The agent found no open crew legality cases.</p>}
     {run.resolved.map(a=><div key={a.flight_id} className="agent-outcome ok">
      <div className="ao-head"><b>{a.flight_id}</b><ArrowRight/><span>{a.crew_id} · {a.crew_name}</span><span className="badge success"><Check/> LEGAL</span></div>
      <p className="muted small">{a.rationale}</p>
      <div className="ao-checks">{Object.entries(a.checks).map(([k,v])=>
       <span key={k} className={`badge ${v?'success':'danger'}`}>{k.replace(/_/g,' ')}</span>)}
       <span className="muted small">ruleset {a.ruleset_version}</span>
      </div>
     </div>)}
     {run.escalated.map(e=><div key={e.flight_id} className="agent-outcome esc">
      <div className="ao-head"><b>{e.flight_id}</b><span className="badge danger">TIER 3 · HUMAN DECISION</span><span className="muted small">{e.passengers} passengers</span></div>
      <p className="muted small">{e.reason}</p>
      <div className="ao-blockers">{e.blockers.map(b=><div key={b.crew_id} className="ao-blocker">
       <b>{b.crew_id} · {b.crew_name}</b>
       {b.violations.map(v=><span key={v} className="badge danger">{v}</span>)}
       <span className="muted small">{b.detail}</span>
      </div>)}</div>
     </div>)}
     {run.unresolved.map(id=><div key={id} className="agent-outcome esc"><div className="ao-head"><b>{id}</b><span className="badge warning">STILL OPEN</span></div></div>)}
    </section>

    {run.handover&&<section className="card"><header className="rowbetween"><h2>Handover</h2><span className="muted small">agent to duty manager</span></header>
     <p className="agent-handover">{run.handover}</p>
    </section>}

    {applied&&<div className="banner-ok"><Check/> <span>
     Applied to the recovery plan — {applied.resolved} case{applied.resolved===1?'':'s'} resolved
     {applied.escalated>0&&<> and {applied.escalated} escalated to Tier 3</>}.
     {' '}Decisions and Deployment now reflect this plan.
     {applied.unknown.length>0&&<> Could not apply: {applied.unknown.join(', ')}.</>}
    </span></div>}

    <div className="page-actions">
     <button onClick={()=>go('tier3')}>Open Tier 3 queue</button>
     <button onClick={()=>go('audit')}>View audit trail</button>
     <button className="primary" onClick={()=>go('decisions')}>Continue to decisions <ArrowRight/></button>
    </div>
   </>}
  </>}

  <p className="muted small footnote">
   <Bot style={{width:13,height:13,verticalAlign:'-2px'}}/> The agent proposes a plan; it does not deploy. Publishing still requires the scheduler, duty-manager and deployment-controller gates.
  </p>
 </>;
}
