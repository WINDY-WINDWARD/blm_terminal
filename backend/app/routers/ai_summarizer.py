"""AI summarizer router."""

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.schemas.ai_summarizer import AlertDigestResult, AlertSummarizeRequest, SummarizeRequest, SummaryResult
from app.services.ai_summarizer import ai_summarizer
from app.services.ai_config import get_configured_verifier_model

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/summarize", response_model=SummaryResult)
async def summarize(request: SummarizeRequest) -> SummaryResult:
    """Summarize a financial statement using the configured LLM API."""
    is_configured = await ai_summarizer.is_configured()
    if not is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI API key is not configured.",
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


@router.post("/alerts/summarize", response_model=AlertDigestResult)
async def summarize_alerts(request: AlertSummarizeRequest) -> AlertDigestResult:
    """Summarize stock alerts into a structured, decision-ready digest."""
    is_configured = await ai_summarizer.is_configured()
    if not is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI API key is not configured.",
        )

    try:
        alerts_data = [a.model_dump() for a in request.alerts]
        return await ai_summarizer.summarize_alerts(
            symbol=request.symbol,
            alerts=alerts_data,
            max_tokens=request.max_tokens,
        )

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
    if not await ai_summarizer.is_configured():
        return {"status": "unconfigured", "model": None}

    reachable = await ai_summarizer.ping_provider()
    model = await get_configured_verifier_model() if reachable else None
    return {
        "status": "ready" if reachable else "unreachable",
        "model": model,
    }
