"""Separate, read-only health facts for one authorized Gateway account."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .contracts import AccountReadView

GatewaySessionStatus = Literal["ready", "not_ready", "unobserved"]


class GatewayHealthContractError(ValueError):
    """The SDK Gateway status reply was malformed or internally inconsistent."""

    def __init__(self, code: str = "INVALID_GATEWAY_HEALTH_REPLY") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class GatewayHealthView:
    """Owner-reported session state, account observation, and explicit unknowns.

    ``rpc_reachable`` means only that the authorized ``account.head`` call
    returned. It says nothing about a provider socket, and account snapshot
    freshness remains an independent fact. Market-feed health is unobserved
    until a market owner supplies its own status.
    """

    account_ref: str
    rpc_reachable: bool
    gateway_session_status: GatewaySessionStatus
    session_generation: str | None
    session_fresh_for_seconds: float | None
    latest_cursor: int | None
    account_observation: AccountReadView

    @classmethod
    def from_replies(
        cls,
        account_ref: str,
        head_reply: object,
        account_observation: AccountReadView,
    ) -> GatewayHealthView:
        if type(account_ref) is not str or not account_ref or account_ref != account_ref.strip():
            raise GatewayHealthContractError()
        if type(account_observation) is not AccountReadView:
            raise GatewayHealthContractError()
        if account_observation.account_ref != account_ref:
            raise GatewayHealthContractError()
        if not isinstance(head_reply, Mapping):
            raise GatewayHealthContractError()
        if set(head_reply) not in ({"latest_cursor"}, {"latest_cursor", "state_status"}):
            raise GatewayHealthContractError()

        latest_cursor = head_reply["latest_cursor"]
        if type(latest_cursor) is not int or latest_cursor < 0:
            raise GatewayHealthContractError()

        if "state_status" not in head_reply:
            return cls(
                account_ref=account_ref,
                rpc_reachable=True,
                gateway_session_status="unobserved",
                session_generation=None,
                session_fresh_for_seconds=None,
                latest_cursor=latest_cursor,
                account_observation=account_observation,
            )

        owner_status = head_reply["state_status"]
        if not isinstance(owner_status, Mapping) or set(owner_status) != {
            "session_generation",
            "ready",
            "fresh_for_seconds",
        }:
            raise GatewayHealthContractError()
        generation = owner_status["session_generation"]
        if generation is not None and (
            type(generation) is not str or not generation or generation != generation.strip()
        ):
            raise GatewayHealthContractError()
        ready = owner_status["ready"]
        fresh_for = owner_status["fresh_for_seconds"]
        if type(ready) is not bool or isinstance(fresh_for, bool) or type(fresh_for) not in {
            int,
            float,
        }:
            raise GatewayHealthContractError()
        fresh_for = float(fresh_for)
        if not math.isfinite(fresh_for) or fresh_for < 0:
            raise GatewayHealthContractError()
        if ready and (generation is None or fresh_for <= 0):
            raise GatewayHealthContractError()

        return cls(
            account_ref=account_ref,
            rpc_reachable=True,
            gateway_session_status="ready" if ready else "not_ready",
            session_generation=generation,
            session_fresh_for_seconds=fresh_for,
            latest_cursor=latest_cursor,
            account_observation=account_observation,
        )
