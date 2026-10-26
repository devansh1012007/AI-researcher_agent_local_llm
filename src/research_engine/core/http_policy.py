"""Egress policy: decide whether the process may talk to a given host.

Built on the existing fail-closed `is_loopback_host`. Under strict (LOCAL_ONLY)
mode the policy refuses every non-loopback host at construction time and at
every outbound request, so no provider can silently call out to the network.
"""

from __future__ import annotations

from research_engine.core.config import is_loopback_host


class EgressPolicy:
    """Allow/deny outbound network calls by host.

    `allows(host) -> bool` is the single decision point. It is consulted
    (a) at provider construction (no network provider is constructed in
    LOCAL_ONLY) and (b) at every outbound request through a guarded client.
    """

    def __init__(self, environment: str) -> None:
        self.environment = environment
        self.strict = environment == "LOCAL_ONLY"

    def allows(self, host: str) -> bool:
        """Return True iff a call to ``host`` is permitted.

        In LOCAL_ONLY only loopback hosts are allowed; in HYBRID and ONLINE
        every host is allowed (network policy is a configuration decision,
        not a per-host one).
        """
        if self.strict:
            return is_loopback_host(host)
        return True

    def require(self, host: str, what: str = "network call") -> None:
        """Raise if ``host`` is not allowed, naming the caller."""
        if not self.allows(host):
            raise RuntimeError(
                f"{what} to {host!r} is not allowed in {self.environment} "
                f"mode (LOCAL_ONLY permits loopback only)"
            )


def build_egress_policy(cfg) -> EgressPolicy:
    """Build an EgressPolicy from an AppConfig (or anything with .platform)."""
    env = getattr(cfg.platform, "effective_environment", lambda: "LOCAL_ONLY")()
    return EgressPolicy(env)
