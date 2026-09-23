"""
simulator.py — Phase 1
The core procurement simulator.
- Holds the TRUE hidden state
- Exposes tool methods that return clean results
- Has a reset() method to restore to a known initial state per task
- Uses deterministic ID counters (not uuid) for reproducibility
"""
import copy
import random as _random_module
from typing import Optional, Dict, Any, List
from .state import SimulatorState
from .entities import (
    Vendor, Component, SupplierQuote, Project,
    Budget, PurchaseOrder, Approval, Invoice, Shipment,
    POStatus, ApprovalStatus, QuoteStatus
)


# ─── Tool Registry ─────────────────────────────────────────────────────────────

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # READ — Low Risk
    "search_vendors":       {"risk": "low",    "type": "read",  "description": "Find candidate suppliers"},
    "get_vendor_details":   {"risk": "low",    "type": "read",  "description": "Vendor profile/eligibility"},
    "check_vendor_status":  {"risk": "low",    "type": "read",  "description": "Current approval/suspension"},
    "get_quotes":           {"risk": "low",    "type": "read",  "description": "Supplier quotes for a component"},
    "check_quote_validity": {"risk": "low",    "type": "read",  "description": "Expiry/constraint check"},
    "check_budget":         {"risk": "low",    "type": "read",  "description": "Budget/reserved amount"},
    "check_existing_orders":{"risk": "low",    "type": "read",  "description": "Existing commitments for a project"},
    "compare_quotes":       {"risk": "low",    "type": "compute", "description": "Compare and rank quotes"},
    "check_invoice":        {"risk": "low",    "type": "read",  "description": "Inspect invoice/PO consistency"},
    # WRITE — Medium Risk
    "request_discount":     {"risk": "medium", "type": "write", "description": "Request negotiated terms"},
    "request_approval":     {"risk": "medium", "type": "write", "description": "Submit PO for approval"},
    # WRITE — High Risk
    "create_purchase_order":{"risk": "high",   "type": "write", "description": "Create PO/reserve budget"},
    "modify_order":         {"risk": "high",   "type": "write", "description": "Change PO quantity/price"},
    "approve_order":        {"risk": "high",   "type": "write", "description": "Change approval state"},
    "release_order":        {"risk": "high",   "type": "write", "description": "Release approved PO"},
    "cancel_order":         {"risk": "high",   "type": "write", "description": "Cancel PO"},
}


class ProcurementSimulator:
    """
    The ground-truth simulator. Tool methods here return CLEAN results.
    The Fault Injector wraps these calls to corrupt results before the agent sees them.

    Uses deterministic counters for ID generation (not uuid).
    Counters reset to 0 on reset(), ensuring full reproducibility:
        load → create PO → PO-001 → reset() → create PO → PO-001
    """

    def __init__(self):
        self._true_state: Optional[SimulatorState] = None
        self._initial_state: Optional[SimulatorState] = None   # snapshot for reset
        self._po_counter: int = 0
        self._approval_counter: int = 0

    # ─── Setup ────────────────────────────────────────────────────────────────

    def load(self, state: SimulatorState):
        """Load a SimulatorState (from a task definition)."""
        self._initial_state = state.model_copy(deep=True)
        self._true_state    = state.model_copy(deep=True)

    def reset(self):
        """Reset to initial state — called between trials. Resets ID counters to 0."""
        assert self._initial_state is not None, "Call load() first."
        self._true_state = self._initial_state.model_copy(deep=True)
        self._po_counter = 0
        self._approval_counter = 0

    @property
    def state(self) -> SimulatorState:
        """Access the hidden true state (oracle only)."""
        return self._true_state

    def advance_step(self):
        """Tick the simulator clock — used for quote expiry tracking."""
        self._true_state.step += 1

    def get_tools(self) -> Dict[str, Dict[str, Any]]:
        """Return the tool registry with callable references."""
        registry = {}
        for name, meta in TOOL_REGISTRY.items():
            entry = dict(meta)
            entry["callable"] = getattr(self, name)
            registry[name] = entry
        return registry

    def get_tool_names(self) -> List[str]:
        """Return list of all available tool names."""
        return list(TOOL_REGISTRY.keys())

    # ─── Tools — READ (Low Risk) ───────────────────────────────────────────────

    def search_vendors(self) -> Dict[str, Any]:
        return {
            "vendors": [
                {"id": v.id, "name": v.name, "preferred": v.preferred}
                for v in self._true_state.vendors.values()
            ]
        }

    def get_vendor_details(self, vendor_id: str) -> Dict[str, Any]:
        v = self._true_state.vendors.get(vendor_id)
        if not v:
            return {"error": f"Vendor {vendor_id} not found"}
        return {
            "id": v.id, "name": v.name, "eligible": v.eligible,
            "approved": v.approved, "preferred": v.preferred,
            "payment_profile": v.payment_profile
        }

    def check_vendor_status(self, vendor_id: str) -> Dict[str, Any]:
        v = self._true_state.vendors.get(vendor_id)
        if not v:
            return {"error": f"Vendor {vendor_id} not found"}
        return {"id": v.id, "approved": v.approved, "suspended": v.suspended, "eligible": v.eligible}

    def get_quotes(self, component_id: str) -> Dict[str, Any]:
        step = self._true_state.step
        quotes = [
            {
                "id": q.id, "vendor_id": q.vendor_id,
                "unit_price": q.unit_price, "quantity": q.quantity,
                "shipping_cost": q.shipping_cost, "total_price": q.total_price,
                "status": q.status.value,
                "expired": step >= q.expiry_days
            }
            for q in self._true_state.quotes.values()
            if q.component_id == component_id
        ]
        return {"quotes": quotes}

    def check_quote_validity(self, quote_id: str) -> Dict[str, Any]:
        q = self._true_state.quotes.get(quote_id)
        if not q:
            return {"error": f"Quote {quote_id} not found"}
        expired = self._true_state.step >= q.expiry_days
        return {"id": q.id, "status": q.status.value, "expired": expired, "expiry_days": q.expiry_days}

    def check_budget(self, budget_id: str) -> Dict[str, Any]:
        b = self._true_state.budgets.get(budget_id)
        if not b:
            return {"error": f"Budget {budget_id} not found"}
        return {
            "id": b.id, "allocated": b.allocated, "spent": b.spent,
            "reserved": b.reserved, "remaining": b.remaining
        }

    def check_existing_orders(self, project_id: str) -> Dict[str, Any]:
        orders = [
            {"id": o.id, "vendor_id": o.vendor_id, "status": o.status.value, "total": o.total}
            for o in self._true_state.orders.values()
            if o.project_id == project_id
        ]
        return {"orders": orders}

    def compare_quotes(self, quote_ids: list) -> Dict[str, Any]:
        results = []
        for qid in quote_ids:
            q = self._true_state.quotes.get(qid)
            if q:
                results.append({
                    "id": q.id, "vendor_id": q.vendor_id,
                    "unit_price": q.unit_price, "total_price": q.total_price,
                    "shipping_cost": q.shipping_cost
                })
        results.sort(key=lambda x: x["total_price"])
        return {"ranked_quotes": results}

    def check_invoice(self, invoice_id: str) -> Dict[str, Any]:
        inv = self._true_state.invoices.get(invoice_id)
        if not inv:
            return {"error": f"Invoice {invoice_id} not found"}
        return {
            "id": inv.id, "po_id": inv.po_id, "amount": inv.amount,
            "line_items": inv.line_items, "mismatch": inv.mismatch, "status": inv.status
        }

    # ─── Tools — WRITE (Medium Risk) ──────────────────────────────────────────

    def request_discount(self, vendor_id: str, quote_id: str, requested_price: float) -> Dict[str, Any]:
        q = self._true_state.quotes.get(quote_id)
        if not q:
            return {"error": f"Quote {quote_id} not found"}
        # Simple rule: grant 5% discount if requested price is >= 95% of current
        if requested_price >= q.unit_price * 0.90:
            q.unit_price = requested_price
            return {"success": True, "new_unit_price": requested_price, "quote_id": quote_id}
        return {"success": False, "reason": "Requested discount too large", "min_price": q.unit_price * 0.90}

    def request_approval(self, po_id: str, requester: str) -> Dict[str, Any]:
        po = self._true_state.orders.get(po_id)
        if not po:
            return {"error": f"PO {po_id} not found"}
        self._approval_counter += 1
        approval_id = f"APR-{self._approval_counter:03d}"
        approval = Approval(
            id=approval_id, po_id=po_id,
            requester=requester, approver="manager",
            level="manager", status=ApprovalStatus.PENDING
        )
        self._true_state.approvals[approval_id] = approval
        po.status    = POStatus.PENDING
        po.approval_id = approval_id
        return {"approval_id": approval_id, "status": "PENDING", "po_id": po_id}

    # ─── Tools — WRITE (High Risk) ────────────────────────────────────────────

    def create_purchase_order(
        self, vendor_id: str, component_id: str,
        quantity: int, unit_price: float,
        project_id: str, shipping_cost: float = 0.0
    ) -> Dict[str, Any]:
        # Validate vendor
        vendor = self._true_state.vendors.get(vendor_id)
        if not vendor:
            return {"error": f"Vendor {vendor_id} not found"}
        if not vendor.eligible or vendor.suspended:
            return {"error": "Vendor is not eligible or is suspended"}
        # Validate component
        component = self._true_state.components.get(component_id)
        if not component:
            return {"error": f"Component {component_id} not found"}
        # Validate quantity
        if quantity <= 0:
            return {"error": "Quantity must be greater than 0"}
        # Validate project + budget
        project = self._true_state.projects.get(project_id)
        if not project:
            return {"error": f"Project {project_id} not found"}
        budget = self._true_state.budgets.get(project.budget_id)
        total_cost = unit_price * quantity + shipping_cost
        if budget and budget.remaining < total_cost:
            return {"error": "Insufficient budget", "remaining": budget.remaining, "required": total_cost}
        # Create PO with deterministic ID and reserve budget
        self._po_counter += 1
        po_id = f"PO-{self._po_counter:03d}"
        po = PurchaseOrder(
            id=po_id, vendor_id=vendor_id, component_id=component_id,
            quantity=quantity, unit_price=unit_price, shipping_cost=shipping_cost,
            project_id=project_id, status=POStatus.DRAFT
        )
        self._true_state.orders[po_id] = po
        if budget:
            budget.reserved += total_cost
        return {"po_id": po_id, "status": "DRAFT", "total": total_cost}

    def modify_order(self, po_id: str, quantity: int = None, unit_price: float = None) -> Dict[str, Any]:
        po = self._true_state.orders.get(po_id)
        if not po:
            return {"error": f"PO {po_id} not found"}
        if po.status not in [POStatus.DRAFT, POStatus.PENDING]:
            return {"error": f"Cannot modify PO in status {po.status.value}"}
        # Invalidate existing approval if present
        if po.approval_id:
            apr = self._true_state.approvals.get(po.approval_id)
            if apr:
                apr.valid  = False
                apr.status = ApprovalStatus.INVALIDATED
        if quantity is not None:
            po.quantity   = quantity
        if unit_price is not None:
            po.unit_price = unit_price
        po.status = POStatus.DRAFT
        po.approval_id = None
        return {"po_id": po_id, "status": "DRAFT", "modified": True, "approval_invalidated": True}

    def approve_order(self, approval_id: str) -> Dict[str, Any]:
        apr = self._true_state.approvals.get(approval_id)
        if not apr:
            return {"error": f"Approval {approval_id} not found"}
        if not apr.valid:
            return {"error": "Approval is no longer valid (PO was modified)"}
        apr.status = ApprovalStatus.APPROVED
        po = self._true_state.orders.get(apr.po_id)
        if po:
            po.status = POStatus.APPROVED
        return {"approval_id": approval_id, "status": "APPROVED", "po_id": apr.po_id}

    def release_order(self, po_id: str) -> Dict[str, Any]:
        po = self._true_state.orders.get(po_id)
        if not po:
            return {"error": f"PO {po_id} not found"}
        if po.status != POStatus.APPROVED:
            return {"error": f"PO must be APPROVED before release, current: {po.status.value}"}
        po.status   = POStatus.RELEASED
        po.released = True
        # Move budget from reserved → spent
        project = self._true_state.projects.get(po.project_id)
        if project:
            budget = self._true_state.budgets.get(project.budget_id)
            if budget:
                budget.reserved -= po.total
                budget.spent    += po.total
        return {"po_id": po_id, "status": "RELEASED"}

    def cancel_order(self, po_id: str) -> Dict[str, Any]:
        po = self._true_state.orders.get(po_id)
        if not po:
            return {"error": f"PO {po_id} not found"}
        if po.status == POStatus.RELEASED:
            return {"error": "Cannot cancel a released PO"}
        po.status = POStatus.CANCELLED
        # Free reserved budget
        project = self._true_state.projects.get(po.project_id)
        if project:
            budget = self._true_state.budgets.get(project.budget_id)
            if budget:
                budget.reserved = max(0, budget.reserved - po.total)
        return {"po_id": po_id, "status": "CANCELLED"}


# ─── Deterministic Initial-State Generator ─────────────────────────────────────

def generate_initial_state(seed: int = 42) -> SimulatorState:
    """
    Generate a realistic procurement world deterministically from a seed.
    Uses random.Random(seed), never global random.

    Same seed always produces the same state:
        generate_initial_state(42) == generate_initial_state(42)

    Different seeds produce different states:
        generate_initial_state(42) != generate_initial_state(43)
    """
    rng = _random_module.Random(seed)

    # ── Vendor pool ──────────────────────────────────────────────────────────
    vendor_names = [
        ("V1", "TechParts Ltd"),
        ("V2", "GlobalSupply Co"),
        ("V3", "PrecisionMfg Inc"),
        ("V4", "ValueComponents"),
        ("V5", "SuspendedVendor Corp"),
    ]
    vendors = {}
    for vid, vname in vendor_names:
        eligible  = rng.random() > 0.15
        suspended = (vid == "V5") or (rng.random() < 0.1)  # V5 always suspended
        vendors[vid] = Vendor(
            id=vid, name=vname,
            eligible=eligible and not suspended,
            approved=eligible and not suspended,
            suspended=suspended,
            preferred=(vid == "V1"),
            payment_profile=rng.choice(["standard", "net30", "prepaid"]),
        )

    # ── Components ───────────────────────────────────────────────────────────
    component_defs = [
        ("C-A", "Circuit Board Alpha",   "electronics"),
        ("C-B", "Power Supply Unit",     "electronics"),
        ("C-C", "Steel Bracket",         "mechanical"),
        ("C-D", "Cooling Fan Assembly",  "thermal"),
    ]
    components = {}
    for cid, cname, cat in component_defs:
        ref_price = round(rng.uniform(100, 2000), 2)
        components[cid] = Component(
            id=cid, name=cname, category=cat,
            reference_price=ref_price,
            required_qty=rng.randint(5, 50),
            available_qty=rng.randint(20, 200),
        )

    # ── Quotes (2-3 per component from different vendors) ────────────────────
    quotes = {}
    quote_counter = 0
    eligible_vendors = [v for v in vendors.values() if v.eligible and not v.suspended]
    for cid, comp in components.items():
        max_quotes = min(3, len(eligible_vendors))
        n_quotes = rng.randint(1, max(1, max_quotes))
        chosen   = rng.sample(eligible_vendors, n_quotes)
        for vendor in chosen:
            quote_counter += 1
            qid = f"Q{quote_counter:02d}"
            markup = rng.uniform(0.85, 1.20)
            quotes[qid] = SupplierQuote(
                id=qid, vendor_id=vendor.id, component_id=cid,
                unit_price=round(comp.reference_price * markup, 2),
                quantity=comp.required_qty,
                expiry_days=rng.randint(10, 30),
                shipping_cost=round(rng.uniform(50, 500), 2),
                status=QuoteStatus.ACTIVE,
            )

    # ── Projects + Budgets ───────────────────────────────────────────────────
    project_defs = [
        ("PROJ-A", "Project Alpha",  "alice"),
        ("PROJ-B", "Project Beta",   "bob"),
    ]
    projects = {}
    budgets  = {}
    for pid, pname, owner in project_defs:
        bid = f"BUD-{pid.split('-')[1]}"
        allocated = round(rng.uniform(15000, 80000), 2)
        budgets[bid] = Budget(id=bid, allocated=allocated)
        projects[pid] = Project(
            id=pid, name=pname, owner=owner, budget_id=bid,
            procurement_rules={"require_approval_above": rng.choice([5000, 10000, 15000])},
            priority=rng.choice(["normal", "high", "urgent"]),
        )

    return SimulatorState(
        vendors=vendors,
        components=components,
        quotes=quotes,
        projects=projects,
        budgets=budgets,
    )
