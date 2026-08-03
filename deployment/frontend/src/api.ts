import type {AgentRun,AgentToolset,Audit,Candidate,CandidateExplanation,CrewRosterEntry,DataHealth,Deployment,Disruption,Envelope,FleetAircraft,Flight,Overview,PlannedRoute,Provenance,ReassignmentPreview,Recovery,RouteValidation,RuleViolation,SearchResult,SolverTier,Tier3Queue} from './types';

// Typed failure that preserves the backend contract fields the operator UI needs.
// Never invents success: it exposes the exact HTTP status, correlation id, the
// server's authoritative state_version (for optimistic-concurrency recovery) and
// any structured rule findings so callers can render truthful blocked states.
export class ApiError extends Error{
  readonly status:number;
  readonly code?:string;
  readonly permission?:string;
  readonly correlationId?:string;
  readonly stateVersion?:number;
  readonly ruleViolations:RuleViolation[];
  readonly body:unknown;
  constructor(status:number,body:any){
    // Two server error shapes: WorkflowError -> {error,message,correlation_id,rule_violations};
    // FastAPI HTTPException -> {detail:{code,message,permission}} or {detail:"..."}.
    const detail=body&&typeof body.detail==='object'&&!Array.isArray(body.detail)?body.detail:undefined;
    super(body?.message||body?.error||detail?.message||(typeof body?.detail==='string'?body.detail:undefined)||detail?.code||`Request failed (${status||'network error'})`);
    this.name='ApiError';
    this.status=status;
    this.body=body;
    this.code=body?.error||detail?.code;
    this.permission=detail?.permission;
    this.correlationId=body?.correlation_id;
    this.stateVersion=typeof body?.state_version==='number'?body.state_version:undefined;
    this.ruleViolations=Array.isArray(body?.rule_violations)?body.rule_violations:[];
  }
  /** 409 stale_state: the plan advanced elsewhere; preserve the operator's input and retry against the fresh version. */
  get isStale():boolean{return this.status===409&&this.code!=='resource_conflict'}
  /** 409 resource_conflict: crew/aircraft/gates are held by another recovery. Retrying the same call cannot succeed. */
  get isResourceConflict():boolean{return this.status===409&&this.code==='resource_conflict'}
  /** The resources named in a hold conflict, parsed from the server message. */
  get heldResources():string[]{
    if(!this.isResourceConflict)return[];
    const tail=this.message.split(':').slice(1).join(':');
    return tail.split(',').map(s=>s.trim()).filter(Boolean);
  }
  /** 422: the backend rejected the request as invalid/illegal; no candidate is approved. */
  get isValidation():boolean{return this.status===422}
  /** 401/403: caller lacks authority (approval/deploy need stepped-up auth). */
  get isPermission():boolean{return this.status===401||this.status===403}
}
async function request<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await fetch(path,{...init,headers:{'Content-Type':'application/json',...(init?.headers||{})}});
  let data:any=undefined;
  try{data=await response.json()}catch{data=undefined} // tolerate empty / non-JSON error bodies
  if(response.status===401&&typeof window!=='undefined'&&window.location.pathname!=='/'){
    // Session expired / not authenticated: bounce to the sign-in page instead of
    // surfacing a raw auth error. Real product behaviour, not a demo dead-end.
    try{window.location.assign('/')}catch{/* jsdom / non-browser */}
  }
  if(!response.ok)throw new ApiError(response.status,data);
  return data as T;
}
const operationId=():string=>globalThis.crypto?.randomUUID?.()||`demo-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const mutationHeaders=(stateVersion=0,idempotencyKey:string=operationId())=>({'Idempotency-Key':idempotencyKey,'Expected-State-Version':String(stateVersion),'X-Correlation-ID':operationId(),'X-Causation-ID':operationId()});
export const api={
  health:()=>request<{status:string;component:string}>('/api/v1/health/live'),
  login:(username:string,password:string,role?:string)=>request<{ok:boolean;operator:{subject:string;role:string}}>('/api/login',{method:'POST',body:JSON.stringify({username,password,role})}),
  simulateDeployment:(id:string,state_version:number)=>request<Envelope>(`/api/v1/recoveries/${id}/deployments/simulate`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({})}),
  overview:()=>request<Overview>('/api/v1/overview'),
  disruptions:()=>request<{items:Disruption[];provenance?:Provenance}>('/api/v1/disruptions'),
  dataHealth:()=>request<DataHealth>('/api/v1/data-health'),
  flight:(id:string)=>request<Flight>(`/api/v1/flights/${id}`),
  crew:()=>request<{items:CrewRosterEntry[]}>('/api/v1/crew'),
  aircraft:()=>request<{items:FleetAircraft[]}>('/api/v1/aircraft'),
  reassignmentPreview:(flightId:string,crewId:string)=>request<ReassignmentPreview>(`/api/v1/flights/${flightId}/reassignment-preview`,{method:'POST',body:JSON.stringify({crew_id:crewId})}),
  routes:()=>request<{items:PlannedRoute[];data_mode:string;provenance?:Provenance}>('/api/v1/routes'),
  route:(id:string)=>request<PlannedRoute>(`/api/v1/routes/${id}`),
  validateRoute:(id:string)=>request<RouteValidation>(`/api/v1/routes/${id}/validate`,{method:'POST',headers:mutationHeaders(1),body:JSON.stringify({})}),
  solverTiers:()=>request<{generated_at:string;partition_id:string;ruleset_version:string;data_mode:string;provenance?:Provenance;tiers:SolverTier[]}>('/api/v1/solver-tiers'),
  createRecovery:(disruption_id:string,partition_id='DEL',objective='balanced')=>request<Envelope>('/api/v1/recoveries',{method:'POST',headers:mutationHeaders(0),body:JSON.stringify({disruption_id,partition_id,objective})}),
  recovery:(id:string)=>request<Recovery>(`/api/v1/recoveries/${id}`),
  candidates:(id:string)=>request<{items:Candidate[]}>(`/api/v1/recoveries/${id}/candidates`),
  candidateExplanation:(candidateId:string,recoveryId:string)=>request<CandidateExplanation>(`/api/v1/candidates/${candidateId}/explanation?recovery_id=${recoveryId}`),
  holdCandidate:(recoveryId:string,candidateId:string,state_version:number)=>request<Envelope>(`/api/v1/candidates/${candidateId}/hold?recovery_id=${recoveryId}`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({})}),
  tier3Suggestions:(id:string,offset=0,limit=50)=>request<Tier3Queue>(`/api/v1/recoveries/${id}/suggestions?offset=${offset}&limit=${limit}`),
  decideTier3:(id:string,suggestionId:string,stateVersion:number,action:'approve'|'reject'|'hold'|'edit'|'request_more_options',reason='',crew_id?:string,flight_id?:string)=>request<Envelope>(`/api/v1/recoveries/${id}/suggestions/${suggestionId}/decisions`,{method:'POST',headers:mutationHeaders(stateVersion),body:JSON.stringify({action,reason,crew_id,flight_id})}),
  decide:(id:string,state_version:number,candidate_id:string,action='approve',reason='')=>request<Envelope>(`/api/v1/recoveries/${id}/decisions`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({candidate_id,action,reason})}),
  validate:(id:string,state_version:number,candidate_id='')=>request<Envelope>(`/api/v1/candidates/${candidate_id}/validate?recovery_id=${id}`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({})}),
  // Approval is a distinct authority step from deployment (duty-manager grants approval).
  approve:(id:string,state_version:number,reason:string)=>request<Envelope>(`/api/v1/recoveries/${id}/approvals`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({reason})}),
  deploy:(id:string,state_version:number)=>request<Envelope>(`/api/v1/recoveries/${id}/deployments`,{method:'POST',headers:mutationHeaders(state_version,`deploy-${id}-${state_version}`),body:JSON.stringify({})}),
  deployment:(id:string)=>request<Deployment>(`/api/v1/deployments/${id}`),
  retryDeployment:(id:string,state_version:number,command_id:string)=>request<Envelope>(`/api/v1/deployments/${id}/retry`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({command_id})}),
  compensateDeployment:(id:string,state_version:number,reason:string)=>request<Envelope>(`/api/v1/deployments/${id}/compensate`,{method:'POST',headers:mutationHeaders(state_version),body:JSON.stringify({reason})}),
  search:(q:string)=>request<{items:SearchResult[];query:string;authoritative:boolean}>(`/api/v1/search?q=${encodeURIComponent(q)}`),
  audit:()=>request<{items:Audit[];immutable?:boolean;storage?:string}>('/api/v1/audit'),
  note:(action:string,detail:string)=>request<{ok:boolean}>('/api/v1/audit',{method:'POST',body:JSON.stringify({action,detail})}),
  // Recovery agent. An LLM planner that is unconfigured or rate-limited degrades
  // to the deterministic planner server-side; the response says which one ran.
  // Role elevation without re-authenticating. The console must act as a
  // different role per governance step; doing that by signing in again meant
  // shipping the demo password in this bundle.
  assumeRole:(role:'scheduler-demo'|'duty-manager'|'deployment-controller')=>request<{ok:boolean;operator:{subject:string;role:string}}>('/api/v1/session/role',{method:'POST',body:JSON.stringify({role})}),
  agentTools:()=>request<AgentToolset>('/api/v1/agent/tools'),
  agentRun:(planner:'deterministic'|'gemini'|'openai'='deterministic')=>request<AgentRun>('/api/v1/agent/run',{method:'POST',body:JSON.stringify({planner})})
};
