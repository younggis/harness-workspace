"""Minimal in-process Prometheus text exposition (no external dependency).

Process-local counters/gauges are sufficient for a single replica; scrape each
replica and aggregate in Prometheus. Label values are escaped per the text format.
"""
from __future__ import annotations

import re
from collections import defaultdict
from threading import Lock

_SAFE = re.compile(r"[^a-zA-Z0-9_]")


def _name(value: str) -> str:
    return _SAFE.sub("_", value)


def _label_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self, prefix: str = "harness_"):
        self.prefix = prefix
        self._counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple], float] = {}
        self._lock = Lock()

    def inc(self, name: str, labels: dict | None = None, value: float = 1) -> None:
        key = (_name(name), _label_key(labels))
        with self._lock:
            self._counters[key] += value

    def set(self, name: str, value: float, labels: dict | None = None) -> None:
        key = (_name(name), _label_key(labels))
        with self._lock:
            self._gauges[key] = value

    def render(self) -> str:
        lines = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"# TYPE {self.prefix}{name} counter")
                lines.append(f"{self.prefix}{name}{_label_text(labels)} {value}")
            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {self.prefix}{name} gauge")
                lines.append(f"{self.prefix}{name}{_label_text(labels)} {value}")
        return "\n".join(lines) + "\n"


def _label_key(labels: dict | None) -> tuple:
    if not labels:
        return ()
    return tuple(sorted((_name(str(k)), _label_value(v)) for k, v in labels.items()))


def _label_text(key: tuple) -> str:
    if not key:
        return ""
    return "{" + ",".join(f'{k}="{v}"' for k, v in key) + "}"
