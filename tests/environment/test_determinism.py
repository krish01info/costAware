"""
test_determinism.py — Phase 1 Tests
Prove that:
  1. Same seed → same initial state
  2. Different seed → different initial state
  3. Same state + same tool calls → same results + same final state
  4. Reset restores exact initial state (including counters)
"""
import pytest
from src.environment.entities import (
    Vendor, Component, SupplierQuote, Project, Budget,
    POStatus, ApprovalStatus, QuoteStatus,
)
from src.environment.state import SimulatorState
from src.environment.simulator import ProcurementSimulator, generate_initial_state


# ─── Initial-State Generator Determinism ───────────────────────────────────────

class TestInitialStateGenerator:
    def test_same_seed_same_state(self):
        """generate_initial_state(42) == generate_initial_state(42)"""
        state_a = generate_initial_state(42)
        state_b = generate_initial_state(42)
        assert state_a == state_b

    def test_same_seed_same_state_multiple_calls(self):
        """Call 3 times — all identical."""
        states = [generate_initial_state(42) for _ in range(3)]
        assert states[0] == states[1] == states[2]

    def test_different_seed_different_state(self):
        """generate_initial_state(42) != generate_initial_state(43)"""
        state_a = generate_initial_state(42)
        state_b = generate_initial_state(43)
        assert state_a != state_b

    def test_generated_state_has_vendors(self):
        state = generate_initial_state(42)
        assert len(state.vendors) >= 3

    def test_generated_state_has_components(self):
        state = generate_initial_state(42)
        assert len(state.components) >= 2

    def test_generated_state_has_quotes(self):
        state = generate_initial_state(42)
        assert len(state.quotes) >= 4

    def test_generated_state_has_projects_and_budgets(self):
        state = generate_initial_state(42)
        assert len(state.projects) >= 1
        assert len(state.budgets) >= 1

    def test_generated_state_has_at_least_one_eligible_vendor(self):
        state = generate_initial_state(42)
        eligible = [v for v in state.vendors.values() if v.eligible and not v.suspended]
        assert len(eligible) >= 1

    def test_generated_state_has_suspended_vendor(self):
        """V5 is always suspended."""
        state = generate_initial_state(42)
        assert "V5" in state.vendors
        assert state.vendors["V5"].suspended is True

    def test_different_seeds_vary(self):
        """Multiple different seeds produce distinct states."""
        states = {seed: generate_initial_state(seed) for seed in range(10)}
        # At least some should differ (practically all will)
        unique_count = len(set(s.model_dump_json() for s in states.values()))
        assert unique_count > 5  # Conservatively, at least 6 out of 10 differ


# ─── Trajectory Determinism ────────────────────────────────────────────────────

class TestTrajectoryDeterminism:
    @staticmethod
    def _build_state() -> SimulatorState:
        """Fixed known state for trajectory tests."""
        return SimulatorState(
            vendors={
                "V1": Vendor(id="V1", name="GoodVendor", eligible=True, approved=True, suspended=False),
                "V2": Vendor(id="V2", name="BadVendor", eligible=False, approved=False, suspended=True),
            },
            components={
                "C-A": Component(id="C-A", name="Board", category="electronics",
                                 reference_price=500.0, required_qty=10, available_qty=50),
            },
            quotes={
                "Q1": SupplierQuote(id="Q1", vendor_id="V1", component_id="C-A",
                                    unit_price=480.0, quantity=10, expiry_days=20,
                                    shipping_cost=200.0),
            },
            projects={
                "PROJ-A": Project(id="PROJ-A", name="Alpha", owner="alice", budget_id="BUD-A"),
            },
            budgets={
                "BUD-A": Budget(id="BUD-A", allocated=20000.0),
            },
        )

    @staticmethod
    def _run_tool_sequence(sim: ProcurementSimulator):
        """Fixed sequence of tool calls. Returns all results + final state snapshot."""
        results = []
        results.append(sim.search_vendors())
        results.append(sim.get_vendor_details("V1"))
        results.append(sim.check_vendor_status("V1"))
        results.append(sim.get_quotes("C-A"))
        results.append(sim.check_budget("BUD-A"))
        results.append(sim.compare_quotes(["Q1"]))
        r_po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        results.append(r_po)
        r_apr = sim.request_approval(r_po["po_id"], "alice")
        results.append(r_apr)
        r_approve = sim.approve_order(r_apr["approval_id"])
        results.append(r_approve)
        r_release = sim.release_order(r_po["po_id"])
        results.append(r_release)
        final_state = sim.state.model_copy(deep=True)
        return results, final_state

    def test_same_state_same_trajectory_same_results(self):
        """
        State A → tool 1 → tool 2 → ... → Final A
        State B (== State A) → tool 1 → tool 2 → ... → Final B
        All results match, Final A == Final B.
        """
        # Run 1
        sim1 = ProcurementSimulator()
        sim1.load(self._build_state())
        results_1, final_1 = self._run_tool_sequence(sim1)

        # Run 2 — fresh simulator, same initial state
        sim2 = ProcurementSimulator()
        sim2.load(self._build_state())
        results_2, final_2 = self._run_tool_sequence(sim2)

        # Every tool result must match
        assert len(results_1) == len(results_2)
        for i, (r1, r2) in enumerate(zip(results_1, results_2)):
            assert r1 == r2, f"Step {i} results differ: {r1} vs {r2}"

        # Final states must match
        assert final_1 == final_2

    def test_same_trajectory_three_runs(self):
        """Repeat 3 times — all identical."""
        all_results = []
        all_finals = []
        for _ in range(3):
            sim = ProcurementSimulator()
            sim.load(self._build_state())
            results, final = self._run_tool_sequence(sim)
            all_results.append(results)
            all_finals.append(final)

        for i in range(1, 3):
            assert all_results[0] == all_results[i], f"Run {i} results differ from run 0"
            assert all_finals[0] == all_finals[i], f"Run {i} final state differs from run 0"


# ─── Reset Determinism ────────────────────────────────────────────────────────

class TestResetDeterminism:
    def test_reset_restores_initial_state(self):
        """state → tool calls → reset() → state matches initial."""
        state = TestTrajectoryDeterminism._build_state()
        sim = ProcurementSimulator()
        sim.load(state)

        initial_snapshot = sim.state.model_copy(deep=True)

        # Mutate state
        sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        assert sim.state != initial_snapshot  # Confirm state changed

        sim.reset()
        assert sim.state == initial_snapshot

    def test_reset_then_same_trajectory(self):
        """
        load → create PO → PO-001 → reset()
        → create PO → PO-001 (same ID)
        → same trajectory as first time
        """
        state = TestTrajectoryDeterminism._build_state()
        sim = ProcurementSimulator()
        sim.load(state)

        results_1, final_1 = TestTrajectoryDeterminism._run_tool_sequence(sim)

        sim.reset()

        results_2, final_2 = TestTrajectoryDeterminism._run_tool_sequence(sim)

        assert results_1 == results_2
        assert final_1 == final_2

    def test_reset_counters_explicitly(self):
        """PO counter and approval counter must reset to 0."""
        state = TestTrajectoryDeterminism._build_state()
        sim = ProcurementSimulator()
        sim.load(state)

        po1 = sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")
        po2 = sim.create_purchase_order("V1", "C-A", 3, 200.0, "PROJ-A")
        apr1 = sim.request_approval(po1["po_id"], "alice")
        assert po1["po_id"] == "PO-001"
        assert po2["po_id"] == "PO-002"
        assert apr1["approval_id"] == "APR-001"

        sim.reset()

        po3 = sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")
        apr2 = sim.request_approval(po3["po_id"], "alice")
        assert po3["po_id"] == "PO-001"  # Starts from 001 again
        assert apr2["approval_id"] == "APR-001"  # Starts from 001 again

    def test_multiple_resets(self):
        """Multiple reset cycles all produce the same initial state."""
        state = TestTrajectoryDeterminism._build_state()
        sim = ProcurementSimulator()
        sim.load(state)
        initial = sim.state.model_copy(deep=True)

        for _ in range(5):
            sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
            sim.reset()
            assert sim.state == initial


# ─── Generated State + Simulator Integration ──────────────────────────────────

class TestGeneratedStateIntegration:
    def test_generated_state_loads_into_simulator(self):
        """generate_initial_state → load → tools work."""
        state = generate_initial_state(42)
        sim = ProcurementSimulator()
        sim.load(state)
        result = sim.search_vendors()
        assert "vendors" in result
        assert len(result["vendors"]) > 0

    def test_generated_state_deterministic_trajectory(self):
        """Same seed → same generated state → same tool results."""
        results_all = []
        for _ in range(2):
            state = generate_initial_state(99)
            sim = ProcurementSimulator()
            sim.load(state)
            r = sim.search_vendors()
            results_all.append(r)
        assert results_all[0] == results_all[1]
