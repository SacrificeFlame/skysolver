import{describe,expect,it}from'vitest';
import{flightGroundState,impactOf}from'./AirportView';
import type{Flight}from'./types';
import type{ScenarioCase}from'./scenario';

const flight=(over:Partial<Flight>):Flight=>({id:'AI421',origin:'DEL',destination:'BOM',aircraft:{registration:'VT-EXA',type:'A321',status:'blocked'},gate:'T3-42',proposed_gate:'T3-46',crew:{id:'IC-184',status:'illegal',duty_remaining:'-00:38',qualifications:['A321']},passengers:186,connections:42,delay:92,state:'recovery_pending',tier:'tier1',risk:'critical',...over});
const kase=(status:ScenarioCase['status'],over:Partial<ScenarioCase>={}):ScenarioCase=>({flight:'AI421',origin:'DEL',destination:'BOM',aircraft:'A321',gate:'T3-42',passengers:186,incumbentId:'IC-184',incumbentName:'Rohit Sharma',requiredQual:'A321',status,...over});

describe('airport ground-state derivation',()=>{
 it('an open crew case dominates the airframe state',()=>{
  const s=flightGroundState(flight({}),kase('open'));
  expect(s.label).toBe('CREW ILLEGAL');expect(s.tone).toBe('danger');
 });
 it('escalated cases read as Tier 3 review',()=>{
  expect(flightGroundState(flight({}),kase('escalated')).tone).toBe('purple');
 });
 it('a resolved case shows the replacement crew and how it was resolved',()=>{
  const s=flightGroundState(flight({}),kase('resolved',{replacementId:'IC-533',resolvedVia:'reassign'}));
  expect(s.label).toBe('CREW IC-533');expect(s.tone).toBe('success');expect(s.detail).toBe('reassigned');
  expect(flightGroundState(flight({}),kase('resolved',{replacementId:'IC-507',resolvedVia:'override'})).detail).toBe('override accepted');
 });
 it('falls back to the airframe state without a case',()=>{
  expect(flightGroundState(flight({})).label).toBe('AIRCRAFT BLOCK');
  expect(flightGroundState(flight({aircraft:{registration:'VT-ANR',type:'B787-8',status:'inbound'},origin:'BOM'})).tone).toBe('cyan');
  expect(flightGroundState(flight({aircraft:{registration:'VT-IZR',type:'A320neo',status:'ready'}})).tone).toBe('success');
 });
 it('classifies delay impact',()=>{
  expect(impactOf(92)).toBe('high');expect(impactOf(48)).toBe('moderate');expect(impactOf(43)).toBe('low');
 });
});
