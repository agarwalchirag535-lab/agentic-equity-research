"""Tests for the DAG runner, gates, and budget guard."""

import pytest

from firm.core.orchestrator.budget import BudgetExceeded, BudgetGuard
from firm.core.orchestrator.dag import Task, run_dag


def test_run_dag_executes_in_dependency_order():
    tasks = [
        Task("t1", (), lambda _: 1),
        Task("t2", ("t1",), lambda inp: inp["t1"] + 1),
        Task("t3", ("t2",), lambda inp: inp["t2"] * 10),
    ]
    results = run_dag(tasks, as_of="2026-07-23")
    assert results == {"t1": 1, "t2": 2, "t3": 20}


def test_run_dag_resumes_from_cache_without_rerunning():
    cache: dict = {}
    run_dag([Task("t1", (), lambda _: 42)], as_of="2026-07-23", cache=cache)

    def boom(_):
        raise AssertionError("should have been skipped via cache")

    results = run_dag([Task("t1", (), boom)], as_of="2026-07-23", cache=cache)
    assert results["t1"] == 42


def test_run_dag_detects_cycle_and_unknown_dep():
    with pytest.raises(ValueError):
        run_dag([Task("a", ("b",), lambda _: 0), Task("b", ("a",), lambda _: 0)], as_of="x")
    with pytest.raises(ValueError):
        run_dag([Task("a", ("missing",), lambda _: 0)], as_of="x")


def test_budget_guard():
    g = BudgetGuard(ceiling_usd=1.0)
    g.charge("stage1", 0.4)
    g.charge("stage2", 0.4)
    assert g.remaining_usd == pytest.approx(0.2)
    with pytest.raises(BudgetExceeded):
        g.charge("stage3", 0.4)


def test_budget_guard_rejects_negative():
    with pytest.raises(ValueError):
        BudgetGuard(1.0).charge("x", -0.1)
