import{afterEach,describe,expect,it,vi}from'vitest';
import{cleanup,fireEvent,render,screen}from'@testing-library/react';
import DataHealthWorkspace from'./DataHealthWorkspace';
import SolverWorkspace from'./SolverWorkspace';
import Tier3Workspace from'./Tier3Workspace';
import{Deployment}from'./App';
import type{Recovery}from'./types';
import type{Scenario}from'./scenario';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});
const ok=(data:unknown)=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(data)} as Response);
const fail=(status:number,data:unknown={})=>Promise.resolve({ok:false,status,json:()=>Promise.resolve(data)} as Response);

describe('Data Health workspace states',()=>{
 it('shows a loading state, then the source table and blocked gate',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>ok({status:'blocked_for_operations',solve_allowed:true,deployment_allowed:false,evaluated_at:'',sources:[{source_system:'scenario-fixture',authoritative:false,contract_version:'fixture-v1',fresh:false,age_seconds:null,dead_letter_count:0,reconciliation_drift_count:0,circuit_state:'closed',findings:[]}],findings:[{code:'SOURCE_NOT_AUTHORITATIVE',severity:'blocking',message:'not authoritative'}]})));
  render(<DataHealthWorkspace/>);
  expect(screen.getByText(/Evaluating source systems/i)).toBeTruthy();
  await screen.findByText(/operation gates/i);
  expect(screen.getByText(/scenario-fixture/)).toBeTruthy();
  expect(screen.getByText(/Closed — publication requires/i)).toBeTruthy();
 });
 it('shows an explicit unavailable state on error',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>fail(503,{message:'health down'})));
  render(<DataHealthWorkspace/>);
  await screen.findByText(/Data health unavailable/i);
 });
});

describe('Solver tier workspace truthful states',()=>{
 it('renders a Tier 2 solver_unavailable banner without inventing success',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>ok({generated_at:'',partition_id:'X',ruleset_version:'r',data_mode:'d',tiers:[{id:'tier2',name:'Optimization Upgrade',status:'solver_unavailable',coverage:1,legal_assignments:5,unresolved:0,elapsed_s:0.001,reason:"No module named 'pyomo'",solver_name:'highs',generated_columns:7,upgraded:false,objective_value:null,best_bound:null,optimality_gap:null}]})));
  render(<SolverWorkspace selected="tier2" onOpen={()=>{}}/>);
  await screen.findByText(/no result is fabricated/i);
  expect(screen.getByText(/No certified gap/i)).toBeTruthy();
 });
 it('shows an error state when telemetry fails',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>fail(500,{message:'solver error'})));
  render(<SolverWorkspace onOpen={()=>{}}/>);
  await screen.findByText(/Solver telemetry unavailable/i);
 });
});

describe('Tier 3 workspace states',()=>{
 const baseScenario={loading:false,error:'',roster:[],cases:[],usedCrew:new Set<string>(),spares:[],reload:()=>{},reset:()=>{},availableFor:()=>[],reassign:()=>{},overrideAssign:()=>{},escalate:()=>{},reopen:()=>{},stats:{total:0,open:0,resolved:0,escalated:0,pax:0,paxResolved:0,coverage:0}} as unknown as Scenario;
 it('shows a clear queue when nothing is escalated',()=>{
  render(<Tier3Workspace scenario={baseScenario} go={()=>{}}/>);
  expect(screen.getByText(/Human review queue is clear/i)).toBeTruthy();
 });
 it('offers ranked options with residual risk for an escalated case',()=>{
  const crew={id:'IC-507',name:'Dev Patel',rank:'Captain',base:'BOM',qualifications:['B787'],status:'reserve',duty_remaining:'07:40',rest_hours:9,assigned_flight:null,seniority:13,current_route:null};
  const esc={flight:'AI807',origin:'BOM',destination:'DEL',aircraft:'B787-8',gate:'T2-16',passengers:242,incumbentId:'IC-333',incumbentName:'Meera Nair',requiredQual:'B787',status:'escalated' as const};
  const overrideAssign=vi.fn();
  const scenario={...baseScenario,cases:[esc],availableFor:()=>[crew],overrideAssign} as unknown as Scenario;
  render(<Tier3Workspace scenario={scenario} go={()=>{}}/>);
  expect(screen.getAllByText(/RESIDUAL RISK/i).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole('button',{name:/Accept override/i}));
  expect(overrideAssign).toHaveBeenCalledWith('AI807',crew);
 });
});

describe('Deployment authority separation',()=>{
 const recovery={id:'R1',disruption_id:'D',partition_id:'DEL',objective:'balanced',status:'awaiting_joint_feasibility',stage:'',tier:'tier1',progress:90,state_version:3,selected_candidate_id:'C1',validated:true,deployed:false,approvals:[],acknowledgements:[],carrier_writes_enabled:false,created_at:'',updated_at:'',candidates:[{id:'C1',joint_feasibility:{status:'not_evaluated',deployable:false,findings:[{code:'AUTHORITATIVE_RESOURCE_DATA_REQUIRED',blocking:true,message:'resource data required'}]}}]} as unknown as Recovery;
 it('gates approval on a reason and calls authorize, not deploy',()=>{
  const authorize=vi.fn(),deployNow=vi.fn();
  const{rerender}=render(<Deployment recovery={recovery} approvalReason="" setApprovalReason={()=>{}} authorize={authorize} deployNow={deployNow} validate={()=>{}} busy={false}/>);
  expect(screen.getByText(/Duty-manager approval/i)).toBeTruthy();
  const btn=screen.getByRole('button',{name:/Authorize as duty manager/i})as HTMLButtonElement;
  expect(btn.disabled).toBe(true); // reason too short
  rerender(<Deployment recovery={recovery} approvalReason="Reviewed and sound" setApprovalReason={()=>{}} authorize={authorize} deployNow={deployNow} validate={()=>{}} busy={false}/>);
  const btn2=screen.getByRole('button',{name:/Authorize as duty manager/i})as HTMLButtonElement;
  expect(btn2.disabled).toBe(false);
  fireEvent.click(btn2);
  expect(authorize).toHaveBeenCalledWith('Reviewed and sound');
  expect(deployNow).not.toHaveBeenCalled();
 });
 it('shows the deployment result with a partial state and ack grid',()=>{
  const deployed={...recovery,approvals:[{role:'duty-manager',reason:'ok'}],simulated:true,deployment_status:'partial',deployment_id:'DEP-ABC123',acknowledgements:[{resource:'crew:SIM-001',status:'acknowledged'},{resource:'gate:BLR:D08',status:'timed_out'},{resource:'passenger:6E203',status:'rejected',detail:'adapter declined'}]} as unknown as Recovery;
  render(<Deployment recovery={deployed} approvalReason="" setApprovalReason={()=>{}} authorize={()=>{}} deployNow={()=>{}} validate={()=>{}} busy={false}/>);
  expect(screen.getByText(/Deployment result/i)).toBeTruthy();
  expect(screen.getAllByText(/PARTIAL/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/crew:SIM-001/)).toBeTruthy();
  expect(screen.getByText(/require retry or compensation/i)).toBeTruthy();
 });
 it('shows the no-recovery empty state',()=>{
  render(<Deployment recovery={null} approvalReason="" setApprovalReason={()=>{}} authorize={()=>{}} deployNow={()=>{}} validate={()=>{}} busy={false}/>);
  expect(screen.getByText(/No recovery in progress/i)).toBeTruthy();
 });
});
