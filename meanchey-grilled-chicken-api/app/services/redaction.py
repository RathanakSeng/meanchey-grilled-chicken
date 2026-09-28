"""Hide the superadmin from every other viewer.

The general manager (and everyone below) must not be able to tell that a superadmin exists.
Two mechanisms, both applied centrally:

- **References.** Every user reference in a response is a `schemas.common.UserRef`. Its
  serializer asks `hides(role)` and, for a non-superadmin viewer, turns a reference to the
  superadmin into `{id: null, full_name: "System", is_system: true}`. New endpoints are covered as
  long as they use `UserRef` for user references.
- **Lookups.** `user_service.get_user_or_404(..., viewer=...)` answers `404 USER_NOT_FOUND` when a
  non-superadmin asks for the superadmin by id (a 403 would confirm the account exists).

The viewer is recorded per request by the auth dependency (`deps.get_current_user_allow_pending`)
and reset for every request by `ViewerContextMiddleware`. When no viewer is known the redaction
fails closed: the superadmin is hidden.
"""

from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

from app.models import Role, User

SYSTEM_NAME = "System"

_viewer_role: ContextVar[Role | None] = ContextVar("viewer_role", default=None)


def set_viewer(user: User) -> None:
    _viewer_role.set(user.role)


def viewer_is_superadmin() -> bool:
    return _viewer_role.get() == Role.SUPERADMIN


def hides(role: Role | str | None) -> bool:
    """True when a reference to a user with `role` must be shown as "System"."""
    return role == Role.SUPERADMIN and not viewer_is_superadmin()


def hides_user(user: User | None, viewer: User | None) -> bool:
    """Explicit-viewer variant for services (lookups, filters)."""
    return (
        user is not None
        and user.role == Role.SUPERADMIN
        and (viewer is None or viewer.role != Role.SUPERADMIN)
    )


class ViewerContextMiddleware:
    """Start every request with no viewer, so nothing leaks between requests on one task."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        token = _viewer_role.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            _viewer_role.reset(token)
