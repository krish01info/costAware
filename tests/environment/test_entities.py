"""
test_entities.py — Phase 1 Tests
Verify that all procurement entity models construct correctly,
computed properties work, and enum values are correct.
"""
import pytest
from src.environment.entities import (
    Vendor, Component, SupplierQuote, Project, Budget,
    PurchaseOrder, Approval, Invoice, Shipment,
    POStatus, ApprovalStatus, QuoteStatus, ShipmentStatus,
)


# ─── Enum Tests ────────────────────────────────────────────────────────────────

class TestEnums:
    def test_po_status_values(self):
        assert POStatus.NOT_CREATED == "NOT_CREATED"
        assert POStatus.DRAFT == "DRAFT"
        assert POStatus.PENDING == "PENDING_APPROVAL"
        assert POStatus.APPROVED == "APPROVED"
        assert POStatus.RELEASED == "RELEASED"
        assert POStatus.CANCELLED == "CANCELLED"

    def test_approval_status_values(self):
        assert ApprovalStatus.PENDING == "PENDING"
        assert ApprovalStatus.APPROVED == "APPROVED"
        assert ApprovalStatus.REJECTED == "REJECTED"
        assert ApprovalStatus.INVALIDATED == "INVALIDATED"

    def test_quote_status_values(self):
        assert QuoteStatus.ACTIVE == "ACTIVE"
        assert QuoteStatus.EXPIRED == "EXPIRED"
        assert QuoteStatus.USED == "USED"

    def test_shipment_status_values(self):
        assert ShipmentStatus.NOT_DISPATCHED == "NOT_DISPATCHED"
        assert ShipmentStatus.DISPATCHED == "DISPATCHED"
        assert ShipmentStatus.DELIVERED == "DELIVERED"


# ─── Entity Construction Tests ─────────────────────────────────────────────────

class TestVendor:
    def test_construct_with_defaults(self):
        v = Vendor(id="V1", name="Test")
        assert v.id == "V1"
        assert v.name == "Test"
        assert v.eligible is True
        assert v.approved is True
        assert v.suspended is False
        assert v.preferred is False
        assert v.payment_profile == "standard"

    def test_construct_suspended(self):
        v = Vendor(id="V2", name="Bad", eligible=False, suspended=True)
        assert v.eligible is False
        assert v.suspended is True


class TestComponent:
    def test_construct(self):
        c = Component(id="C-A", name="Board", category="electronics",
                      reference_price=500.0, required_qty=10, available_qty=50)
        assert c.id == "C-A"
        assert c.reference_price == 500.0
        assert c.required_qty == 10
        assert c.available_qty == 50


class TestSupplierQuote:
    def test_construct_and_total_price(self):
        q = SupplierQuote(id="Q1", vendor_id="V1", component_id="C-A",
                          unit_price=100.0, quantity=10, expiry_days=20,
                          shipping_cost=50.0)
        assert q.total_price == 100.0 * 10 + 50.0  # 1050.0
        assert q.status == QuoteStatus.ACTIVE

    def test_total_price_no_shipping(self):
        q = SupplierQuote(id="Q2", vendor_id="V1", component_id="C-A",
                          unit_price=200.0, quantity=5, expiry_days=10)
        assert q.total_price == 200.0 * 5  # 1000.0
        assert q.shipping_cost == 0.0


class TestProject:
    def test_construct_with_defaults(self):
        p = Project(id="PROJ-A", name="Alpha", owner="alice", budget_id="BUD-A")
        assert p.procurement_rules == {}
        assert p.priority == "normal"


class TestBudget:
    def test_remaining_calculation(self):
        b = Budget(id="BUD-A", allocated=20000.0, spent=5000.0, reserved=3000.0)
        assert b.remaining == 12000.0

    def test_remaining_fresh(self):
        b = Budget(id="BUD-B", allocated=50000.0)
        assert b.remaining == 50000.0

    def test_remaining_fully_spent(self):
        b = Budget(id="BUD-C", allocated=10000.0, spent=10000.0)
        assert b.remaining == 0.0


class TestPurchaseOrder:
    def test_construct_and_total(self):
        po = PurchaseOrder(id="PO-001", vendor_id="V1", component_id="C-A",
                           quantity=10, unit_price=480.0, shipping_cost=200.0,
                           project_id="PROJ-A")
        assert po.total == 480.0 * 10 + 200.0  # 5000.0
        assert po.status == POStatus.DRAFT
        assert po.approval_id is None
        assert po.released is False


class TestApproval:
    def test_construct_with_defaults(self):
        a = Approval(id="APR-001", po_id="PO-001", requester="alice",
                     approver="manager", level="manager")
        assert a.status == ApprovalStatus.PENDING
        assert a.valid is True


class TestInvoice:
    def test_construct_with_defaults(self):
        inv = Invoice(id="INV-001", po_id="PO-001", amount=5000.0)
        assert inv.mismatch is False
        assert inv.status == "unpaid"
        assert inv.line_items == []


class TestShipment:
    def test_construct_with_defaults(self):
        s = Shipment(id="SHP-001", po_id="PO-001", quantity=10, destination="Warehouse A")
        assert s.status == ShipmentStatus.NOT_DISPATCHED
