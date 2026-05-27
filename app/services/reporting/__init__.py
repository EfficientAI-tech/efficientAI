"""Reporting service package.

Keep optional report backends importable by their concrete modules instead of
eagerly importing every PDF dependency when the package is touched.
"""

__all__: list[str] = []
