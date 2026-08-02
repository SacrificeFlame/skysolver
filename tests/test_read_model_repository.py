from datetime import datetime,timedelta,timezone

from state.read_model_repository import OperationalReadRepository


NOW=datetime(2026,8,2,tzinfo=timezone.utc)
class Cursor:
    def __init__(self,ones=None,alls=None):self.ones=list(ones or []);self.alls=list(alls or []);self.executed=[]
    def execute(self,sql,parameters=()):self.executed.append((" ".join(sql.split()),parameters))
    def fetchone(self):return self.ones.pop(0) if self.ones else None
    def fetchall(self):return self.alls.pop(0) if self.alls and isinstance(self.alls[0],list) else self.alls
class Connection:
    def __init__(self,c):self.c=c;self.commits=self.rollbacks=self.closed=0
    def cursor(self):return self.c
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1
    def close(self):self.closed+=1


def test_recovery_read_sets_tenant_context_and_preserves_version():
    cursor=Cursor(ones=[(4,{"id":"REC-1"},"event-4",NOW)]);connection=Connection(cursor)
    result=OperationalReadRepository(lambda:connection).recovery("airline-1","REC-1")
    assert result["state_version"]==4 and result["recovery"]["id"]=="REC-1"
    assert "set_config('skysolver.tenant_id'" in cursor.executed[0][0]


def test_candidate_listing_marks_expiry_from_authoritative_clock():
    rows=[("CAN-1",1,"SNP","tier1","solver","RULE","OBJ","a"*64,"v1",NOW-timedelta(seconds=1),NOW),
          ("CAN-2",1,"SNP","tier2","solver","RULE","OBJ","b"*64,"v2",NOW+timedelta(minutes=1),NOW)]
    result=OperationalReadRepository(lambda:Connection(Cursor(alls=rows))).candidates("airline-1","REC-1",NOW)
    assert [item["expired"] for item in result]==[True,False]


def test_deployment_complete_is_recomputed_from_required_command_acknowledgements():
    deployment=("REC-1","CAN-1",1,"partial",5,"corr","controller",NOW,None)
    commands=[["CMD-1","crew","IC-1","crew","publish","acknowledged",True,True,1,"ref",None,None,NOW,NOW],
              ["CMD-2","gate","DEL:1","aodb","publish","rejected",True,True,1,None,"NACK",None,NOW,NOW]]
    cursor=Cursor(ones=[deployment],alls=[commands]);result=OperationalReadRepository(lambda:Connection(cursor)).deployment("airline-1","DPL-1")
    assert result["complete"] is False and result["partial"] is True


def test_audit_cursor_and_filters_are_parameterized():
    cursor=Cursor(ones=[(NOW,)],alls=[[]]);repository=OperationalReadRepository(lambda:Connection(cursor))
    assert repository.audit("airline-1",recovery_id="REC-1",after_event_id="event-1",limit=10)==[]
    sql,parameters=cursor.executed[-1]
    assert "aggregate_id=%s" in sql and "recorded_at>%s" in sql
    assert parameters==("airline-1","REC-1",NOW,10)
