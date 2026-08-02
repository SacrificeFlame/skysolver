import{afterEach,describe,expect,it,vi}from'vitest';
import{cleanup,fireEvent,render,screen}from'@testing-library/react';
import DataHealthWorkspace from'./DataHealthWorkspace';
import SolverWorkspace from'./SolverWorkspace';
import Tier3Workspace from'./Tier3Workspace';
import{Deployment}from'./App';
import type{Recovery}from'./types';

afterEach(()=>{cleanup();vi.unstubAllGlobals()});
const ok=(data:unknown)=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(data)} as Response);
const fail=(status:number,data:unknown={})=>Promise.resolve({ok:false,status,json:()=>Promise.resolve(data)} as Response);

describe('Data Health workspace states',()=>{
 it('shows a loading state, then the source table and blocked gate',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>ok({status:'blocked_for_operations',solve_allowed:true,deployment_allowed:false,evaluated_at:'',sources:[{source_system:'scenario-fixture',authoritative:false,contract_version:'fixture-v1',fresh:false,age_seconds:null,dead_letter_count:0,reconciliation_drift_count:0,circuit_state:'closed',findings:[]}],findings:[{code:'SOURCE_NOT_AUTHORITATIVE',severity:'blocking',message:'not authoritative'}]})));
  render(<DataHealthWorkspace/>);
  expect(screen.getByText(/Evaluating source systems/i)).toBeTruthy();
  await screen.findByText(/Authoritative-source readiness/i);
  expect(screen.getByText(/scenario-fixture/)).toBeTruthy();
  expect(screen.getByText(/DEPLOYMENT BLOCKED/i)).toBeTruthy();
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
 it('shows an error state when telemetry is unauthorized',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>fail(401,{detail:{code:'authentication_required'}})));
  render(<SolverWorkspace onOpen={()=>{}}/>);
  await screen.findByText(/Solver telemetry unavailable/i);
 });
});

describe('Tier 3 workspace guard state',()=>{
 it('guards when no recovery exists',()=>{
  render(<Tier3Workspace recovery={null} onRecovery={()=>{}} onStart={()=>{}}/>);
  expect(screen.getByText(/No active recovery/i)).toBeTruthy();
 });
});

describe('Deployment authority separation',()=>{
 const recovery={id:'R1',disruption_id:'D',partition_id:'DEL',objective:'balanced',status:'awaiting_joint_feasibility',stage:'',tier:'tier1',progress:90,state_version:3,selected_candidate_id:'C1',validated:true,deployed:false,approvals:[],acknowledgements:[],carrier_writes_enabled:false,created_at:'',updated_at:'',candidates:[{id:'C1',joint_feasibility:{status:'not_evaluated',deployable:false,findings:[{code:'AUTHORITATIVE_RESOURCE_DATA_REQUIRED',blocking:true,message:'resource data required'}]}}]} as unknown as Recovery;
 it('blocks deploy on joint feasibility and gates approval on a reason',()=>{
  const approve=vi.fn(),deploy=vi.fn();
  const{rerender}=render(<Deployment recovery={recovery} approvalReason="" setApprovalReason={()=>{}} approve={approve} deploy={deploy} busy={false}/>);
  expect(screen.getByText(/CARRIER WRITES DISABLED/i)).toBeTruthy();
  expect(screen.getByText(/Joint feasibility not satisfied/i)).toBeTruthy();
  expect((screen.getByRole('button',{name:/Publish to carrier systems/i})as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button',{name:/Submit for approval/i})as HTMLButtonElement).disabled).toBe(true);
  rerender(<Deployment recovery={recovery} approvalReason="duty manager sign-off" setApprovalReason={()=>{}} approve={approve} deploy={deploy} busy={false}/>);
  const approveBtn=screen.getByRole('button',{name:/Submit for approval/i})as HTMLButtonElement;
  expect(approveBtn.disabled).toBe(false);
  fireEvent.click(approveBtn);
  expect(approve).toHaveBeenCalledWith('duty manager sign-off');
  expect(deploy).not.toHaveBeenCalled();
 });
 it('shows the no-recovery empty state',()=>{
  render(<Deployment recovery={null} approvalReason="" setApprovalReason={()=>{}} approve={()=>{}} deploy={()=>{}} busy={false}/>);
  expect(screen.getByText(/No recovery in progress/i)).toBeTruthy();
 });
});
