import{afterEach,describe,expect,it,vi}from'vitest';
import{api,ApiError}from'./api';

afterEach(()=>vi.unstubAllGlobals());
function response(data:unknown,ok=true){return Promise.resolve({ok,json:()=>Promise.resolve(data)} as Response)}
function errResponse(status:number,data:unknown){return Promise.resolve({ok:false,status,json:()=>Promise.resolve(data)} as Response)}

describe('operations API client',()=>{
 it('requests backend route validation',async()=>{const fetch=vi.fn(()=>response({legal:true,checks:{airport_sequence:true}}));vi.stubGlobal('fetch',fetch);const result=await api.validateRoute('AI421');expect(result.legal).toBe(true);expect(fetch).toHaveBeenCalledWith('/api/v1/routes/AI421/validate',expect.objectContaining({method:'POST'}))});
 it('loads executable solver telemetry',async()=>{vi.stubGlobal('fetch',vi.fn(()=>response({tiers:[{id:'tier1',coverage:1}]})));const result=await api.solverTiers();expect(result.tiers[0].id).toBe('tier1')});
 it('surfaces backend errors',async()=>{vi.stubGlobal('fetch',vi.fn(()=>response({message:'illegal route'},false)));await expect(api.validateRoute('BAD')).rejects.toThrow('illegal route')});
});

describe('typed contract-preserving errors',()=>{
 it('raises a typed ApiError preserving correlation, state version and rule findings',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>errResponse(422,{message:'illegal candidate',correlation_id:'corr-1',state_version:7,rule_violations:[{code:'DUTY_LIMIT',message:'Duty over limit',rule_ref:'FAR-117.13'}]})));
  const err=(await api.decide('R1',7,'C1').catch(e=>e)) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(422);
  expect(err.isValidation).toBe(true);
  expect(err.isStale).toBe(false);
  expect(err.correlationId).toBe('corr-1');
  expect(err.stateVersion).toBe(7);
  expect(err.ruleViolations[0].code).toBe('DUTY_LIMIT');
 });
 it('flags a 409 stale-state conflict distinctly and exposes the fresh version',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>errResponse(409,{message:'stale state',state_version:9})));
  const err=(await api.deploy('R1',3).catch(e=>e)) as ApiError;
  expect(err.isStale).toBe(true);
  expect(err.isValidation).toBe(false);
  expect(err.stateVersion).toBe(9);
 });
 it('flags permission failures',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>errResponse(403,{message:'forbidden'})));
  const err=(await api.deploy('R1',1).catch(e=>e)) as ApiError;
  expect(err.isPermission).toBe(true);
  expect(err.ruleViolations).toEqual([]);
 });
 it('does not crash on an empty or non-JSON error body',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:false,status:500,json:()=>Promise.reject(new Error('not json'))} as unknown as Response)));
  const err=(await api.disruptions().catch(e=>e)) as ApiError;
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(500);
  expect(err.message).toContain('Request failed');
  expect(err.ruleViolations).toEqual([]);
 });
 it('parses FastAPI permission-denied detail shape',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>errResponse(403,{detail:{code:'permission_denied',permission:'approve'}})));
  const err=(await api.approve('R1',5,'duty manager approval').catch(e=>e)) as ApiError;
  expect(err.isPermission).toBe(true);
  expect(err.code).toBe('permission_denied');
  expect(err.permission).toBe('approve');
  expect(err.message).toContain('permission_denied');
 });
});

describe('full contract endpoints',()=>{
 it('requests approvals separately from deployments',async()=>{
  const fetch=vi.fn((_p:string,_i?:RequestInit)=>response({recovery:{id:'R1'}}));vi.stubGlobal('fetch',fetch);
  await api.approve('R1',4,'duty manager sign-off');
  expect(fetch).toHaveBeenCalledWith('/api/v1/recoveries/R1/approvals',expect.objectContaining({method:'POST'}));
  const init=fetch.mock.calls[0][1]!;
  expect((init.headers as Record<string,string>)['Expected-State-Version']).toBe('4');
 });
 it('loads recovery candidates',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>response({items:[{id:'CAN-1'}]})));
  const result=await api.candidates('R1');
  expect(result.items[0].id).toBe('CAN-1');
 });
 it('reads a deployment record',async()=>{
  const fetch=vi.fn((_p:string,_i?:RequestInit)=>response({id:'DEP-1',status:'partial',acknowledgements:[]}));vi.stubGlobal('fetch',fetch);
  const result=await api.deployment('DEP-1');
  expect(result.status).toBe('partial');
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/deployments/DEP-1');
 });
});
