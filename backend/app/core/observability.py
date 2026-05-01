from collections import Counter
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class ApiMetrics:
    request_volume: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    status_counts: Counter[int] = field(default_factory=Counter)


@dataclass
class WorkerMetrics:
    completed_jobs: int = 0
    failed_jobs: int = 0
    timeout_jobs: int = 0


@dataclass
class EmailMetrics:
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0


api_metrics = ApiMetrics()
worker_metrics = WorkerMetrics()
email_metrics = EmailMetrics()


def monotonic_ms() -> float:
    return perf_counter() * 1000


def reset_observability_metrics() -> None:
    api_metrics.request_volume = 0
    api_metrics.error_count = 0
    api_metrics.total_latency_ms = 0.0
    api_metrics.max_latency_ms = 0.0
    api_metrics.status_counts.clear()
    worker_metrics.completed_jobs = 0
    worker_metrics.failed_jobs = 0
    worker_metrics.timeout_jobs = 0
    email_metrics.attempted = 0
    email_metrics.succeeded = 0
    email_metrics.failed = 0


def record_api_request(status_code: int, latency_ms: float) -> None:
    api_metrics.request_volume += 1
    api_metrics.total_latency_ms += latency_ms
    api_metrics.max_latency_ms = max(api_metrics.max_latency_ms, latency_ms)
    api_metrics.status_counts[status_code] += 1
    if status_code >= 500:
        api_metrics.error_count += 1


def record_api_exception(latency_ms: float) -> None:
    record_api_request(500, latency_ms)


def record_worker_job(status: str) -> None:
    worker_metrics.completed_jobs += 1
    if status == "failed":
        worker_metrics.failed_jobs += 1
    if status == "timeout":
        worker_metrics.timeout_jobs += 1


def record_email_delivery(success: bool) -> None:
    email_metrics.attempted += 1
    if success:
        email_metrics.succeeded += 1
    else:
        email_metrics.failed += 1


def api_snapshot() -> dict:
    average_latency = api_metrics.total_latency_ms / api_metrics.request_volume if api_metrics.request_volume else 0.0
    error_rate = api_metrics.error_count / api_metrics.request_volume if api_metrics.request_volume else 0.0
    return {
        "request_volume": api_metrics.request_volume,
        "error_count": api_metrics.error_count,
        "error_rate": round(error_rate, 4),
        "average_latency_ms": round(average_latency, 2),
        "max_latency_ms": round(api_metrics.max_latency_ms, 2),
        "status_counts": {str(code): count for code, count in sorted(api_metrics.status_counts.items())},
    }


def worker_snapshot(queued_jobs: int, running_jobs: int, failed_jobs: int, total_jobs: int) -> dict:
    terminal_jobs = max(total_jobs - queued_jobs - running_jobs, 0)
    failure_rate = failed_jobs / terminal_jobs if terminal_jobs else 0.0
    return {
        "queue_backlog": queued_jobs,
        "running_jobs": running_jobs,
        "failed_jobs": failed_jobs,
        "completed_jobs_observed": worker_metrics.completed_jobs,
        "failed_jobs_observed": worker_metrics.failed_jobs,
        "timeout_jobs_observed": worker_metrics.timeout_jobs,
        "job_failure_rate": round(failure_rate, 4),
    }


def email_snapshot() -> dict:
    failure_rate = email_metrics.failed / email_metrics.attempted if email_metrics.attempted else 0.0
    return {
        "attempted": email_metrics.attempted,
        "succeeded": email_metrics.succeeded,
        "failed": email_metrics.failed,
        "failure_rate": round(failure_rate, 4),
    }


def build_alerts(api: dict, worker: dict, email: dict, database: dict, storage: dict) -> list[dict]:
    alerts: list[dict] = []
    if api["error_rate"] >= 0.05:
        alerts.append({"name": "critical_api_error_rate", "severity": "critical", "status": "firing"})
    if api["max_latency_ms"] >= 2000:
        alerts.append({"name": "critical_api_latency", "severity": "warning", "status": "firing"})
    if worker["queue_backlog"] >= 100:
        alerts.append({"name": "critical_worker_queue_backlog", "severity": "critical", "status": "firing"})
    if worker["job_failure_rate"] >= 0.2:
        alerts.append({"name": "critical_worker_failure_rate", "severity": "critical", "status": "firing"})
    if email["failure_rate"] >= 0.1:
        alerts.append({"name": "critical_email_failure_rate", "severity": "warning", "status": "firing"})
    if database.get("health") != "healthy":
        alerts.append({"name": "critical_database_health", "severity": "critical", "status": "firing"})
    if storage.get("health") != "healthy":
        alerts.append({"name": "critical_storage_health", "severity": "critical", "status": "firing"})
    if not alerts:
        alerts.append({"name": "all_clear", "severity": "info", "status": "ok"})
    return alerts
