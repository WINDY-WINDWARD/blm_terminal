"""corporate filings schema for NSE India stock corporate filings."""

from datetime import datetime

from pydantic import BaseModel


class CorporateFilingRecord(BaseModel):
    """Pydantic schema representing a cached corporate filing entry."""

    symbol: str
    csv_data: str
    last_fetched_at: datetime

    model_config = {"from_attributes": True}
