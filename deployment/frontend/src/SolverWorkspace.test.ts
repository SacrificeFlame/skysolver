import{describe,expect,it}from'vitest';
import{tierViability}from'./SolverWorkspace';

describe('tier viability classification',()=>{
 it('marks a solver_unavailable tier as unavailable and never viable',()=>{
  const v=tierViability('solver_unavailable');
  expect(v.unavailable).toBe(true);
  expect(v.tone).toBe('danger');
 });
 it('treats partial / standby as risk, not success or failure',()=>{
  expect(tierViability('partial').tone).toBe('warning');
  expect(tierViability('standby').unavailable).toBe(false);
 });
 it('treats viable / optimal / ready as success',()=>{
  expect(tierViability('viable').tone).toBe('success');
  expect(tierViability('optimal').tone).toBe('success');
  expect(tierViability('ready').tone).toBe('success');
 });
 it('never crashes on an empty status',()=>{
  expect(tierViability('').label).toBe('viable');
 });
});
