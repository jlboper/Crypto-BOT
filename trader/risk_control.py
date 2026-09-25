"""Explicit PAPER-only risk fractions, always at or below the configured cap."""

PROFILES = {"minimo": 0.25, "prudente": 0.50, "normal": 1.0}


def profile_multiplier(database) -> float:
    # Invalid persisted settings block new entries until reviewed.
    return PROFILES.get(database.setting("paper_risk_profile", "normal"), 0.0)


def profile_name(database) -> str:
    value = database.setting("paper_risk_profile", "normal")
    return value if value in PROFILES else "invalid"
