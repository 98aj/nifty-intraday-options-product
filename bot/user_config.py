"""User-editable configuration: the subset of settings the dashboard lets the user
personalize (capital, lot, risk limits). Edits are applied to the live config and
persisted to config/user_overrides.yaml (merged over config.yaml on next start).

Only runtime-safe fields are exposed here — the risk manager and strategies read
these from cfg on every cycle, so changes take effect immediately. Structural
settings (session times, instrument keys) are intentionally NOT editable here.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from bot.config import deep_merge, project_root

# dotted key -> UI/validation spec
# Only two fields are user-facing. Everything else (risk %, daily limits, max
# trades, lot size, strike step, session times, instrument keys) is configured at
# the backend in config.yaml and intentionally NOT exposed in the dashboard.
EDITABLE: dict[str, dict] = {
    "capital.total": {"type": "float", "label": "Initial capital (₹)",
                      "min": 0, "group": "Trading"},
    "capital.lots": {"type": "int", "label": "Number of lots",
                     "min": 1, "group": "Trading"},
}


def _get(cfg, dotted: str):
    obj = cfg
    for p in dotted.split("."):
        obj = getattr(obj, p)
    return obj


def _set(cfg, dotted: str, val) -> None:
    parts = dotted.split(".")
    obj = cfg
    for p in parts[:-1]:
        obj = getattr(obj, p)
    setattr(obj, parts[-1], val)


def read_editable(cfg) -> dict:
    """Current values of the editable fields (flat dotted keys)."""
    return {k: _get(cfg, k) for k in EDITABLE}


def _coerce(spec: dict, val):
    v = int(float(val)) if spec["type"] == "int" else float(val)
    if "min" in spec:
        v = max(spec["min"], v)
    if "max" in spec:
        v = min(spec["max"], v)
    return v


def validate_and_apply(cfg, updates: dict) -> dict:
    """Coerce/clamp valid fields, set them live on cfg, return what was applied."""
    applied: dict = {}
    for k, val in (updates or {}).items():
        spec = EDITABLE.get(k)
        if spec is None or val in (None, ""):
            continue
        try:
            v = _coerce(spec, val)
        except (TypeError, ValueError):
            continue
        _set(cfg, k, v)
        applied[k] = v
    return applied


def overrides_path() -> Path:
    return project_root() / "config" / "user_overrides.yaml"


def load_overrides() -> dict:
    p = overrides_path()
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def _nest(flat: dict) -> dict:
    out: dict = {}
    for k, v in flat.items():
        parts = k.split(".")
        d = out
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = v
    return out


def save_overrides(applied: dict) -> Path:
    """Merge applied flat updates into config/user_overrides.yaml (persisted)."""
    cur = load_overrides()
    deep_merge(cur, _nest(applied))
    p = overrides_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(cur, sort_keys=False, default_flow_style=False),
                 encoding="utf-8")
    return p
