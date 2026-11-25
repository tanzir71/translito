"""Speech-end to displayed translation timing using one monotonic clock."""
import math
from statistics import median
from uuid import uuid4


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    at = (len(values) - 1) * fraction
    lower = int(at)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (at - lower)


class DelayTracker:
    def __init__(self, *, ledger=None, session_id=None):
        self.ledger, self.session_id = ledger, session_id or uuid4().hex
        self.lines = {}

    def record(self, entry, now):
        entry["target_shown_at"] = now
        ended = entry.get("speech_end_at")
        delay = max(0.0, now - ended) if ended is not None and math.isfinite(ended) else None
        entry["delay_s"] = delay
        if delay is not None:
            self.lines[entry["id"]] = delay
        summary = self.summary()
        if self.ledger:
            self.ledger.record_session(self.session_id, **summary)
        return summary

    def summary(self):
        values = list(self.lines.values())
        return {"delay_p50_s": percentile(values, .5), "delay_p95_s": percentile(values, .95),
                "delay_median_s": median(values[-30:]) if values else None, "measured_lines": len(values)}
