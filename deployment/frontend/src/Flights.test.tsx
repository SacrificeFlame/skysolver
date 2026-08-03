import{afterEach,describe,expect,it,vi}from'vitest';
import{cleanup,render,screen,within}from'@testing-library/react';
import React from'react';
import{Flights}from'./App';
import type{Flight}from'./types';
import type{ScenarioCase}from'./scenario';

const flight:Flight={id:'AI421',origin:'DEL',destination:'BOM',aircraft:{registration:'VT-EXA',type:'A321',status:'blocked'},gate:'T3-42',proposed_gate:'T3-46',crew:{id:'IC-184',status:'illegal',duty_remaining:'-00:38',qualifications:['A321']},passengers:186,connections:42,delay:92,state:'recovery_pending',tier:'tier1',risk:'critical'};

function scenarioWith(cases:ScenarioCase[]){return{cases} as any}
function makeCase(over:Partial<ScenarioCase>={}):ScenarioCase{
 return{flight:'AI421',origin:'DEL',destination:'BOM',aircraft:'A321',gate:'T3-42',passengers:186,incumbentId:'IC-184',incumbentName:'Rohit Sharma',requiredQual:'A321',status:'open',...over};
}
function row(){return screen.getByRole('row',{name:/AI421/})}
function draw(cases:ScenarioCase[],deployed=false){
 render(React.createElement(Flights,{flights:[flight],scenario:scenarioWith(cases),deployed,setFlight:vi.fn(),go:vi.fn()}));
}

afterEach(cleanup);

// Regression: this table rendered the backend's static crew record, so a flight
// stayed ILLEGAL no matter what the operator decided or deployed.
describe('Flights crew status',()=>{
 it('shows ILLEGAL while the case is still open',()=>{
  draw([makeCase()]);
  expect(within(row()).getByText('ILLEGAL')).toBeTruthy();
 });

 it('shows the replacement as cleared but not yet legal before deployment',()=>{
  draw([makeCase({status:'resolved',replacementId:'IC-318',replacementName:'Priya Iyer',resolvedVia:'reassign'})]);
  expect(within(row()).getByText('CLEARED · PENDING DEPLOY')).toBeTruthy();
  expect(within(row()).getByText('IC-184 → IC-318')).toBeTruthy();
  expect(within(row()).queryByText('ILLEGAL')).toBeNull();
 });

 it('shows LEGAL once the plan has been deployed',()=>{
  draw([makeCase({status:'resolved',replacementId:'IC-318',replacementName:'Priya Iyer',resolvedVia:'reassign'})],true);
  expect(within(row()).getByText('LEGAL')).toBeTruthy();
  expect(within(row()).getByText('T3-46')).toBeTruthy();
  expect(within(row()).getByText('RECOVERED · +18m')).toBeTruthy();
  expect(within(row()).queryByText('92m')).toBeNull();
 });

 it('shows HUMAN REVIEW for an escalated flight',()=>{
  draw([makeCase({status:'escalated'})]);
  expect(within(row()).getByText('HUMAN REVIEW')).toBeTruthy();
 });

 it('falls back to the backend status when the flight has no case',()=>{
  draw([]);
  expect(within(row()).getByText('ILLEGAL')).toBeTruthy();
 });
});
