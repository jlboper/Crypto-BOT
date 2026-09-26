"""Explicit PAPER-only risk fractions, always at or below the configured cap."""

# Keep the old values stable for existing PAPER installations. The highest
# selectable level is the configured risk budget, never an increase above it.
PROFILES = {"minimo": 0.25, "leve": 0.35, "prudente": 0.50,
            "moderado": 0.65, "alto": 0.85, "normal": 1.0}


def profile_multiplier(database) -> float:
    # Invalid persisted settings block new entries until reviewed.
    return PROFILES.get(database.setting("paper_risk_profile", "normal"), 0.0)


def profile_name(database) -> str:
    value = database.setting("paper_risk_profile", "normal")
    return value if value in PROFILES else "invalid"
