"""
test_state_transitions.py — Phase 1 Tests
Verify PO lifecycle, approval invalidation, budget flows,
and that invalid transitions do not corrupt state.
"""
import pytest
from src.environment.entities import (
    Vendor, Component, SupplierQuote, Project, Budget,
    POStatus, ApprovalStatus, QuoteStatus,
)
from src.environment.state import SimulatorState
from src.environment.simulator import ProcurementSimulator


@pytest.fixture
def sim() -> ProcurementSimulator:
    state = SimulatorState(
        vendors={
            "V1": Vendor(id="V1", name="Good", eligible=True, approved=True, suspended=False),
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
    s = ProcurementSimulator()
    s.load(state)
    return s


# ─── PO Lifecycle ─────────────────────────────────────────────────────────────

class TestPOLifecycle:
    def test_full_lifecycle_draft_to_released(self, sim):
        """DRAFT → PENDING_APPROVAL → APPROVED → RELEASED"""
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        po_id = po["po_id"]
        assert sim.state.orders[po_id].status == POStatus.DRAFT

        apr = sim.request_approval(po_id, "alice")
        assert sim.state.orders[po_id].status == POStatus.PENDING

        sim.approve_order(apr["approval_id"])
        assert sim.state.orders[po_id].status == POStatus.APPROVED

        sim.release_order(po_id)
        assert sim.state.orders[po_id].status == POStatus.RELEASED
        assert sim.state.orders[po_id].released is True

    def test_draft_to_cancelled(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        sim.cancel_order(po["po_id"])
        assert sim.state.orders[po["po_id"]].status == POStatus.CANCELLED

    def test_cannot_release_draft(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        result = sim.release_order(po["po_id"])
        assert "error" in result
        # Status unchanged
        assert sim.state.orders[po["po_id"]].status == POStatus.DRAFT

    def test_cannot_release_pending(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        sim.request_approval(po["po_id"], "alice")
        result = sim.release_order(po["po_id"])
        assert "error" in result
        assert sim.state.orders[po["po_id"]].status == POStatus.PENDING

    def test_cannot_release_cancelled(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        sim.cancel_order(po["po_id"])
        result = sim.release_order(po["po_id"])
        assert "error" in result
        assert sim.state.orders[po["po_id"]].status == POStatus.CANCELLED

    def test_cannot_cancel_released(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        apr = sim.request_approval(po["po_id"], "alice")
        sim.approve_order(apr["approval_id"])
        sim.release_order(po["po_id"])
        result = sim.cancel_order(po["po_id"])
        assert "error" in result
        assert sim.state.orders[po["po_id"]].status == POStatus.RELEASED

    def test_cannot_modify_cancelled(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        sim.cancel_order(po["po_id"])
        result = sim.modify_order(po["po_id"], quantity=20)
        assert "error" in result
        assert sim.state.orders[po["po_id"]].quantity == 10  # unchanged

    def test_cannot_modify_approved(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        apr = sim.request_approval(po["po_id"], "alice")
        sim.approve_order(apr["approval_id"])
        result = sim.modify_order(po["po_id"], quantity=20)
        assert "error" in result

    def test_cannot_modify_released(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        apr = sim.request_approval(po["po_id"], "alice")
        sim.approve_order(apr["approval_id"])
        sim.release_order(po["po_id"])
        result = sim.modify_order(po["po_id"], quantity=20)
        assert "error" in result


# ─── Approval Invalidation ────────────────────────────────────────────────────

class TestApprovalInvalidation:
    def test_modify_invalidates_approval(self, sim):
        """Modifying a PO after approval request must invalidate the approval."""
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        apr = sim.request_approval(po["po_id"], "alice")
        apr_id = apr["approval_id"]

        # Modify while pending
        sim.modify_order(po["po_id"], quantity=20)

        # Approval should be invalidated
        assert sim.state.approvals[apr_id].valid is False
        assert sim.state.approvals[apr_id].status == ApprovalStatus.INVALIDATED
        # PO should be back to DRAFT with no approval
        assert sim.state.orders[po["po_id"]].status == POStatus.DRAFT
        assert sim.state.orders[po["po_id"]].approval_id is None

    def test_cannot_approve_invalidated(self, sim):
        """An invalidated approval cannot be approved."""
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        apr = sim.request_approval(po["po_id"], "alice")
        sim.modify_order(po["po_id"], quantity=20)
        result = sim.approve_order(apr["approval_id"])
        assert "error" in result
        assert "no longer valid" in result["error"]

    def test_reapproval_after_modification(self, sim):
        """After modification, a new approval can be requested and approved."""
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        apr1 = sim.request_approval(po["po_id"], "alice")
        sim.modify_order(po["po_id"], quantity=20)

        # New approval
        apr2 = sim.request_approval(po["po_id"], "alice")
        assert apr2["approval_id"] != apr1["approval_id"]
        sim.approve_order(apr2["approval_id"])
        assert sim.state.orders[po["po_id"]].status == POStatus.APPROVED


# ─── Budget Flows ──────────────────────────────────────────────────────────────

class TestBudgetFlows:
    def test_create_reserves_budget(self, sim):
        assert sim.state.budgets["BUD-A"].reserved == 0.0
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        assert sim.state.budgets["BUD-A"].reserved == 5000.0
        assert sim.state.budgets["BUD-A"].remaining == 15000.0

    def test_release_moves_reserved_to_spent(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        apr = sim.request_approval(po["po_id"], "alice")
        sim.approve_order(apr["approval_id"])
        sim.release_order(po["po_id"])

        assert sim.state.budgets["BUD-A"].reserved == 0.0
        assert sim.state.budgets["BUD-A"].spent == 5000.0
        assert sim.state.budgets["BUD-A"].remaining == 15000.0

    def test_cancel_frees_reserved(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        assert sim.state.budgets["BUD-A"].reserved == 5000.0
        sim.cancel_order(po["po_id"])
        assert sim.state.budgets["BUD-A"].reserved == 0.0
        assert sim.state.budgets["BUD-A"].remaining == 20000.0

    def test_multiple_pos_accumulate_reserved(self, sim):
        sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")   # 500
        sim.create_purchase_order("V1", "C-A", 3, 200.0, "PROJ-A")   # 600
        assert sim.state.budgets["BUD-A"].reserved == 1100.0

    def test_insufficient_budget_does_not_reserve(self, sim):
        # Use most of the budget
        sim.create_purchase_order("V1", "C-A", 10, 1800.0, "PROJ-A")  # 18000
        reserved_after = sim.state.budgets["BUD-A"].reserved
        assert reserved_after == 18000.0

        # This should fail (remaining = 2000, need 5000)
        result = sim.create_purchase_order("V1", "C-A", 10, 500.0, "PROJ-A")
        assert "error" in result
        # Reserved should not have changed
        assert sim.state.budgets["BUD-A"].reserved == reserved_after


# ─── Error Handling — State Integrity ──────────────────────────────────────────

class TestErrorStateIntegrity:
    def test_invalid_operations_dont_corrupt_orders(self, sim):
        orders_before = dict(sim.state.orders)
        sim.release_order("PO-FAKE")
        sim.cancel_order("PO-FAKE")
        sim.modify_order("PO-FAKE", quantity=5)
        sim.approve_order("APR-FAKE")
        sim.request_approval("PO-FAKE", "alice")
        assert sim.state.orders == orders_before

    def test_invalid_operations_dont_corrupt_budget(self, sim):
        budget_before = sim.state.budgets["BUD-A"].model_copy()
        sim.create_purchase_order("V99", "C-A", 10, 480.0, "PROJ-A")
        sim.create_purchase_order("V1", "C-NONE", 10, 480.0, "PROJ-A")
        sim.create_purchase_order("V1", "C-A", -1, 480.0, "PROJ-A")
        assert sim.state.budgets["BUD-A"].allocated == budget_before.allocated
        assert sim.state.budgets["BUD-A"].spent == budget_before.spent
        assert sim.state.budgets["BUD-A"].reserved == budget_before.reserved
