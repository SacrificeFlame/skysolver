import type{Flight}from'./types';
import type{ScenarioCase}from'./scenario';

export type GroundState={label:string;tone:'danger'|'warning'|'success'|'purple'|'cyan';detail:string};

// Derive an aircraft's ground-state label from live flight + scenario case data.
// Crew-case status wins (it is the active problem); otherwise the airframe state.
export function flightGroundState(f:Flight,c?:ScenarioCase):GroundState{
 if(c){
  if(c.status==='open')return{label:'CREW ILLEGAL',tone:'danger',detail:`${c.incumbentId} over duty`};
  if(c.status==='escalated')return{label:'TIER 3 REVIEW',tone:'purple',detail:'supervisor deciding'};
  if(c.status==='resolved')return{label:`CREW ${c.replacementId}`,tone:'success',detail:c.resolvedVia==='override'?'override accepted':'reassigned'};
 }
 const s=f.aircraft.status;
 if(s==='blocked')return{label:'AIRCRAFT BLOCK',tone:'danger',detail:'LVP hold'};
 if(s==='inbound'||f.origin!=='DEL')return{label:'INBOUND',tone:'cyan',detail:`from ${f.origin}`};
 if(s==='ready'||s==='available')return{label:'READY',tone:'success',detail:`gate ${f.gate}`};
 return{label:s.toUpperCase(),tone:'warning',detail:''};
}

export function impactOf(delay:number):'high'|'moderate'|'low'{return delay>=60?'high':delay>=45?'moderate':'low'}

const TONE:Record<GroundState['tone'],string>={danger:'#ef6a6a',warning:'#e7c15a',success:'#57d08a',purple:'#b98af0',cyan:'#38cfe0'};

function PlaneGlyph({x,y,angle,color,onClick}:{x:number;y:number;angle:number;color:string;onClick?:()=>void}){
 return <g transform={`translate(${x} ${y}) rotate(${angle})`} onClick={onClick} style={onClick?{cursor:'pointer'}:undefined}>
  <path d="M0 -9 L2.4 -2.6 L10 1.4 L10 4 L2.2 2 L1.6 7 L4.4 9.4 L4.4 11 L0 10 L-4.4 11 L-4.4 9.4 L-1.6 7 L-2.2 2 L-10 4 L-10 1.4 L-2.4 -2.6 Z" fill={color} stroke="#08131c" strokeWidth=".8"/>
 </g>;
}

function StatusPill({x,y,state,name}:{x:number;y:number;state:GroundState;name:string}){
 const w=12+Math.max(name.length,state.label.length)*6.4;
 return <g transform={`translate(${x} ${y})`}>
  <rect x="0" y="-11" width={w} height="15" rx="3" fill="#0b1720" stroke="#2a3b46"/>
  <text x="6" y="0" fontSize="9" fontWeight="700" fill="#dfe8ed" style={{letterSpacing:'.04em'}}>{name}</text>
  <rect x="0" y="6" width={w} height="14" rx="3" fill="#0b1720" stroke={TONE[state.tone]} opacity=".95"/>
  <text x="6" y="16" fontSize="8" fontWeight="700" fill={TONE[state.tone]} style={{letterSpacing:'.06em'}}>{state.label}</text>
 </g>;
}

export default function AirportView({flights,cases,onSelect}:{flights:Flight[];cases:ScenarioCase[];onSelect?:(f:Flight)=>void}){
 const byId=(id:string)=>flights.find(f=>f.id===id);
 const caseOf=(id:string)=>cases.find(c=>c.flight===id);
 const departures=[['AI421',96],['UK945',176],['6E531',256]] as [string,number][];
 const inbounds=[['AI807',150],['6E203',66]] as [string,number][];
 return <div className="airport-wrap">
  <svg viewBox="0 0 960 520" role="img" aria-label="Delhi airport operational view: gates, taxiways, runway 28 and inbound traffic" preserveAspectRatio="xMidYMid meet">
   <defs>
    <linearGradient id="apron" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#0b1926"/><stop offset="1" stopColor="#08131c"/></linearGradient>
    <linearGradient id="fog" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#9fb2bd" stopOpacity=".08"/><stop offset="1" stopColor="#9fb2bd" stopOpacity="0"/></linearGradient>
   </defs>
   <rect width="960" height="520" rx="10" fill="url(#apron)"/>
   <rect width="960" height="150" fill="url(#fog)"/>

   {/* Runway 28 — diagonal */}
   <g transform="rotate(-16 480 330)">
    <rect x="70" y="308" width="820" height="46" rx="4" fill="#16242f" stroke="#2a3b46"/>
    <line x1="100" y1="331" x2="860" y2="331" stroke="#8598a3" strokeWidth="2.5" strokeDasharray="26 20"/>
    {[92,100,108].map(x=><rect key={x} x={x} y="313" width="4" height="36" fill="#8598a3" opacity=".8"/>)}
    {[852,860,868].map(x=><rect key={x} x={x} y="313" width="4" height="36" fill="#8598a3" opacity=".8"/>)}
    <text x="132" y="337" fontSize="17" fontWeight="800" fill="#c3d2db">28</text>
    <text x="806" y="337" fontSize="17" fontWeight="800" fill="#c3d2db">10</text>
    {/* Parallel taxiway */}
    <rect x="110" y="252" width="740" height="17" rx="3" fill="#132430" stroke="#243642"/>
    <line x1="120" y1="260" x2="840" y2="260" stroke="#b9a23c" strokeWidth="1.4" strokeDasharray="10 8" opacity=".7"/>
    {/* High-speed exit */}
    <path d="M600 269 L556 308" stroke="#243642" strokeWidth="15" fill="none"/>
    <path d="M600 261 L552 305" stroke="#b9a23c" strokeWidth="1.2" strokeDasharray="7 6" opacity=".7" fill="none"/>
    {/* Runway entry */}
    <path d="M250 269 L250 308" stroke="#243642" strokeWidth="15" fill="none"/>
   </g>
   <text x="676" y="346" fontSize="9" fontWeight="700" fill="#7f909b" style={{letterSpacing:'.09em'}}>HIGH-SPEED EXIT E7</text>
   <text x="700" y="470" fontSize="10" fontWeight="700" fill="#7f909b" style={{letterSpacing:'.08em'}}>RWY 28 · CAT III</text>

   {/* Hold short bar */}
   <g transform="translate(320 316)">
    <rect x="-2" y="-3" width="34" height="7" fill="#e7c15a" opacity=".85"/>
    <rect x="-2" y="-3" width="34" height="7" fill="none" stroke="#08131c" strokeDasharray="4 4"/>
    <text x="-4" y="20" fontSize="9" fontWeight="700" fill="#e7c15a" style={{letterSpacing:'.08em'}}>HOLD SHORT 28</text>
   </g>

   {/* Gate stands + taxi lines from stands toward the taxiway */}
   {departures.map(([id,y])=>{const f=byId(id);if(!f)return null;const st=flightGroundState(f,caseOf(id));const active=st.tone!=='danger';
    return <g key={id}>
     <path d={`M148 ${y+14} C 240 ${y+14} 250 ${y+40} 296 ${Math.min(y+92,332)}`} fill="none" stroke={active?'#27637a':'#22313c'} strokeWidth="2" strokeDasharray="7 7" opacity=".8"/>
     <rect x="66" y={y-6} width="76" height="40" rx="6" fill="#0d1a23" stroke="#2a3b46"/>
     <text x="80" y={y+13} fontSize="11" fontWeight="800" fill="#c3d2db">{f.gate}</text>
     <text x="80" y={y+26} fontSize="8" fill="#7f909b">{f.aircraft.registration}</text>
     <PlaneGlyph x={172} y={y+13} angle={62} color={TONE[st.tone]} onClick={onSelect?()=>onSelect(f):undefined}/>
     <StatusPill x={196} y={y+8} state={st} name={`${id} · ${f.destination}`}/>
    </g>;
   })}
   <text x="66" y="66" fontSize="10" fontWeight="700" fill="#7f909b" style={{letterSpacing:'.1em'}}>DEL · T3/T2 STANDS</text>

   {/* Inbound traffic on approach to 28 */}
   <path d="M940 60 C 840 120 720 200 560 292" fill="none" stroke="#27637a" strokeWidth="1.6" strokeDasharray="4 9" opacity=".9"/>
   {inbounds.map(([id,x],i)=>{const f=byId(id);if(!f)return null;const st=flightGroundState(f,caseOf(id));const px=940-(i?330:130),py=60+(i?118:44);
    return <g key={id}>
     <PlaneGlyph x={px} y={py} angle={230} color={TONE[st.tone]} onClick={onSelect?()=>onSelect(f):undefined}/>
     <StatusPill x={px+16} y={py-6} state={st} name={`${id} · ${f.origin}→DEL`}/>
    </g>;
   })}
   <text x="742" y="36" fontSize="9" fontWeight="700" fill="#7f909b" style={{letterSpacing:'.09em'}}>APPROACH RWY 28</text>
   <g transform="translate(66 486)"><circle r="4" cx="4" cy="-3" fill="#e7c15a" opacity=".9"/><text x="14" y="0" fontSize="9" fontWeight="700" fill="#e7c15a" style={{letterSpacing:'.07em'}}>LVP ACTIVE — CAT III MINIMA</text></g>
  </svg>
 </div>;
}
