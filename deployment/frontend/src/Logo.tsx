// SkySolver Kinetic brand mark (front-view airliner over the kinetic flight shape).
// Vector paths from the official artwork; text is rendered separately so it stays
// legible on the dark UI.
export function LogoMark({size=34,id='sk'}:{size?:number;id?:string}){
 return <svg width={size} height={size} viewBox="205 175 790 285" fill="none" aria-hidden="true" focusable="false" style={{overflow:'visible'}}>
  <defs>
   <linearGradient id={`${id}-fus`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#116da3"/><stop offset=".48" stopColor="#80b4d0"/><stop offset="1" stopColor="#f3f8fb"/></linearGradient>
   <linearGradient id={`${id}-flt`} x1="0" y1="0" x2=".78" y2="1"><stop offset="0" stopColor="#19aed0"/><stop offset=".58" stopColor="#59cee1"/><stop offset="1" stopColor="#d5f2f7"/></linearGradient>
  </defs>
  <path d="M270 292 L600 442 L930 292 L741 354 L600 396 L459 354 Z" fill={`url(#${id}-flt)`}/>
  <path d="M225 267 L565 291 L565 331 L482 323 L469 316 L452 316 L447 333 L420 329 L415 314 L396 312 L391 323 L366 320 L360 307 L225 276 Z" fill="#086aa1"/>
  <path d="M975 267 L635 291 L635 331 L718 323 L731 316 L748 316 L753 333 L780 329 L785 314 L804 312 L809 323 L834 320 L840 307 L975 276 Z" fill="#086aa1"/>
  <g fill="#f8fcfe" stroke="#f8fcfe" strokeWidth="7"><circle cx="470" cy="317" r="24"/><circle cx="730" cy="317" r="24"/></g>
  <g fill="none" stroke="#116fa5" strokeWidth="6"><circle cx="470" cy="317" r="18"/><circle cx="730" cy="317" r="18"/></g>
  <g fill="#116fa5"><circle cx="470" cy="317" r="5"/><circle cx="730" cy="317" r="5"/><path d="M470 299l4 12 12-4-9 10 9 10-12-4-4 12-4-12-12 4 9-10-9-10 12 4z"/><path d="M730 299l4 12 12-4-9 10 9 10-12-4-4 12-4-12-12 4 9-10-9-10 12 4z"/></g>
  <path d="M600 187 L591 224 L609 224 Z" fill="#08699e"/>
  <path d="M600 216 C578 216 563 228 560 247 L558 306 C557 352 572 382 600 382 C628 382 643 352 642 306 L640 247 C637 228 622 216 600 216 Z" fill="#f7fbfd" stroke="#08699e" strokeWidth="5"/>
  <path d="M600 249 C576 259 564 279 565 316 C566 350 578 370 600 370 C622 370 634 350 635 316 C636 279 624 259 600 249 Z" fill={`url(#${id}-fus)`}/>
  <path d="M560 286 C552 329 563 380 600 389 C637 380 648 329 640 286 L643 342 C640 384 624 402 600 402 C576 402 560 384 557 342 Z" fill="#ffffff" stroke="#8dd9e8" strokeWidth="3"/>
 </svg>;
}

export default function Logo({compact=false}:{compact?:boolean}){
 return <div className={`brand-lockup${compact?' compact':''}`}>
  <LogoMark size={compact?38:72} id={compact?'skc':'skl'}/>
  <div className="wordmark"><strong>SKYSOLVER</strong><span>KINETIC</span></div>
 </div>;
}
