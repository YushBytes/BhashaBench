"""What each workspace role may do. One table, read by every check.

Roles are ordered (`owner` > `admin` > `member` > `viewer`) and each
permission names the least role that holds it, so the matrix cannot drift
into a role holding a permission a more privileged role lacks.
"""

from __future__ import annotations

from enum import StrEnum

from app.models.identity import Role

RANK: dict[Role, int] = {Role.VIEWER: 0, Role.MEMBER: 1, Role.ADMIN: 2, Role.OWNER: 3}


class Permission(StrEnum):
    VIEW = "view"
    """Read suites, scenarios, runs, turns, artefacts, evaluations, reports."""
    EDIT = "edit"
    """Create and change suites and scenarios; create, start, drive and cancel
    runs and conversations; evaluate; record references."""
    DELETE = "delete"
    """Delete suites and scenarios."""
    MANAGE_PROJECTS = "manage_projects"
    """Create, rename and delete projects."""
    MANAGE_MEMBERS = "manage_members"
    """Add, change and remove members - never above one's own role."""


MINIMUM_ROLE: dict[Permission, Role] = {
    Permission.VIEW: Role.VIEWER,
    Permission.EDIT: Role.MEMBER,
    Permission.DELETE: Role.ADMIN,
    Permission.MANAGE_PROJECTS: Role.ADMIN,
    Permission.MANAGE_MEMBERS: Role.ADMIN,
}


def allows(role: Role, permission: Permission) -> bool:
    return RANK[role] >= RANK[MINIMUM_ROLE[permission]]


def can_assign(actor: Role, target_current: Role | None, target_new: Role | None) -> bool:
    """Whether `actor` may move a member from `target_current` to `target_new`.

    `None` means "not a member" on either side, so adding is
    `(None, role)` and removing is `(role, None)`. Only an owner may grant,
    change or remove the owner or admin role; an admin manages members and
    viewers only. Keeping the last owner is enforced by the service, which
    can count owners.
    """
    if not allows(actor, Permission.MANAGE_MEMBERS):
        return False
    if actor is Role.OWNER:
        return True
    privileged = {Role.OWNER, Role.ADMIN}
    return target_current not in privileged and target_new not in privileged


__all__ = ["MINIMUM_ROLE", "RANK", "Permission", "allows", "can_assign"]
