"""Thin AFI adapter for Risk's durable offline portfolio analytics tasks."""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import HTTPException, status

from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.portfolio_analytics_tasks import PortfolioAnalyticsTaskCreate

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TASK_STATES = frozenset(
    {"pending", "running", "succeeded", "unavailable", "failed", "cancelled", "expired"}
)
_IDENTIFIER_SUFFIX = re.compile(r"^[0-9a-f]{24}$")


class PortfolioAnalyticsWorker(Protocol):
    """The four fixed async methods added to the existing service-read owner."""

    async def upload_portfolio_analytics_input(
        self, scope_ref: str, input_snapshot_id: str, facts: dict[str, Any]
    ) -> Any: ...

    async def submit_portfolio_analytics_task(
        self,
        scope_ref: str,
        task_ref: str,
        input_snapshot_id: str,
        request: dict[str, Any],
    ) -> Any: ...

    async def query_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> Any: ...

    async def cancel_portfolio_analytics_task(self, scope_ref: str, task_ref: str) -> Any: ...


class PortfolioAnalyticsTaskError(RuntimeError):
    """Finite application-side task projection error."""

    def __init__(self, code: str, http_status: int) -> None:
        self.code = code
        self.http_status = http_status
        super().__init__(code)


class PortfolioAnalyticsTaskService:
    """Bind typed V2 inputs and task references to one owned membership cut."""

    def __init__(
        self,
        worker: PortfolioAnalyticsWorker,
        *,
        scope_ref: str,
        owner_subject: str,
        membership: PortfolioCompositionVersion,
    ) -> None:
        if (
            type(scope_ref) is not str
            or not scope_ref
            or scope_ref != scope_ref.strip()
            or type(owner_subject) is not str
            or not owner_subject
            or type(membership.membership_sha256) is not str
            or _SHA256.fullmatch(membership.membership_sha256) is None
            or type(membership.membership_version) is not int
            or membership.membership_version < 1
        ):
            raise PortfolioAnalyticsTaskError("ANALYTICS_BINDING_UNAVAILABLE", 503)
        self._worker = worker
        self._scope_ref = scope_ref
        self._owner_subject = owner_subject
        self._membership = membership

    async def create(self, payload: PortfolioAnalyticsTaskCreate) -> dict[str, Any]:
        facts = dict(payload.facts)
        request = dict(payload.request)
        row = self._membership
        if row.source_type not in {"research", "imported", "paper"}:
            raise PortfolioAnalyticsTaskError("ANALYTICS_OFFLINE_SOURCE_REQUIRED", 403)
        if facts.get("portfolio_ref") != row.portfolio_ref:
            raise PortfolioAnalyticsTaskError("ANALYTICS_PORTFOLIO_MISMATCH", 422)
        if facts.get("source_mode") != row.source_type:
            raise PortfolioAnalyticsTaskError("ANALYTICS_SOURCE_MODE_MISMATCH", 422)
        if request.get("portfolio_ref") != row.portfolio_ref:
            raise PortfolioAnalyticsTaskError("ANALYTICS_PORTFOLIO_MISMATCH", 422)

        task_ref, input_snapshot_id = self._task_identity(payload.idempotency_key)
        upload = await self._call(
            "upload_portfolio_analytics_input",
            self._scope_ref,
            input_snapshot_id,
            facts,
        )
        input_result = self._require_success(upload)
        input_sha256 = self._validate_input_result(
            input_result, input_snapshot_id, row.source_type
        )

        submitted = await self._call(
            "submit_portfolio_analytics_task",
            self._scope_ref,
            task_ref,
            input_snapshot_id,
            request,
        )
        result = self._require_success(submitted)
        return self._task_payload(
            result,
            task_ref,
            input_snapshot_id,
            expected_input_sha256=input_sha256,
        )

    async def query(self, task_ref: str) -> dict[str, Any]:
        input_snapshot_id = self._input_for_task(task_ref)
        result = self._require_success(
            await self._call(
                "query_portfolio_analytics_task", self._scope_ref, task_ref
            )
        )
        return self._task_payload(result, task_ref, input_snapshot_id)

    async def cancel(self, task_ref: str) -> dict[str, Any]:
        input_snapshot_id = self._input_for_task(task_ref)
        result = self._require_success(
            await self._call(
                "cancel_portfolio_analytics_task", self._scope_ref, task_ref
            )
        )
        return self._task_payload(result, task_ref, input_snapshot_id)

    async def _call(self, method_name: str, *args: Any) -> Any:
        method = getattr(self._worker, method_name, None)
        if not callable(method) or not inspect.iscoroutinefunction(method):
            raise PortfolioAnalyticsTaskError("ANALYTICS_WORKER_UNAVAILABLE", 503)
        try:
            return await method(*args)
        except Exception as error:  # noqa: BLE001 - expose only stable worker codes
            code = getattr(error, "code", None)
            if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
                raise PortfolioAnalyticsTaskError(code, _worker_status(code)) from None
            raise PortfolioAnalyticsTaskError("ANALYTICS_WORKER_FAILED", 503) from None

    def _task_identity(self, idempotency_key: str) -> tuple[str, str]:
        row = self._membership
        owner_tag = _digest(self._owner_subject)[:16]
        portfolio_tag = _digest(row.portfolio_ref)[:16]
        key_tag = _digest(idempotency_key)[:24]
        version_tag = f"v{row.membership_version}"
        membership_tag = row.membership_sha256[:16]
        task_ref = (
            f"afi2:{owner_tag}:{portfolio_tag}:{version_tag}:{membership_tag}:{key_tag}"
        )
        input_snapshot_id = (
            f"afi2-input:{owner_tag}:{portfolio_tag}:{version_tag}:"
            f"{membership_tag}:{key_tag}"
        )
        if len(task_ref) > 128 or len(input_snapshot_id) > 128:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REFERENCE_INVALID", 422)
        return task_ref, input_snapshot_id

    def _input_for_task(self, task_ref: str) -> str:
        if type(task_ref) is not str:
            raise PortfolioAnalyticsTaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        row = self._membership
        owner_tag = _digest(self._owner_subject)[:16]
        portfolio_tag = _digest(row.portfolio_ref)[:16]
        prefix = (
            f"afi2:{owner_tag}:{portfolio_tag}:v{row.membership_version}:"
            f"{row.membership_sha256[:16]}:"
        )
        if not task_ref.startswith(prefix):
            raise PortfolioAnalyticsTaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        key_tag = task_ref[len(prefix) :]
        if _IDENTIFIER_SUFFIX.fullmatch(key_tag) is None:
            raise PortfolioAnalyticsTaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        return (
            f"afi2-input:{owner_tag}:{portfolio_tag}:v{row.membership_version}:"
            f"{row.membership_sha256[:16]}:{key_tag}"
        )

    def _require_success(self, value: object) -> Mapping[str, Any]:
        if type(value) is not dict or set(value) != {"ok", "code", "result"}:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        if type(value["ok"]) is not bool or type(value["code"]) is not str:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        if value["ok"] is False:
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value["code"]) is None:
                raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
            if value["code"] == "TASK_NOT_FOUND":
                raise PortfolioAnalyticsTaskError("ANALYTICS_TASK_NOT_FOUND", 404)
            raise PortfolioAnalyticsTaskError(value["code"], _worker_status(value["code"]))
        if value["code"] != "OK" or type(value["result"]) is not dict:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        return value["result"]

    @staticmethod
    def _validate_input_result(
        value: Mapping[str, Any], input_snapshot_id: str, source_mode: str
    ) -> str:
        if set(value) != {"input_snapshot_id", "input_sha256", "source_mode", "created_ns"}:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        if (
            value["input_snapshot_id"] != input_snapshot_id
            or value["source_mode"] != source_mode
            or type(value["input_sha256"]) is not str
            or _SHA256.fullmatch(value["input_sha256"]) is None
            or type(value["created_ns"]) is not int
            or value["created_ns"] <= 0
        ):
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        return value["input_sha256"]

    def _task_payload(
        self,
        value: Mapping[str, Any],
        task_ref: str,
        input_snapshot_id: str,
        *,
        expected_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        required = {
            "task_ref",
            "state",
            "input_snapshot_id",
            "input_sha256",
            "created_ns",
            "state_ns",
            "detail_code",
            "result",
        }
        if set(value) != required:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        if (
            value["task_ref"] != task_ref
            or value["input_snapshot_id"] != input_snapshot_id
            or type(value["state"]) is not str
            or value["state"] not in _TASK_STATES
            or type(value["input_sha256"]) is not str
            or _SHA256.fullmatch(value["input_sha256"]) is None
            or type(value["created_ns"]) is not int
            or value["created_ns"] <= 0
            or type(value["state_ns"]) is not int
            or value["state_ns"] <= 0
            or (
                value["detail_code"] is not None
                and (
                    type(value["detail_code"]) is not str
                    or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value["detail_code"]) is None
                )
            )
            or (value["result"] is not None and type(value["result"]) is not dict)
            or (
                expected_input_sha256 is not None
                and value["input_sha256"] != expected_input_sha256
            )
        ):
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        if value["result"] is not None:
            _require_finite_json(value["result"])
        row = self._membership
        if value["result"] is not None:
            self._validate_v2_report(value["result"], value["input_sha256"])
        return {
            "task_ref": task_ref,
            "portfolio_ref": row.portfolio_ref,
            "membership_version": row.membership_version,
            "membership_sha256": row.membership_sha256,
            "input_snapshot_id": input_snapshot_id,
            "input_sha256": value["input_sha256"],
            "state": value["state"],
            "detail_code": value["detail_code"],
            "created_ns": str(value["created_ns"]),
            "state_ns": str(value["state_ns"]),
            "result": value["result"],
        }

    def _validate_v2_report(self, report: dict[str, Any], input_sha256: str) -> None:
        required = {
            "calculation_ref",
            "decimal_serialization_ref",
            "facts_snapshot_ref",
            "input_sha256",
            "metrics",
            "portfolio_ref",
            "provenance",
            "report_sha256",
            "reporting_currency",
            "request_sha256",
            "schema_ref",
            "serialization_ref",
            "status",
            "version",
        }
        if set(report) != required:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        if (
            report["calculation_ref"] != "portfolio_metrics_v1_bundle_v2"
            or report["decimal_serialization_ref"] != "finite_decimal_fixed_point_canonical_v1"
            or report["input_sha256"] != input_sha256
            or report["portfolio_ref"] != self._membership.portfolio_ref
            or report["schema_ref"] != "portfolio_analytics_v2"
            or report["serialization_ref"] != "json_sort_keys_compact_ascii_v1"
            or type(report["status"]) is not str
            or report["status"] not in {"AVAILABLE", "UNAVAILABLE"}
            or type(report["version"]) is not int
            or report["version"] != 2
            or type(report["facts_snapshot_ref"]) is not str
            or not report["facts_snapshot_ref"]
            or type(report["reporting_currency"]) is not str
            or type(report["request_sha256"]) is not str
            or _SHA256.fullmatch(report["request_sha256"]) is None
            or type(report["report_sha256"]) is not str
            or _SHA256.fullmatch(report["report_sha256"]) is None
        ):
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        provenance = report["provenance"]
        if type(provenance) is not dict or set(provenance) != {
            "facts_source",
            "loss_history",
            "nav_history",
            "scenario",
            "spot",
        }:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        facts_source = provenance["facts_source"]
        if (
            type(facts_source) is not dict
            or set(facts_source)
            != {"generation", "mode", "source_ref", "source_version", "snapshot_ref"}
            or facts_source["mode"] != self._membership.source_type
            or any(type(facts_source[name]) is not str or not facts_source[name] for name in facts_source)
        ):
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        metrics = report["metrics"]
        if type(metrics) is not dict or set(metrics) != {
            "historical_var_es",
            "max_drawdown",
            "spot_exposure",
            "stress_scenario",
        }:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        unsigned = dict(report)
        claimed_digest = unsigned.pop("report_sha256")
        try:
            encoded = json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        except (TypeError, ValueError, UnicodeEncodeError):
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503) from None
        if hashlib.sha256(encoded).hexdigest() != claimed_digest:
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _worker_status(code: str) -> int:
    if code in {"TASK_QUOTA_EXCEEDED", "QUEUE_FULL"}:
        return status.HTTP_429_TOO_MANY_REQUESTS
    if code in {"TASK_NOT_FOUND", "INPUT_NOT_FOUND"}:
        return status.HTTP_404_NOT_FOUND
    if code in {
        "TASK_REF_CONFLICT",
        "INPUT_ALREADY_COMPLETE",
        "TASK_TERMINAL",
        "TASK_CLEANUP_REQUIRED",
    }:
        return status.HTTP_409_CONFLICT
    if code.startswith("INVALID_") or code in {
        "SOURCE_MODE_NOT_ALLOWED",
        "INPUT_LIMIT_EXCEEDED",
        "INPUT_PORTFOLIO_MISMATCH",
    }:
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    return status.HTTP_503_SERVICE_UNAVAILABLE


def _require_finite_json(value: object, *, depth: int = 0) -> None:
    if depth > 32:
        raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        import math

        if not math.isfinite(value):
            raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
        return
    if type(value) is list:
        for item in value:
            _require_finite_json(item, depth=depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _require_finite_json(item, depth=depth + 1)
        return
    raise PortfolioAnalyticsTaskError("ANALYTICS_REPLY_INVALID", 503)
