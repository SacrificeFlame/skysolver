# Replay and certification status

SkySolver has **not** passed an Elliott-scale or production certification SLA.

The previous report was removed because it described an 800-flight synthetic run,
a sleep-based passenger placeholder, and heuristic Tier 2 output as evidence for a
16,700-flight historical profile. Those results were not certification evidence.

## Current gate

`chaos.replay.evaluate_certification_evidence` is the authoritative evidence gate.
It rejects a result unless all of the following are true:

- the run contains at least 50,100 affected flight records;
- passenger recovery was actually computed rather than simulated;
- Tier 3 suggestions were generated from unresolved cases;
- broker, database and adapter contention were exercised;
- worker loss and regional failover were exercised;
- 100% of solvable Tier 1 cases received legal coverage within five minutes;
- no illegal assignment was accepted.

The current development harness does not yet supply all of that evidence, so its
certification result is deliberately `NOT_CERTIFIED`. Carrier publishing remains
disabled independently of replay results.

## Terminology

Development runs may report measurements, but must not use `PASS`, `certified`,
`Elliott-scale`, or `production-shaped` unless the evidence gate accepts them.
