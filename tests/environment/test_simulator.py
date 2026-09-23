"""
test_simulator.py — Phase 1 Tests
Verify simulator initialization, reset, tool access, read tools,
write tools, and error handling. No LLM, no oracle, no fault injection.
"""
import pytest
from src.environment.entities import (
    Vendor, Component, SupplierQuote, Project, Budget,
    PurchaseOrder, Approval, Invoice, Shipment,
    POStatus, ApprovalStatus, QuoteStatus, ShipmentStatus,
)
from src.environment.state import SimulatorState
from src.environment.simulator import ProcurementSimulator, TOOL_REGISTRY


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def base_state() -> SimulatorState:
    """Minimal procurement world for most tests."""
    return SimulatorState(
        vendors={
            "V1": Vendor(id="V1", name="GoodVendor", eligible=True, approved=True, suspended=False),
            "V2": Vendor(id="V2", name="BadVendor", eligible=False, approved=False, suspended=True),
            "V3": Vendor(id="V3", name="IneligibleVendor", eligible=False, approved=False, suspended=False),
        },
        components={
            "C-A": Component(id="C-A", name="Board", category="electronics",
                             reference_price=500.0, required_qty=10, available_qty=50),
            "C-B": Component(id="C-B", name="PSU", category="electronics",
                             reference_price=300.0, required_qty=5, available_qty=20),
        },
        quotes={
            "Q1": SupplierQuote(id="Q1", vendor_id="V1", component_id="C-A",
                                unit_price=480.0, quantity=10, expiry_days=20,
                                shipping_cost=200.0, status=QuoteStatus.ACTIVE),
            "Q2": SupplierQuote(id="Q2", vendor_id="V1", component_id="C-B",
                                unit_price=280.0, quantity=5, expiry_days=5,
                                shipping_cost=100.0, status=QuoteStatus.ACTIVE),
        },
        projects={
            "PROJ-A": Project(id="PROJ-A", name="Alpha", owner="alice", budget_id="BUD-A",
                              procurement_rules={"require_approval_above": 10000}),
        },
        budgets={
            "BUD-A": Budget(id="BUD-A", allocated=20000.0),
        },
        invoices={
            "INV-1": Invoice(id="INV-1", po_id="PO-EXT", amount=5000.0,
                             line_items=[{"item": "Board", "qty": 10}], mismatch=False),
        },
    )


@pytest.fixture
def sim(base_state) -> ProcurementSimulator:
    """Ready-to-use simulator loaded with base_state."""
    s = ProcurementSimulator()
    s.load(base_state)
    return s


# ─── Initialization Tests ─────────────────────────────────────────────────────

class TestInitialization:
    def test_load_creates_state(self, sim):
        assert sim.state is not None
        assert len(sim.state.vendors) == 3
        assert len(sim.state.components) == 2

    def test_unloaded_simulator_has_no_state(self):
        s = ProcurementSimulator()
        assert s._true_state is None

    def test_reset_without_load_raises(self):
        s = ProcurementSimulator()
        with pytest.raises(AssertionError, match="Call load"):
            s.reset()

    def test_advance_step(self, sim):
        assert sim.state.step == 0
        sim.advance_step()
        assert sim.state.step == 1
        sim.advance_step()
        assert sim.state.step == 2


# ─── Tool Registry Tests ──────────────────────────────────────────────────────

class TestToolRegistry:
    def test_registry_has_all_16_tools(self):
        assert len(TOOL_REGISTRY) == 16

    def test_all_tools_have_risk_and_type(self):
        for name, meta in TOOL_REGISTRY.items():
            assert "risk" in meta, f"{name} missing risk"
            assert "type" in meta, f"{name} missing type"
            assert meta["risk"] in ("low", "medium", "high")
            assert meta["type"] in ("read", "write", "compute")

    def test_get_tools_returns_callables(self, sim):
        tools = sim.get_tools()
        assert len(tools) == 16
        for name, entry in tools.items():
            assert callable(entry["callable"]), f"{name} not callable"

    def test_get_tool_names(self, sim):
        names = sim.get_tool_names()
        assert len(names) == 16
        assert "search_vendors" in names
        assert "create_purchase_order" in names
        assert "cancel_order" in names

    def test_tool_registry_callables_match_methods(self, sim):
        tools = sim.get_tools()
        for name in TOOL_REGISTRY:
            assert hasattr(sim, name), f"Simulator missing method: {name}"
            assert tools[name]["callable"] == getattr(sim, name)


# ─── Read Tool Tests ──────────────────────────────────────────────────────────

class TestReadTools:
    def test_search_vendors(self, sim):
        result = sim.search_vendors()
        assert "vendors" in result
        assert len(result["vendors"]) == 3
        ids = {v["id"] for v in result["vendors"]}
        assert ids == {"V1", "V2", "V3"}

    def test_get_vendor_details(self, sim):
        result = sim.get_vendor_details("V1")
        assert result["id"] == "V1"
        assert result["eligible"] is True
        assert result["approved"] is True

    def test_get_vendor_details_unknown(self, sim):
        result = sim.get_vendor_details("V99")
        assert "error" in result

    def test_check_vendor_status(self, sim):
        result = sim.check_vendor_status("V1")
        assert result["approved"] is True
        assert result["suspended"] is False

    def test_check_vendor_status_suspended(self, sim):
        result = sim.check_vendor_status("V2")
        assert result["suspended"] is True

    def test_check_vendor_status_unknown(self, sim):
        result = sim.check_vendor_status("VXXX")
        assert "error" in result

    def test_get_quotes(self, sim):
        result = sim.get_quotes("C-A")
        assert "quotes" in result
        assert len(result["quotes"]) == 1
        assert result["quotes"][0]["vendor_id"] == "V1"
        assert result["quotes"][0]["unit_price"] == 480.0

    def test_get_quotes_empty(self, sim):
        result = sim.get_quotes("C-NONEXIST")
        assert result["quotes"] == []

    def test_check_quote_validity(self, sim):
        result = sim.check_quote_validity("Q1")
        assert result["expired"] is False  # step=0, expiry_days=20

    def test_check_quote_validity_expired(self, sim):
        # Advance past expiry
        for _ in range(6):
            sim.advance_step()
        result = sim.check_quote_validity("Q2")  # expiry_days=5
        assert result["expired"] is True

    def test_check_quote_validity_unknown(self, sim):
        result = sim.check_quote_validity("Q99")
        assert "error" in result

    def test_check_budget(self, sim):
        result = sim.check_budget("BUD-A")
        assert result["allocated"] == 20000.0
        assert result["remaining"] == 20000.0
        assert result["spent"] == 0.0
        assert result["reserved"] == 0.0

    def test_check_budget_unknown(self, sim):
        result = sim.check_budget("BUD-XXX")
        assert "error" in result

    def test_check_existing_orders_empty(self, sim):
        result = sim.check_existing_orders("PROJ-A")
        assert result["orders"] == []

    def test_compare_quotes(self, sim):
        result = sim.compare_quotes(["Q1", "Q2"])
        assert "ranked_quotes" in result
        assert len(result["ranked_quotes"]) == 2
        # Q2 total = 280*5 + 100 = 1500; Q1 total = 480*10 + 200 = 5000
        assert result["ranked_quotes"][0]["id"] == "Q2"

    def test_compare_quotes_unknown(self, sim):
        result = sim.compare_quotes(["Q99"])
        assert result["ranked_quotes"] == []

    def test_check_invoice(self, sim):
        result = sim.check_invoice("INV-1")
        assert result["po_id"] == "PO-EXT"
        assert result["amount"] == 5000.0
        assert result["mismatch"] is False

    def test_check_invoice_unknown(self, sim):
        result = sim.check_invoice("INV-999")
        assert "error" in result


# ─── Write Tool Tests ─────────────────────────────────────────────────────────

class TestWriteTools:
    def test_create_purchase_order_valid(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-A", shipping_cost=200.0
        )
        assert "po_id" in result
        assert result["po_id"] == "PO-001"
        assert result["status"] == "DRAFT"
        assert result["total"] == 5000.0
        # Budget should be reserved
        assert sim.state.budgets["BUD-A"].reserved == 5000.0

    def test_create_po_nonexistent_vendor(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V99", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert "error" in result
        assert "V99" in result["error"]

    def test_create_po_suspended_vendor(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V2", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert "error" in result
        assert "not eligible" in result["error"] or "suspended" in result["error"]

    def test_create_po_ineligible_vendor(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V3", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert "error" in result

    def test_create_po_nonexistent_component(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-NONE", quantity=10,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert "error" in result
        assert "C-NONE" in result["error"]

    def test_create_po_invalid_quantity_zero(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A", quantity=0,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert "error" in result
        assert "Quantity" in result["error"]

    def test_create_po_invalid_quantity_negative(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A", quantity=-5,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert "error" in result

    def test_create_po_nonexistent_project(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-NONE"
        )
        assert "error" in result

    def test_create_po_insufficient_budget(self, sim):
        result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A", quantity=100,
            unit_price=500.0, project_id="PROJ-A"  # 100*500 = 50000 > 20000
        )
        assert "error" in result
        assert "budget" in result["error"].lower() or "Insufficient" in result["error"]

    def test_create_po_does_not_corrupt_state_on_error(self, sim):
        """Invalid PO creation must not change budget or orders."""
        budget_before = sim.state.budgets["BUD-A"].remaining
        orders_before = len(sim.state.orders)
        sim.create_purchase_order(
            vendor_id="V99", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-A"
        )
        assert sim.state.budgets["BUD-A"].remaining == budget_before
        assert len(sim.state.orders) == orders_before

    def test_request_discount_valid(self, sim):
        result = sim.request_discount("V1", "Q1", 460.0)
        assert result["success"] is True
        assert result["new_unit_price"] == 460.0
        # Verify state mutation
        assert sim.state.quotes["Q1"].unit_price == 460.0

    def test_request_discount_too_large(self, sim):
        result = sim.request_discount("V1", "Q1", 100.0)
        assert result["success"] is False

    def test_request_discount_unknown_quote(self, sim):
        result = sim.request_discount("V1", "Q99", 400.0)
        assert "error" in result

    def test_request_approval(self, sim):
        # First create a PO
        po_result = sim.create_purchase_order(
            vendor_id="V1", component_id="C-A", quantity=10,
            unit_price=480.0, project_id="PROJ-A"
        )
        po_id = po_result["po_id"]
        result = sim.request_approval(po_id, "alice")
        assert result["approval_id"] == "APR-001"
        assert result["status"] == "PENDING"
        # PO should be PENDING_APPROVAL
        assert sim.state.orders[po_id].status == POStatus.PENDING

    def test_request_approval_unknown_po(self, sim):
        result = sim.request_approval("PO-NONE", "alice")
        assert "error" in result

    def test_approve_order(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        apr = sim.request_approval(po["po_id"], "alice")
        result = sim.approve_order(apr["approval_id"])
        assert result["status"] == "APPROVED"
        assert sim.state.orders[po["po_id"]].status == POStatus.APPROVED

    def test_approve_order_unknown(self, sim):
        result = sim.approve_order("APR-NONE")
        assert "error" in result

    def test_modify_order(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        result = sim.modify_order(po["po_id"], quantity=20)
        assert result["modified"] is True
        assert sim.state.orders[po["po_id"]].quantity == 20
        assert sim.state.orders[po["po_id"]].status == POStatus.DRAFT

    def test_modify_order_unknown(self, sim):
        result = sim.modify_order("PO-NONE", quantity=5)
        assert "error" in result

    def test_release_order(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        apr = sim.request_approval(po["po_id"], "alice")
        sim.approve_order(apr["approval_id"])
        result = sim.release_order(po["po_id"])
        assert result["status"] == "RELEASED"
        assert sim.state.orders[po["po_id"]].released is True
        # Budget: reserved → spent
        assert sim.state.budgets["BUD-A"].spent == 5000.0
        assert sim.state.budgets["BUD-A"].reserved == 0.0

    def test_release_unapproved(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        result = sim.release_order(po["po_id"])
        assert "error" in result

    def test_release_unknown(self, sim):
        result = sim.release_order("PO-NONE")
        assert "error" in result

    def test_cancel_order(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        result = sim.cancel_order(po["po_id"])
        assert result["status"] == "CANCELLED"
        # Budget reservation freed
        assert sim.state.budgets["BUD-A"].reserved == 0.0

    def test_cancel_released_order(self, sim):
        po = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A", 200.0)
        apr = sim.request_approval(po["po_id"], "alice")
        sim.approve_order(apr["approval_id"])
        sim.release_order(po["po_id"])
        result = sim.cancel_order(po["po_id"])
        assert "error" in result

    def test_cancel_unknown(self, sim):
        result = sim.cancel_order("PO-NONE")
        assert "error" in result


# ─── Deterministic ID Tests ───────────────────────────────────────────────────

class TestDeterministicIDs:
    def test_po_ids_are_sequential(self, sim):
        r1 = sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")
        r2 = sim.create_purchase_order("V1", "C-B", 3, 200.0, "PROJ-A")
        assert r1["po_id"] == "PO-001"
        assert r2["po_id"] == "PO-002"

    def test_approval_ids_are_sequential(self, sim):
        po1 = sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")
        po2 = sim.create_purchase_order("V1", "C-B", 3, 200.0, "PROJ-A")
        apr1 = sim.request_approval(po1["po_id"], "alice")
        apr2 = sim.request_approval(po2["po_id"], "alice")
        assert apr1["approval_id"] == "APR-001"
        assert apr2["approval_id"] == "APR-002"

    def test_reset_resets_counters(self, sim):
        """After reset, IDs start from 001 again."""
        r1 = sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")
        assert r1["po_id"] == "PO-001"
        apr1 = sim.request_approval(r1["po_id"], "alice")
        assert apr1["approval_id"] == "APR-001"

        sim.reset()

        r2 = sim.create_purchase_order("V1", "C-A", 5, 100.0, "PROJ-A")
        assert r2["po_id"] == "PO-001"
        apr2 = sim.request_approval(r2["po_id"], "alice")
        assert apr2["approval_id"] == "APR-001"

    def test_failed_create_does_not_increment_counter(self, sim):
        """Error paths must not consume an ID."""
        result = sim.create_purchase_order("V99", "C-A", 10, 480.0, "PROJ-A")
        assert "error" in result
        # Next valid create should still be PO-001
        r = sim.create_purchase_order("V1", "C-A", 10, 480.0, "PROJ-A")
        assert r["po_id"] == "PO-001"
