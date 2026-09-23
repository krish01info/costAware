"""
test_scenarios.py — Phase 1 Tests
10 representative deterministic scenarios exercising the simulator
through direct Python tool calls.

NO LLM, NO oracle, NO fault injection, NO policies.

Each scenario verifies a specific procurement workflow
and asserts on final state.
"""
import pytest
from src.environment.entities import (
    Vendor, Component, SupplierQuote, Project, Budget,
    Invoice, Shipment,
    POStatus, ApprovalStatus, QuoteStatus, ShipmentStatus,
)
from src.environment.state import SimulatorState
from src.environment.simulator import ProcurementSimulator


# ─── Shared State Builder ─────────────────────────────────────────────────────

def build_rich_state() -> SimulatorState:
    """
    A rich procurement world with multiple vendors, components, quotes,
    projects, and budgets for scenario testing.
    """
    return SimulatorState(
        vendors={
            "V1": Vendor(id="V1", name="TechParts Ltd", eligible=True, approved=True,
                         suspended=False, preferred=True, payment_profile="net30"),
            "V2": Vendor(id="V2", name="GlobalSupply Co", eligible=True, approved=True,
                         suspended=False, preferred=False),
            "V3": Vendor(id="V3", name="SuspendedVendor", eligible=False, approved=False,
                         suspended=True),
            "V4": Vendor(id="V4", name="IneligibleVendor", eligible=False, approved=False,
                         suspended=False),
        },
        components={
            "C-A": Component(id="C-A", name="Circuit Board", category="electronics",
                             reference_price=500.0, required_qty=10, available_qty=50),
            "C-B": Component(id="C-B", name="Power Supply", category="electronics",
                             reference_price=300.0, required_qty=5, available_qty=30),
            "C-C": Component(id="C-C", name="Steel Bracket", category="mechanical",
                             reference_price=50.0, required_qty=100, available_qty=500),
        },
        quotes={
            "Q1": SupplierQuote(id="Q1", vendor_id="V1", component_id="C-A",
                                unit_price=480.0, quantity=10, expiry_days=20,
                                shipping_cost=200.0),
            "Q2": SupplierQuote(id="Q2", vendor_id="V2", component_id="C-A",
                                unit_price=520.0, quantity=10, expiry_days=15,
                                shipping_cost=150.0),
            "Q3": SupplierQuote(id="Q3", vendor_id="V1", component_id="C-B",
                                unit_price=280.0, quantity=5, expiry_days=10,
                                shipping_cost=100.0),
            "Q4": SupplierQuote(id="Q4", vendor_id="V2", component_id="C-C",
                                unit_price=45.0, quantity=100, expiry_days=25,
                                shipping_cost=300.0),
            "Q5": SupplierQuote(id="Q5", vendor_id="V1", component_id="C-C",
                                unit_price=48.0, quantity=100, expiry_days=3,
                                shipping_cost=250.0),
        },
        projects={
            "PROJ-A": Project(id="PROJ-A", name="Alpha", owner="alice", budget_id="BUD-A",
                              procurement_rules={"require_approval_above": 5000}),
            "PROJ-B": Project(id="PROJ-B", name="Beta", owner="bob", budget_id="BUD-B"),
        },
        budgets={
            "BUD-A": Budget(id="BUD-A", allocated=50000.0),
            "BUD-B": Budget(id="BUD-B", allocated=5000.0),
        },
        invoices={
            "INV-1": Invoice(id="INV-1", po_id="PO-EXT", amount=4800.0,
                             line_items=[{"item": "Board", "qty": 10, "unit_price": 480.0}]),
        },
    )


@pytest.fixture
def sim() -> ProcurementSimulator:
    s = ProcurementSimulator()
    s.load(build_rich_state())
    return s


# ═══════════════════════════════════════════════════════════════════════════════
#  10 REPRESENTATIVE SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario01_SearchVendors:
    """Scenario 1: Search vendors and verify the listing."""

    def test_search_returns_all_vendors(self, sim):
        result = sim.search_vendors()
        vendor_ids = {v["id"] for v in result["vendors"]}
        assert vendor_ids == {"V1", "V2", "V3", "V4"}
        # V1 is preferred
        v1 = next(v for v in result["vendors"] if v["id"] == "V1")
        assert v1["preferred"] is True


class TestScenario02_GetVendorDetails:
    """Scenario 2: Retrieve detailed vendor information."""

    def test_get_good_vendor_details(self, sim):
        result = sim.get_vendor_details("V1")
        assert result["eligible"] is True
        assert result["approved"] is True
        assert result["payment_profile"] == "net30"

    def test_get_suspended_vendor_details(self, sim):
        result = sim.get_vendor_details("V3")
        assert result["eligible"] is False


class TestScenario03_CheckVendorStatus:
    """Scenario 3: Check vendor approval/suspension status."""

    def test_good_vendor_status(self, sim):
        result = sim.check_vendor_status("V1")
        assert result["approved"] is True
        assert result["suspended"] is False
        assert result["eligible"] is True

    def test_suspended_vendor_status(self, sim):
        result = sim.check_vendor_status("V3")
        assert result["suspended"] is True


class TestScenario04_RetrieveQuotes:
    """Scenario 4: Get quotes for a component."""

    def test_get_quotes_for_component_a(self, sim):
        result = sim.get_quotes("C-A")
        assert len(result["quotes"]) == 2
        vendor_ids = {q["vendor_id"] for q in result["quotes"]}
        assert vendor_ids == {"V1", "V2"}

    def test_get_quotes_for_component_c(self, sim):
        result = sim.get_quotes("C-C")
        assert len(result["quotes"]) == 2


class TestScenario05_CheckQuoteValidity:
    """Scenario 5: Check if quotes are expired."""

    def test_fresh_quote_valid(self, sim):
        result = sim.check_quote_validity("Q1")
        assert result["expired"] is False

    def test_quote_expires_after_steps(self, sim):
        # Q5 expires at step 3
        for _ in range(4):
            sim.advance_step()
        result = sim.check_quote_validity("Q5")
        assert result["expired"] is True


class TestScenario06_CheckBudget:
    """Scenario 6: Verify budget information."""

    def test_full_budget(self, sim):
        result = sim.check_budget("BUD-A")
        assert result["allocated"] == 50000.0
        assert result["remaining"] == 50000.0
        assert result["spent"] == 0.0
        assert result["reserved"] == 0.0

    def test_small_budget(self, sim):
        result = sim.check_budget("BUD-B")
        assert result["allocated"] == 5000.0


class TestScenario07_CompareQuotes:
    """Scenario 7: Compare quotes for cost ranking."""

    def test_compare_quotes_ranking(self, sim):
        result = sim.compare_quotes(["Q1", "Q2"])
        ranked = result["ranked_quotes"]
        assert len(ranked) == 2
        # Q1 total = 480*10 + 200 = 5000
        # Q2 total = 520*10 + 150 = 5350
        assert ranked[0]["id"] == "Q1"  # cheaper
        assert ranked[1]["id"] == "Q2"

    def test_compare_three_quotes(self, sim):
        result = sim.compare_quotes(["Q4", "Q5"])
        ranked = result["ranked_quotes"]
        # Q4 = 45*100 + 300 = 4800
        # Q5 = 48*100 + 250 = 5050
        assert ranked[0]["id"] == "Q4"


class TestScenario08_CreateValidPurchaseOrder:
    """Scenario 8: Create a valid purchase order and verify state."""

    def test_create_po_and_verify_state(self, sim):
        # Check budget before
        budget_before = sim.check_budget("BUD-A")
        assert budget_before["reserved"] == 0.0

        # Create PO
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A",
            quantity=10, unit_price=480.0,
            project_id="PROJ-A", shipping_cost=200.0
        )
        assert result["po_id"] == "PO-001"
        assert result["status"] == "DRAFT"
        assert result["total"] == 5000.0

        # Verify state updated
        po = sim.state.orders["PO-001"]
        assert po.vendor_id == "V1"
        assert po.component_id == "C-A"
        assert po.quantity == 10
        assert po.status == POStatus.DRAFT

        # Budget reserved
        budget_after = sim.check_budget("BUD-A")
        assert budget_after["reserved"] == 5000.0
        assert budget_after["remaining"] == 45000.0

        # Existing orders visible
        orders = sim.check_existing_orders("PROJ-A")
        assert len(orders["orders"]) == 1
        assert orders["orders"][0]["id"] == "PO-001"


class TestScenario09_RequestAndApprovePurchaseOrder:
    """Scenario 9: Create PO → request approval → approve."""

    def test_approval_workflow(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        po_id = po["po_id"]
        assert sim.state.orders[po_id].status == POStatus.DRAFT

        # Request approval
        apr = sim.request_approval(po_id, "alice")
        apr_id = apr["approval_id"]
        assert apr["status"] == "PENDING"
        assert sim.state.orders[po_id].status == POStatus.PENDING

        # Approve
        result = sim.approve_order(apr_id)
        assert result["status"] == "APPROVED"
        assert sim.state.orders[po_id].status == POStatus.APPROVED
        assert sim.state.approvals[apr_id].status == ApprovalStatus.APPROVED
        assert sim.state.approvals[apr_id].valid is True


class TestScenario10_FullProcurementEndToEnd:
    """
    Scenario 10: Complete multi-step procurement workflow.

    search_vendors → check_vendor_status → get_quotes → check_budget
    → compare_quotes → create_purchase_order → request_approval
    → approve_order → release_order

    Verify final state: PO released, budget correctly transitioned.
    """

    def test_full_end_to_end(self, sim):
        # Step 1: Search vendors
        vendors = sim.search_vendors()
        assert len(vendors["vendors"]) == 4

        # Step 2: Check V1 status
        status = sim.check_vendor_status("V1")
        assert status["eligible"] is True
        assert status["suspended"] is False

        # Step 3: Get quotes for C-A
        quotes = sim.get_quotes("C-A")
        assert len(quotes["quotes"]) == 2

        # Step 4: Check budget
        budget = sim.check_budget("BUD-A")
        assert budget["remaining"] == 50000.0

        # Step 5: Compare quotes — pick cheapest
        compared = sim.compare_quotes(["Q1", "Q2"])
        best_quote = compared["ranked_quotes"][0]
        assert best_quote["id"] == "Q1"
        assert best_quote["vendor_id"] == "V1"

        # Step 6: Create PO using the best quote
        po = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A",
            quantity=10, unit_price=480.0,
            project_id="PROJ-A", shipping_cost=200.0
        )
        po_id = po["po_id"]
        assert po["status"] == "DRAFT"
        assert sim.state.budgets["BUD-A"].reserved == 5000.0

        # Step 7: Request approval
        apr = sim.request_approval(po_id, "alice")
        assert sim.state.orders[po_id].status == POStatus.PENDING

        # Step 8: Approve
        sim.approve_order(apr["approval_id"])
        assert sim.state.orders[po_id].status == POStatus.APPROVED

        # Step 9: Release
        release = sim.release_order(po_id)
        assert release["status"] == "RELEASED"

        # ── Final State Assertions ────────────────────────────────────────────
        final_po = sim.state.orders[po_id]
        assert final_po.status == POStatus.RELEASED
        assert final_po.released is True
        assert final_po.vendor_id == "V1"
        assert final_po.component_id == "C-A"
        assert final_po.quantity == 10

        final_budget = sim.state.budgets["BUD-A"]
        assert final_budget.reserved == 0.0
        assert final_budget.spent == 5000.0
        assert final_budget.remaining == 45000.0

        final_approval = sim.state.approvals[apr["approval_id"]]
        assert final_approval.status == ApprovalStatus.APPROVED
        assert final_approval.valid is True
