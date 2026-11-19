"""Fine-grained permission checks layered on top of role/tenant scope."""
from __future__ import annotations

from enum import Enum

from fastapi import Depends

from harness_common import models as m
from .deps import IdentityDep


class Perm(str, Enum):
    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    MEMBER_READ = "member:read"
    MEMBER_WRITE = "member:write"
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_WRITE = "workspace:write"
    USAGE_READ = "usage:read"
    AUDIT_READ = "audit:read"
    TEMPLATE_WRITE = "template:write"


_ALL = set(Perm)
_TENANT_ADMIN = {
    Perm.TENANT_READ, Perm.USER_READ, Perm.MEMBER_READ, Perm.MEMBER_WRITE,
    Perm.WORKSPACE_READ, Perm.WORKSPACE_WRITE, Perm.USAGE_READ, Perm.AUDIT_READ,
}
_MEMBER = {Perm.WORKSPACE_READ}


def permissions_for(identity) -> set[Perm]:
    if identity.is_platform_admin:
        return _ALL
    if identity.role == m.MEMBER_ADMIN and identity.tenant_id:
        return _TENANT_ADMIN
    return _MEMBER


def require_permission(perm: Perm):
    async def _check(identity: IdentityDep) -> None:
        if perm not in permissions_for(identity):
            from harness_common.errors import APIError
            raise APIError("FORBIDDEN", f"Missing permission: {perm.value}")
    return Depends(_check)
