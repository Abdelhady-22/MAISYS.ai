"""Business-logic service layer.

Routes are thin HTTP adapters that call into these services. Services
own the orchestration of repository calls, password hashing, JWT
issuance, audit-log writes, and the auth-specific error semantics.

A service takes its dependencies in the constructor (typically just
``AsyncSession``) and never opens its own transactions — the session
lifecycle is owned by the route's FastAPI dependency.
"""

from services.email_service import EmailService
from services.login_service import LoginService
from services.oauth_service import OAuthService
from services.password_reset_service import PasswordResetService
from services.profile_service import ProfileService
from services.registration_service import RegistrationService
from services.token_service import TokenService

__all__ = [
    "EmailService",
    "LoginService",
    "OAuthService",
    "PasswordResetService",
    "ProfileService",
    "RegistrationService",
    "TokenService",
]
