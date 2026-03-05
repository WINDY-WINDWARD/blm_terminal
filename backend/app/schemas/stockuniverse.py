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
    lastUpdateTime: datetime

    @field_validator('lastUpdateTime', mode='before')
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, datetime):
            return v
        return datetime.strptime(v, '%d-%b-%Y %H:%M:%S')
    
    @field_validator('industryInfo', mode='before')
    @classmethod
    def parse_industry_info(cls, v):
        if isinstance(v, dict):
            return v
        return {}