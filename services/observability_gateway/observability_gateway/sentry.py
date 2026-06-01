import os
import re

import httpx

SINCE_PATTERN = re.compile(r"^\d+[smhd]$")


class ClientIssueNotFoundError(Exception):
    """Raised when Sentry has no latest event for one client issue group."""

    pass


def required_environment_value(name: str) -> str:
    """Return one required trimmed environment variable.

    Args:
        name: Environment variable to read.

    Returns:
        The configured value without leading or trailing whitespace.

    Raises:
        ValueError: The variable is absent, empty, or contains only whitespace.

    Example:
        `required_environment_value("SENTRY_ORG")` returns `demo-org` when
        `SENTRY_ORG=demo-org`.
    """

    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} must be configured")
    return value


class SentryClientDiagnostics:
    """Read-only adapter for Flutter client exceptions stored in Sentry.

    It uses a Sentry API token to list recent issues for one configured
    project and normalize them into client issue summaries.

    Example:
        `SentryClientDiagnostics().list_issues(since="15m", limit=20,
        run_id=None)` lists recent Flutter exceptions from the local
        environment.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        auth_token: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        environment: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Configure Sentry project identity, authentication, and HTTP.

        Args:
            api_url: Sentry API base URL. Defaults to `https://sentry.io/api/0`.
            auth_token: Read-only API token. When omitted, read
                `SENTRY_AUTH_TOKEN`.
            organization: Sentry organization slug. When omitted, read
                `SENTRY_ORG`.
            project: Sentry project slug. When omitted, read `SENTRY_PROJECT`.
            environment: Environment included in issue list queries. When
                omitted, read `DIAGNOSTICS_ENVIRONMENT`, falling back to
                `local`.
            client: HTTP client used for Sentry requests. When omitted, create
                a client with a ten-second timeout.
        """

        self._api_url = (api_url or "https://sentry.io/api/0").rstrip("/")
        self._auth_token = auth_token or required_environment_value(
            "SENTRY_AUTH_TOKEN"
        )
        self._organization = organization or required_environment_value("SENTRY_ORG")
        self._project = project or required_environment_value("SENTRY_PROJECT")
        self._environment = (
            environment or os.environ.get("DIAGNOSTICS_ENVIRONMENT", "local").strip()
        )
        self._client = client or httpx.Client(timeout=10)

    def close(self) -> None:
        """Close the HTTP client used for Sentry API requests."""

        self._client.close()

    def list_issues(
        self, *, since: str, limit: int, run_id: str | None
    ) -> list[dict[str, object]]:
        """List recent Flutter issue summaries from the configured project.

        Args:
            since: Relative lookback duration such as `15m`.
            limit: Maximum number of summaries to request, from 1 through 100.
            run_id: Reserved workload UUID filter. Sentry client events do not
                include this field until the workload integration is added.

        Returns:
            Lightweight client issue summaries without stacktraces or
            breadcrumbs.
        """

        if SINCE_PATTERN.fullmatch(since) is None:
            raise ValueError("since must be a duration such as 15m")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        response = self._client.get(
            f"{self._api_url}/organizations/{self._organization}/issues/",
            headers=self._headers(),
            params={
                "query": f"project:{self._project}",
                "environment": self._environment,
                "statsPeriod": since,
                "limit": str(limit),
            },
        )
        response.raise_for_status()
        return [self._summary_from_issue(issue) for issue in response.json()]

    def get_issue(self, issue_id: str) -> dict[str, object]:
        """Return bounded client exception context from one latest Sentry event.

        Args:
            issue_id: Client issue identifier in `client:<group-id>` format.

        Returns:
            One client issue summary, the complete exception frame list, the
            last 100 breadcrumbs, release, environment, user, session context,
            and Sentry trace context attached by the Flutter App.
        """

        group_id = self._group_id_from(issue_id)
        response = self._client.get(
            (
                f"{self._api_url}/organizations/{self._organization}/issues/"
                f"{group_id}/events/latest/"
            ),
            headers=self._headers(),
            params={"environment": self._environment},
        )
        if response.status_code == 404:
            raise ClientIssueNotFoundError(issue_id)
        response.raise_for_status()
        event = response.json()
        exception = self._exception_from(event)
        release = event.get("release")
        if isinstance(release, dict):
            release = release.get("version")
        user = event.get("user")
        if not isinstance(user, dict):
            user = {}
        tags = self._tags_from(event)
        trace_id = self._trace_id_from(event)
        return {
            "summary": {
                "issue_id": issue_id,
                "timestamp": event["dateCreated"],
                "service": self._project,
                "exception_type": exception.get("type", "Exception"),
                "message": exception.get("value", event["title"]),
            },
            "stacktrace": exception.get("stacktrace", {}).get("frames", []),
            "breadcrumbs": self._breadcrumbs_from(event)[-100:],
            "context": {
                "release": release,
                "environment": event.get("environment") or tags.get("environment"),
                "user_id": user.get("id"),
                "session_id": tags.get("session_id"),
            },
            "trace_correlation": {
                "trace_id": trace_id,
                "source": "sentry_trace_context",
            },
        }

    def _headers(self) -> dict[str, str]:
        """Return Bearer authentication headers for one read-only API request."""

        return {"authorization": f"Bearer {self._auth_token}"}

    @staticmethod
    def _group_id_from(issue_id: str) -> str:
        """Return the numeric Sentry group ID from a `client:<group-id>` value."""

        prefix, separator, group_id = issue_id.partition(":")
        if prefix != "client" or not separator or not group_id.isdigit():
            raise ValueError("client issue ID must use the client:<group-id> format")
        return group_id

    @staticmethod
    def _exception_from(event: dict[str, object]) -> dict[str, object]:
        """Return the final exception value from one Sentry event."""

        for entry in event.get("entries", []):
            if entry.get("type") == "exception":
                values = entry.get("data", {}).get("values", [])
                return values[-1] if values else {}
        return {}

    @staticmethod
    def _breadcrumbs_from(event: dict[str, object]) -> list[dict[str, object]]:
        """Return breadcrumb values attached to one Sentry event."""

        for entry in event.get("entries", []):
            if entry.get("type") == "breadcrumbs":
                return entry.get("data", {}).get("values", [])
        return []

    @staticmethod
    def _tags_from(event: dict[str, object]) -> dict[str, object]:
        """Return Sentry event tags keyed by tag name."""

        return {tag["key"]: tag["value"] for tag in event.get("tags", [])}

    @staticmethod
    def _trace_id_from(event: dict[str, object]) -> str | None:
        """Return the Sentry trace ID attached to one event.

        Args:
            event: Latest Sentry event payload returned by the issue event API.
                Missing or non-dictionary `contexts.trace` values mean the
                event has no usable trace ID.

        Returns:
            The string trace ID from `contexts.trace.trace_id`, or `None` when
            the field is absent or not a string.

        Example:
            An event containing `{"contexts": {"trace": {"trace_id": "abc"}}}`
            returns `abc`.
        """

        contexts = event.get("contexts", {})
        if not isinstance(contexts, dict):
            return None
        trace = contexts.get("trace", {})
        if not isinstance(trace, dict):
            return None
        trace_id = trace.get("trace_id")
        return trace_id if isinstance(trace_id, str) else None

    def _summary_from_issue(self, issue: dict[str, object]) -> dict[str, object]:
        """Normalize one Sentry issue group into a lightweight client summary."""

        metadata = issue.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "issue_id": f"client:{issue['id']}",
            "timestamp": issue["lastSeen"],
            "service": self._project,
            "exception_type": metadata.get("type", "Exception"),
            "message": metadata.get("value", issue["title"]),
        }
