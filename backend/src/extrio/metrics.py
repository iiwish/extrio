"""Prometheus text-format metrics computed at scrape time from store counts.

The endpoint renders the Prometheus text exposition format (version 0.0.4) by
hand so the backend keeps zero extra dependencies. Every series is derived
from the store's count queries at scrape time; nothing is cached or aggregated
in the process, so values always match the durable state.
"""

from extrio.store import Store

METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _escape_label(value: str) -> str:
    """Escape a label value per the Prometheus text exposition format."""

    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _series(name: str, labels: dict[str, str], value: int) -> str:
    label_text = ""
    if labels:
        rendered = ",".join(f'{key}="{_escape_label(label_value)}"' for key, label_value in sorted(labels.items()))
        label_text = f"{{{rendered}}}"
    return f"{name}{label_text} {value}"


def render_metrics(store: Store) -> str:
    """Render the full ``/metrics`` payload for the given store."""

    collectors = store.count_collectors_by_status()
    runs_total = store.count_runs_by_status()
    runs_24h = store.count_runs_by_status(within_days=1)
    items = store.count_items_by_decision()
    deliveries = store.count_deliveries_by_status()
    sinks = store.count_sinks_by_enabled()

    lines: list[str] = [
        "# HELP extrio_up Whether the Extrio control plane answered this scrape.",
        "# TYPE extrio_up gauge",
        _series("extrio_up", {}, 1),
        "# HELP extrio_collectors_total Collectors by lifecycle status.",
        "# TYPE extrio_collectors_total gauge",
    ]
    for status in sorted(collectors):
        lines.append(_series("extrio_collectors_total", {"status": status}, collectors[status]))
    lines.extend(
        [
            "# HELP extrio_runs_total Runs by run status.",
            "# TYPE extrio_runs_total counter",
        ]
    )
    for status in sorted(runs_total):
        lines.append(_series("extrio_runs_total", {"status": status}, runs_total[status]))
    lines.extend(
        [
            "# HELP extrio_runs_24h_total Runs started in the last 24 hours by run status.",
            "# TYPE extrio_runs_24h_total gauge",
        ]
    )
    for status in sorted(runs_24h):
        lines.append(_series("extrio_runs_24h_total", {"status": status}, runs_24h[status]))
    lines.extend(
        [
            "# HELP extrio_items_total Items by review decision.",
            "# TYPE extrio_items_total counter",
        ]
    )
    for decision in sorted(items):
        lines.append(_series("extrio_items_total", {"decision": decision}, items[decision]))
    lines.extend(
        [
            "# HELP extrio_deliveries_total Webhook deliveries by delivery status.",
            "# TYPE extrio_deliveries_total counter",
        ]
    )
    for status in sorted(deliveries):
        lines.append(_series("extrio_deliveries_total", {"status": status}, deliveries[status]))
    lines.extend(
        [
            "# HELP extrio_sinks_total Output sinks by enabled state.",
            "# TYPE extrio_sinks_total gauge",
            _series("extrio_sinks_total", {"enabled": "true"}, sinks["enabled"]),
            _series("extrio_sinks_total", {"enabled": "false"}, sinks["disabled"]),
        ]
    )
    lines.extend(
        [
            "# HELP extrio_db_dialect_info Active database dialect.",
            "# TYPE extrio_db_dialect_info gauge",
            _series("extrio_db_dialect_info", {"dialect": store.dialect.name}, 1),
        ]
    )
    return "\n".join(lines) + "\n"
