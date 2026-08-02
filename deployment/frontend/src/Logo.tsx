// SkySolver Kinetic brand mark: front-view airliner over a cyan kinetic beam.
// Vector so it stays crisp at every size and tints cleanly on dark surfaces.
export function LogoMark({size=34,id='sk'}:{size?:number;id?:string}){
 return <svg width={size} height={size*0.78} viewBox="0 0 160 125" fill="none" aria-hidden="true" focusable="false">
  <defs>
   <linearGradient id={`${id}-beam`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#3fd0e6" stopOpacity=".95"/><stop offset="1" stopColor="#3fd0e6" stopOpacity="0"/></linearGradient>
   <linearGradient id={`${id}-body`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#eaf4fc"/><stop offset="1" stopColor="#3f93c4"/></linearGradient>
   <linearGradient id={`${id}-glass`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#0c2c4a"/><stop offset="1" stopColor="#54a9dd"/></linearGradient>
  </defs>
  {/* kinetic beam */}
  <path d="M58 60 L102 60 L80 116 Z" fill={`url(#${id}-beam)`}/>
  {/* swept wings */}
  <path d="M74 44 L20 32 L15 35 L18 40 L72 51 Z" fill="#2f7fb8"/>
  <path d="M86 44 L140 32 L145 35 L142 40 L88 51 Z" fill="#2f7fb8"/>
  <path d="M15 35 L11 27 L18 32 Z" fill="#2f7fb8"/>
  <path d="M145 35 L149 27 L142 32 Z" fill="#2f7fb8"/>
  {/* engines */}
  <circle cx="50" cy="50" r="7" fill="#2f7fb8"/><circle cx="50" cy="50" r="3" fill="#0b243c"/>
  <circle cx="110" cy="50" r="7" fill="#2f7fb8"/><circle cx="110" cy="50" r="3" fill="#0b243c"/>
  {/* fuselage + antenna */}
  <line x1="80" y1="5" x2="80" y2="14" stroke="#2f7fb8" strokeWidth="1.8"/>
  <path d="M80 12 C 75 16 73 23 73 35 C 73 51 76 60 80 63 C 84 60 87 51 87 35 C 87 23 85 16 80 12 Z" fill={`url(#${id}-body)`} stroke="#2f7fb8" strokeWidth="1"/>
  {/* cockpit glass */}
  <path d="M80 22 C 77 25 76 31 76 39 C 76 47 78 51 80 53 C 82 51 84 47 84 39 C 84 31 83 25 80 22 Z" fill={`url(#${id}-glass)`}/>
 </svg>;
}

export default function Logo({compact=false}:{compact?:boolean}){
 return <div className={`brand-lockup${compact?' compact':''}`}>
  <LogoMark size={compact?36:64} id={compact?'skc':'skl'}/>
  <div className="wordmark"><strong>SKYSOLVER</strong><span>KINETIC</span></div>
 </div>;
}
