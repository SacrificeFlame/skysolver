from state.immutable_artifacts import ArtifactIntegrityError,ArtifactReference,ObjectLockArtifactStore


class S3:
    def __init__(self,version="v1"):self.version=version;self.put=None
    def put_object(self,**kwargs):self.put=kwargs;return {"VersionId":self.version} if self.version else {}
    def head_object(self,**kwargs):return {"Metadata":self.put["Metadata"],"ObjectLockMode":self.put["ObjectLockMode"],"SSEKMSKeyId":self.put["SSEKMSKeyId"]}


def test_artifact_is_canonical_kms_encrypted_versioned_and_compliance_locked():
    s3=S3();store=ObjectLockArtifactStore(s3,"artifacts","kms-1")
    reference=store.put(tenant_id="airline-1",recovery_id="REC-1",artifact_type="candidate",artifact_id="CAN-1",value={"b":2,"a":1})
    assert s3.put["Body"]==b'{"a":1,"b":2}'
    assert s3.put["ServerSideEncryption"]=="aws:kms"
    assert s3.put["ObjectLockMode"]=="COMPLIANCE"
    assert reference.version_id=="v1" and store.verify(reference)


def test_missing_version_id_fails_closed():
    try:ObjectLockArtifactStore(S3(version=""),"artifacts","kms-1").put(tenant_id="a",recovery_id="r",artifact_type="audit",artifact_id="e",value={})
    except ArtifactIntegrityError:pass
    else:raise AssertionError("unversioned artifact accepted")


def test_tampered_metadata_fails_verification():
    s3=S3();store=ObjectLockArtifactStore(s3,"artifacts","kms-1");reference=store.put(tenant_id="a",recovery_id="r",artifact_type="validation",artifact_id="v",value={"legal":True})
    s3.put["Metadata"]["sha256"]="0"*64
    assert not store.verify(reference)


def test_verified_read_rejects_body_tampering():
    class Body:
        def read(self):return b'{"different":true}'
    class S3:
        def head_object(self,**kwargs):return {"Metadata":{"sha256":"a"*64},"ObjectLockMode":"COMPLIANCE","SSEKMSKeyId":"kms-1"}
        def get_object(self,**kwargs):return {"Body":Body()}
    reference=ArtifactReference("bucket","key","v1","a"*64,"kms-1","future","candidate")
    with __import__("pytest").raises(ArtifactIntegrityError,match="digest"):
        ObjectLockArtifactStore(S3(),"bucket","kms-1").get_verified(reference)
