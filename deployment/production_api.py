"""Typed FastAPI surface for the contained SkySolver recovery workflow.

The application exposes truthful synthetic contracts today and is structured so
the store can be replaced by Aurora/MSK repositories without changing clients.
Carrier publication remains disabled in the configured store.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from deployment.auth import COOKIE_NAME, Principal, issue_session, session_cookie, verify_session
from deployment.authorization import Permission, allows
from deployment.recovery_api import DATA_PROVENANCE, FLIGHTS, recovery_store, WorkflowError
from deployment.observability import HTTP_LATENCY, HTTP_REQUESTS
from deployment.runtime_config import UnsafeRuntimeConfiguration, load_runtime_configuration
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from integrations.health import demo_registry
from deployment.oidc import OidcTokenError, configured_verifier
from deployment.production_composition import IncompleteProductionComposition, RuntimeDependencyRegistry


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    role: str | None = None


# Demo role identities. Distinct subjects keep segregation-of-duties intact so a
# duty manager can approve a plan a scheduler proposed, and a controller deploys.
DEMO_ROLE_SUBJECTS = {
    "scheduler-demo": "ops",
    "duty-manager": "duty.manager",
    "deployment-controller": "ops.controller",
}


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disruption_id: str
    partition_id: str
    objective: Literal["balanced", "legality", "passenger", "cost"] = "balanced"


class ReassignmentPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    crew_id: str = Field(min_length=1, max_length=64)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    action: Literal["approve", "reject", "override", "hold"] = "approve"
    reason: str = ""


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str = Field(min_length=8, max_length=128)


class CompensationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)


class SuggestionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "reject", "hold", "edit", "request_more_options"]
    reason: str = Field(default="", max_length=1000)
    crew_id: str | None = None
    flight_id: str | None = None


class MutationContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    idempotency_key: str
    state_version: int
    correlation_id: str
    causation_id: str


def principal(session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None, authorization: Annotated[str | None, Header()] = None) -> Principal:
    runtime=load_runtime_configuration()
    authenticated=None
    if authorization and authorization.startswith("Bearer "):
        try:authenticated=configured_verifier().verify(authorization[7:])
        except (OidcTokenError,RuntimeError):authenticated=None
    elif not runtime.is_production_shaped:
        authenticated=verify_session(session or "")
    if authenticated is None:
        raise HTTPException(status_code=401, detail={"code": "authentication_required", "message": "Authenticate before accessing SkySolver."})
    return authenticated


def mutation_context(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
    state_version: Annotated[int, Header(alias="Expected-State-Version", ge=0)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID", min_length=8, max_length=128)],
    causation_id: Annotated[str, Header(alias="X-Causation-ID", min_length=8, max_length=128)],
) -> MutationContext:
    return MutationContext(
        idempotency_key=idempotency_key,
        state_version=state_version,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def require_permission(permission: Permission, step_up: bool=False):
    def dependency(actor: Principal = Depends(principal)) -> Principal:
        if not allows(actor.role, permission):
            raise HTTPException(status_code=403, detail={"code": "permission_denied", "permission": permission.value})
        runtime=load_runtime_configuration()
        if step_up and runtime.is_production_shaped:
            if actor.auth_method!="oidc" or "mfa" not in actor.amr or actor.auth_time<=0 or int(time.time())-actor.auth_time>900:
                raise HTTPException(status_code=403,detail={"code":"step_up_required","message":"Recent MFA is required for this action"})
        return actor
    return dependency


def create_app(recovery_store=recovery_store, data_health_registry=None,
               runtime_health: RuntimeDependencyRegistry | None = None) -> FastAPI:
    runtime = load_runtime_configuration()
    if runtime.is_production_shaped and not getattr(recovery_store, "durable_authoritative", False):
        raise UnsafeRuntimeConfiguration(
            "Production-shaped API refuses the local demo store; inject the Aurora/MSK durable workflow composition"
        )
    if runtime.is_production_shaped:
        if runtime_health is None:
            raise UnsafeRuntimeConfiguration("Production-shaped API requires an authoritative dependency registry")
        try:
            runtime_health.assert_configured()
        except IncompleteProductionComposition as exc:
            raise UnsafeRuntimeConfiguration(f"Production dependency composition is incomplete: {exc}") from exc
    app = FastAPI(
        title="SkySolver Recovery API",
        version="1.0.0-demo",
        description="SYNTHETIC DEMO — NOT FOR OPERATIONAL USE. Carrier writes are disabled.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
    )
    app.state.runtime_configuration = runtime
    data_health_registry=data_health_registry or demo_registry()
    frontend = Path(__file__).parent / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.middleware("http")
    async def correlation_and_metrics(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(method=request.method, route=route_path, status=str(response.status_code)).inc()
        HTTP_LATENCY.labels(method=request.method, route=route_path).observe(time.perf_counter() - started)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.exception_handler(WorkflowError)
    async def workflow_error(_: Request, exc: WorkflowError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": exc.code, "message": exc.message, "correlation_id": str(uuid.uuid4()), "rule_violations": []},
        )

    @app.get("/api/v1/health/live", include_in_schema=False)
    def live():
        return {"status": "live", "component": "recovery-api"}

    @app.get("/api/v1/health/ready", include_in_schema=False)
    def ready():
        if runtime.is_production_shaped:
            health=runtime_health.snapshot()
            content={**health,"status":"ready" if health["ready"] else "not_ready",
                     "carrier_writes_enabled":runtime.carrier_writes_enabled,
                     "runtime_mode":runtime.mode.value}
            return JSONResponse(content,status_code=200 if health["ready"] else 503)
        return {"status": "ready_for_demo", "authoritative": False, "carrier_writes_enabled": False,
                "dependencies": {"state": "local-json-demo", "events": "local-demo", "carrier_adapters": "not_configured"}}

    @app.get("/api/v1/metrics", include_in_schema=False)
    def metrics(_: Principal = Depends(principal)):
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/api/login", include_in_schema=False)
    def login(body: LoginRequest, response: Response):
        import hmac

        if runtime.is_production_shaped:
            raise HTTPException(status_code=404,detail={"code":"demo_login_disabled"})

        expected_user = os.environ.get("SKYSOLVER_DEMO_USER", "ops")
        expected_password = os.environ.get("SKYSOLVER_DEMO_PASSWORD", "sky2026")
        if not hmac.compare_digest(body.username, expected_user) or not hmac.compare_digest(body.password, expected_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        role = body.role if body.role in DEMO_ROLE_SUBJECTS else "scheduler-demo"
        subject = DEMO_ROLE_SUBJECTS[role]
        token = issue_session(subject, role=role)
        response.headers["Set-Cookie"] = session_cookie(token, os.environ.get("SKYSOLVER_COOKIE_SECURE", "false").lower() == "true")
        return {"ok": True, "redirect": "/dashboard", "operator": {"subject": subject, "role": role, "tenant_id": "synthetic-airline"}}

    @app.get("/api/v1/overview")
    def overview(_: Principal = Depends(principal)):
        disruption = recovery_store.disruptions()[0]
        return {"api_version": "v1", "data_mode": "synthetic-demo", "authoritative": False, "provenance": DATA_PROVENANCE, "disruption": disruption, "recovery": None, "partitions": disruption["partitions"], "passengers": disruption["passengers"]}

    @app.get("/api/v1/data-health")
    def data_health(_: Principal = Depends(principal)):
        return {**data_health_registry.snapshot(),"provenance":DATA_PROVENANCE}

    @app.get("/api/v1/disruptions")
    def disruptions(_: Principal = Depends(principal)):
        return {"items": recovery_store.disruptions(), "provenance": DATA_PROVENANCE}

    @app.get("/api/v1/disruptions/{disruption_id}")
    def disruption(disruption_id: str, _: Principal = Depends(principal)):
        return recovery_store.disruption(disruption_id)

    @app.get("/api/v1/flights/{flight_id}")
    def flight(flight_id: str, _: Principal = Depends(principal)):
        return recovery_store.flight(flight_id)

    @app.get("/api/v1/crew")
    def crew(_: Principal = Depends(principal)):
        return recovery_store.crew_roster()

    @app.get("/api/v1/aircraft")
    def aircraft(_: Principal = Depends(principal)):
        return recovery_store.aircraft_fleet()

    @app.post("/api/v1/flights/{flight_id}/reassignment-preview")
    def reassignment_preview(flight_id: str, body: ReassignmentPreviewRequest, _: Principal = Depends(principal)):
        return recovery_store.reassignment_preview(flight_id, body.crew_id)

    @app.get("/api/v1/routes")
    def routes(_: Principal = Depends(principal)):
        return {"items": recovery_store.routes(), "data_mode": "synthetic-demo", "provenance": DATA_PROVENANCE}

    @app.get("/api/v1/routes/{flight_id}")
    def route(flight_id: str, _: Principal = Depends(principal)):
        return recovery_store.route(flight_id)

    @app.post("/api/v1/routes/{flight_id}/validate")
    def validate_route(flight_id: str, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(principal)):
        return recovery_store.validate_route(flight_id, {"operator_id": actor.subject, "state_version": context.state_version, "correlation_id": context.correlation_id, "causation_id": context.causation_id})

    @app.get("/api/v1/solver-tiers")
    def solver_tiers(_: Principal = Depends(principal)):
        return recovery_store.solver_tiers()

    @app.post("/api/v1/recoveries", status_code=201)
    def create_recovery(body: RecoveryRequest, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.PROPOSE))):
        payload = body.model_dump()
        payload.update({"operator_id": actor.subject, "correlation_id": context.correlation_id, "causation_id": context.causation_id})
        return recovery_store.create(payload)

    @app.get("/api/v1/recoveries/{recovery_id}")
    def recovery(recovery_id: str, _: Principal = Depends(principal)):
        return recovery_store.get(recovery_id)

    @app.get("/api/v1/recoveries/{recovery_id}/tiers")
    def recovery_tiers(recovery_id: str, _: Principal = Depends(principal)):
        recovery_store.get(recovery_id)
        return recovery_store.solver_tiers()

    @app.get("/api/v1/recoveries/{recovery_id}/candidates")
    def candidates(recovery_id: str, _: Principal = Depends(principal)):
        return {"items": recovery_store.candidates(recovery_id)}

    @app.get("/api/v1/recoveries/{recovery_id}/suggestions")
    def tier3_suggestions(recovery_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200), _: Principal = Depends(principal)):
        return recovery_store.tier3_suggestions(recovery_id,offset,limit)

    @app.post("/api/v1/recoveries/{recovery_id}/suggestions/{suggestion_id}/decisions")
    def decide_tier3_suggestion(recovery_id: str,suggestion_id: str,body: SuggestionDecisionRequest,context: MutationContext = Depends(mutation_context),actor: Principal = Depends(require_permission(Permission.PROPOSE))):
        return recovery_store.decide_tier3_suggestion(recovery_id,suggestion_id,{**body.model_dump(),"state_version":context.state_version,"operator_id":actor.subject,"correlation_id":context.correlation_id,"causation_id":context.causation_id})

    @app.get("/api/v1/candidates/{candidate_id}/explanation")
    def candidate_explanation(candidate_id: str, recovery_id: str = Query(...), _: Principal = Depends(principal)):
        candidate = next((item for item in recovery_store.candidates(recovery_id) if item["id"] == candidate_id), None)
        if candidate is None:
            raise WorkflowError(404, "candidate_not_found", "Candidate not found")
        return {"candidate_id": candidate_id, "problem": "Synthetic disruption recovery", "constraints_considered": candidate["legality_certificate"], "changes": candidate["changes"], "remaining_risk": candidate["warnings"], "tier": candidate["tier"], "ruleset_version": candidate["ruleset_version"], "state_version": candidate["state_version"], "input_snapshot_id": candidate["input_snapshot_id"]}

    @app.post("/api/v1/candidates/{candidate_id}/hold")
    def hold_candidate(candidate_id: str, recovery_id: str = Query(...), context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.PROPOSE))):
        return recovery_store.decide(recovery_id, {"candidate_id": candidate_id, "action": "hold", "reason": "Candidate resources held for review", "state_version": context.state_version, "operator_id": actor.subject, "correlation_id": context.correlation_id, "causation_id": context.causation_id})

    @app.post("/api/v1/recoveries/{recovery_id}/decisions")
    def decide(recovery_id: str, body: DecisionRequest, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.PROPOSE))):
        return recovery_store.decide(recovery_id, {**body.model_dump(), "state_version": context.state_version, "operator_id": actor.subject, "correlation_id": context.correlation_id, "causation_id": context.causation_id})

    @app.post("/api/v1/candidates/{candidate_id}/validate")
    def validate_candidate(candidate_id: str, recovery_id: str = Query(...), context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.VALIDATE))):
        recovery = recovery_store.get(recovery_id)
        if recovery["selected_candidate_id"] != candidate_id:
            raise WorkflowError(409, "candidate_not_selected", "Candidate must be selected before validation")
        return recovery_store.validate(recovery_id, {"state_version": context.state_version, "operator_id": actor.subject, "correlation_id": context.correlation_id, "causation_id": context.causation_id})

    @app.post("/api/v1/recoveries/{recovery_id}/approvals")
    def approve(recovery_id: str, body: ApprovalRequest, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.APPROVE,step_up=True))):
        return recovery_store.approve(recovery_id, {"state_version": context.state_version, "operator_id": actor.subject, "operator_role": actor.role, "reason": body.reason, "correlation_id": context.correlation_id, "causation_id": context.causation_id})

    @app.post("/api/v1/recoveries/{recovery_id}/deployments")
    def deploy(recovery_id: str, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.DEPLOY,step_up=True))):
        return recovery_store.deploy(recovery_id, {"state_version": context.state_version, "operator_id": actor.subject, "correlation_id": context.correlation_id, "causation_id": context.causation_id}, context.idempotency_key)

    @app.post("/api/v1/recoveries/{recovery_id}/deployments/simulate")
    def simulate_deployment(recovery_id: str, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.DEPLOY))):
        return recovery_store.simulate_deployment(recovery_id, {"state_version": context.state_version, "operator_id": actor.subject, "correlation_id": context.correlation_id, "causation_id": context.causation_id, "idempotency_key": context.idempotency_key})

    @app.get("/api/v1/deployments/{deployment_id}")
    def deployment(deployment_id: str, _: Principal = Depends(principal)):
        return recovery_store.deployment(deployment_id)

    @app.post("/api/v1/deployments/{deployment_id}/retry")
    def retry_deployment(deployment_id: str, body: RetryRequest, context: MutationContext = Depends(mutation_context), _: Principal = Depends(require_permission(Permission.DEPLOY))):
        return recovery_store.retry_deployment_command(deployment_id, body.command_id, context.state_version)

    @app.post("/api/v1/deployments/{deployment_id}/compensate")
    def compensate_deployment(deployment_id: str, body: CompensationRequest, context: MutationContext = Depends(mutation_context), actor: Principal = Depends(require_permission(Permission.DEPLOY))):
        return recovery_store.compensate_deployment(deployment_id, context.state_version, actor.subject, body.reason)

    @app.get("/api/v1/audit")
    def audit(_: Principal = Depends(principal)):
        return {"items": recovery_store.audit(), "storage": "mutable-local-demo", "immutable": False}

    @app.get("/api/v1/search")
    def search(q: str = Query(min_length=2, max_length=80), _: Principal = Depends(principal)):
        needle = q.casefold()
        items = []
        for flight_record in FLIGHTS:
            searchable = " ".join([flight_record["id"], flight_record["origin"], flight_record["destination"], flight_record["aircraft"]["registration"], flight_record["crew"]["id"]])
            if needle in searchable.casefold():
                items.append({"type": "flight", "id": flight_record["id"], "label": f"{flight_record['id']} · {flight_record['origin']} → {flight_record['destination']}", "provenance": DATA_PROVENANCE})
        return {"items": items, "query": q, "authoritative": False}

    @app.get("/api/v1/events")
    def events(last_event_id: str | None = Header(default=None, alias="Last-Event-ID"), _: Principal = Depends(principal)):
        audit = recovery_store.events()
        start = next((index + 1 for index, item in enumerate(audit) if item["id"] == last_event_id), 0) if last_event_id else 0

        def stream():
            for event in audit[start:]:
                yield f"id: {event['id']}\nevent: recovery.audit\ndata: {json.dumps(event)}\n\n"
            yield ": heartbeat\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/dashboard", include_in_schema=False)
    def dashboard(
        session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ):
        # Unauthenticated visitors are sent to the sign-in page rather than a raw 401.
        try:
            principal(session, authorization)
        except HTTPException as exc:
            if exc.status_code == 401:
                return RedirectResponse("/", status_code=303)
            raise
        index = frontend / "index.html"
        return FileResponse(index, headers={"Cache-Control": "no-store"}) if index.is_file() else JSONResponse({"error": "frontend_not_built"}, status_code=503)

    @app.get("/", include_in_schema=False)
    def root():
        login_file = Path(__file__).parent / "login.html"
        return FileResponse(login_file, headers={"Cache-Control": "no-store"}) if login_file.is_file() else RedirectResponse("/api/v1/docs")

    return app


app = create_app()
