"""Settings sections extracted from :class:`app.config.Settings`.

Each module holds one cohesive section of the application settings as a plain
mixin class. ``app.config`` composes them into the single ``Settings`` model that
the rest of the codebase imports, so no caller changes.
"""

from app.settings.ai_assistant import AiAssistantSettingsMixin
from app.settings.ai_research_v2 import AiResearchV2SettingsMixin
from app.settings.application import ApplicationSettingsMixin
from app.settings.asset_research import AssetResearchSettingsMixin
from app.settings.broker_accounts import BrokerAccountSettingsMixin
from app.settings.database import DatabaseSettingsMixin
from app.settings.market_data import MarketDataSettingsMixin
from app.settings.operations import OperationsSettingsMixin
from app.settings.security_auth import SecurityAuthSettingsMixin
from app.settings.service_deployments import ServiceDeploymentSecretsMixin

__all__ = [
    "AiAssistantSettingsMixin",
    "AiResearchV2SettingsMixin",
    "ApplicationSettingsMixin",
    "AssetResearchSettingsMixin",
    "BrokerAccountSettingsMixin",
    "DatabaseSettingsMixin",
    "MarketDataSettingsMixin",
    "OperationsSettingsMixin",
    "SecurityAuthSettingsMixin",
    "ServiceDeploymentSecretsMixin",
]
