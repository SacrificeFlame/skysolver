"""Transactional-outbox publisher process with graceful drain semantics."""

from __future__ import annotations

import os
import signal
import threading
import time

from state.aws_runtime import AuroraIamConnectionFactory, AuroraIamSettings, MskIamProducer
from state.postgres_event_store import OutboxPublisher, PostgresEventRepository


def build_publisher() -> OutboxPublisher:
    settings=AuroraIamSettings.from_url(os.environ["SKYSOLVER_DATABASE_URL"],region=os.environ.get("AWS_REGION","ap-south-1"),sslrootcert=os.environ["AWS_RDS_CA_BUNDLE"])
    repository=PostgresEventRepository(AuroraIamConnectionFactory(settings))
    producer=MskIamProducer(os.environ["MSK_BOOTSTRAP_SERVERS"],os.environ.get("AWS_REGION","ap-south-1"))
    return OutboxPublisher(repository,producer,os.environ.get("HOSTNAME","outbox-worker"))


def run(publisher: OutboxPublisher|None=None, stop: threading.Event|None=None) -> None:
    publisher=publisher or build_publisher(); stop=stop or threading.Event()
    while not stop.is_set():
        result=publisher.publish_batch(int(os.environ.get("OUTBOX_BATCH_SIZE","100")))
        if result["claimed"]==0: stop.wait(float(os.environ.get("OUTBOX_IDLE_SECONDS","0.5")))


def main():
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set()); signal.signal(signal.SIGINT,lambda *_:stop.set())
    run(stop=stop)


if __name__=="__main__": main()
