from state.aws_runtime import AuroraIamConnectionFactory,AuroraIamSettings,MskIamProducer,RuntimeDependencyError


def test_aurora_iam_rejects_static_password_and_requires_ca():
    for url,ca in (("postgresql://user:secret@db/skysolver","ca.pem"),("postgresql://user@db/skysolver","")):
        try: AuroraIamSettings.from_url(url,region="ap-south-1",sslrootcert=ca)
        except ValueError: pass
        else: raise AssertionError("unsafe Aurora settings accepted")


def test_aurora_connection_uses_fresh_iam_token_and_verify_full():
    calls=[]
    settings=AuroraIamSettings.from_url("postgresql://app@cluster:5432/skysolver",region="ap-south-1",sslrootcert="rds-ca.pem")
    factory=AuroraIamConnectionFactory(settings,token_factory=lambda **kwargs:"fresh-token",connect=lambda **kwargs:calls.append(kwargs) or object())
    factory();factory()
    assert len(calls)==2 and all(item["password"]=="fresh-token" for item in calls)
    assert calls[0]["sslmode"]=="verify-full" and calls[0]["sslrootcert"]=="rds-ca.pem"


class Message:
    def partition(self): return 2
    def offset(self): return 91
class Producer:
    def __init__(self,config): self.config=config;self.callback=None
    def produce(self,**kwargs): self.callback=kwargs["on_delivery"];self.callback(None,Message())
    def flush(self,timeout): return 0
class Token:
    @staticmethod
    def generate_auth_token(region): return "token",2_000_000


def test_msk_producer_enforces_iam_tls_idempotence_and_waits_for_ack():
    holder=[]
    producer=MskIamProducer("broker:9098","ap-south-1",producer_factory=lambda config:holder.append(Producer(config)) or holder[0],token_provider=Token)
    assert holder[0].config["security.protocol"]=="SASL_SSL"
    assert holder[0].config["sasl.mechanism"]=="OAUTHBEARER"
    assert holder[0].config["enable.idempotence"] is True
    assert producer.publish("events","DEL",b"{}",{"event_id":"1"})=="events:2:91"
