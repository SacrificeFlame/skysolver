import type {Audit,Disruption,Envelope,Flight,PlannedRoute,Recovery} from './types';
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(path,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}});const data=await response.json();if(!response.ok)throw new Error(data.message||data.error||'Request failed');return data}
export const api={
  disruptions:()=>request<{items:Disruption[]}>('/api/v1/disruptions'),
  flight:(id:string)=>request<Flight>(`/api/v1/flights/${id}`),
  routes:()=>request<{items:PlannedRoute[];data_mode:string}>('/api/v1/routes'),
  route:(id:string)=>request<PlannedRoute>(`/api/v1/routes/${id}`),
  createRecovery:(disruption_id:string)=>request<Envelope>('/api/v1/recoveries',{method:'POST',body:JSON.stringify({disruption_id,partition_id:'DEL',objective:'balanced'})}),
  recovery:(id:string)=>request<Recovery>(`/api/v1/recoveries/${id}`),
  decide:(id:string,state_version:number,candidate_id:string,action='approve',reason='')=>request<Envelope>(`/api/v1/recoveries/${id}/decisions`,{method:'POST',body:JSON.stringify({state_version,candidate_id,action,reason,operator_id:'ops-controller'})}),
  validate:(id:string,state_version:number)=>request<Envelope>(`/api/v1/recoveries/${id}/validate`,{method:'POST',body:JSON.stringify({state_version,operator_id:'ops-controller'})}),
  deploy:(id:string,state_version:number)=>request<Envelope>(`/api/v1/recoveries/${id}/deploy`,{method:'POST',headers:{'Idempotency-Key':`deploy-${id}-${state_version}`},body:JSON.stringify({state_version,operator_id:'ops-controller'})}),
  rollback:(id:string,state_version:number)=>request<Envelope>(`/api/v1/recoveries/${id}/rollback`,{method:'POST',body:JSON.stringify({state_version,operator_id:'ops-controller',reason:'Operational rollback'})}),
  audit:()=>request<{items:Audit[]}>('/api/v1/audit')
};
