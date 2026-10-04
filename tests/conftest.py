"""Pytest configuration and Hypothesis profiles."""

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "default",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "ci",
    parent=settings.get_profile("default"),
    max_examples=300,
    derandomize=True,
    print_blob=True,
)
settings.register_profile(
    "thorough",
    parent=settings.get_profile("default"),
    max_examples=2_000,
    print_blob=True,
)
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))
