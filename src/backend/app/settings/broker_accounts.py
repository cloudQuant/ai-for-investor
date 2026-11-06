"""CTP, MT5, IB, Binance and OKX account credential settings.

Trading-gateway credentials read from ``.env`` for form pre-fill: CTP, MT5,
IB (web/paper/live), Binance and OKX.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field


class BrokerAccountSettingsMixin:
    """CTP, MT5, IB, Binance and OKX account credential settings."""

    # CTP credentials (read from .env for form pre-fill)
    CTP_BROKER_ID: str = Field(default="", description="CTP broker ID")

    CTP_USER_ID: str = Field(default="", description="CTP user/investor ID")

    CTP_INVESTOR_ID: str = Field(default="", description="CTP investor ID")

    CTP_PASSWORD: str = Field(default="", description="CTP password")

    CTP_APP_ID: str = Field(default="simnow_client_test", description="CTP app ID")

    CTP_AUTH_CODE: str = Field(default="0000000000000000", description="CTP auth code")

    # MT5 credentials
    MT5_LOGIN: str = Field(default="", description="MT5 login")

    MT5_PASSWORD: str = Field(default="", description="MT5 password")

    MT5_SERVER: str = Field(default="", description="MT5 server name")

    MT5_WS_URI: str = Field(default="", description="MT5 WebSocket URI")

    MT5_DEMO_LOGIN: str = Field(default="", description="MT5 demo login")

    MT5_DEMO_PASSWORD: str = Field(default="", description="MT5 demo password")

    MT5_DEMO_SERVER: str = Field(default="", description="MT5 demo server name")

    MT5_DEMO_WS_URI: str = Field(default="", description="MT5 demo WebSocket URI")

    MT5_LIVE_LOGIN: str = Field(default="", description="MT5 live login")

    MT5_LIVE_PASSWORD: str = Field(default="", description="MT5 live password")

    MT5_LIVE_SERVER: str = Field(default="", description="MT5 live server name")

    MT5_LIVE_WS_URI: str = Field(default="", description="MT5 live WebSocket URI")

    MT5_SYMBOL_SUFFIX: str = Field(default="", description="MT5 symbol suffix")

    MT5_TIMEOUT: float = Field(default=60.0, description="MT5 request timeout in seconds")

    # IB Web credentials
    IB_ACCOUNT_ID: str = Field(default="", description="IB account ID")

    IB_ASSET_TYPE: str = Field(default="STK", description="IB asset type")

    IB_BASE_URL: str = Field(default="https://localhost:5000", description="IB Web base URL")

    IB_ACCESS_TOKEN: str = Field(default="", description="IB access token")

    IB_VERIFY_SSL: bool = Field(default=True, description="IB Web verify SSL")

    IB_TIMEOUT: float = Field(default=10.0, description="IB Web request timeout in seconds")

    IB_COOKIE_SOURCE: str = Field(default="", description="IB Web cookie source")

    IB_COOKIE_BROWSER: str = Field(default="chrome", description="IB Web cookie browser")

    IB_COOKIE_PATH: str = Field(default="/sso", description="IB Web cookie path")

    IB_USERNAME: str = Field(default="", description="IB Web username")

    IB_PASSWORD: str = Field(default="", description="IB Web password")

    IB_LOGIN_BROWSER: str = Field(default="chrome", description="IB Web login browser")

    IB_LOGIN_HEADLESS: bool = Field(default=False, description="IB Web login headless")

    IB_LOGIN_TIMEOUT: int = Field(default=180, description="IB Web login timeout in seconds")

    IB_COOKIE_OUTPUT: str = Field(default="", description="IB Web cookie output path")

    IB_WEB_ACCOUNT_ID: str = Field(default="", description="IB Web account ID")

    IB_WEB_ASSET_TYPE: str = Field(default="", description="IB Web asset type")

    IB_WEB_BASE_URL: str = Field(default="", description="IB Web base URL override")

    IB_WEB_ACCESS_TOKEN: str = Field(default="", description="IB Web access token override")

    IB_WEB_VERIFY_SSL: bool = Field(default=True, description="IB Web verify SSL override")

    IB_WEB_TIMEOUT: float = Field(default=0.0, description="IB Web request timeout override")

    IB_WEB_COOKIE_SOURCE: str = Field(default="", description="IB Web cookie source override")

    IB_WEB_COOKIE_BROWSER: str = Field(default="", description="IB Web cookie browser override")

    IB_WEB_COOKIE_PATH: str = Field(default="", description="IB Web cookie path override")

    IB_WEB_USERNAME: str = Field(default="", description="IB Web username override")

    IB_WEB_PASSWORD: str = Field(default="", description="IB Web password override")

    IB_WEB_LOGIN_MODE: str = Field(default="", description="IB Web login mode override")

    IB_WEB_LOGIN_BROWSER: str = Field(default="", description="IB Web login browser override")

    IB_WEB_LOGIN_HEADLESS: bool = Field(default=False, description="IB Web login headless override")

    IB_WEB_LOGIN_TIMEOUT: int = Field(default=0, description="IB Web login timeout override")

    IB_WEB_COOKIE_OUTPUT: str = Field(default="", description="IB Web cookie output override")

    IB_PAPER_ACCOUNT_ID: str = Field(default="", description="IB paper account ID")

    IB_PAPER_ASSET_TYPE: str = Field(default="", description="IB paper asset type")

    IB_PAPER_BASE_URL: str = Field(default="", description="IB paper base URL")

    IB_PAPER_ACCESS_TOKEN: str = Field(default="", description="IB paper access token")

    IB_PAPER_VERIFY_SSL: bool = Field(default=True, description="IB paper verify SSL")

    IB_PAPER_TIMEOUT: float = Field(default=0.0, description="IB paper request timeout in seconds")

    IB_PAPER_COOKIE_SOURCE: str = Field(default="", description="IB paper cookie source")

    IB_PAPER_COOKIE_BROWSER: str = Field(default="", description="IB paper cookie browser")

    IB_PAPER_COOKIE_PATH: str = Field(default="", description="IB paper cookie path")

    IB_LIVE_ACCOUNT_ID: str = Field(default="", description="IB live account ID")

    IB_LIVE_ASSET_TYPE: str = Field(default="", description="IB live asset type")

    IB_LIVE_BASE_URL: str = Field(default="", description="IB live base URL")

    IB_LIVE_ACCESS_TOKEN: str = Field(default="", description="IB live access token")

    IB_LIVE_VERIFY_SSL: bool = Field(default=True, description="IB live verify SSL")

    IB_LIVE_TIMEOUT: float = Field(default=0.0, description="IB live request timeout in seconds")

    IB_LIVE_COOKIE_SOURCE: str = Field(default="", description="IB live cookie source")

    IB_LIVE_COOKIE_BROWSER: str = Field(default="", description="IB live cookie browser")

    IB_LIVE_COOKIE_PATH: str = Field(default="", description="IB live cookie path")

    # Binance credentials
    BINANCE_ACCOUNT_ID: str = Field(default="", description="Binance account identifier")

    BINANCE_ASSET_TYPE: str = Field(default="SWAP", description="Binance asset type")

    BINANCE_API_KEY: str = Field(default="", description="Binance API key")

    BINANCE_SECRET_KEY: str = Field(default="", description="Binance secret key")

    BINANCE_TESTNET: bool = Field(default=False, description="Binance testnet flag")

    BINANCE_BASE_URL: str = Field(default="", description="Binance REST base URL")

    # OKX credentials
    OKX_ACCOUNT_ID: str = Field(default="", description="OKX account identifier")

    OKX_ASSET_TYPE: str = Field(default="SWAP", description="OKX asset type")

    OKX_API_KEY: str = Field(default="", description="OKX API key")

    OKX_SECRET_KEY: str = Field(default="", description="OKX secret key")

    OKX_PASSPHRASE: str = Field(default="", description="OKX passphrase")

    OKX_TESTNET: bool = Field(default=False, description="OKX testnet flag")

    OKX_BASE_URL: str = Field(default="", description="OKX REST base URL")
