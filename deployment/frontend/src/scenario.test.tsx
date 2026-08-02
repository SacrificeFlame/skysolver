import{afterEach,describe,expect,it,vi}from'vitest';
import{act,cleanup,renderHook,waitFor}from'@testing-library/react';
import{aircraftQual,checkLegality,useScenario}from'./scenario';
import type{CrewRosterEntry}from'./types';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});

const crew=(over:Partial<CrewRosterEntry>):CrewRosterEntry=>({id:'IC-1',name:'Test',rank:'Captain',base:'DEL',qualifications:['A321'],status:'standby',duty_remaining:'09:00',rest_hours:12,assigned_flight:null,seniority:5,current_route:null,...over});

describe('legality mirror',()=>{
 it('derives the required type rating from the airframe',()=>{
  expect(aircraftQual('A321neo')).toBe('A321');
  expect(aircraftQual('B787-8')).toBe('B787');
 });
 it('passes a qualified, positioned, rested crew',()=>{
  expect(checkLegality(crew({}),{requiredQual:'A321',origin:'DEL'}).legal).toBe(true);
 });
 it('flags each violation type',()=>{
  expect(checkLegality(crew({qualifications:['A320']}),{requiredQual:'A321',origin:'DEL'}).violations[0]).toContain('type rating');
  expect(checkLegality(crew({base:'BOM'}),{requiredQual:'A321',origin:'DEL'}).violations[0]).toContain('Positioned at BOM');
  expect(checkLegality(crew({rest_hours:8}),{requiredQual:'A321',origin:'DEL'}).violations[0]).toContain('below 10h');
 });
});

describe('scenario state machine',()=>{
 const roster=[
  crew({id:'IC-184',status:'illegal',assigned_flight:'AI421',current_origin:'DEL',current_destination:'BOM',current_aircraft:'A321',current_gate:'T3-42',passengers:186,rest_hours:5}),
  crew({id:'IC-205',name:'Kabir Khan'}),
 ];
 const stub=()=>vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({items:roster})} as Response)));
 it('builds cases from illegal roster entries and resolves them on reassignment',async()=>{
  stub();
  const{result}=renderHook(()=>useScenario());
  await waitFor(()=>expect(result.current.cases.length).toBe(1));
  expect(result.current.cases[0]).toMatchObject({flight:'AI421',status:'open',requiredQual:'A321'});
  act(()=>result.current.reassign('AI421',roster[1]));
  expect(result.current.cases[0].status).toBe('resolved');
  expect(result.current.cases[0].replacementId).toBe('IC-205');
  expect(result.current.stats).toMatchObject({total:1,open:0,resolved:1,escalated:0});
  // The used replacement is no longer offered for other cases.
  expect(result.current.availableFor(result.current.cases[0]).map(c=>c.id)).not.toContain('IC-205');
 });
 it('escalates and reopens without losing the case',async()=>{
  stub();
  const{result}=renderHook(()=>useScenario());
  await waitFor(()=>expect(result.current.cases.length).toBe(1));
  act(()=>result.current.escalate('AI421'));
  expect(result.current.cases[0].status).toBe('escalated');
  expect(result.current.stats.escalated).toBe(1);
  act(()=>result.current.reopen('AI421'));
  expect(result.current.cases[0].status).toBe('open');
 });
});
