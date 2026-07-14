"""Prometheus metrics for DriftWatch.

Label values are closed sets — never put free-form strings (resource IDs,
exception messages, attribute names) on labels. Unexpected values map to
``unknown`` so cardinality stays O(1).
"""

from __future__ import annotations

from typing import Any, Literal

from prometheus_client import Counter, Gauge, Histogram

_STATUS = frozenset({"success", "error"})
_SEVERITY = frozenset({"low", "medium", "high"})

# Closed sets used by callers (documented here so cardinality stays intentional):
#   kind     ∈ {drifted, missing_in_live, missing_in_tf}
#   dry_run  ∈ {true, false}
#   status   ∈ {success, error}  (else → unknown)
#   severity ∈ {low, medium, high} (else → unknown)

# Scan durations are seconds-to-minutes, not HTTP-scale ms. Defaults would
# clump everything into the +Inf bucket and make p95/p99 useless.
_SCAN_DURATION_BUCKETS = (1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0)

SCANS_TOTAL = Counter(
    "driftwatch_scans_total",
    "Total drift scans completed",
    ["status", "dry_run"],
)

SCAN_DURATION = Histogram(
    "driftwatch_scan_duration_seconds",
    "End-to-end drift scan duration in seconds",
    ["dry_run"],
    buckets=_SCAN_DURATION_BUCKETS,
)

DRIFT_EVENTS_TOTAL = Counter(
    "driftwatch_drift_events_total",
    "Drift findings counted by kind and severity",
    ["kind", "severity"],
)

RESOURCES_SCANNED = Gauge(
    "driftwatch_resources_scanned",
    "Number of Terraform-managed resources in the most recent scan",
)


def _bound(value: str, allowed: frozenset[str]) -> str:
    return value if value in allowed else "unknown"


def record_scan(
    *,
    status: Literal["success", "error"] | str,
    dry_run: bool,
    duration_seconds: float,
    report: dict[str, Any] | None = None,
    drift_events: list[Any] | None = None,
) -> None:
    """Record scan counters/histogram and optional drift breakdown."""
    status_label = _bound(status, _STATUS)
    dry_run_label = "true" if dry_run else "false"

    SCANS_TOTAL.labels(status=status_label, dry_run=dry_run_label).inc()
    SCAN_DURATION.labels(dry_run=dry_run_label).observe(duration_seconds)

    if report is None:
        return

    summary = report.get("summary", {})
    RESOURCES_SCANNED.set(float(summary.get("tf_resources", 0)))

    # Attribute-level drifts: use severity from DriftEvent when available.
    if drift_events:
        for event in drift_events:
            severity = _bound(getattr(event, "severity", "medium"), _SEVERITY)
            DRIFT_EVENTS_TOTAL.labels(kind="drifted", severity=severity).inc()
    else:
        # Fallback when only the raw report is available (CLI / tests).
        drifted_count = int(summary.get("drifted", 0))
        if drifted_count:
            DRIFT_EVENTS_TOTAL.labels(kind="drifted", severity="medium").inc(
                drifted_count
            )

    # Presence/absence findings do not carry severity in the report —
    # use fixed, documented defaults (still within the closed severity set).
    missing_live = int(summary.get("missing_in_live", 0))
    if missing_live:
        DRIFT_EVENTS_TOTAL.labels(kind="missing_in_live", severity="high").inc(
            missing_live
        )

    missing_tf = int(summary.get("missing_in_tf", 0))
    if missing_tf:
        DRIFT_EVENTS_TOTAL.labels(kind="missing_in_tf", severity="medium").inc(
            missing_tf
        )
