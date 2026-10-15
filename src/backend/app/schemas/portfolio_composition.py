"""Request validation for immutable, display-only portfolio memberships."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PortfolioSource = Literal["research", "imported", "paper", "live"]
MemberKind = Literal[
    "account",
    "strategy",
    "research_artifact",
    "imported_ledger",
    "paper_account",
]

_SOURCE_MEMBER_KINDS: dict[str, frozenset[str]] = {
    "research": frozenset({"research_artifact"}),
    "imported": frozenset({"imported_ledger"}),
    "paper": frozenset({"paper_account", "strategy"}),
    "live": frozenset({"account", "strategy"}),
}


class PortfolioCompositionMember(BaseModel):
    """One source-scoped account, strategy, or offline artifact reference."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: MemberKind
    ref: str = Field(min_length=1, max_length=256)

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        if value != value.strip() or value == "*" or not value.isprintable():
            raise ValueError("member reference is invalid")
        return value


class PortfolioCompositionCreate(BaseModel):
    """Create a new immutable membership version for the authenticated owner."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    portfolio_ref: str = Field(min_length=1, max_length=128)
    source_type: PortfolioSource
    base_currency: str = Field(min_length=3, max_length=16)
    members: list[PortfolioCompositionMember] = Field(min_length=1, max_length=256)

    @field_validator("portfolio_ref")
    @classmethod
    def validate_portfolio_ref(cls, value: str) -> str:
        if value != value.strip() or value == "*" or not value.isprintable():
            raise ValueError("portfolio reference is invalid")
        return value

    @field_validator("base_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if value != value.upper() or not value.isascii() or not value.isalnum():
            raise ValueError("base currency must be an uppercase code")
        return value

    @model_validator(mode="after")
    def validate_membership(self) -> PortfolioCompositionCreate:
        allowed_kinds = _SOURCE_MEMBER_KINDS[self.source_type]
        if any(member.kind not in allowed_kinds for member in self.members):
            raise ValueError("member kind does not belong to the selected source")
        identities = [(member.kind, member.ref) for member in self.members]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate members are not allowed")
        return self
