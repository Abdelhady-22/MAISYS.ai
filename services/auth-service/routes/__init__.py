"""HTTP route handlers — one APIRouter per concern.

Routes are thin: they extract request data, call a service method,
wrap the result in ``APIResponse[T].ok(data)``, and return. They
never touch repositories or compose SQL directly.

The exception handlers wired in main.py (Session C) translate
typed exceptions from ``exceptions/auth_exceptions.py`` into the
shared error envelope.
"""

from routes.login import router as login_router
from routes.logout import router as logout_router
from routes.me import router as me_router
from routes.oauth_callback import router as oauth_router
from routes.password_reset import router as password_reset_router
from routes.refresh import router as refresh_router
from routes.register import router as register_router
from routes.sessions import router as sessions_router
from routes.verify_otp import router as verify_otp_router

ALL_ROUTERS = [
    register_router,
    verify_otp_router,
    login_router,
    refresh_router,
    logout_router,
    oauth_router,
    password_reset_router,
    me_router,
    sessions_router,
]

__all__ = [
    "ALL_ROUTERS",
    "login_router",
    "logout_router",
    "me_router",
    "oauth_router",
    "password_reset_router",
    "refresh_router",
    "register_router",
    "sessions_router",
    "verify_otp_router",
]
