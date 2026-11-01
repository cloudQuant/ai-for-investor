# Iteration10 AFI08 reduction CURVE key repair

Repository: ai-for-investor, existing dev checkout. Base: `090552b062f81b76e20e203e584dbe009e56c9e1`.

The reduction client decoded configured CURVE keys to 32 raw bytes, while the SDK client credentials require the 40-byte Z85 form. `_z85_bytes` now validates by decoding and returns the original ASCII encoding. Invalid lengths and invalid Z85 characters remain rejected.

Root focused regression: `tests/test_strategy_reduction_control.py::test_reduction_curve_keys_remain_z85_encoded_for_transport`, 1 passed, pytest exit 0, 1.57 seconds. It checks generated synthetic keys against the real SDK credentials constructor and rejects invalid values, without network or Host startup. Source hashes matched before and after. Raw evidence: `D:/temp/afi08-z85-key-unit-r2-20261017/` (stdout, stderr, JUnit, exit and source pins). The earlier unit attempt stopped during collection because PYTHONPATH omitted Base; its output is preserved separately.

This accepts the key-conversion component only. The prior HTTP Host R11 failed REQUIRED_REGISTRATION_FAILED and remains preserved; a new HTTP acceptance is still required. No formal AFI08 PASS is claimed.
