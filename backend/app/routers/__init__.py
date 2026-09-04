"""FastAPI router registry."""

from app.routers.ai_chat import router as ai_chat_router
from app.routers.ai_picks import router as ai_picks_router
from app.routers.ai_summarizer import router as ai_summarizer_router
from app.routers.announcements import router as announcements_router
from app.routers.breakouts import router as breakouts_router
from app.routers.corporatefilings import router as filings_router
from app.routers.jobs import router as jobs_router
from app.routers.markets import router as markets_router
from app.routers.morningstar import router as morningstar_router
from app.routers.nonpersistence import router as market_router
from app.routers.news import router as news_router
from app.routers.news_ws import router as news_ws_router
from app.routers.notifications import router as notifications_router
from app.routers.screener import router as screener_router
from app.routers.iinvest import router as iinvest_router
from app.routers.system_config import router as system_config_router
from app.routers.stockuniverse import router as stockuniverse_router, errors_router as stockuniverse_errors_router
from app.routers.portfolio import router as portfolio_router
from app.routers.valuation import router as valuation_router
from app.routers.watchlist import router as watchlist_router
from app.routers.layout import router as layout_router

from app.routers.auth import router as auth_router
from app.routers.gemini_auth import router as gemini_auth_router
from app.routers.users import router as users_router

__all__ = [
    "ai_chat_router",
    "ai_picks_router",
    "ai_summarizer_router",
    "announcements_router",
    "breakouts_router",
    "filings_router",
    "jobs_router",
    "markets_router",
    "morningstar_router",
    "market_router",
    "news_router",
    "news_ws_router",
    "notifications_router",
    "screener_router",
    "iinvest_router",
    "system_config_router",
    "stockuniverse_router",
    "stockuniverse_errors_router",
    "valuation_router",
    "portfolio_router",
    "watchlist_router",
    "layout_router",
    "auth_router",
    "gemini_auth_router",
    "users_router",
]
