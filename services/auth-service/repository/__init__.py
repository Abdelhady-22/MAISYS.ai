"""Repository layer — all data access lives here.

Per ``services/CLAUDE.md`` the rule is strict: business logic never writes
SQL or composes queries. Routes never touch the database directly. The
dependency direction is one-way: routes → services → repository.

Every repository takes an ``AsyncSession`` in its constructor and is
typically constructed via a FastAPI ``Depends`` factory that yields a
fresh session per request.
"""

from repository.audit_repository import AuditRepository
from repository.oauth_repository import OAuthAccountRepository
from repository.otp_repository import OTPRepository
from repository.password_reset_repository import PasswordResetRepository
from repository.session_repository import SessionRepository
from repository.user_repository import UserRepository

__all__ = [
    "AuditRepository",
    "OAuthAccountRepository",
    "OTPRepository",
    "PasswordResetRepository",
    "SessionRepository",
    "UserRepository",
]
