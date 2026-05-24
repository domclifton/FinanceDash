"""Small shared utility helpers for InvestHome."""


def safe_float(value, default=0.0):
    """Return value as float, falling back safely for blank/invalid inputs."""
    try:
        return float(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return float(default)
