"""Role policy for recovery actions.

Airline IdP groups will map to these roles at the Cognito boundary. The policy
is centralized so UI visibility never becomes the authorization control.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    SCHEDULER = "scheduler"
    DUTY_MANAGER = "duty-manager"
    DEPLOYMENT_CONTROLLER = "deployment-controller"
    RECOVERY_MANAGER = "recovery-manager"
    SUPERVISOR_READ_ONLY = "supervisor-read-only"
    DEMO_SCHEDULER = "scheduler-demo"


class Permission(str, Enum):
    READ = "read"
    PROPOSE = "propose"
    VALIDATE = "validate"
    APPROVE = "approve"
    DEPLOY = "deploy"
    OVERRIDE = "override"


ROLE_PERMISSIONS = {
    Role.SCHEDULER: {Permission.READ, Permission.PROPOSE, Permission.VALIDATE},
    Role.DEMO_SCHEDULER: {Permission.READ, Permission.PROPOSE, Permission.VALIDATE},
    Role.DUTY_MANAGER: {Permission.READ, Permission.VALIDATE, Permission.APPROVE, Permission.OVERRIDE},
    Role.DEPLOYMENT_CONTROLLER: {Permission.READ, Permission.DEPLOY},
    Role.RECOVERY_MANAGER: {Permission.READ, Permission.PROPOSE, Permission.VALIDATE},
    Role.SUPERVISOR_READ_ONLY: {Permission.READ},
}


def allows(role: str, permission: Permission) -> bool:
    try:
        normalized = Role(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS[normalized]
