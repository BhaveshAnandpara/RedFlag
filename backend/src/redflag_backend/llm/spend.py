"""Running total of estimated paid spend, kept in Postgres so a restart cannot reset the cap."""

from sqlalchemy import Engine, text


class SqlSpend:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def total(self) -> float:
        with self._engine.connect() as conn:
            value = conn.execute(text("SELECT total_usd FROM llm_spend WHERE id = 1")).scalar()
        return float(value or 0.0)

    def add(self, amount: float) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO llm_spend (id, total_usd) VALUES (1, :amount) "
                    "ON CONFLICT (id) DO UPDATE SET total_usd = llm_spend.total_usd + :amount"
                ),
                {"amount": amount},
            )
