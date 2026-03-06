"""stockuniverse schema for NSE India stock universe data."""
from datetime import datetime
from pydantic import BaseModel, field_validator

class StockUniverse(BaseModel):
    """Pydantic schema for NSE India stock universe data."""
    symbol: str
    companyName: str
    segment: str
    industry: str
    sectorPE: float | None
    symbolPE: float | None
    industryInfo: dict[str, str]
    lastUpdateTime: datetime | None

    @field_validator('sectorPE', 'symbolPE', mode='before')
    @classmethod
    def parse_pe(cls, v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @field_validator('lastUpdateTime', mode='before')
    @classmethod
    def parse_datetime(cls, v: object) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        try:
            return datetime.strptime(str(v), '%d-%b-%Y %H:%M:%S')
        except (ValueError, TypeError):
            return None
    
    @field_validator('industryInfo', mode='before')
    @classmethod
    def parse_industry_info(cls, v):
        if isinstance(v, dict):
            return v
        return {}