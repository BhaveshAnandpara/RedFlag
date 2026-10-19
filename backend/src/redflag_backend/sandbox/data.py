"""The Acme Store demo data as Python objects, for the verdict checks.

The data itself lives in backend/bots/_shared/acme_store/data.json, so the bots and the checks
read one source. Nobody and nothing in it is real.
"""

import json
from dataclasses import dataclass

from redflag_backend.sandbox.paths import ACME_SHARED

_RAW = json.loads((ACME_SHARED / "data.json").read_text(encoding="utf-8"))

SIGNED_IN_CUSTOMER: str = _RAW["signed_in_customer"]


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    email: str
    address: str


@dataclass(frozen=True)
class Order:
    id: str
    customer_id: str
    items: str
    total: float
    status: str


CUSTOMERS = {key: Customer(**value) for key, value in _RAW["customers"].items()}
ORDERS = {key: Order(**value) for key, value in _RAW["orders"].items()}
ARTICLES: dict[str, str] = _RAW["articles"]

# An obviously fake value. It is in the weak bot's prompt so a leak can be recorded.
SECRET: str = _RAW["secret"]
