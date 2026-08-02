import{useEffect,useState}from'react';
import{AlertTriangle,CheckCircle2,Database,RefreshCw,ShieldCheck}from'lucide-react';
import{api}from'./api';
import type{DataHealth}from'./types';

export default function DataHealthWorkspace(){
 const[data,setData]=useState<DataHealth|null>(null),[error,setError]=useState('');
 const load=()=>{setError('');api.dataHealth().then(setData).catch(e=>setError(e.message))};useEffect(load,[]);
 if(error)return <section className="empty"><AlertTriangle/><h2>Data health unavailable</h2><p>{error}</p><button onClick={load}><RefreshCw/> Retry</button></section>;
 if(!data)return <section className="empty" role="status" aria-live="polite"><RefreshCw className="spin"/><h2>Evaluating source systems</h2></section>;
 const authoritative=data.sources.filter(s=>s.authoritative).length,fresh=data.sources.filter(s=>s.fresh).length,dlq=data.sources.reduce((n,s)=>n+s.dead_letter_count,0),drift=data.sources.reduce((n,s)=>n+s.reconciliation_drift_count,0),openCircuits=data.sources.filter(s=>s.circuit_state!=='closed').length,blocking=data.findings.filter(f=>f.severity==='blocking').length;
 const tiles:[string,any,string,string][]=[['Sources connected',data.sources.length,'neutral','feeding recovery'],['Authoritative',`${authoritative}/${data.sources.length}`,authoritative===data.sources.length?'success':'warning','carrier-grade feeds'],['Freshness',`${fresh}/${data.sources.length}`,fresh===data.sources.length?'success':'warning','within SLA'],['Dead letters',dlq,dlq?'danger':'success','failed events'],['Reconciliation drift',drift,drift?'danger':'success','mismatched records'],['Circuit breakers',openCircuits?`${openCircuits} open`:'all closed',openCircuits?'danger':'success','source protection']];
 return <>
  <header className="page-head"><div><span>OPERATIONS DATA HEALTH</span><h1>Source readiness &amp; operation gates</h1><p>Freshness, contract, dead-letter and reconciliation checks independently gate solving and carrier publication.</p></div><div className="page-actions"><button onClick={load}><RefreshCw/> Refresh</button></div></header>
  <div className="kpis">{tiles.map(([k,v,tone,sub])=><div className={`kpi ${tone}`} key={k}><span>{k}</span><strong>{v}</strong><small>{sub}</small></div>)}</div>
  <div className="gate-row">
   <div className={`gate ${data.solve_allowed?'ok':'blocked'}`}>{data.solve_allowed?<CheckCircle2/>:<AlertTriangle/>}<div><b>Solve gate</b><span>{data.solve_allowed?'Open — solver may generate recovery plans':'Blocked — inputs unsafe for solving'}</span></div></div>
   <div className={`gate ${data.deployment_allowed?'ok':'blocked'}`}>{data.deployment_allowed?<CheckCircle2/>:<ShieldCheck/>}<div><b>Publication gate</b><span>{data.deployment_allowed?'Open — plans may be published to carrier systems':'Closed — publication requires authoritative, fresh feeds'}</span></div></div>
  </div>
  <section className="card"><header className="rowbetween"><h2>Source systems</h2><span className="muted small">evaluated {data.evaluated_at?new Date(data.evaluated_at).toLocaleTimeString():'now'}</span></header><div className="table-wrap"><table><thead><tr><th>Source</th><th>Authority</th><th>Contract</th><th>Freshness</th><th>DLQ</th><th>Drift</th><th>Circuit</th></tr></thead><tbody>{data.sources.map(s=><tr key={s.source_system}><td><Database/> {s.source_system}</td><td>{s.authoritative?<><CheckCircle2/> Authoritative</>:<><AlertTriangle/> Scenario feed</>}</td><td>{s.contract_version}</td><td>{s.fresh?`${Math.round(s.age_seconds||0)}s old`:'Scenario snapshot'}</td><td>{s.dead_letter_count}</td><td>{s.reconciliation_drift_count}</td><td><span className={`badge ${s.circuit_state==='closed'?'success':'danger'}`}>{s.circuit_state.toUpperCase()}</span></td></tr>)}</tbody></table></div></section>
  {data.findings.length>0&&<section className="card"><header className="rowbetween"><h2>Gate findings</h2><span className={`badge ${blocking?'warning':'success'}`}>{blocking} affect publication</span></header><p className="muted small">These findings keep the carrier-publication gate closed. Solving and plan comparison remain fully available.</p><div className="impact-list">{data.findings.map((f,i)=><span key={`${f.code}-${i}`}><b>{f.code.replaceAll('_',' ')}</b><strong>{f.message}</strong></span>)}</div></section>}
 </>;
}
