"""S3 Object Lock writer for immutable recovery and audit artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import base64
import hashlib
import json
from typing import Any


class ArtifactIntegrityError(RuntimeError):pass


@dataclass(frozen=True)
class ArtifactReference:
    bucket:str
    key:str
    version_id:str
    content_sha256:str
    kms_key_id:str
    retained_until:str
    artifact_type:str


class ObjectLockArtifactStore:
    def __init__(self,s3_client,bucket:str,kms_key_id:str,retention_days:int=2555):
        if retention_days<1:raise ValueError("Object Lock retention must be positive")
        self.s3=s3_client;self.bucket=bucket;self.kms_key_id=kms_key_id;self.retention_days=retention_days
    @staticmethod
    def canonical(value:Any)->bytes:return json.dumps(value,sort_keys=True,separators=(",",":"),default=str,ensure_ascii=True).encode()
    def put(self,*,tenant_id:str,recovery_id:str,artifact_type:str,artifact_id:str,value:Any)->ArtifactReference:
        body=self.canonical(value);sha=hashlib.sha256(body).hexdigest();md5=base64.b64encode(hashlib.md5(body,usedforsecurity=False).digest()).decode()
        retained=datetime.now(timezone.utc)+timedelta(days=self.retention_days)
        key=f"tenants/{tenant_id}/recoveries/{recovery_id}/{artifact_type}/{artifact_id}.json"
        response=self.s3.put_object(Bucket=self.bucket,Key=key,Body=body,ContentType="application/json",ContentMD5=md5,
            ServerSideEncryption="aws:kms",SSEKMSKeyId=self.kms_key_id,ObjectLockMode="COMPLIANCE",ObjectLockRetainUntilDate=retained,
            Metadata={"sha256":sha,"artifact-type":artifact_type,"tenant-id":tenant_id,"recovery-id":recovery_id})
        version=response.get("VersionId")
        if not version:raise ArtifactIntegrityError("Versioned Object Lock bucket did not return a VersionId")
        return ArtifactReference(self.bucket,key,version,sha,self.kms_key_id,retained.isoformat(),artifact_type)
    def verify(self,reference:ArtifactReference)->bool:
        head=self.s3.head_object(Bucket=reference.bucket,Key=reference.key,VersionId=reference.version_id)
        metadata=head.get("Metadata",{});mode=head.get("ObjectLockMode");kms=head.get("SSEKMSKeyId")
        return metadata.get("sha256")==reference.content_sha256 and mode=="COMPLIANCE" and kms==reference.kms_key_id
