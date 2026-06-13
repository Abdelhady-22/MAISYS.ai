"""GCP Secret Manager resolution shim for the scrapers.

Temporary until ``shared/security.get_secret`` exists (see
``data-pipeline/CLAUDE.md``). Resolves a secret by name with: ``<NAME>`` env-var
fallback (local dev), then Secret Manager with project discovery via
``GOOGLE_CLOUD_PROJECT``/``google.auth.default()`` — never a hardcoded project.

Modeled on ``download_mtsamples_kaggle.resolve_kaggle_credentials`` /
``download_huggingface_medical.resolve_hf_token``.
"""

from __future__ import annotations

import os

from ._logging import get_logger

log = get_logger()


class SecretError(Exception):
    """Raised when a required secret cannot be resolved."""


def _env_name(secret_name: str) -> str:
    return secret_name.upper().replace("-", "_")


def _discover_project() -> str | None:
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if project:
        return project
    try:
        import google.auth

        _, project = google.auth.default()
    except Exception as exc:  # noqa: BLE001 - best-effort discovery
        log.warning("gcp_project_discovery_failed", error=str(exc))
        return None
    return project


def resolve_secret(
    secret_name: str, *, required: bool = True, create_hint: str | None = None
) -> str | None:
    """Resolve a secret's value.

    Order: ``<SECRET_NAME>`` env var, then GCP Secret Manager
    ``projects/<project>/secrets/<secret_name>/versions/latest``.

    Args:
        secret_name: The Secret Manager secret id (e.g. ``infermedica-app-id``).
        required: When True, raise :class:`SecretError` (with ``create_hint``) if
            the secret cannot be resolved. When False, return ``None`` instead.
        create_hint: Extra guidance appended to the error (e.g. the
            ``gcloud secrets create …`` command).

    Raises:
        SecretError: When ``required`` and resolution fails.
    """
    env_value = os.getenv(_env_name(secret_name))
    if env_value:
        return env_value

    def _fail(message: str) -> str | None:
        full = message if not create_hint else f"{message}\n{create_hint}"
        if required:
            raise SecretError(full)
        log.warning("secret_unresolved", secret=secret_name, reason=message)
        return None

    try:
        from google.cloud import secretmanager
    except ImportError:
        return _fail(
            "google-cloud-secret-manager is not installed "
            "(pip install google-cloud-secret-manager)."
        )

    project = _discover_project()
    if not project:
        return _fail(
            "could not determine the GCP project; set GOOGLE_CLOUD_PROJECT or run "
            "'gcloud auth application-default login'."
        )

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_name}/versions/latest"
    try:
        response = client.access_secret_version(name=name)
    except Exception as exc:  # noqa: BLE001 - not found / no access
        return _fail(f"could not read secret '{secret_name}' in project '{project}': {exc}")

    value: str = response.payload.data.decode("utf-8")
    return value
