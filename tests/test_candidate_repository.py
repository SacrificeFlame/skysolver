from tests.test_candidate_lifecycle import create,draft
from state.candidate_repository import CandidateRepositoryConflict,PostgresCandidateRepository


class Cursor:
    def __init__(self,row):self.row=row;self.executed=[]
    def execute(self,sql,parameters=()):self.executed.append((" ".join(sql.split()),parameters))
    def fetchone(self):return self.row
class Connection:
    def __init__(self,row):self.c=Cursor(row);self.commits=self.rollbacks=self.closed=0
    def cursor(self):return self.c
    def commit(self):self.commits+=1
    def rollback(self):self.rollbacks+=1
    def close(self):self.closed+=1


def test_candidate_index_commits_object_version_and_content_hash():
    candidate=create(draft());connection=Connection((candidate.candidate_id,))
    PostgresCandidateRepository(lambda:connection).insert(candidate)
    parameters=connection.c.executed[-1][1]
    assert candidate.content_sha256 in parameters and candidate.artifact.version_id in parameters
    assert connection.commits==1


def test_duplicate_candidate_index_rolls_back():
    candidate=create(draft());connection=Connection(None)
    try:PostgresCandidateRepository(lambda:connection).insert(candidate)
    except CandidateRepositoryConflict:pass
    else:raise AssertionError("duplicate candidate accepted")
    assert connection.rollbacks==1
