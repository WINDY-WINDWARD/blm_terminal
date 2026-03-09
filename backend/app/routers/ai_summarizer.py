"""AI summarizer router."""

import asyncio

from fastapi import APIRouter, HTTPException, Response, status

from app.schemas.ai_summarizer import SummarizeRequest, SummaryResult
from app.services.ai_summarizer import ai_summarizer

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/summarize", response_model=SummaryResult)
async def summarize(request: SummarizeRequest) -> SummaryResult:
    """Summarize a financial statement using AI."""
    if not ai_summarizer.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI summarizer is still loading. Please try again shortly.",
        )

    try:
        result = await asyncio.to_thread(
            ai_summarizer.summarize,
            request.text,
            request.max_tokens,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {e}",
        )


@router.get("/health")
async def ai_health() -> dict[str, str | None]:
    """Check AI summarizer health."""
    return {
        "status": "ready" if ai_summarizer.is_ready else "loading",
        "model": "gemma3-4b-it-Q4_K_M.gguf" if ai_summarizer.is_ready else None,
    }
