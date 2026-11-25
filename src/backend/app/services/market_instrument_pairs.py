"""FX and crypto symbol normalization helpers."""

from __future__ import annotations


def fx_pair_legs(symbol: str) -> tuple[str, str] | None:
    """Split onshore/offshore FX codes into two three-character currency legs."""
    code = symbol.upper()
    if len(code) == 7 and code.endswith("C"):
        code = code[:-1]
    if len(code) != 6 or not code.isalpha():
        return None
    return code[:3], code[3:]


def crypto_pair_code(symbol: str) -> str:
    """Normalise BTC-USDT / BTC/USDT / btcusdt to BTCUSDT."""
    return "".join(character for character in symbol.upper() if character.isalnum())
