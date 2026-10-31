"""Owner-bound V1 task adapter for persisted offline analytics datasets."""

from __future__ import annotations

import hashlib
import inspect
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.models.portfolio_analytics_dataset import PortfolioAnalyticsDatasetV1
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.portfolio_analytics_v1 import (
    PortfolioAnalyticsFactsV1,
    PortfolioAnalyticsTaskCreateV1,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TASK_STATES = frozenset(
    {"pending", "running", "succeeded", "unavailable", "failed", "cancelled", "expired"}
)
_TASK_SUFFIX = re.compile(r"^([0-9a-f]{24}):([0-9a-f]{20})$")
_CURRENCY = re.compile(r"^[A-Z][A-Z0-9]{1,11}$")


class PortfolioAnalyticsV1Worker(Protocol):
    """The fixed analytics methods on the configured service-read worker."""

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


class PortfolioAnalyticsV1TaskError(RuntimeError):
    """Finite application-side worker/task projection error."""

    def __init__(self, code: str, http_status: int) -> None:
        self.code = code
        self.http_status = http_status
        super().__init__(code)


class PortfolioAnalyticsV1TaskService:
    """Run V1 against one persisted dataset and exact owner membership cut."""

    def __init__(
        self,
        worker: PortfolioAnalyticsV1Worker,
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
            or owner_subject != membership.owner_subject
            or type(membership.membership_sha256) is not str
            or _SHA256.fullmatch(membership.membership_sha256) is None
            or type(membership.membership_version) is not int
            or membership.membership_version < 1
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_BINDING_UNAVAILABLE", 503)
        if membership.source_type not in {"research", "imported", "paper"}:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_OFFLINE_SOURCE_REQUIRED", 403)
        self._worker = worker
        self._scope_ref = scope_ref
        self._owner_subject = owner_subject
        self._membership = membership

    async def create(
        self,
        dataset: PortfolioAnalyticsDatasetV1,
        facts: PortfolioAnalyticsFactsV1,
        payload: PortfolioAnalyticsTaskCreateV1,
    ) -> dict[str, Any]:
        self._validate_dataset(dataset, facts)
        request = {
            "membership_version": self._membership.membership_version,
            "period_end_date_utc": payload.request.period_end_date_utc,
            "period_start_date_utc": payload.request.period_start_date_utc,
            "portfolio_ref": self._membership.portfolio_ref,
            "reporting_currency": payload.request.reporting_currency,
            "version": 1,
        }
        task_ref, input_snapshot_id = self._task_identity(
            dataset.dataset_ref, payload.idempotency_key
        )
        facts_payload = facts.model_dump(mode="json")
        input_result = self._require_success(
            await self._call(
                "upload_portfolio_analytics_input",
                self._scope_ref,
                input_snapshot_id,
                facts_payload,
            )
        )
        input_sha256 = self._validate_input_result(
            input_result, input_snapshot_id, dataset
        )
        submitted = self._require_success(
            await self._call(
                "submit_portfolio_analytics_task",
                self._scope_ref,
                task_ref,
                input_snapshot_id,
                request,
            )
        )
        return self._task_payload(
            submitted,
            dataset,
            task_ref,
            input_snapshot_id,
            expected_input_sha256=input_sha256,
            request=request,
            facts=facts,
        )

    async def query(
        self,
        dataset: PortfolioAnalyticsDatasetV1,
        facts: PortfolioAnalyticsFactsV1,
        task_ref: str,
    ) -> dict[str, Any]:
        input_snapshot_id = self._input_for_task(task_ref, dataset)
        result = self._require_success(
            await self._call(
                "query_portfolio_analytics_task", self._scope_ref, task_ref
            )
        )
        return self._task_payload(
            result, dataset, task_ref, input_snapshot_id, facts=facts
        )

    async def cancel(
        self,
        dataset: PortfolioAnalyticsDatasetV1,
        facts: PortfolioAnalyticsFactsV1,
        task_ref: str,
    ) -> dict[str, Any]:
        input_snapshot_id = self._input_for_task(task_ref, dataset)
        result = self._require_success(
            await self._call(
                "cancel_portfolio_analytics_task", self._scope_ref, task_ref
            )
        )
        return self._task_payload(
            result, dataset, task_ref, input_snapshot_id, facts=facts
        )

    def dataset_ref_for_task(self, task_ref: str) -> str:
        """Extract and verify the owner/version-bound dataset selector in a task ref."""

        row = self._membership
        owner_tag = _digest(self._owner_subject)[:12]
        portfolio_tag = _digest(row.portfolio_ref)[:12]
        prefix = (
            f"afi1:{owner_tag}:{portfolio_tag}:v{row.membership_version}:"
            f"{row.membership_sha256[:12]}:"
        )
        if type(task_ref) is not str or not task_ref.startswith(prefix):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        match = _TASK_SUFFIX.fullmatch(task_ref[len(prefix) :])
        if match is None:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        return f"afi1d:{match.group(1)}"

    def _validate_dataset(
        self, dataset: PortfolioAnalyticsDatasetV1, facts: PortfolioAnalyticsFactsV1
    ) -> None:
        row = self._membership
        if (
            dataset.owner_subject != self._owner_subject
            or dataset.portfolio_ref != row.portfolio_ref
            or dataset.membership_version != row.membership_version
            or dataset.membership_sha256 != row.membership_sha256
            or dataset.source_type != row.source_type
            or dataset.source_trust != "USER_SUPPLIED_OFFLINE"
            or facts.portfolio_ref != row.portfolio_ref
            or facts.source_mode != row.source_type
            or facts.facts_snapshot_ref != dataset.facts_snapshot_ref
            or facts.source_ref != dataset.source_ref
            or facts.source_version != dataset.source_version
            or facts.source_generation != dataset.source_generation
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_DATASET_NOT_FOUND", 404)

    async def _call(self, method_name: str, *args: Any) -> Any:
        method = getattr(self._worker, method_name, None)
        if not callable(method) or not inspect.iscoroutinefunction(method):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_WORKER_UNAVAILABLE", 503)
        try:
            return await method(*args)
        except Exception as error:  # noqa: BLE001 - expose only stable worker codes
            code = getattr(error, "code", None)
            if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
                raise PortfolioAnalyticsV1TaskError(code, _worker_status(code)) from None
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_WORKER_FAILED", 503) from None

    def _task_identity(self, dataset_ref: str, idempotency_key: str) -> tuple[str, str]:
        row = self._membership
        dataset_tag = _dataset_tag(dataset_ref)
        key_tag = _digest(idempotency_key)[:20]
        owner_tag = _digest(self._owner_subject)[:12]
        portfolio_tag = _digest(row.portfolio_ref)[:12]
        membership_tag = row.membership_sha256[:12]
        version_tag = f"v{row.membership_version}"
        identity = (
            f"{owner_tag}:{portfolio_tag}:{version_tag}:{membership_tag}:"
            f"{dataset_tag}:{key_tag}"
        )
        task_ref = f"afi1:{identity}"
        input_snapshot_id = f"afi1-input:{identity}"
        if len(task_ref) > 128 or len(input_snapshot_id) > 128:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REFERENCE_INVALID", 422)
        return task_ref, input_snapshot_id

    def _input_for_task(
        self, task_ref: str, dataset: PortfolioAnalyticsDatasetV1
    ) -> str:
        row = self._membership
        owner_tag = _digest(self._owner_subject)[:12]
        portfolio_tag = _digest(row.portfolio_ref)[:12]
        prefix = (
            f"afi1:{owner_tag}:{portfolio_tag}:v{row.membership_version}:"
            f"{row.membership_sha256[:12]}:"
        )
        if type(task_ref) is not str or not task_ref.startswith(prefix):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        suffix = task_ref[len(prefix) :]
        match = _TASK_SUFFIX.fullmatch(suffix)
        if match is None or match.group(1) != _dataset_tag(dataset.dataset_ref):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        input_ref = "afi1-input:" + task_ref[len("afi1:") :]
        if len(input_ref) > 128:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_TASK_NOT_FOUND", 404)
        return input_ref

    def _require_success(self, value: object) -> Mapping[str, Any]:
        if type(value) is not dict or set(value) != {"ok", "code", "result"}:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if type(value["ok"]) is not bool or type(value["code"]) is not str:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if value["ok"] is False:
            if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value["code"]) is None:
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
            if value["code"] == "TASK_NOT_FOUND":
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_TASK_NOT_FOUND", 404)
            raise PortfolioAnalyticsV1TaskError(value["code"], _worker_status(value["code"]))
        if value["code"] != "OK" or type(value["result"]) is not dict:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        return value["result"]

    @staticmethod
    def _validate_input_result(
        value: Mapping[str, Any],
        input_snapshot_id: str,
        dataset: PortfolioAnalyticsDatasetV1,
    ) -> str:
        if set(value) != {"input_snapshot_id", "input_sha256", "source_mode", "created_ns"}:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if (
            value["input_snapshot_id"] != input_snapshot_id
            or value["source_mode"] != dataset.source_type
            or type(value["input_sha256"]) is not str
            or _SHA256.fullmatch(value["input_sha256"]) is None
            or value["input_sha256"] != dataset.facts_sha256
            or type(value["created_ns"]) is not int
            or value["created_ns"] <= 0
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        return value["input_sha256"]

    def _task_payload(
        self,
        value: Mapping[str, Any],
        dataset: PortfolioAnalyticsDatasetV1,
        task_ref: str,
        input_snapshot_id: str,
        *,
        expected_input_sha256: str | None = None,
        request: dict[str, Any] | None = None,
        facts: PortfolioAnalyticsFactsV1,
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
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if (
            value["task_ref"] != task_ref
            or value["input_snapshot_id"] != input_snapshot_id
            or type(value["state"]) is not str
            or value["state"] not in _TASK_STATES
            or type(value["input_sha256"]) is not str
            or _SHA256.fullmatch(value["input_sha256"]) is None
            or value["input_sha256"] != dataset.facts_sha256
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
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        state = value["state"]
        detail_code = value["detail_code"]
        result = value["result"]
        if (
            (state in {"pending", "running", "succeeded", "cancelled"} and detail_code is not None)
            or (state in {"pending", "running", "failed", "cancelled", "expired"} and result is not None)
            or (state in {"failed", "unavailable", "expired"} and detail_code is None)
            or (state == "expired" and detail_code != "TASK_EXPIRED")
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if value["result"] is not None:
            self._require_finite_json(value["result"])
            self._validate_report(
                value["result"],
                dataset,
                facts,
                request=request,
                state=value["state"],
                detail_code=value["detail_code"],
            )
        elif value["state"] in {"succeeded", "unavailable"}:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        row = self._membership
        return {
            "task_ref": task_ref,
            "portfolio_ref": row.portfolio_ref,
            "membership_version": row.membership_version,
            "membership_sha256": row.membership_sha256,
            "dataset_ref": dataset.dataset_ref,
            "source_trust": dataset.source_trust,
            "input_snapshot_id": input_snapshot_id,
            "input_sha256": value["input_sha256"],
            "state": value["state"],
            "detail_code": value["detail_code"],
            "created_ns": str(value["created_ns"]),
            "state_ns": str(value["state_ns"]),
            "result": value["result"],
        }

    def _validate_report(
        self,
        report: dict[str, Any],
        dataset: PortfolioAnalyticsDatasetV1,
        facts: PortfolioAnalyticsFactsV1,
        *,
        request: dict[str, Any] | None,
        state: str,
        detail_code: str | None,
    ) -> None:
        expected_keys = {
            "beginning",
            "calculation_ref",
            "decimal_policy",
            "ending",
            "external_cashflow_net",
            "facts_snapshot_ref",
            "flow_source",
            "flow_weight_policy",
            "fx_policy",
            "input_sha256",
            "membership",
            "model_profile_ref",
            "portfolio_ref",
            "reason_codes",
            "reporting_currency",
            "return_method",
            "return_ratio",
            "source",
            "status",
            "version",
        }
        if set(report) != expected_keys:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        membership = report["membership"]
        source = report["source"]
        flow = report["flow_source"]
        reason_codes = report["reason_codes"]
        if (
            type(membership) is not dict
            or type(source) is not dict
            or type(flow) is not dict
            or type(reason_codes) is not list
            or any(type(code) is not str for code in reason_codes)
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        start = request["period_start_date_utc"] if request is not None else None
        end = request["period_end_date_utc"] if request is not None else None
        has_facts = report["facts_snapshot_ref"] is not None
        source_values = ("mode", "source_ref", "source_version", "generation")
        flow_values = ("end_cursor", "source_ref", "source_version", "start_cursor")
        if (
            type(report["version"]) is not int
            or report["version"] != 1
            or report["calculation_ref"] != "spot_nav_modified_dietz_v1"
            or report["return_method"] != "MODIFIED_DIETZ_ESTIMATE_V1"
            or report["flow_weight_policy"] != "UTC_CALENDAR_DAY_END_V1"
            or report["fx_policy"] != "IDENTITY_OR_DIRECT_BASE_TO_REPORTING_V1"
            or report["decimal_policy"]
            != (
                "PRECISION_50_EMIN_NEG999999_EMAX_999999_HALF_EVEN_TRAPS_INVALID_"
                "DIVISION_OVERFLOW_QUANTIZE_18_CANONICAL_STRING_V1"
            )
            or report["portfolio_ref"] != self._membership.portfolio_ref
            or type(report["reporting_currency"]) is not str
            or _CURRENCY.fullmatch(report["reporting_currency"]) is None
            or (has_facts and report["facts_snapshot_ref"] != facts.facts_snapshot_ref)
            or (not has_facts and state != "unavailable")
            or (
                not has_facts
                and "PERIOD_TOO_LONG" not in reason_codes
            )
            or type(report["model_profile_ref"]) is not str
            or not report["model_profile_ref"]
            or type(report["status"]) is not str
            or report["status"] != ("AVAILABLE" if state == "succeeded" else "UNAVAILABLE")
            or type(report["reason_codes"]) is not list
            or any(type(code) is not str for code in report["reason_codes"])
            or type(report["input_sha256"]) not in (str, type(None))
            or (
                report["input_sha256"] is not None
                and _SHA256.fullmatch(report["input_sha256"]) is None
            )
            or type(membership) is not dict
            or set(membership) != {"content_sha256", "version"}
            or type(membership.get("content_sha256")) not in (str, type(None))
            or (
                membership.get("content_sha256") is not None
                and _SHA256.fullmatch(membership["content_sha256"]) is None
            )
            or type(membership.get("version")) is not int
            or membership["version"] != self._membership.membership_version
            or type(source) is not dict
            or set(source) != {"generation", "mode", "source_ref", "source_version"}
            or (
                has_facts
                and (
                    source.get("mode") != dataset.source_type
                    or source.get("source_ref") != dataset.source_ref
                    or source.get("source_version") != dataset.source_version
                    or source.get("generation") != dataset.source_generation
                )
            )
            or (not has_facts and any(source.get(name) is not None for name in source_values))
            or type(flow) is not dict
            or set(flow) != {"end_cursor", "source_ref", "source_version", "start_cursor"}
            or (
                has_facts
                and (
                    flow.get("end_cursor") != facts.flow_coverage.end_cursor
                    or flow.get("source_ref") != facts.flow_coverage.source_ref
                    or flow.get("source_version") != facts.flow_coverage.source_version
                    or flow.get("start_cursor") != facts.flow_coverage.start_cursor
                )
            )
            or (not has_facts and any(flow.get(name) is not None for name in flow_values))
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        for name, point, expected_date in (
            ("beginning", facts.beginning, start),
            ("ending", facts.ending, end),
        ):
            value = report[name]
            report_date = value.get("date_utc") if type(value) is dict else None
            if (
                type(value) is not dict
                or set(value)
                != {"as_of_ns", "date_utc", "nav", "native_values", "snapshot_ref", "source_cursor"}
                or (value.get("date_utc") is not None and not self._is_iso_date(report_date))
                or (expected_date is not None and value.get("date_utc") != expected_date)
                or (
                    expected_date is None
                    and state == "succeeded"
                    and value.get("date_utc") != point.valuation_date_utc
                )
                or (
                    has_facts
                    and (
                        value.get("as_of_ns") != point.as_of_ns
                        or value.get("snapshot_ref") != point.snapshot_ref
                        or value.get("source_cursor") != point.source_cursor
                    )
                )
                or (
                    not has_facts
                    and any(
                        value.get(field) is not None
                        for field in ("as_of_ns", "snapshot_ref", "source_cursor")
                    )
                )
                or not self._optional_decimal(value.get("nav"))
                or type(value.get("native_values")) is not list
                or any(
                    type(item) is not dict
                    or set(item) != {"currency", "value"}
                    or type(item.get("currency")) is not str
                    or not self._decimal_or_none(item.get("value"))
                    for item in value["native_values"]
                )
            ):
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if not self._decimal_or_none(report["external_cashflow_net"]) or not self._decimal_or_none(
            report["return_ratio"]
        ):
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if request is not None and report["reporting_currency"] != request["reporting_currency"]:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if has_facts and membership.get("content_sha256") != facts.membership.content_sha256:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if not has_facts and membership.get("content_sha256") is not None:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if report["status"] == "AVAILABLE":
            if (
                report["input_sha256"] is None
                or not report["reason_codes"] == []
                or report["beginning"]["nav"] is None
                or report["ending"]["nav"] is None
                or report["return_ratio"] is None
                or report["external_cashflow_net"] is None
            ):
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        else:
            if (
                state != "unavailable"
                or not reason_codes
                or reason_codes != sorted(set(reason_codes))
            ):
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
            if report["input_sha256"] is None and "PERIOD_TOO_LONG" not in reason_codes:
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
            if detail_code != reason_codes[0]:
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)

    @staticmethod
    def _optional_decimal(value: object) -> bool:
        return value is None or PortfolioAnalyticsV1TaskService._decimal_or_none(value)

    @staticmethod
    def _is_iso_date(value: object) -> bool:
        if type(value) is not str:
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False

    @staticmethod
    def _decimal_or_none(value: object) -> bool:
        if value is None:
            return True
        if type(value) is not str:
            return False
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError):
            return False
        return parsed.is_finite() and _canonical_decimal(parsed) == value

    @classmethod
    def _require_finite_json(cls, value: object, *, depth: int = 0) -> None:
        if depth > 32:
            raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
        if value is None or type(value) in {str, bool, int}:
            return
        if type(value) is float:
            import math

            if not math.isfinite(value):
                raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)
            return
        if type(value) is list:
            for item in value:
                cls._require_finite_json(item, depth=depth + 1)
            return
        if type(value) is dict and all(type(key) is str for key in value):
            for item in value.values():
                cls._require_finite_json(item, depth=depth + 1)
            return
        raise PortfolioAnalyticsV1TaskError("ANALYTICS_REPLY_INVALID", 503)


def _dataset_tag(dataset_ref: str) -> str:
    if type(dataset_ref) is not str or not dataset_ref.startswith("afi1d:"):
        raise PortfolioAnalyticsV1TaskError("ANALYTICS_DATASET_NOT_FOUND", 404)
    tag = dataset_ref[len("afi1d:") :]
    if re.fullmatch(r"[0-9a-f]{24}", tag) is None:
        raise PortfolioAnalyticsV1TaskError("ANALYTICS_DATASET_NOT_FOUND", 404)
    return tag


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _worker_status(code: str) -> int:
    if code in {"TASK_QUOTA_EXCEEDED", "QUEUE_FULL"}:
        return 429
    if code in {"TASK_NOT_FOUND", "INPUT_NOT_FOUND"}:
        return 404
    if code in {
        "TASK_REF_CONFLICT",
        "INPUT_ALREADY_COMPLETE",
        "TASK_TERMINAL",
        "TASK_CLEANUP_REQUIRED",
    }:
        return 409
    if code.startswith("INVALID_") or code in {
        "SOURCE_MODE_NOT_ALLOWED",
        "INPUT_LIMIT_EXCEEDED",
        "INPUT_PORTFOLIO_MISMATCH",
    }:
        return 422
    return 503
