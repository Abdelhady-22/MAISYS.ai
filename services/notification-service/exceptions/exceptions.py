"""notification-service exception classes."""

from __future__ import annotations

from shared.error_handler import MaisysException


class NotificationServiceException(MaisysException):
    """Base for every notification-service error."""

    code = "NOTIFICATION_SERVICE_ERROR"
    status_code = 500


class TemplateNotFound(NotificationServiceException):
    """Requested template name isn't registered."""

    code = "TEMPLATE_NOT_FOUND"
    status_code = 400


class TemplateVariableMissing(NotificationServiceException):
    """A template variable required by the template was missing from the request."""

    code = "TEMPLATE_VARIABLE_MISSING"
    status_code = 400


class TemplateNameMismatch(NotificationServiceException):
    """``notification_type`` and ``template_name`` disagree.

    Per Part 5 §7.1 these are separate fields on the queue payload
    and we accept that duplication in the HTTP body for parity. They
    must match — otherwise the audit log can't be trusted.
    """

    code = "TEMPLATE_NAME_MISMATCH"
    status_code = 400


class EmailDeliveryFailed(NotificationServiceException):
    """SendGrid (or SMTP) rejected the message after all retries.

    The HTTP route does NOT raise this — delivery happens in a
    background task and failures are recorded in the
    ``notification_log`` row. This exception is raised inside the
    delivery service and surfaced via the GET endpoint.
    """

    code = "EMAIL_DELIVERY_FAILED"
    status_code = 502


class NotificationNotFound(NotificationServiceException):
    """``GET /notifications/{id}`` referenced an unknown id."""

    code = "NOTIFICATION_NOT_FOUND"
    status_code = 404


__all__ = [
    "EmailDeliveryFailed",
    "NotificationNotFound",
    "NotificationServiceException",
    "TemplateNameMismatch",
    "TemplateNotFound",
    "TemplateVariableMissing",
]
