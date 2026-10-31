from __future__ import annotations

from typing import Any, Mapping, Optional


DEFAULT_CUSTOM_COLOR = 150


def _channel(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CUSTOM_COLOR
    if not 0 <= number <= 255:
        return DEFAULT_CUSTOM_COLOR
    return number


def custom_color_state(
    upgrade_ranks: Optional[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return normalized persisted color state without discarding unknown data."""
    if not isinstance(upgrade_ranks, Mapping):
        return None
    color = upgrade_ranks.get("localColor")
    if not isinstance(color, Mapping):
        return None
    return {
        "enabled": bool(color.get("enabled", True)),
        "r": _channel(color.get("r")),
        "g": _channel(color.get("g")),
        "b": _channel(color.get("b")),
    }


def custom_color_fields(upgrade_ranks: Optional[Mapping[str, Any]]) -> dict:
    color = custom_color_state(upgrade_ranks) or {
        "enabled": False,
        "r": DEFAULT_CUSTOM_COLOR,
        "g": DEFAULT_CUSTOM_COLOR,
        "b": DEFAULT_CUSTOM_COLOR,
    }
    return {
        "useCustomColor": color["enabled"],
        "customColorR": color["r"],
        "customColorG": color["g"],
        "customColorB": color["b"],
    }


def with_custom_color(
    upgrade_ranks: Optional[Mapping[str, Any]],
    red: int,
    green: int,
    blue: int,
    enabled: Optional[bool] = None,
) -> dict:
    ranks = dict(upgrade_ranks) if isinstance(upgrade_ranks, Mapping) else {}
    previous = ranks.get("localColor")
    color = dict(previous) if isinstance(previous, Mapping) else {}
    color.update({
        "r": _channel(red),
        "g": _channel(green),
        "b": _channel(blue),
    })
    if enabled is None:
        color["enabled"] = bool(color.get("enabled", True))
    else:
        color["enabled"] = bool(enabled)
    ranks["localColor"] = color
    return ranks


def with_custom_color_enabled(
    upgrade_ranks: Optional[Mapping[str, Any]],
    enabled: bool,
) -> dict:
    state = custom_color_state(upgrade_ranks)
    if state is None:
        state = {
            "r": DEFAULT_CUSTOM_COLOR,
            "g": DEFAULT_CUSTOM_COLOR,
            "b": DEFAULT_CUSTOM_COLOR,
        }
    return with_custom_color(
        upgrade_ranks, state["r"], state["g"], state["b"], enabled=enabled)
