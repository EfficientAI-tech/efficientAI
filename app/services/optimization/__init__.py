"""
GEPA prompt optimization service package.

Public API::

    from app.services.optimization import run_optimization
"""

from app.services.optimization.gepa_service import run_optimization

__all__ = ["run_optimization"]
