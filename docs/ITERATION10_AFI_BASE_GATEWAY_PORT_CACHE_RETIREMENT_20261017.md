# AFI Base Gateway port-cache cleanup

AFI `dev` at parent `b637c2eb5e325a3352a9c4828b2dbef4bd46d64a` removes the dead
`manual.py::_release_gateway_zmq_ports` helper and its four legacy-runtime
call sites. This was the remaining literal AFI import of
`bt_api_base.gateway.config`; public credential-based connect/disconnect and
the strategy legacy launch boundary already fail closed. The no-Gateway
strategy environment builder in `gateway/runtime.py` remains for ordinary
offline/research use. ServiceV2 and Paper paths are outside this change.

Focused evidence: `tests/test_gateway_base_retirement.py::test_offline_gateway_runtime_helpers_work_without_base_gateway`
passed once in the AFI Python 3.12.10 venv. Its isolated child blocks all
`bt_api_base.gateway` imports, imports the AFI manual/runtime modules, and builds
an ordinary no-Gateway strategy environment. Ruff passed for the changed source
and test. Independent static review returned GO_STATIC; the reviewer did not
run tests or a Host. No live provider/account or Host acceptance is claimed.
