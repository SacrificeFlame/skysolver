import type {Audit,DataHealth,Disruption,Envelope,Flight,PlannedRoute,Recovery,RouteValidation,SolverTier,Tier3Queue} from './types';
async function request<T>(path:string,init?:RequestInit):Promise<T>{const response=await fetch(path,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}});const data=await response.json();if(!response.ok)throw new Error(data.message||data.error||'Request failed');return data}
const operationId=():string=>globalThis.crypto?.randomUUID?.()||`demo-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const mutationHeaders=(stateVersion=0,idempotencyKey:string=operationId())=>({'Idempotency-Key':idempotencyKey,'Expected-State-Version':String(stateVersion),'X-Correlation-ID':operationId(),'X-Causation-ID':operationId()});
export const api={
  disruptions:()=>request<{items:Disruption[]}>('/api/v1/disruptions'),
  dataHealth:()=>request<DataHealth>('/api/v1/data-health'),
  flight:(id:string)=>request<Flight>(`/api/v1/flights/${id}`),
  routes:()=>request<{items:PlannedRoute[];data_mode:string}>('/api/v1/routes'),
  route:(id:string)=>request<PlannedRoute>(`/api/v1/routes/${id}`),
  validateRoute:(id:string)=>request<RouteValidation>(`/api/v1/routes/${id}/validate`,{method:'POST',headers:mutationHeaders(1),body:JSON.stringify({})}),
  solverTiers:()=>request<{generated_at:string;partition_id:string;ruleset_version:string;data_mode:string;tiers:SolverTier[]}>('/api/v1/solver-tiers'),
  createRecovery:(disruption_id:string)=>request<Envelope>('/api/v1/recoveries',{method:'POST',headers:mutationHeaders(0),body:JSON.stringify({disruption_id,partition_id:'DEL',objective:'balanced'})}),
  recovery:(id:string)=>request<Recovery>(`/api/v1/recoveries/${id}`),
  tier3Suggestions:(id:string,offset=0,limit=50)=>request<Tier3Queue>(`/api/v1/recoveries/${id}/suggestions?offset=${offset}&limit=${limit}`),
  decideTier3:(id:string,suggestionId:string,stateVersion:number,action:'approve'|'reject'|'hold'|'edit'|'request_more_options',reason='',crew_id?:string,flight_id?:string)=>request<Envelope>(`/api/v1/recoveries/${id}/suggestions/${suggestionId}/decisions`,{method:'POST',headers:mutationHeaders(stateVersion),body:JSON.stringify({action,reason,crew_id,flight_id})}),
  decide:(id:string,state_version:number,candidate_id:string,action='approve',reason='')=>request<Envelope>(`/api/v1/recoveries/${id}/decisions`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({candidate_id,action,reason})}),
  validate:(id:string,state_version:number,candidate_id='')=>request<Envelope>(`/api/v1/candidates/${candidate_id}/validate?recovery_id=${id}`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({})}),
  deploy:(id:string,state_version:number)=>request<Envelope>(`/api/v1/recoveries/${id}/deployments`,{method:'POST',headers:mutationHeaders(state_version,`deploy-${id}-${state_version}`),body:JSON.stringify({})}),
  audit:()=>request<{items:Audit[]}>('/api/v1/audit')
};
