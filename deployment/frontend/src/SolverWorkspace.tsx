import{useEffect,useState}from'react';
import{ArrowRight,CheckCircle2,RefreshCw,Users}from'lucide-react';
import{api}from'./api';
import type{SolverTier}from'./types';

export default function SolverWorkspace({selected,onOpen}:{selected?:SolverTier['id'];onOpen:(id:SolverTier['id'])=>void}){
 const[tiers,setTiers]=useState<SolverTier[]>([]),[ruleset,setRuleset]=useState(''),[loading,setLoading]=useState(true),[error,setError]=useState('');
 const load=()=>{setLoading(true);setError('');api.solverTiers().then(x=>{setTiers(x.tiers);setRuleset(x.ruleset_version)}).catch(e=>setError(e.message)).finally(()=>setLoading(false))};
 useEffect(load,[]);const shown=selected?tiers.filter(t=>t.id===selected):tiers;
 if(loading)return <section className="empty"><RefreshCw className="spin"/><h2>Executing solver benchmark</h2><p>Solving the current synthetic India partition.</p></section>;
 if(error)return <section className="empty"><h2>Solver telemetry unavailable</h2><p>{error}</p><button onClick={load}>Retry</button></section>;
 return <><header className="page-head"><div><span>{selected?selected.toUpperCase():'SOLVER ORCHESTRATION'}</span><h1>{selected?shown[0]?.name:'Executable recovery tiers'}</h1><p>Backend solver output, not a scripted animation.</p></div><div className="page-actions"><span className="badge cyan">{ruleset}</span><button onClick={load}><RefreshCw/> Run again</button></div></header><div className="tier-grid">{shown.map(t=><article className="tier-card" key={t.id}><header><span className={`badge ${t.id==='tier1'?'success':t.id==='tier2'?'cyan':'purple'}`}>{t.id.toUpperCase()}</span><span>{t.status.replaceAll('_',' ').toUpperCase()}</span></header><h2>{t.name}</h2><p>{t.reason}</p><div className="tier-metrics"><span>Coverage<b>{Math.round(t.coverage*100)}%</b></span><span>Elapsed<b>{t.elapsed_s.toFixed(3)}s</b></span><span>Unresolved<b>{t.unresolved}</b></span></div>{t.id==='tier2'&&<div className="explain"><strong>Optimization evidence</strong><p>{t.solver_name||'No configured solver'} · {t.generated_columns??0} legal columns · {t.upgraded?'Incumbent upgraded':'Tier 1 retained'}</p><small>{t.objective_value==null?'No objective value available':`Objective ${t.objective_value.toFixed(2)}`} · {t.optimality_gap==null?'No certified gap':`Gap ${(t.optimality_gap*100).toFixed(2)}%`}</small></div>}<div className="tier-status">{t.id==='tier3'?<Users/>:<CheckCircle2/>}<strong>{t.legal_assignments} legal assignments</strong></div>{!selected&&<button onClick={()=>onOpen(t.id)}>Open workspace <ArrowRight/></button>}</article>)}</div></>
}
