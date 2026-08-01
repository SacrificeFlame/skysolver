import{describe,expect,it}from'vitest';
import{routeArc}from'./RouteWorkspace';
import type{PlannedRoute}from'./types';

const route={origin:{x:445,y:112},destination:{x:332,y:262}} as PlannedRoute;
describe('planned route geometry',()=>{
 it('uses the selected route endpoints',()=>expect(routeArc(route)).toMatch(/^M445 112/));
 it('renders proposed route differently',()=>expect(routeArc(route,true)).not.toBe(routeArc(route,false)));
});
