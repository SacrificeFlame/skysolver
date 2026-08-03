# SkySolver

SkySolver is an early-stage, synthetic-data prototype for resilient airline disruption recovery. Its goal is to produce a legal partial crew-recovery plan quickly, improve that plan within a time budget, and preserve a human-assisted path when automation cannot safely resolve every flight.

The repository is **not production-ready airline software**. It does not process real carrier data, and its DGCA-oriented rules profile is not operator-approved or certified. Carrier publishing is disabled and production-shaped configuration fails closed unless a durable workflow composition is injected.

## Implemented prototype capabilities

- Hub-based synthetic crew and flight partitioning.
- A dedicated, independently tested crew-legality module.
- An agentic recovery loop where an LLM chooses what to try and the rules engine decides what is allowed, with the legality guard enforced in code.
- A bounded Tier 1 greedy heuristic with legal partial results.
- A restricted-master MILP Tier 2 upgrade path with a Tier 1 warm start and truthful solver telemetry.
- An authenticated, versioned Tier 3 scheduler workflow with no automatic approval.
- Aurora event/outbox repositories, MSK IAM publishing, rebuildable projections and cross-partition sagas.
- Synthetic passenger-recovery examples.
- A synthetic chaos/replay harness.
- A React + TypeScript cinematic OCC command canvas with real recovery workflow state.
- KMS/S3 Object Lock artifacts, OIDC/RBAC/MFA gates and signed release evidence.
- Terraform for EKS, Aurora, MSK, Redis, S3, KMS, Cognito federation, ALB/WAF/Route 53, backups and managed Prometheus.

See [docs/implementation-status.md](docs/implementation-status.md) for the verified maturity of each area and the current production gaps.

## Recovery agent

An LLM plans the recovery; a deterministic rules engine decides what is permitted. The split is the point, and it is enforced in code rather than in a prompt.

The agent runs a perceive → plan → act → observe → re-plan → escalate loop over six tools. For each flight whose crew has fallen out of legal limits, it shortlists type-rated replacements, asks the FAR117/DGCA-style engine to rule on each candidate, and reads the actual violation codes back. `agents/tools.py` enforces two invariants that no planner can talk its way around:

- `commit_reassignment` is refused unless that exact flight and crew already returned `legal: true` from the rules engine **in the same run**.
- `escalate_to_tier3` is refused until every type-rated candidate has genuinely been evaluated and rejected.

Because those guards live in Python, a hallucinating or adversarial model cannot publish an illegal roster. The test suite includes a `RoguePlanner` that tries exactly that and is refused.

The agent proposes; it does not deploy. A committed reassignment enters the run's plan and the audit trail, and publishing still passes through the existing scheduler → duty-manager → deployment-controller gates.

```bash
python -m agents                    # deterministic planner, no API key required
python -m agents --planner gemini   # LLM planner (needs GEMINI_API_KEY)
python -m agents --json             # full decision trace as JSON
```

Two planners implement one interface. `DeterministicPlanner` is a scarcity-aware constraint heuristic: it works the most constrained flight first and avoids spending a rare type rating on a flight that many crew could cover. The LLM planner drives the identical tool surface and contributes judgement about what is worth trying — never about what is allowed.

If the model is unreachable, rate-limited or out of quota, the run steps down to a lighter model and then to the deterministic planner, and says so in the trace. A recovery plan therefore never depends on a credential being healthy. Every step — the tool called, its arguments, the stated reason, and what the domain actually answered — is recorded and rendered in the **Recovery Agent** workspace of the dashboard.

## Tech stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.11+ (CI on 3.12), FastAPI, Pydantic v2, Uvicorn |
| Optimization | Pyomo with the HiGHS MILP backend (`highspy`) for Tier 2; a bounded greedy/LNS heuristic for Tier 1 |
| Legality | A dedicated FAR117/DGCA-oriented rules engine of pure functions, versioned and independently tested |
| Agent | Six-tool registry with code-enforced guards; deterministic planner plus an optional LLM planner via the `openai` SDK against Google's OpenAI-compatible Gemini endpoint |
| Frontend | React 19, TypeScript 7, Vite 8, `lucide-react`; pnpm |
| Frontend tests | Vitest with Testing Library and jsdom |
| Data plane | Aurora PostgreSQL (`psycopg` v3) for events and outbox, MSK with IAM SASL for publication, Redis for short-lived coordination only |
| AWS | `boto3`, KMS, S3 with Object Lock, Cognito federation, ALB/WAF/Route 53 |
| Identity | OIDC with `PyJWT`, RBAC, MFA step-up, separation of duties across scheduler, duty manager and deployment controller |
| Observability | Prometheus client, OpenTelemetry API and SDK |
| Infrastructure | Terraform for EKS, Aurora, MSK, Redis, S3, KMS and networking |
| CI | GitHub Actions: backend, frontend, contracts, infrastructure and security gates, with bandit, gitleaks, `pip-audit` and Trivy |
| Tests | 273 Python tests and 62 frontend tests |

## Local setup

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run the dashboard

```bash
python main.py
```

The server uses the `PORT` environment variable and defaults to `8000`. The current UI is a clearly synthetic operational scenario; it is not a live airline feed.

The production frontend bundle is committed under `deployment/frontend/dist` and served at `/dashboard`. To develop or rebuild it:

```bash
cd deployment/frontend
pnpm install
pnpm run dev      # Vite with /api proxy to port 8501
pnpm run build    # production bundle served by Python
```

The command canvas connects to `/api/v1/disruptions`, `/flights`, `/recoveries`, `/audit`, and `/events`. Recovery mutations enforce state versions, legality gates, explicit validation and idempotent deployment.

## Run solver-worker demos

```bash
python -m deployment.worker --partition DEL --tier 1 --time-budget 1
python -m deployment.worker --partition DEL --tier 2 --time-budget 1
```

These commands generate synthetic inputs and exit after processing them. The transactional outbox publisher has a concrete Aurora IAM/MSK IAM runtime; the solver job-consumer runtime remains incomplete.

## Run tests

```bash
python -m pytest -q
```

The suite covers structured legality, optimistic event concurrency, tier orchestration, durable human decisions, passenger recovery, versioned dashboard routes, and worker result handling. Passing tests demonstrate modeled prototype behavior only; they are not evidence of regulatory certification or production-scale recovery performance.

## Important limitations

- Tier 2 is an actual restricted-master MILP when a configured solver is available, but it is not branch-and-price and has no certified optimality claim.
- Tier 3 is integrated into the authenticated recovery API, but real airline resource inputs are unavailable.
- Aurora/MSK adapters and projections exist; the full API-side durable workflow store and solver job consumer are not yet activated.
- The dashboard is backend-connected but uses an explicitly labelled synthetic scenario rather than carrier feeds.
- Enterprise OIDC validation, RBAC and MFA step-up paths exist, but no airline IdP is configured in this repository.
- The recovery agent reasons over the same synthetic roster as the rest of the prototype. Its legality verdicts are real engine output, but the crew, flights and rest hours it reasons about are fixtures.
- The agent proposes a plan and never publishes one. Nothing it does bypasses the approval and deployment gates, and it holds no carrier credentials.
- No license has been selected.

## Project direction

The intended direction is documented in `architecture.md`. That document describes a target architecture; when it differs from working code, `docs/implementation-status.md` is authoritative about current behavior.
