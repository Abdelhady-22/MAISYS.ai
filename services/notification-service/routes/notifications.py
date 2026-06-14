"""``/notifications/send`` and ``/notifications/{id}`` HTTP routes."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from services.notification_service.exceptions.exceptions import NotificationNotFound
from services.notification_service.models.schemas import (
    Language,
    NotificationStatus,
    NotificationStatusResponse,
    NotificationType,
    SendNotificationRequest,
    SendNotificationResponse,
)
from services.notification_service.repository.notification_repo import (
    NotificationRepository,
)
from services.notification_service.services.notification_sender import (
    NotificationSender,
)
from shared.auth import TokenPayload, get_current_user
from shared.error_handler import APIResponse
from shared.logger import get_logger

_log = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_sender(request: Request) -> NotificationSender:
    sender: NotificationSender | None = getattr(request.app.state, "notification_sender", None)
    if sender is None:  # pragma: no cover — wiring guarantees this
        raise RuntimeError("notification_sender is not wired into app.state")
    return sender


@router.post(
    "/send",
    response_model=APIResponse[SendNotificationResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Accept a notification for asynchronous delivery",
)
async def send_notification(
    body: SendNotificationRequest,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),
) -> JSONResponse:
    sender = _get_sender(http_request)
    notification_id = await sender.accept(body)

    async with http_request.app.state.session_factory() as session:
        repo = NotificationRepository(session)
        row = await repo.get_by_id(notification_id)
    assert row is not None

    response = SendNotificationResponse(
        notification_id=notification_id,
        status=cast(NotificationStatus, row.status),
        accepted_at=row.accepted_at,
    )
    _log.info(
        "notification.accepted",
        notification_id=notification_id,
        user_id=user.sub,
        notification_type=body.notification_type,
        priority=body.priority,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=APIResponse[SendNotificationResponse].ok(response).model_dump(mode="json"),
    )


@router.get(
    "/{notification_id}",
    response_model=APIResponse[NotificationStatusResponse],
    summary="Get the current status of a notification",
)
async def get_notification_status(
    notification_id: str,
    http_request: Request,
    user: TokenPayload = Depends(get_current_user),
) -> JSONResponse:
    async with http_request.app.state.session_factory() as session:
        repo = NotificationRepository(session)
        row = await repo.get_by_id(notification_id)
    if row is None:
        raise NotificationNotFound(f"No notification with id {notification_id!r}")

    response = NotificationStatusResponse(
        notification_id=row.id,
        notification_type=cast(NotificationType, row.notification_type),
        user_id=row.user_id,
        recipient_email=row.recipient_email,
        language=cast(Language, row.language),
        status=cast(NotificationStatus, row.status),
        attempts=row.attempts,
        last_error=row.last_error,
        accepted_at=row.accepted_at,
        delivered_at=row.delivered_at,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=APIResponse[NotificationStatusResponse].ok(response).model_dump(mode="json"),
    )
