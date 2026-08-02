import{useEffect,useState}from'react';
import{ArrowRight,CheckCircle2,AlertTriangle,RefreshCw,Users,Cpu,Gauge}from'lucide-react';
import{api}from'./api';
import type{Provenance,SolverTier}from'./types';

// Truthful viability classification derived from the backend tier status string.
// Never upgrades an unavailable/degraded solver into an operational-looking state.
export function tierViability(status:string):{tone:'success'|'warning'|'danger';unavailable:boolean;label:string}{
 const s=(status||'').toLowerCase();
 if(['solver_unavailable','infeasible','error','timeout','failed','unavailable'].some(k=>s.includes(k)))return{tone:'danger',unavailable:true,label:(status||'unavailable').replaceAll('_',' ')};
 if(['partial','standby','degraded'].some(k=>s.includes(k)))return{tone:'warning',unavailable:false,label:status.replaceAll('_',' ')};
 return{tone:'success',unavailable:false,label:(status||'').replaceAll('_',' ')||'viable'};
}

const eyebrow:Record<string,string>={tier1:'TIER 1 · IMMEDIATE LEGAL RECOVERY',tier2:'TIER 2 · OPTIMIZATION UPGRADE',tier3:'TIER 3 · HUMAN-ASSISTED RECOVERY'};
const meaning:Record<string,string>={tier1:'Bounded greedy construction with local-search improvement. Guarantees a legal partial assignment quickly; optimality is deliberately secondary to always responding.',tier2:'Warm-started column generation that may upgrade the Tier 1 incumbent within a time budget. It never replaces a better current legal incumbent.',tier3:'Human-assisted queue for work automation could not resolve. Accepting an option creates a candidate; it does not approve or deploy it.'};

function Provline({p}:{p:Provenance|null}){if(!p)return null;return <p className="muted small">Provenance: {p.source_system} · {p.freshness} · state v{p.state_version} · {p.authoritative?'authoritative':'synthetic — not authoritative'}</p>}

export default function SolverWorkspace({selected,onOpen}:{selected?:SolverTier['id'];onOpen:(id:SolverTier['id'])=>void}){
 const[tiers,setTiers]=useState<SolverTier[]>([]),[ruleset,setRuleset]=useState(''),[prov,setProv]=useState<Provenance|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const load=()=>{setLoading(true);setError('');api.solverTiers().then(x=>{setTiers(x.tiers);setRuleset(x.ruleset_version);setProv(x.provenance||null)}).catch(e=>setError(e.message)).finally(()=>setLoading(false))};
 useEffect(load,[]);
 if(loading)return <section className="empty" role="status" aria-live="polite"><RefreshCw className="spin"/><h2>Executing solver benchmark</h2><p>Solving the current synthetic India partition.</p></section>;
 if(error)return <section className="empty"><AlertTriangle/><h2>Solver telemetry unavailable</h2><p>{error}</p><button onClick={load}>Retry</button></section>;

 if(selected){
  const t=tiers.find(x=>x.id===selected);
  if(!t)return <section className="empty"><AlertTriangle/><h2>{selected.toUpperCase()} telemetry not present</h2><p>The backend solver-tiers response did not include {selected}. Nothing is invented in its place.</p><button onClick={load}><RefreshCw/> Refresh</button></section>;
  const v=tierViability(t.status);
  return <>
   <header className="page-head"><div><span>{eyebrow[selected]}</span><h1>{t.name}</h1><p>{meaning[selected]}</p></div><div className="page-actions"><span className={`badge ${v.tone}`}>{v.label.toUpperCase()}</span><button onClick={load}><RefreshCw/> Run again</button></div></header>
   {v.unavailable&&<div className="provenance" role="alert"><AlertTriangle/><span><strong>{t.name} unavailable — no synthetic success is shown</strong><small>{t.reason}. The Tier 1 legal incumbent is retained; this tier did not modify the plan.</small></span></div>}
   <div className="fact-strip"><span>Coverage<b>{Math.round(t.coverage*100)}%</b></span><span>Legal assignments<b>{t.legal_assignments}</b></span><span>Unresolved<b>{t.unresolved}</b></span><span>Elapsed<b>{t.elapsed_s.toFixed(3)}s</b></span><span>Ruleset<b>{ruleset||'—'}</b></span></div>
   {selected==='tier2'&&<section className="card"><header><h2><Cpu/> Optimization evidence</h2><span className={`badge ${v.tone}`}>{t.solver_name||'no solver'}</span></header><div className="fact-strip"><span>Solver<b>{t.solver_name||'None configured'}</b></span><span>Legal columns<b>{t.generated_columns??0}</b></span><span>Incumbent<b>{t.upgraded?'Upgraded':'Tier 1 retained'}</b></span><span>Objective<b>{t.objective_value==null?'—':t.objective_value.toFixed(2)}</b></span><span>Best bound<b>{t.best_bound==null?'—':t.best_bound.toFixed(2)}</b></span><span>Optimality gap<b>{t.optimality_gap==null?'No certified gap':`${(t.optimality_gap*100).toFixed(2)}%`}</b></span></div><p className="muted">A null objective, bound or gap means the optimizer produced no certified value — the UI does not fabricate one.</p></section>}
   {selected==='tier3'&&<section className="card"><header><h2><Users/> Human-assisted queue</h2></header><p>Open the Tier 3 workspace to review ranked, legality-gated options for unresolved work.</p><div className="page-actions"><button className="primary" onClick={()=>onOpen('tier3')}>Open Tier 3 queue <ArrowRight/></button></div></section>}
   <section className="card"><header><h2><Gauge/> What this tier guarantees</h2></header><p>{meaning[selected]}</p><p className="muted">{t.reason}</p></section>
   <Provline p={prov}/>
  </>;
 }

 return <>
  <header className="page-head"><div><span>SOLVER ORCHESTRATION</span><h1>Executable recovery tiers</h1><p>Backend solver output for the current partition, not a scripted animation.</p></div><div className="page-actions"><span className="badge cyan">{ruleset}</span><button onClick={load}><RefreshCw/> Run again</button></div></header>
  <div className="tier-grid">{tiers.map(t=>{const v=tierViability(t.status);return <article className="tier-card" key={t.id}><header><span className={`badge ${t.id==='tier1'?'success':t.id==='tier2'?'cyan':'purple'}`}>{t.id.toUpperCase()}</span><span className={`badge ${v.tone}`}>{v.label.toUpperCase()}</span></header><h2>{t.name}</h2><p>{t.reason}</p><div className="tier-metrics"><span>Coverage<b>{Math.round(t.coverage*100)}%</b></span><span>Elapsed<b>{t.elapsed_s.toFixed(3)}s</b></span><span>Unresolved<b>{t.unresolved}</b></span></div><div className="tier-status">{t.id==='tier3'?<Users/>:<CheckCircle2/>}<strong>{t.legal_assignments} legal assignments</strong></div><button onClick={()=>onOpen(t.id)}>Open workspace <ArrowRight/></button></article>})}</div>
  <Provline p={prov}/>
 </>;
}
