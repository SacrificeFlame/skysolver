import{useEffect,useState}from'react';
import{AlertTriangle,CheckCircle2,Database,RefreshCw}from'lucide-react';
import{api}from'./api';
import type{DataHealth}from'./types';

export default function DataHealthWorkspace(){
 const[data,setData]=useState<DataHealth|null>(null),[error,setError]=useState('');
 const load=()=>{setError('');api.dataHealth().then(setData).catch(e=>setError(e.message))};useEffect(load,[]);
 if(error)return <section className="empty"><AlertTriangle/><h2>Data health unavailable</h2><p>{error}</p><button onClick={load}>Retry</button></section>;
 if(!data)return <section className="empty"><RefreshCw className="spin"/><h2>Evaluating source systems</h2></section>;
 return <><header className="page-head"><div><span>OPERATIONS DATA HEALTH</span><h1>Authoritative-source readiness</h1><p>Freshness, contract, dead-letter and reconciliation findings independently gate solving and deployment.</p></div><div className="page-actions"><span className={`badge ${data.deployment_allowed?'success':'danger'}`}>{data.deployment_allowed?'DEPLOYMENT ALLOWED':'DEPLOYMENT BLOCKED'}</span><button onClick={load}><RefreshCw/> Refresh</button></div></header><div className="fact-strip"><span>Solve gate<b>{data.solve_allowed?'Allowed':'Blocked'}</b></span><span>Deployment gate<b>{data.deployment_allowed?'Allowed':'Blocked'}</b></span><span>Sources<b>{data.sources.length}</b></span><span>Findings<b>{data.findings.length}</b></span></div><section className="card"><div className="table-wrap"><table><thead><tr><th>Source</th><th>Authority</th><th>Contract</th><th>Freshness</th><th>DLQ</th><th>Drift</th><th>Circuit</th></tr></thead><tbody>{data.sources.map(s=><tr key={s.source_system}><td><Database/> {s.source_system}</td><td>{s.authoritative?<><CheckCircle2/> Authoritative</>:<><AlertTriangle/> Non-authoritative</>}</td><td>{s.contract_version}</td><td>{s.fresh?`${Math.round(s.age_seconds||0)}s old`:'Stale / unavailable'}</td><td>{s.dead_letter_count}</td><td>{s.reconciliation_drift_count}</td><td>{s.circuit_state}</td></tr>)}</tbody></table></div></section>{data.findings.length>0&&<section className="card"><h2>Blocking findings</h2><div className="impact-list">{data.findings.map((f,i)=><span key={`${f.code}-${i}`}><b>{f.code.replaceAll('_',' ')}</b><strong>{f.message}</strong></span>)}</div></section>}</>
}
