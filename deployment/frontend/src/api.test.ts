import{afterEach,describe,expect,it,vi}from'vitest';
import{api}from'./api';

afterEach(()=>vi.unstubAllGlobals());
function response(data:unknown,ok=true){return Promise.resolve({ok,json:()=>Promise.resolve(data)} as Response)}

describe('operations API client',()=>{
 it('requests backend route validation',async()=>{const fetch=vi.fn(()=>response({legal:true,checks:{airport_sequence:true}}));vi.stubGlobal('fetch',fetch);const result=await api.validateRoute('AI421');expect(result.legal).toBe(true);expect(fetch).toHaveBeenCalledWith('/api/v1/routes/AI421/validate',expect.objectContaining({method:'POST'}))});
 it('loads executable solver telemetry',async()=>{vi.stubGlobal('fetch',vi.fn(()=>response({tiers:[{id:'tier1',coverage:1}]})));const result=await api.solverTiers();expect(result.tiers[0].id).toBe('tier1')});
 it('surfaces backend errors',async()=>{vi.stubGlobal('fetch',vi.fn(()=>response({message:'illegal route'},false)));await expect(api.validateRoute('BAD')).rejects.toThrow('illegal route')});
});
