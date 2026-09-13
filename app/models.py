import uuid

from sqlalchemy import DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StateObservation(Base):
    __tablename__ = "state_observation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()"
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    subject_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[object] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    __table_args__ = (
        Index("ix_state_observation_subject_domain", "subject_type", "subject_id", "domain"),
    )
