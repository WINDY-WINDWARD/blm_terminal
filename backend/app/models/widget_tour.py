"""SQLAlchemy ORM model for widget tour seen state."""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WidgetTour(Base):
    """Persisted widget tour seen state for a user."""

    __tablename__ = "widget_tours"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    widget_command: Mapped[str] = mapped_column(String(32), nullable=False)
    seen_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    user = relationship("User", backref="widget_tours")

    __table_args__ = (
        UniqueConstraint("user_id", "widget_command", name="uq_widget_tour_user_command"),
    )
