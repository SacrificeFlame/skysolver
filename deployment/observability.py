"""Low-cardinality operational telemetry for the recovery control plane."""

from prometheus_client import Counter, Gauge, Histogram


HTTP_REQUESTS = Counter("skysolver_http_requests_total", "API requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("skysolver_http_request_duration_seconds", "API request latency", ["method", "route"])
RECOVERY_MUTATIONS = Counter("skysolver_recovery_mutations_total", "Recovery mutations", ["action", "status"])
DEPLOYMENT_COMMANDS = Gauge("skysolver_deployment_commands", "Deployment commands by state", ["status"])
DATA_SOURCE_HEALTH = Gauge("skysolver_data_source_health", "Data-source health (1 healthy, 0 blocked)", ["source"])
CARRIER_WRITE_GATE = Gauge("skysolver_carrier_writes_enabled", "Carrier publishing interlock")

CARRIER_WRITE_GATE.set(0)
DATA_SOURCE_HEALTH.labels(source="skysolver-scenario-fixture").set(0)
