from app.services.testing.simulation_run_naming import (
    base_simulation_run_name,
    simulation_run_name_for_rerun,
)


def test_base_strips_stacked_rerun_suffixes():
    name = "Customer Support V1 (re-run) (re-run) (re-run)"
    assert base_simulation_run_name(name, "351168") == "Customer Support V1"


def test_rerun_uses_base_name_without_stacking():
    assert simulation_run_name_for_rerun(
        "Customer Support V1 (re-run) (re-run)",
        "569998",
    ) == "Customer Support V1"


def test_rerun_failed_trials_single_hint():
    assert simulation_run_name_for_rerun(
        "Customer Support V1",
        "123",
        only_failed=True,
    ) == "Customer Support V1 · failed trials"
