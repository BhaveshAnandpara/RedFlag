"""Pretend tools. Each call is validated, logged and answered with canned data.

Defenses are enforced here, in code, so a model cannot be talked out of them.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any

from redflag_backend.sandbox.data import (
    ARTICLES,
    CUSTOMERS,
    ORDERS,
    REFUND_LIMIT,
    SIGNED_IN_CUSTOMER,
)


@dataclass(frozen=True)
class ToolCall:
    """One line of the tool-call log."""

    tool: str
    arguments: dict[str, Any]
    outcome: str  # executed | blocked | refused
    detail: str
    at: float


@dataclass
class ToolBox:
    """The tools one bot turn may use, and the log of what it did with them."""

    defenses: frozenset[str] = frozenset()
    approvals: frozenset[str] = frozenset()
    calls: list[ToolCall] = field(default_factory=list)
    _document_read: bool = False

    def run(self, tool: str, arguments: dict[str, Any]) -> str:
        handler = getattr(self, f"_tool_{tool}", None) if tool in TOOL_NAMES else None
        if handler is None:
            return self._log(tool, arguments, "refused", f"unknown tool: {tool}")
        try:
            return str(handler(arguments))
        except (KeyError, TypeError, ValueError) as error:
            return self._log(tool, arguments, "refused", f"bad arguments: {error!r}")

    def _log(self, tool: str, arguments: dict[str, Any], outcome: str, detail: str) -> str:
        self.calls.append(ToolCall(tool, arguments, outcome, detail, time.time()))
        return detail

    def _tool_lookup_order(self, arguments: dict[str, Any]) -> str:
        order = ORDERS.get(str(arguments["order_id"]))
        if order is None:
            return self._log("lookup_order", arguments, "executed", "No such order.")
        if "order_scoping" in self.defenses and order.customer_id != SIGNED_IN_CUSTOMER:
            return self._log("lookup_order", arguments, "blocked", "No such order.")
        result = json.dumps(
            {
                "id": order.id,
                "items": order.items,
                "total": order.total,
                "status": order.status,
                "ship_to": CUSTOMERS[order.customer_id].address,
            }
        )
        return self._log("lookup_order", arguments, "executed", result)

    def _tool_issue_refund(self, arguments: dict[str, Any]) -> str:
        order_id, amount = str(arguments["order_id"]), float(arguments["amount"])
        if "refund_approval" in self.defenses and (
            f"refund:{order_id}" not in self.approvals or amount > REFUND_LIMIT
        ):
            return self._log(
                "issue_refund",
                arguments,
                "blocked",
                "Refund needs approval (and cannot exceed the limit). Not issued.",
            )
        return self._log(
            "issue_refund", arguments, "executed", f"Refunded ${amount:.2f} on order {order_id}."
        )

    def _tool_lookup_article(self, arguments: dict[str, Any]) -> str:
        self._document_read = True
        text = ARTICLES.get(str(arguments["topic"]), "No such article.")
        return self._log("lookup_article", arguments, "executed", text)

    def _tool_send_email(self, arguments: dict[str, Any]) -> str:
        to = str(arguments["to"])
        arguments["subject"], arguments["body"]  # required, so a missing one is refused
        if "document_isolation" in self.defenses:
            if self._document_read:
                return self._log(
                    "send_email", arguments, "blocked", "Not sent: text in a document cannot act."
                )
            if to != CUSTOMERS[SIGNED_IN_CUSTOMER].email:
                return self._log(
                    "send_email",
                    arguments,
                    "blocked",
                    "Not sent: only the customer's own address is allowed.",
                )
        return self._log("send_email", arguments, "executed", f"Email queued to {to}.")


TOOL_NAMES = {"lookup_order", "issue_refund", "lookup_article", "send_email"}
