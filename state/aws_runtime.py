"""Concrete Aurora IAM and Amazon MSK IAM runtime adapters."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse


class RuntimeDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuroraIamSettings:
    host: str
    port: int
    database: str
    username: str
    region: str
    sslrootcert: str

    @classmethod
    def from_url(cls, url: str, *, region: str, sslrootcert: str) -> "AuroraIamSettings":
        parsed=urlparse(url)
        if parsed.scheme not in {"postgresql","postgres"} or not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
            raise ValueError("Aurora URL must contain PostgreSQL scheme, username, host and database")
        if parsed.password:
            raise ValueError("Aurora IAM URL must not embed a static password")
        if not sslrootcert:
            raise ValueError("Aurora IAM requires an RDS CA bundle")
        return cls(parsed.hostname,parsed.port or 5432,parsed.path.strip("/"),unquote(parsed.username),region,sslrootcert)


class AuroraIamConnectionFactory:
    def __init__(self, settings: AuroraIamSettings, token_factory: Callable[...,str]|None=None, connect: Callable[...,Any]|None=None):
        self.settings=settings
        if token_factory is None:
            import boto3
            token_factory=boto3.client("rds",region_name=settings.region).generate_db_auth_token
        if connect is None:
            import psycopg
            connect=psycopg.connect
        self._token_factory=token_factory; self._connect=connect

    def __call__(self):
        token=self._token_factory(DBHostname=self.settings.host,Port=self.settings.port,DBUsername=self.settings.username,Region=self.settings.region)
        return self._connect(host=self.settings.host,port=self.settings.port,dbname=self.settings.database,user=self.settings.username,password=token,
                             sslmode="verify-full",sslrootcert=self.settings.sslrootcert,connect_timeout=10,application_name="skysolver")


class MskIamProducer:
    def __init__(self, bootstrap_servers: str, region: str, *, producer_factory=None, token_provider=None):
        if not bootstrap_servers.strip(): raise ValueError("MSK bootstrap servers are required")
        if producer_factory is None:
            from confluent_kafka import Producer
            producer_factory=Producer
        if token_provider is None:
            from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
            token_provider=MSKAuthTokenProvider
        self._region=region; self._token_provider=token_provider
        self._producer=producer_factory({
            "bootstrap.servers":bootstrap_servers,
            "security.protocol":"SASL_SSL",
            "sasl.mechanism":"OAUTHBEARER",
            "oauth_cb":self._oauth_token,
            "enable.idempotence":True,
            "acks":"all",
            "retries":10,
            "max.in.flight.requests.per.connection":5,
            "client.id":"skysolver-outbox",
        })

    def _oauth_token(self,_config=None):
        token,expiry_ms=self._token_provider.generate_auth_token(self._region)
        return token,expiry_ms/1000

    def publish(self, topic: str, key: str, value: bytes, headers: dict[str,str]) -> str:
        acknowledgement={"error":None,"partition":None,"offset":None}
        def delivered(error,message):
            acknowledgement.update(error=error,partition=message.partition() if message else None,offset=message.offset() if message else None)
        self._producer.produce(topic=topic,key=key.encode(),value=value,headers=list(headers.items()),on_delivery=delivered)
        remaining=self._producer.flush(10)
        if remaining or acknowledgement["error"] is not None:
            raise RuntimeDependencyError(f"MSK broker did not acknowledge event: {acknowledgement['error'] or 'flush timeout'}")
        return f"{topic}:{acknowledgement['partition']}:{acknowledgement['offset']}"
