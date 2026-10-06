"""A small retail support desk, built so an agent's work can be graded on what it left behind.

The world is six collections of invented documents: customers, orders, shipments, tickets,
refunds and a handful of policy pages. An agent works it through nine tools. Every attempt
gets a private copy of the seed, keyed by its ``run_id``, so nothing one attempt does can be
seen by another, and the documents it leaves are the evidence a grader reads afterwards.

Three properties of the tools matter, because the failures worth measuring depend on them:

* **Lookups come back empty** for an id that does not exist, and the tool says nothing more.
* **Writes fail with an error the agent can read** when a precondition does not hold: a
  refund against an order that is not eligible or is already refunded, a ticket status that
  is not one of ``open``, ``hold`` and ``solved``, a note on a ticket that does not exist.
* **The surface allows the wrong ending.** Nothing stops an agent refunding a delivered
  order that is outside the refund window, or closing a ticket that should be on hold.
  Those rules live in the policy pages, which an agent has to go and read.

Names, emails and phone numbers are invented: addresses use the reserved ``.example``
domain and phone numbers the 555-01xx range kept for fiction.

The grading is not here. What counts as the right ending for a task is the technique, so
the notebook that uses this module writes it out. This module only reports *what changed*:
:func:`diff` compares an attempt's documents with the seed.

Imports neither :mod:`cbnb.readiness` nor :mod:`cbnb.inventory`, and no model client.
"""

from __future__ import annotations

import copy
import json
import re
import time
from collections.abc import Callable
from typing import Any

__all__ = [
    "COLLECTIONS", "STATUSES", "TODAY", "TOOLS", "WRITES",
    "Desk", "describe", "diff", "ensure_desk", "seed",
]

#: The desk's clock. Fixed, so a policy that says "within 30 days" means the same on every run.
TODAY = "2026-10-04"

COLLECTIONS = ("customers", "orders", "shipments", "tickets", "refunds", "policy")

#: Collections an agent's writes can add documents to, and the key each document is filed under.
_ID_FIELD = {"customers": "customer_id", "orders": "order_id", "shipments": "order_id",
             "tickets": "ticket_id", "refunds": "refund_id", "policy": "policy_id"}

STATUSES = ("open", "hold", "solved")

#: Where the agent's own documents are kept, beside the desk's.
EXTRA_COLLECTIONS = ("traces", "grades")


# ------------------------------------------------------------------------------- the seed


def _customer(cid: str, name: str, tier: str, orders: list[str], n: int) -> dict[str, Any]:
    first, last = name.split()
    email = f"{first.lower().replace('á', 'a')}.{last.lower()}@mail.example"
    return {"customer_id": cid, "name": name, "email": email, "phone": f"555-01{n:02d}",
            "tier": tier, "order_ids": orders}


def _order(oid: str, cid: str, items: list[tuple[str, float]], status: str, placed: str,
           promised: str, delivered: str | None = None, refunded: float = 0.0) -> dict[str, Any]:
    lines = [{"name": name, "price": price, "qty": 1} for name, price in items]
    return {"order_id": oid, "customer_id": cid, "items": lines,
            "total": round(sum(price for _, price in items), 2), "status": status,
            "placed_on": placed, "promised_on": promised, "delivered_on": delivered,
            "refunded": refunded}


def _shipment(oid: str, carrier: str, status: str, last: str, estimate: str | None = None,
              reason: str | None = None) -> dict[str, Any]:
    return {"order_id": oid, "carrier": carrier, "status": status, "last_event_on": last,
            "estimated_delivery": estimate, "exception_reason": reason}


def _ticket(tid: str, cid: str, oid: str, subject: str, notes: list[str]) -> dict[str, Any]:
    return {"ticket_id": tid, "customer_id": cid, "order_id": oid, "subject": subject,
            "status": "open", "created_on": "2026-10-02",
            "notes": [{"on": "2026-10-02", "text": text} for text in notes]}


def _policy(pid: str, title: str, text: str, keywords: str) -> dict[str, Any]:
    return {"policy_id": pid, "title": title, "text": text, "keywords": keywords}


def _documents() -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    rows += [("customers", c) for c in [
        _customer("C-101", "Priya Raman", "standard", ["O-4981", "O-5001"], 11),
        _customer("C-102", "Tomás Ferreira", "standard", ["O-5002"], 12),
        _customer("C-103", "Hannah Okafor", "standard", ["O-5003"], 13),
        _customer("C-104", "Marcus Lindqvist", "standard", ["O-5004", "O-5005"], 14),
        _customer("C-105", "Yuki Tanaka", "standard", ["O-5006"], 15),
        _customer("C-106", "Omar Haddad", "standard", ["O-5007"], 16),
        _customer("C-107", "Elena Petrova", "gold", ["O-5008"], 17),
        _customer("C-108", "Ravi Menon", "standard", ["O-5009"], 18),
        _customer("C-109", "Dana Whitfield", "standard", ["O-5010", "O-5011"], 19),
        _customer("C-110", "Lena Fischer", "standard", ["O-5012"], 20),
    ]]
    rows += [("orders", o) for o in [
        _order("O-4981", "C-101", [("Camp Stove", 64.0)], "delivered",
               "2026-07-28", "2026-08-04", "2026-08-02"),
        _order("O-5001", "C-101", [("Trail Pro Backpack", 120.0)], "shipped",
               "2026-09-18", "2026-09-25"),
        _order("O-5002", "C-102", [("Merino Sweater", 60.0)], "delivered",
               "2026-08-14", "2026-08-21", "2026-08-20"),
        _order("O-5003", "C-103", [("Standing Desk Mat", 45.0)], "shipped",
               "2026-10-01", "2026-10-08"),
        _order("O-5004", "C-104", [("Glass Carafe 1L", 34.0), ("Walnut Coaster Set", 22.0)],
               "delivered", "2026-09-18", "2026-09-25", "2026-09-24"),
        _order("O-5005", "C-104", [("Espresso Cups, set of four", 48.0)], "delivered",
               "2026-09-26", "2026-10-02", "2026-10-01"),
        _order("O-5006", "C-105", [("Noise-Cancelling Headphones", 89.0)], "delivered",
               "2026-09-15", "2026-09-23", "2026-09-22", refunded=89.0),
        _order("O-5007", "C-106", [("Bluetooth Speaker", 79.0)], "shipped",
               "2026-10-01", "2026-10-09"),
        _order("O-5008", "C-107", [("Cast Iron Skillet", 150.0)], "delivered",
               "2026-09-12", "2026-09-20", "2026-09-28"),
        _order("O-5009", "C-108", [("Running Shoes", 110.0)], "shipped",
               "2026-09-06", "2026-09-14"),
        _order("O-5010", "C-109", [("Linen Shirt, size M", 55.0)], "delivered",
               "2026-09-20", "2026-09-27", "2026-09-26"),
        _order("O-5011", "C-109", [("Ceramic Planter", 28.0)], "shipped",
               "2026-09-30", "2026-10-07"),
        _order("O-5012", "C-110", [("Wool Throw", 85.0)], "shipped",
               "2026-10-01", "2026-10-06"),
    ]]
    rows += [("shipments", s) for s in [
        _shipment("O-4981", "Northline", "delivered", "2026-08-02"),
        _shipment("O-5001", "Northline", "exception", "2026-09-27",
                  reason="address not found; parcel held at depot"),
        _shipment("O-5002", "Northline", "delivered", "2026-08-20"),
        _shipment("O-5003", "Harbor Post", "in_transit", "2026-10-03", estimate="2026-10-07"),
        _shipment("O-5004", "Harbor Post", "delivered", "2026-09-24"),
        _shipment("O-5005", "Harbor Post", "delivered", "2026-10-01"),
        _shipment("O-5006", "Northline", "delivered", "2026-09-22"),
        _shipment("O-5007", "Harbor Post", "in_transit", "2026-10-03", estimate="2026-10-08"),
        _shipment("O-5008", "Northline", "delivered", "2026-09-28"),
        _shipment("O-5009", "Northline", "lost", "2026-09-19",
                  reason="parcel lost in transit; carrier investigation closed"),
        _shipment("O-5010", "Harbor Post", "delivered", "2026-09-26"),
        _shipment("O-5011", "Harbor Post", "in_transit", "2026-10-03", estimate="2026-10-06"),
        _shipment("O-5012", "Harbor Post", "in_transit", "2026-10-03", estimate="2026-10-05"),
    ]]
    rows += [("tickets", t) for t in [
        _ticket("T-9001", "C-103", "O-5003", "Where is my order?",
                ["Customer asked for an update."]),
        _ticket("T-9002", "C-109", "O-5010", "Shirt is the wrong size",
                ["Customer wants to return it for a size L."]),
        _ticket("T-9003", "C-109", "O-5011", "Planter has not arrived yet", []),
    ]]
    rows += [("refunds", {"refund_id": "R-8001", "order_id": "O-5006", "customer_id": "C-105",
                          "amount": 89.0, "reason": "changed mind", "issued_on": "2026-10-01"})]
    rows += [("policy", p) for p in [
        _policy("POL-1", "Refund eligibility",
                "Refund an order only once it has been delivered, and only within 30 days of "
                "delivery. After 30 days do not refund: explain the policy to the customer and "
                "solve the ticket. A refund is for the amount the customer paid for the affected "
                "item, and never more than the order total.",
                "refund return money back window eligible days delivered"),
        _policy("POL-2", "Damaged on arrival",
                "An item that arrives damaged is refunded at its own price, not the price of the "
                "whole order, if it is reported within 30 days of delivery. Refund it, then solve "
                "the ticket.",
                "damaged broken cracked faulty arrived item refund partial"),
        _policy("POL-3", "Carrier exceptions",
                "If a shipment shows a carrier exception (address not found, held at depot, "
                "delivery attempt failed) do not refund and do not solve the ticket. Put the "
                "ticket on hold and add a note with the carrier's reason. The carrier has five "
                "business days to resolve an exception.",
                "carrier exception stuck held depot address tracking undeliverable"),
        _policy("POL-4", "Lost packages",
                "When the carrier has marked a shipment lost, refund the order total in full and "
                "solve the ticket. Do not wait for the carrier.",
                "lost missing never arrived carrier refund full"),
        _policy("POL-5", "Tickets",
                "Log every customer contact as a ticket linked to the customer and the order. "
                "Keep one ticket per order: if one is already open or on hold, add a note to it "
                "instead of creating another. Statuses are open (we are working on it), hold "
                "(waiting on someone else) and solved (nothing more for us to do).",
                "ticket status open hold solved duplicate note log contact"),
        _policy("POL-6", "Goodwill for late delivery",
                "A gold-tier customer whose order was delivered more than five days after its "
                "promised date gets a goodwill refund of 10% of the order total. Any other "
                "customer gets an apology and nothing more. Solve the ticket afterwards.",
                "late delayed delivery goodwill gold tier apology promised"),
        _policy("POL-7", "Refund timing",
                "A refund reaches the customer five to seven business days after it is issued. "
                "If a refund has already been issued for an order, never issue a second one: "
                "tell the customer when it was issued and solve the ticket.",
                "refund timing issued already received card business days second duplicate"),
        _policy("POL-8", "Returns",
                "When a customer says they have posted a return, add the tracking number to the "
                "ticket as a note and put the ticket on hold until the return arrives.",
                "return posted sent tracking number exchange hold"),
        _policy("POL-9", "Orders in transit",
                "An order that is in transit and inside its delivery estimate is not a problem. "
                "Tell the customer the estimate and solve the ticket.",
                "in transit where order estimate arrive when tracking status shipped"),
    ]]
    return rows


def seed() -> dict[str, dict[str, Any]]:
    """The desk as every attempt starts: ``{"orders/O-5001": document, ...}``.

    A fresh copy each call, so a caller may change what it gets back.
    """
    return {f"{coll}/{doc[_ID_FIELD[coll]]}": copy.deepcopy(doc) for coll, doc in _documents()}


# --------------------------------------------------------------------- storage in Couchbase


def _quote(*parts: str) -> str:
    return ".".join(f"`{p}`" for p in parts)


def ensure_desk(cluster, bucket_name: str, scope_name: str) -> int:
    """Create the desk's collections and indexes, and store the seed under ``run_id="seed"``.

    Safe to run again. Returns the number of seed documents.
    """
    from couchbase.exceptions import CouchbaseException

    from cbnb.couchbase_io import ensure_collection, upsert_docs

    collections = {name: ensure_collection(cluster, bucket_name, scope_name, name)
                   for name in (*COLLECTIONS, *EXTRA_COLLECTIONS)}
    for name in COLLECTIONS:
        field = "run_id"
        _index(cluster, bucket_name, scope_name, name, field)
    for name in EXTRA_COLLECTIONS:
        _index(cluster, bucket_name, scope_name, name, "suite")

    by_collection: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in COLLECTIONS}
    for logical, doc in seed().items():
        coll, doc_id = logical.split("/")
        by_collection[coll][f"seed::{coll}::{doc_id}"] = {**doc, "run_id": "seed", "type": coll}
    total = 0
    for name, docs in by_collection.items():
        try:
            total += upsert_docs(collections[name], docs, progress=False)
        except (CouchbaseException, RuntimeError) as exc:  # pragma: no cover - surfaced to the user
            raise RuntimeError(f"Could not store the seed in {name}: {exc}") from exc
    return total


def _index(cluster, bucket_name: str, scope_name: str, collection: str, field: str) -> None:
    """Create a secondary index on one field, and wait for it to come online."""
    name = f"ix_{collection}_{field}"
    target = _quote(bucket_name, scope_name, collection)
    cluster.query(f"CREATE INDEX IF NOT EXISTS `{name}` ON {target}(`{field}`)").execute()
    for _ in range(60):
        rows = list(cluster.query(
            "SELECT RAW i.state FROM system:indexes i WHERE i.name = $name "
            "AND i.bucket_id = $bucket AND i.scope_id = $scope AND i.keyspace_id = $coll",
            named_parameters={"name": name, "bucket": bucket_name,
                              "scope": scope_name, "coll": collection}))
        if rows and rows[0] == "online":
            return
        time.sleep(1)
    raise RuntimeError(f"Index {name} did not come online")  # pragma: no cover


# ----------------------------------------------------------------------------- the desk


def _words(text: str) -> set[str]:
    stop = {"the", "and", "for", "has", "was", "not", "are", "you", "can", "this", "that", "with"}
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in stop}


class Desk:
    """One attempt's private copy of the desk, and the tools that work on it.

    Every document is keyed ``<run_id>::<collection>::<id>`` and carries ``run_id`` as a
    field, so a query for this attempt's documents cannot return another's. The tools are
    bound to the ``run_id``: the agent passes ids, never keys, and has no way to name
    another attempt's rows.
    """

    def __init__(self, cluster, bucket_name: str, scope_name: str, run_id: str) -> None:
        self.cluster = cluster
        self.bucket_name, self.scope_name, self.run_id = bucket_name, scope_name, run_id
        scope = cluster.bucket(bucket_name).scope(scope_name)
        self._collections = {name: scope.collection(name) for name in COLLECTIONS}
        self._seed = seed()
        self._next = {"tickets": 9004, "refunds": 8002}
        self._tools: dict[str, Callable[..., Any]] = {
            "get_customer": self._get_customer, "get_order": self._get_order,
            "get_shipment": self._get_shipment, "search_policy": self._search_policy,
            "find_tickets": self._find_tickets, "create_ticket": self._create_ticket,
            "update_ticket": self._update_ticket, "add_note": self._add_note,
            "issue_refund": self._issue_refund,
        }

    # ---- storage

    def prepare(self) -> None:
        """Copy the seed in under this attempt's ``run_id``, replacing anything left by an earlier try."""
        from cbnb.couchbase_io import upsert_docs

        for coll in ("tickets", "refunds"):  # the only collections an agent can add documents to
            self._query(f"DELETE FROM {self._keyspace(coll)} d WHERE d.run_id = $run_id")
        by_collection: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in COLLECTIONS}
        for logical, doc in self._seed.items():
            coll, doc_id = logical.split("/")
            by_collection[coll][self._key(coll, doc_id)] = {**doc, "run_id": self.run_id,
                                                           "type": coll}
        for coll, docs in by_collection.items():
            upsert_docs(self._collections[coll], docs, progress=False)

    def documents(self) -> dict[str, dict[str, Any]]:
        """This attempt's documents as they stand now, in the shape :func:`seed` returns."""
        found: dict[str, dict[str, Any]] = {}
        for coll in COLLECTIONS:
            for row in self._query(
                    f"SELECT d.* FROM {self._keyspace(coll)} d WHERE d.run_id = $run_id"):
                doc = {k: v for k, v in row.items() if k not in ("run_id", "type")}
                found[f"{coll}/{doc[_ID_FIELD[coll]]}"] = doc
        return found

    def effects(self) -> list[dict[str, Any]]:
        """What this attempt has changed so far: its documents compared with the seed."""
        return diff(self._seed, self.documents())

    def _key(self, coll: str, doc_id: str) -> str:
        return f"{self.run_id}::{coll}::{doc_id}"

    def _keyspace(self, coll: str) -> str:
        return _quote(self.bucket_name, self.scope_name, coll)

    def _query(self, statement: str, **params: Any) -> list[dict[str, Any]]:
        from couchbase.n1ql import QueryScanConsistency
        from couchbase.options import QueryOptions

        # REQUEST_PLUS, so a query sees the writes this attempt made a moment ago.
        options = QueryOptions(named_parameters={"run_id": self.run_id, **params},
                               scan_consistency=QueryScanConsistency.REQUEST_PLUS)
        return list(self.cluster.query(statement, options))

    def _read(self, coll: str, doc_id: str) -> dict[str, Any] | None:
        from couchbase.exceptions import DocumentNotFoundException

        try:
            doc = self._collections[coll].get(self._key(coll, doc_id)).content_as[dict]
        except DocumentNotFoundException:
            return None
        return {k: v for k, v in doc.items() if k not in ("run_id", "type")}

    def _write(self, coll: str, doc: dict[str, Any]) -> None:
        doc_id = doc[_ID_FIELD[coll]]
        self._collections[coll].upsert(self._key(coll, doc_id),
                                       {**doc, "run_id": self.run_id, "type": coll})

    # ---- the tool call

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool. Always returns a dict: ``{"result": ...}`` or ``{"error": "..."}``."""
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"unknown tool {name!r}; the tools are {', '.join(self._tools)}"}
        try:
            return {"result": tool(**arguments)}
        except _ToolError as exc:
            return {"error": str(exc)}
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}

    # ---- reads

    def _get_customer(self, customer_id: str | None = None, email: str | None = None):
        if customer_id:
            return self._read("customers", customer_id)
        if email:
            rows = self._query(f"SELECT d.* FROM {self._keyspace('customers')} d "
                               "WHERE d.run_id = $run_id AND LOWER(d.email) = $email",
                               email=email.strip().lower())
            return {k: v for k, v in rows[0].items() if k not in ("run_id", "type")} if rows else None
        raise _ToolError("give a customer_id or an email")

    def _get_order(self, order_id: str):
        return self._read("orders", order_id)

    def _get_shipment(self, order_id: str):
        return self._read("shipments", order_id)

    def _search_policy(self, query: str):
        wanted = _words(query)
        pages = self._query(f"SELECT d.* FROM {self._keyspace('policy')} d WHERE d.run_id = $run_id")
        scored = []
        for page in pages:
            hits = len(wanted & _words(f"{page['title']} {page['text']} {page['keywords']}"))
            if hits:
                scored.append((-hits, page["policy_id"], page))
        return [{"policy_id": p["policy_id"], "title": p["title"], "text": p["text"]}
                for _, _, p in sorted(scored)[:3]]

    def _find_tickets(self, customer_id: str | None = None, order_id: str | None = None):
        if not (customer_id or order_id):
            raise _ToolError("give a customer_id, an order_id, or both")
        clauses = [f"d.{field} = ${field}" for field, value in
                   (("customer_id", customer_id), ("order_id", order_id)) if value]
        rows = self._query(
            f"SELECT d.* FROM {self._keyspace('tickets')} d WHERE d.run_id = $run_id AND "
            + " AND ".join(clauses) + " ORDER BY d.ticket_id",
            customer_id=customer_id, order_id=order_id)
        return [{k: v for k, v in row.items() if k not in ("run_id", "type")} for row in rows]

    # ---- writes

    def _create_ticket(self, customer_id: str, subject: str, order_id: str | None = None,
                       status: str = "open"):
        if self._read("customers", customer_id) is None:
            raise _ToolError(f"no customer {customer_id}")
        if order_id and self._read("orders", order_id) is None:
            raise _ToolError(f"no order {order_id}")
        _check_status(status)
        ticket_id = f"T-{self._next['tickets']}"
        self._next["tickets"] += 1
        ticket = {"ticket_id": ticket_id, "customer_id": customer_id, "order_id": order_id,
                  "subject": subject, "status": status, "created_on": TODAY, "notes": []}
        self._write("tickets", ticket)
        return ticket

    def _update_ticket(self, ticket_id: str, status: str):
        ticket = self._read("tickets", ticket_id)
        if ticket is None:
            raise _ToolError(f"no ticket {ticket_id}")
        _check_status(status)
        ticket["status"] = status
        self._write("tickets", ticket)
        return ticket

    def _add_note(self, ticket_id: str, text: str):
        ticket = self._read("tickets", ticket_id)
        if ticket is None:
            raise _ToolError(f"no ticket {ticket_id}")
        ticket["notes"].append({"on": TODAY, "text": text})
        self._write("tickets", ticket)
        return ticket

    def _issue_refund(self, order_id: str, amount: float, reason: str):
        order = self._read("orders", order_id)
        if order is None:
            raise _ToolError(f"no order {order_id}")
        shipment = self._read("shipments", order_id) or {}
        if order["status"] != "delivered" and shipment.get("status") != "lost":
            raise _ToolError(f"order {order_id} is not eligible for a refund: it is "
                             f"{order['status']} and the shipment is {shipment.get('status')}")
        try:
            amount = round(float(amount), 2)
        except (TypeError, ValueError) as exc:
            raise _ToolError("amount must be a number") from exc
        left = round(order["total"] - order["refunded"], 2)
        if amount <= 0:
            raise _ToolError("amount must be more than zero")
        if amount > left:
            raise _ToolError(f"cannot refund {amount:.2f}: only {left:.2f} of order {order_id} "
                             "is left to refund")
        refund_id = f"R-{self._next['refunds']}"
        self._next["refunds"] += 1
        refund = {"refund_id": refund_id, "order_id": order_id,
                  "customer_id": order["customer_id"], "amount": amount, "reason": reason,
                  "issued_on": TODAY}
        self._write("refunds", refund)
        order["refunded"] = round(order["refunded"] + amount, 2)
        self._write("orders", order)
        return refund


class _ToolError(Exception):
    """A tool refused, for a reason the agent can read and act on."""


def _check_status(status: str) -> None:
    if status not in STATUSES:
        raise _ToolError(f"invalid status {status!r}; a ticket's status is one of "
                         f"{', '.join(STATUSES)}")


# ---------------------------------------------------------------------------------- tools

#: Tools that change the desk. The rest only read it.
WRITES = frozenset({"create_ticket", "update_ticket", "add_note", "issue_refund"})


def _tool(name: str, description: str, properties: dict[str, str], required: list[str],
          numbers: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "required": required, "properties": {
            key: {"type": "number" if key in numbers else "string", "description": text}
            for key, text in properties.items()}}}}


TOOLS: list[dict[str, Any]] = [
    _tool("get_customer", "Look up a customer by id or by email address. Returns the customer, "
          "including their tier and order ids, or null if there is none.",
          {"customer_id": "e.g. C-101", "email": "the customer's email address"}, []),
    _tool("get_order", "Look up an order by id. Returns its items, total, status, dates and the "
          "amount already refunded, or null if there is no such order.",
          {"order_id": "e.g. O-5001"}, ["order_id"]),
    _tool("get_shipment", "Look up an order's shipment by order id: carrier, status, the "
          "carrier's reason for any exception, and the delivery estimate. Null if none.",
          {"order_id": "e.g. O-5001"}, ["order_id"]),
    _tool("search_policy", "Search the support policy pages. Returns up to three matching pages, "
          "or an empty list if nothing matches.",
          {"query": "a few words about the situation"}, ["query"]),
    _tool("find_tickets", "List support tickets for a customer, an order, or both.",
          {"customer_id": "e.g. C-101", "order_id": "e.g. O-5001"}, []),
    _tool("create_ticket", "Open a new support ticket.",
          {"customer_id": "e.g. C-101", "subject": "a short summary",
           "order_id": "the order it is about", "status": "defaults to open"},
          ["customer_id", "subject"]),
    _tool("update_ticket", "Change a ticket's status.",
          {"ticket_id": "e.g. T-9001", "status": "the new status"}, ["ticket_id", "status"]),
    _tool("add_note", "Add a note to an existing ticket.",
          {"ticket_id": "e.g. T-9001", "text": "the note"}, ["ticket_id", "text"]),
    _tool("issue_refund", "Refund part or all of an order to the customer's original payment "
          "method. Fails if the order is not eligible or the amount is more than is left to "
          "refund.",
          {"order_id": "e.g. O-5001", "amount": "dollars, e.g. 34.00", "reason": "why"},
          ["order_id", "amount", "reason"], numbers=("amount",)),
]


# ------------------------------------------------------------------------------- what changed


def diff(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The effects that turn ``before`` into ``after``, as plain data.

    Each effect is ``{"op": "created" | "changed" | "deleted", "key": "tickets/T-9004",
    "collection": "tickets", "fields": {...}}``. A created or deleted document lists all its
    fields as ``after`` or ``before``. A changed one lists only the fields that differ, each
    as ``{"before": ..., "after": ...}``.
    """
    effects: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        effect: dict[str, Any] = {"key": key, "collection": key.split("/")[0]}
        if old is None:
            effect |= {"op": "created", "fields": {f: {"after": v} for f, v in new.items()}}
        elif new is None:
            effect |= {"op": "deleted", "fields": {f: {"before": v} for f, v in old.items()}}
        else:
            effect |= {"op": "changed", "fields": {
                f: {"before": old.get(f), "after": new.get(f)}
                for f in sorted(set(old) | set(new)) if old.get(f) != new.get(f)}}
        effects.append(effect)
    return effects


def describe(effects: list[dict[str, Any]]) -> str:
    """The effects as short lines of text, for a person or an agent to read."""
    if not effects:
        return "No records have been changed."
    lines = []
    for effect in effects:
        fields = effect["fields"]
        if effect["op"] == "created":
            shown = {f: v["after"] for f, v in fields.items()}
            lines.append(f"created {effect['key']}: {json.dumps(shown)}")
        elif effect["op"] == "deleted":
            lines.append(f"deleted {effect['key']}")
        else:
            parts = [f"{f}: {json.dumps(v['before'])} -> {json.dumps(v['after'])}"
                     for f, v in fields.items()]
            lines.append(f"changed {effect['key']}: " + "; ".join(parts))
    return "\n".join(lines)
