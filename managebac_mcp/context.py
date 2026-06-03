"""
Request-scoped user context — the core of multi-user isolation.

Every data operation (HTTP fetch, cache read/write) must know WHICH user it is
acting for. That user is stored in a contextvar, which is isolated per async
task: even with many users hitting the server at once, each request sees only
its own user.

FAIL CLOSED: if no user is set, `require_user()` raises. There is no global
default user in multi-user mode — no context means no data access, ever. This
is what prevents a bug from turning into a cross-user data leak.
"""
import contextvars
from dataclasses import dataclass

_current_user: contextvars.ContextVar = contextvars.ContextVar("current_user", default=None)


class ManageBacError(Exception):
    """
    A fetch/parse failure carrying a human-readable reason.

    Raised instead of letting a tool return a silently-empty result, so the AI
    (and the student) get told WHY something failed — bad login, ManageBac
    redirect loop, unexpected page — rather than a confusing empty answer. The
    reason is also written to the request log for the admin to see.
    """
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class User:
    id: str            # stable random id, used to namespace cache + sessions
    token: str         # secret in the connector URL
    label: str         # friendly name (usually their email)
    mb_url: str        # their ManageBac base URL (schools differ)
    email: str         # ManageBac login
    password: str      # decrypted, in-memory only — never logged or cached


def set_current_user(user: User):
    """Bind a user to the current context. Returns a token for reset()."""
    return _current_user.set(user)

def reset_user(token) -> None:
    _current_user.reset(token)

def get_current_user() -> User | None:
    return _current_user.get()

def require_user() -> User:
    """Return the current user, or raise if none is set (fail closed)."""
    user = _current_user.get()
    if user is None:
        raise RuntimeError(
            "No user context set — refusing to access ManageBac data. "
            "This is a safety guard against cross-user data leaks."
        )
    return user
