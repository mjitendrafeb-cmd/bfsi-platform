"""Compatibility module exposing the deterministic delta engine."""
from pipeline.delta import diff_snapshots, grade_delta, baseline_note

__all__ = ["diff_snapshots", "grade_delta", "baseline_note"]
