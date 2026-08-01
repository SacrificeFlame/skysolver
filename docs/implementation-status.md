# SkySolver implementation status

Last audited: 2026-08-01
Operational authority: disabled
Data classification: realistic synthetic demonstration data only

## Current verdict

SkySolver is a production-oriented reference implementation and contained OCC
demonstration. It is not certified airline software and has no carrier write
authority. The UI, API and release gates must continue to say this plainly.

## Implemented in this repository

| Area | Evidence | Current boundary |
|---|---|---|
| Truthful OCC UI | Persistent synthetic banner, India routes, dedicated Tier pages, Tier 3 queue, Data Health and Deployment gates | No carrier feed |
| API safety | FastAPI/OpenAPI, signed demo sessions, OIDC claim verifier, RBAC, MFA step-up, optimistic versions, idempotency and correlation | Airline IdP not configured |
| Canonical state | Versioned/provenanced airline records and temporal context | Vendor mappings remain adapter-specific |
| Ingestion | Contract validation, minimization, duplicate/out-of-order handling, cursor, DLQ and reconciliation | No carrier endpoint credentials |
| Data health | Freshness, DLQ, drift, circuit and authority interlocks | Fixture intentionally blocks deployment |
| Tier 1 | Legal-first regional incumbent and explicit partial coverage | Demo DGCA profile only |
| Tier 2 | Restricted-master binary MILP, legal columns, warm start, solver availability and upgrade rejection | Not branch-and-price; no certified gap claim |
| Tier 3 | Uncapped legal-option generation, stable IDs, ranking, authenticated accept/reject/hold/edit, revalidation and candidate creation | Depends on synthetic snapshot |
| Rules | DGCA-oriented checks, signed effective-dated package governance, four-eyes approval, shadow activation and rollback | Incomplete regulatory corpus; not certified |
| Validation | Separately deployable service, package-bound execution and calculation findings | Certified context requires external approvals |
| Event state | Atomic workflow command receipts, optimistic aggregate stream, event/outbox/snapshot transaction, deterministic replay, idempotent MSK projection consumer, DLQ and MSK IAM publishing | Production API composition and live AWS dependencies not activated |
| Cross-partition recovery | Reservation/validation/commit/dual-ACK/compensation saga | No live station capacity systems |
| Deployment | Resource commands, ACK/NACK/timeout, partial state, retry and compensation distinctions | Carrier adapters and writes disabled |
| Immutable evidence | KMS-encrypted S3 versioned COMPLIANCE Object Lock writer and integrity verification | AWS bucket not provisioned here |
| AWS platform | EKS, Aurora, MSK, Redis, S3, KMS, ECR, Cognito/SAML, ALB/WAF/DNS, backups, Prometheus | Terraform not applied to an AWS account |
| Release governance | Signed evidence gate for shadow/controlled production | Required evidence has not been supplied |
| Replay | Evidence gate rejects toy volume, simulated passenger work and missing resilience dimensions | No certified 50,100-flight distributed run |

## External exit gates still required

1. Supply and validate real carrier read adapters and airline identity federation.
2. Complete and obtain DGCA, operator and labour-agreement approval for rules packages.
3. Activate the Aurora-backed API workflow store and MSK solver-job consumers.
4. Implement carrier-specific crew, aircraft, AODB and passenger publication adapters.
5. Run security assessment, penetration test, accessibility acceptance and SBOM/signature gates.
6. Execute production-shaped load, broker/database failure and regional DR exercises.
7. Complete read-only shadow operations and reconciliation against incumbent airline processes.
8. Obtain safety-board, security and operational acceptance evidence.
9. Enable one controlled action type only through a separately approved production overlay.

No repository test, mock, synthetic replay or Terraform file is evidence that
these external gates passed.
