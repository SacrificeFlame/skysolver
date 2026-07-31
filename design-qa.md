# Design QA — India Airline Recovery Workspace

Viewport: 1440 × 900. Data mode: clearly labelled synthetic India network.

## Results

- P0/P1/P2 issues: none.
- Planned Routes is API-backed through `GET /api/v1/routes` and `GET /api/v1/routes/{flight_id}`.
- Five distinct routes verified: AI421 DEL–BOM, 6E203 BLR–DEL, UK945 DEL–HYD, AI807 BOM–DEL, and 6E531 DEL–CCU.
- Selecting 6E203 changed the map, airport labels, distance, timings, aircraft, restriction and movement chain from AI421.
- Flight route, aircraft rotation, crew pairing, deadhead journey, recovery changes and cross-partition controls are interactive.
- Movement validation changes the selected plan to a validated state.
- Delhi low-visibility disruption, Indian airports, VT registrations, IST operations, rupee costs and DGCA FDTL terminology are used in the active product surfaces.
- Browser console errors: none.
- Frontend production build passed.
- 48 backend and contract tests passed.

final result: passed
