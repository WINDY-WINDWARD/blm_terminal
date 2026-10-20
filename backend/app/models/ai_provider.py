"""SQLAlchemy ORM models for AI provider routes and credentials."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AIProviderRoute(Base):
    """Route definition for AI provider inference and routing."""

    __tablename__ = "ai_provider_routes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # 'oauth' | 'endpoint' | 'direct'
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    display_label: Mapped[str] = mapped_column(String(128), nullable=False)
    proxy_prefix: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    credentials: Mapped[list["AIProviderCredential"]] = relationship(
        "AIProviderCredential",
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="AIProviderCredential.priority",
        lazy="selectin",
    )


class AIProviderCredential(Base):
    """Credential record associated with an AI provider route.

    Secrets are never stored in the database; vault_reference points to the
    encrypted entry in the OS-keyring-backed provider vault.
    """

    __tablename__ = "ai_provider_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    route_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_provider_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # 'oauth' | 'custom_endpoint_key'
    vault_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    proxy_credential_name: Mapped[str] = mapped_column(String(128), nullable=False)
    masked_identity: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    cooldown: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_redacted_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    route: Mapped[AIProviderRoute] = relationship("AIProviderRoute", back_populates="credentials", lazy="selectin")

    @property
    def vault_ref(self) -> str:
        return self.vault_reference

    @vault_ref.setter
    def vault_ref(self, val: str) -> None:
        self.vault_reference = val

    @property
    def masked_label(self) -> str:
        return self.masked_identity

    @masked_label.setter
    def masked_label(self, val: str) -> None:
        self.masked_identity = val

    @property
    def last_error(self) -> str | None:
        return self.last_redacted_error

    @last_error.setter
    def last_error(self, val: str | None) -> None:
        self.last_redacted_error = val

    @property
    def cooldown_until(self) -> datetime | None:
        return self.cooldown

    @cooldown_until.setter
    def cooldown_until(self, val: datetime | None) -> None:
        self.cooldown = val


# Compatibility aliases
AiProviderRoute = AIProviderRoute
AiProviderCredential = AIProviderCredential
