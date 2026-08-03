import{afterEach,describe,expect,it,vi}from'vitest';
import{cleanup,render,screen}from'@testing-library/react';
import React from'react';
import FleetWorkspace from'./FleetWorkspace';

afterEach(()=>{cleanup();vi.restoreAllMocks()});

const fleet={items:[
 {registration:'VT-EXA',type:'A321',status:'blocked',location:'DEL',gate:'T3-42',assigned_flight:'AI421',next_available:'On stand — LVP hold'},
 {registration:'VT-ISP',type:'A320neo',status:'maintenance',location:'DEL',gate:'MRO-2',assigned_flight:null,next_available:'AOG — check A2 ETA 14:00'},
]};

describe('post-deployment fleet projection',()=>{
 it('releases operationally blocked tails but preserves maintenance restrictions',async()=>{
  vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(fleet)} as Response)));
  render(React.createElement(FleetWorkspace,{deployed:true}));
  await screen.findByText('Recovered fleet status');
  expect(screen.queryByText('BLOCKED')).toBeNull();
  expect(screen.getByText('READY')).toBeTruthy();
  expect(screen.getByText('Released · recovered rotation')).toBeTruthy();
  expect(screen.getByText('MAINTENANCE')).toBeTruthy();
  expect(screen.getByText('Not dispatchable')).toBeTruthy();
 });
});
