from deployment.authorization import Permission, allows


def test_scheduler_can_propose_but_cannot_approve_or_deploy():
    assert allows("scheduler", Permission.PROPOSE)
    assert not allows("scheduler", Permission.APPROVE)
    assert not allows("scheduler", Permission.DEPLOY)


def test_duty_manager_and_controller_have_separate_authority():
    assert allows("duty-manager", Permission.APPROVE)
    assert not allows("duty-manager", Permission.DEPLOY)
    assert allows("deployment-controller", Permission.DEPLOY)
    assert not allows("deployment-controller", Permission.APPROVE)


def test_unknown_role_has_no_permissions():
    assert not allows("client-supplied-admin", Permission.READ)
