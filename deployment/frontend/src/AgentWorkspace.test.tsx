import{describe,expect,it,vi,beforeEach,afterEach}from'vitest';
import{cleanup,fireEvent,render,screen,waitFor}from'@testing-library/react';
import React from'react';
import AgentWorkspace from'./AgentWorkspace';
import{api}from'./api';
import type{AgentRun,AgentToolset}from'./types';

const toolset:AgentToolset={
 items:[
  {name:'preview_reassignment',description:'Validate a crew member against a flight.',input_schema:{type:'object',properties:{flight_id:{type:'string'}},required:['flight_id']}},
  {name:'commit_reassignment',description:'Add a reassignment to the plan.',input_schema:{type:'object',properties:{},required:[]}},
 ],
 guarantees:['commit_reassignment is refused unless the rules engine cleared it','escalate_to_tier3 is refused until every candidate is evaluated','the agent proposes a plan; publishing still requires the gates'],
};

function makeRun(over:Partial<AgentRun>={}):AgentRun{
 return{
  planner:'gemini:gemini-flash-latest',
  requested_planner:'gemini',
  notes:[],
  handover:'AI421 and UK945 resolved. AI807 needs a duty-manager decision.',
  summary:{resolved:2,escalated:1,unresolved:0,tool_calls:3,elapsed_s:4.2,stopped_because:'complete'},
  resolved:[{flight_id:'AI421',crew_id:'IC-318',crew_name:'Priya Iyer',aircraft_type:'A321',ruleset_version:'dgca-2024.1',checks:{qualified:true,positioned_at_origin:true,rest_ok:true},rationale:'Cleared by the rules engine.'}],
  escalated:[{flight_id:'AI807',passengers:242,reason:'No legal B787 option.',candidates_evaluated:2,blockers:[{crew_id:'IC-507',crew_name:'Dev Patel',violations:['MIN_REST'],detail:'Rest period 8.2h below 10h minimum'}]}],
  unresolved:[],
  trace:{planner:'gemini:gemini-flash-latest',started_at:'2026-08-03T10:00:00Z',finished_at:'2026-08-03T10:00:04Z',tool_calls:3,steps:[
   {index:1,phase:'perceive',tool:'get_operational_picture',tool_input:{},rationale:'Read the disruption first.',outcome:'3 open crew case(s)',observation:{tool:'get_operational_picture',ok:true,data:{}},ok:true,duration_ms:2,at:'2026-08-03T10:00:00Z'},
   {index:2,phase:'act',tool:'preview_reassignment',tool_input:{flight_id:'AI807',crew_id:'IC-507'},rationale:'Only two B787-rated crew exist.',outcome:'REJECTED [MIN_REST] - Rest period 8.2h below 10h minimum',observation:{tool:'preview_reassignment',ok:true,data:{legal:false,rule_violations:[{code:'MIN_REST',message:'Rest period 8.2h below 10h minimum'}]}},ok:true,duration_ms:5,at:'2026-08-03T10:00:01Z'},
   {index:3,phase:'escalate',tool:'escalate_to_tier3',tool_input:{flight_id:'AI807',reason:'No legal option.'},rationale:'Every candidate was rejected.',outcome:'Escalated to Tier 3 after 2 candidate(s)',observation:{tool:'escalate_to_tier3',ok:true,data:{}},ok:true,duration_ms:1,at:'2026-08-03T10:00:02Z'},
  ]},
  ...over,
 };
}

// Minimal scenario double: the agent must push its outcomes into the shared
// recovery state, so the calls are what we assert on.
function makeScenario(){
 const reassign=vi.fn();
 const escalate=vi.fn();
 return{
  loading:false,error:'',roster:[
   {id:'IC-318',name:'Priya Iyer',rank:'Captain',base:'DEL',qualifications:['A321'],status:'standby',duty_remaining:'10:30',rest_hours:14,assigned_flight:null,seniority:15,current_route:null},
  ],
  cases:[],usedCrew:new Set<string>(),spares:[],
  reload:vi.fn(),reset:vi.fn(),availableFor:vi.fn(()=>[]),
  reassign,overrideAssign:vi.fn(),escalate,reopen:vi.fn(),
  stats:{total:0,open:0,resolved:0,escalated:0,pax:0,paxResolved:0,coverage:0},
 } as any;
}

beforeEach(()=>{vi.spyOn(api,'agentTools').mockResolvedValue(toolset)});
afterEach(()=>{cleanup();vi.restoreAllMocks()});

describe('AgentWorkspace',()=>{
 it('shows an empty state before any run',async()=>{
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  expect(await screen.findByText('No run yet')).toBeTruthy();
  expect(screen.queryByText('Decision trace')).toBeNull();
 });

 it('renders the trace with each step reasoning and outcome',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  await waitFor(()=>expect(screen.getByText('Decision trace')).toBeTruthy());
  expect(await screen.findByText('Read the disruption first.')).toBeTruthy();
  await waitFor(()=>expect(screen.getByText('Every candidate was rejected.')).toBeTruthy());
  expect(screen.getByText(/REJECTED \[MIN_REST\]/)).toBeTruthy();
 });

 it('surfaces the real rule violation codes from the escalation',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  await waitFor(()=>expect(screen.getAllByText('MIN_REST').length).toBeGreaterThan(0));
  expect(await screen.findByText(/Dev Patel/)).toBeTruthy();
  expect(screen.getByText(/242 passengers/)).toBeTruthy();
 });

 it('states plainly when the run degraded to the deterministic planner',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun({
   planner:'deterministic',
   notes:['LLM planner unavailable (RateLimitError). Switched to the deterministic planner.'],
  }));
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  expect(await screen.findByText(/Ran on the deterministic planner/)).toBeTruthy();
  expect(screen.getByText(/RateLimitError/)).toBeTruthy();
 });

 it('does not claim a degraded run when the LLM planner completed',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  await waitFor(()=>expect(screen.getByText('Decision trace')).toBeTruthy());
  expect(screen.queryByText(/Ran on the/)).toBeNull();
 });

 it('publishes the guardrails the agent operates under',async()=>{
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(await screen.findByRole('button',{name:/Guardrails/}));

  expect(await screen.findByText('Enforced in code, not in a prompt')).toBeTruthy();
  expect(screen.getByText(/refused unless the rules engine cleared it/)).toBeTruthy();
  expect(screen.getByText('preview_reassignment')).toBeTruthy();
 });

 it('reports a failed run instead of showing a blank page',async()=>{
  vi.spyOn(api,'agentRun').mockRejectedValue(Object.assign(new Error('Agent unavailable'),{status:500}));
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  expect(await screen.findByText('Agent unavailable')).toBeTruthy();
 });

 it('lets the operator pick the planner before running',async()=>{
  const agentRun=vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));

  fireEvent.click(screen.getByRole('button',{name:/Deterministic/}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));
  expect(agentRun).toHaveBeenCalledWith('deterministic');
 });
});

// Regression: the agent's plan used to stop at the trace. Decisions read
// scenario.stats.resolved, saw zero, and kept "Generate recovery plan"
// disabled, so nothing could reach Deployment.
describe('AgentWorkspace -> recovery state',()=>{
 it('pushes resolved reassignments into the shared recovery state',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  const scenario=makeScenario();
  render(React.createElement(AgentWorkspace,{scenario,go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  await waitFor(()=>expect(scenario.reassign).toHaveBeenCalledTimes(1));
  expect(scenario.reassign).toHaveBeenCalledWith('AI421',expect.objectContaining({id:'IC-318'}));
 });

 it('pushes escalations into the shared recovery state',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  const scenario=makeScenario();
  render(React.createElement(AgentWorkspace,{scenario,go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  await waitFor(()=>expect(scenario.escalate).toHaveBeenCalledWith('AI807'));
 });

 it('tells the operator the plan was applied rather than doing it silently',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun());
  render(React.createElement(AgentWorkspace,{scenario:makeScenario(),go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  expect(await screen.findByText(/Applied to the recovery plan/)).toBeTruthy();
  expect(screen.getByText(/1 case resolved and 1 escalated/)).toBeTruthy();
 });

 it('reports a crew member it could not match instead of dropping it',async()=>{
  vi.spyOn(api,'agentRun').mockResolvedValue(makeRun({
   resolved:[{flight_id:'AI421',crew_id:'IC-999',crew_name:'Ghost',aircraft_type:'A321',ruleset_version:'x',checks:{qualified:true,positioned_at_origin:true,rest_ok:true},rationale:'r'}],
  }));
  const scenario=makeScenario();
  render(React.createElement(AgentWorkspace,{scenario,go:vi.fn()}));
  fireEvent.click(screen.getByRole('button',{name:/Run agent/}));

  expect(await screen.findByText(/Could not apply: AI421 \(IC-999\)/)).toBeTruthy();
  expect(scenario.reassign).not.toHaveBeenCalled();
 });
});
