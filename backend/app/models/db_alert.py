"""SQLAlchemy ORM model for persisted DB-stats alert events."""

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DbAlert(Base):
    """Silent DB-health alert (queue/latency spikes), shown only in Jobs → DB Stats."""

    __tablename__ = "db_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Unix epoch seconds (float) — matches the in-memory alert ring format.
    ts: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # warning | critical
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    # Frozen queue snapshot JSON at fire time (occupancy, per-prio, p95, rec/min, db size).
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    __table_args__ = (Index("ix_db_alerts_ts", "ts"),)
