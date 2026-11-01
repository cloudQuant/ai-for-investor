from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


def test_offline_gateway_runtime_helpers_work_without_base_gateway(tmp_path):
    backend_root = Path(__file__).resolve().parents[1]
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys
        from pathlib import Path

        class RejectBaseGateway(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "bt_api_base.gateway" or fullname.startswith("bt_api_base.gateway."):
                    raise AssertionError("retired Base Gateway import attempted")
                return None

        sys.meta_path.insert(0, RejectBaseGateway())

        from app.services.gateway import manual, runtime

        assert not hasattr(manual, "_release_gateway_zmq_ports")
        runtime._refresh_runtime_asset_specs = lambda *_args: None
        acquired = []

        def no_gateway(*_args, **_kwargs):
            acquired.append(True)
            return None

        env = runtime.build_subprocess_env(
            instance_id="offline-strategy",
            instance={},
            strategy_dir=Path.cwd() / "offline-strategy",
            acquire_gateway_for_instance=no_gateway,
            os_environ={},
            bt_api_py_dir=None,
            backtrader_dir=None,
        )
        assert acquired == [True]
        assert env["BT_TRADING_INSTANCE_ID"] == "offline-strategy"
        assert "BT_GATEWAY_COMMAND_ENDPOINT" not in env
        """
    )
    environment = os.environ.copy()
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
