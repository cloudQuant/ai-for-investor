from pydantic import BaseModel, ConfigDict
from typing import Optional


class UserPreferenceUpdate(BaseModel):
    ui_theme: Optional[str] = None
    system_theme_sync: Optional[bool] = None


class UserPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    ui_theme: str
    system_theme_sync: bool
