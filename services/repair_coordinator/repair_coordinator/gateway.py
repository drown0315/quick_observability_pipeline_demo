import json
import os
from urllib.parse import urlencode
from urllib.request import urlopen


class GatewayClient:
    """Read recent normalized issues from the Observability Gateway.

    The client contains the Gateway base URL used for issue discovery. It does
    not query Sentry or Victoria services directly.

    Example:
        `GatewayClient("http://localhost:8001").list_issues()` returns recent
        backend and Flutter client issue summaries.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    @classmethod
    def from_environment(cls) -> "GatewayClient":
        """Create a Gateway client from local Coordinator configuration."""

        return cls(os.environ.get("DIAGNOSTICS_GATEWAY_URL", "http://localhost:8001"))

    def list_issues(self, *, run_id: str | None = None) -> list[dict[str, object]]:
        """Return recent Gateway issue summaries eligible for repair.

        Returns:
            Backend and Flutter client issue summaries observed during the last
            15 minutes, capped at 20 records.

        Example:
            A Flutter exception returns an issue summary whose `issue_id` is
            `client:123`.
        """

        parameters = {"since": "15m", "limit": 20}
        if run_id is not None:
            parameters["run_id"] = run_id
        with urlopen(
            f"{self._base_url}/diagnostics/issues?{urlencode(parameters)}", timeout=5
        ) as response:
            return json.load(response)
