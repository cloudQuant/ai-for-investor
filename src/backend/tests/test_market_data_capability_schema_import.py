"""Cold-import FastAPI response-model binding for market-data capabilities."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_capabilities_response_can_bind_to_fastapi_route_on_cold_import(tmp_path: Path) -> None:
    """Register the real capability response model before validation can rebuild it."""
    backend_root = Path(__file__).resolve().parents[1]
    script = r"""
import sys

# Schema loading must not launch commands or contact providers. On Windows,
# platform._syscmd_ver catches OSError and uses sys.getwindowsversion instead;
# this also avoids a machine-level cmd AutoRun recursively activating Conda.
def reject_external_effects(event, args):
    if event in {"subprocess.Popen", "os.system", "socket.connect", "socket.bind"}:
        raise PermissionError("schema-only import forbids external effects")

sys.addaudithook(reject_external_effects)
from fastapi import APIRouter
from app.schemas.market_data_platform import MarketDataCapabilitiesResponse

router = APIRouter()

@router.get(
    "/market-data/capabilities",
    response_model=MarketDataCapabilitiesResponse,
    summary="Read effective market-data rollout capabilities",
)
async def get_market_data_capabilities() -> MarketDataCapabilitiesResponse:
    return {}

assert len(router.routes) == 1
assert router.routes[0].response_model is MarketDataCapabilitiesResponse
"""
    env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(backend_root),
        "DEBUG": "true",
        "DATABASE_URL": "sqlite+aiosqlite://",
        "LOG_DIR": str(tmp_path),
        "BT_API_LOG_DIR": str(tmp_path),
    }
    for name, value in os.environ.items():
        if name.upper().startswith(("CONDA_", "_CONDA", "_CE")):
            env[name] = value
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
