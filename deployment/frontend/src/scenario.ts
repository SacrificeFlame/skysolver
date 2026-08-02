import{useCallback,useEffect,useMemo,useState}from'react';
import{api}from'./api';
import type{CrewRosterEntry}from'./types';

export type CaseStatus='open'|'resolved'|'escalated';
export type ScenarioCase={flight:string;origin:string;destination:string;aircraft:string;gate:string;passengers:number;incumbentId:string;incumbentName:string;requiredQual:string;status:CaseStatus;replacementId?:string;replacementName?:string;resolvedVia?:'reassign'|'override'};

export function aircraftQual(t:string):string{const x=(t||'').toUpperCase();if(x.startsWith('B787'))return'B787';if(x.startsWith('B777'))return'B777';if(x.startsWith('A321'))return'A321';if(x.startsWith('A320'))return'A320';if(x.startsWith('B737'))return'B737';return x;}

// Client-side legality mirrors the backend rules engine (MISSING_QUALIFICATION,
// CREW_POSITION, MIN_REST) for instant filtering; the backend endpoint enforces the same.
export function checkLegality(crew:CrewRosterEntry,c:{requiredQual:string;origin:string}){
 const qualified=crew.qualifications.includes(c.requiredQual);
 const positioned=crew.base===c.origin;
 const rested=crew.rest_hours>=10;
 const violations:string[]=[];
 if(!qualified)violations.push(`Missing ${c.requiredQual} type rating`);
 if(!positioned)violations.push(`Positioned at ${crew.base}, not ${c.origin}`);
 if(!rested)violations.push(`Rest ${crew.rest_hours}h below 10h minimum`);
 return{legal:violations.length===0,qualified,positioned,rested,violations};
}

export type Scenario=ReturnType<typeof useScenario>;

export function useScenario(){
 const[roster,setRoster]=useState<CrewRosterEntry[]>([]);
 const[cases,setCases]=useState<ScenarioCase[]>([]);
 const[loading,setLoading]=useState(true);
 const[error,setError]=useState('');
 const load=useCallback(()=>{setLoading(true);setError('');api.crew().then(r=>{
  setRoster(r.items);
  setCases(r.items.filter(c=>c.status==='illegal'&&c.assigned_flight).map(c=>({flight:c.assigned_flight!,origin:c.current_origin||'',destination:c.current_destination||'',aircraft:c.current_aircraft||'',gate:c.current_gate||'',passengers:c.passengers||0,incumbentId:c.id,incumbentName:c.name,requiredQual:aircraftQual(c.current_aircraft||''),status:'open' as CaseStatus})));
 }).catch(e=>setError(e.message)).finally(()=>setLoading(false))},[]);
 useEffect(load,[load]);
 const usedCrew=useMemo(()=>new Set(cases.filter(c=>c.replacementId).map(c=>c.replacementId!)),[cases]);
 const spares=useMemo(()=>roster.filter(c=>!c.assigned_flight),[roster]);
 const availableFor=useCallback((_c:ScenarioCase)=>spares.filter(s=>!usedCrew.has(s.id)),[spares,usedCrew]);
 const patch=(flight:string,p:Partial<ScenarioCase>)=>setCases(cs=>cs.map(c=>c.flight===flight?{...c,...p}:c));
 const reassign=(flight:string,crew:CrewRosterEntry)=>patch(flight,{status:'resolved',replacementId:crew.id,replacementName:crew.name,resolvedVia:'reassign'});
 const overrideAssign=(flight:string,crew:CrewRosterEntry)=>patch(flight,{status:'resolved',replacementId:crew.id,replacementName:crew.name,resolvedVia:'override'});
 const escalate=(flight:string)=>patch(flight,{status:'escalated',replacementId:undefined,replacementName:undefined,resolvedVia:undefined});
 const reopen=(flight:string)=>patch(flight,{status:'open',replacementId:undefined,replacementName:undefined,resolvedVia:undefined});
 const stats=useMemo(()=>{const total=cases.length,resolved=cases.filter(c=>c.status==='resolved').length,escalated=cases.filter(c=>c.status==='escalated').length,open=cases.filter(c=>c.status==='open').length,pax=cases.reduce((s,c)=>s+c.passengers,0),paxResolved=cases.filter(c=>c.status==='resolved').reduce((s,c)=>s+c.passengers,0);return{total,open,resolved,escalated,pax,paxResolved,coverage:total?resolved/total:0};},[cases]);
 return{loading,error,roster,cases,usedCrew,spares,reload:load,reset:load,availableFor,reassign,overrideAssign,escalate,reopen,stats};
}
