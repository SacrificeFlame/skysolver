import{afterEach,describe,expect,it,vi}from'vitest';
import{describeFailure}from'./App';
import{ApiError}from'./api';
import type{Recovery}from'./types';

afterEach(()=>vi.unstubAllGlobals());
const recovery={id:'R1',state_version:3}as Recovery;
const noop=()=>{};

describe('describeFailure operator messaging',()=>{
 it('preserves operator work and refreshes state on a 409 stale conflict',async()=>{
  const fresh={id:'R1',state_version:9}as Recovery;
  vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:true,json:()=>Promise.resolve(fresh)} as Response)));
  const setRecovery=vi.fn();
  const message=describeFailure(new ApiError(409,{state_version:9}),recovery,setRecovery);
  expect(message).toContain('preserved');
  expect(message).toContain('v9');
  await vi.waitFor(()=>expect(setRecovery).toHaveBeenCalledWith(fresh));
 });
 it('reports validation findings without implying approval',()=>{
  const err=new ApiError(422,{rule_violations:[{code:'DUTY_LIMIT',message:'x',rule_ref:'FAR-117.13'}]});
  const message=describeFailure(err,recovery,noop);
  expect(message).toContain('1 rule finding');
  expect(message).toContain('No candidate was approved');
 });
 it('explains permission failures',()=>{
  expect(describeFailure(new ApiError(403,{message:'forbidden'}),recovery,noop)).toContain('Not authorized');
 });
 it('appends correlation id for other typed failures',()=>{
  expect(describeFailure(new ApiError(500,{message:'boom',correlation_id:'corr-9'}),recovery,noop)).toBe('boom (correlation corr-9)');
 });
 it('falls back to plain error and unknown messages',()=>{
  expect(describeFailure(new Error('plain'),recovery,noop)).toBe('plain');
  expect(describeFailure('weird',recovery,noop)).toBe('Action failed');
 });
});
