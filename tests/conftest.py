"""Hypothesis profiles: "ci" (default, fast) and "deep" (HYPOTHESIS_PROFILE=deep, for nightly runs)."""
import os

from hypothesis import HealthCheck, settings

settings.register_profile("ci", max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("deep", max_examples=2000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
