"""AI summarizer router."""

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.schemas.ai_summarizer import SummarizeRequest, SummaryResult
from app.services.ai_summarizer import ai_summarizer

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/summarize", response_model=SummaryResult)
async def summarize(request: SummarizeRequest) -> SummaryResult:
    """Summarize a financial statement using the configured LLM API."""
    if not ai_summarizer.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI API key is not configured. Set AI_API_KEY in .env.",
        )

    try:
        return await ai_summarizer.summarize(request.text, request.max_tokens)

    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {exc}",
        )


@router.get("/health")
async def ai_health() -> dict[str, str | None]:
    """Ping the configured LLM provider and report connectivity status."""
    if not ai_summarizer.is_configured:
        return {"status": "unconfigured", "model": None}

    reachable = await ai_summarizer.ping_provider()
    return {
        "status": "ready" if reachable else "unreachable",
        "model": settings.ai_model if reachable else None,
    }
