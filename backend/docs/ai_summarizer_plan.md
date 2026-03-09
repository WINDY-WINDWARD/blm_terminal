# AI Summarizer Service Plan

## Overview

A new backend service that uses **llama-cpp-python** with a **Gemma 3 4B** GGUF model to summarize financial statements. The service is designed to be:

- **Platform agnostic** — works on macOS, Linux, Windows
- **Self-contained** — downloads model automatically at startup
- **Memory efficient** — uses Q4_K_M quantization (~2.7 GB download)
- **Non-blocking** — app starts immediately; AI endpoint returns 503 until model loads

## Target Systems

- **Primary**: macOS with 16 GB RAM (Apple Silicon)
- **Secondary**: Linux/Windows systems with 16+ GB RAM
- **Note**: CPU inference is used; Metal/CUDA acceleration can be enabled via `CMAKE_ARGS` at install time if needed

---

## Dependencies

### New PyPI Packages

| Package | Version | Purpose |
|---------|---------|---------|
| `llama-cpp-python` | `>=0.3.0` | GGUF inference engine |
| `huggingface-hub` | `>=0.24.0` | Model download from HF Hub |

### Rationale

- **llama-cpp-python**: Ships with CPU-only wheels by default on PyPI. Works cross-platform without special build flags. GPU acceleration (Metal on macOS, CUDA on Linux) requires rebuilding with `CMAKE_ARGS`, but CPU inference at Q4_K_M quantization is performant enough for 16 GB systems.
- **huggingface-hub**: Provides `hf_hub_download` for resumable downloads with local caching at `~/.cache/huggingface/`.

---

## Configuration

### New Setting: `app/config.py`

```python
ai_model_path: str | None = None  # optional: path to pre-downloaded GGUF file
```

If `ai_model_path` is set in `.env`, the service uses that local file instead of downloading from HuggingFace.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_MODEL_PATH` | `None` | Optional path to a local GGUF file (skip download) |
| `AI_MAX_TOKENS` | `512` | Default max tokens for summarization |
| `AI_N_CTX` | `8192` | Context window size |

---

## Model Details

### Source

- **Repository**: `bartowski/gemma-3-4b-it-GGUF` (public, no auth required)
- **File**: `gemma-3-4b-it-Q4_K_M.gguf`
- **Size**: ~2.7 GB
- **Quantization**: Q4_K_M (4-bit, K-means optimized, medium)

### Why Gemma 3?

- Instruction-tuned (`it`) — good for chat/completion tasks
- 4B parameters — fits in RAM at Q4_K_M
- GGUF format — native to llama-cpp-python
- Public repo — no `HF_TOKEN` required

### Automatic Download

At startup, the service checks:
1. If `settings.ai_model_path` is set → use that file (skip download)
2. Otherwise → call `hf_hub_download()` which caches in `~/.cache/huggingface/`

Subsequent startups are instant (cached).

---

## Service Implementation

### File: `app/services/ai_summarizer.py`

```python
class AISummarizer:
    """Financial statement summarizer using GGUF inference."""
    
    def __init__(self) -> None:
        self._model_path: str | None = None
        self._llm: Llama | None = None
        self._is_ready: bool = False
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Download (if needed) and load the GGUF model."""
        # 1. Resolve model path (local or download from HF)
        # 2. Load Llama instance with n_ctx=8192
        # 3. Set _is_ready = True
    
    def summarize(self, text: str, max_tokens: int = 512) -> SummaryResult:
        """Run inference on financial text."""
        # 1. Build prompt with financial analysis instructions
        # 2. Call llm.create_completion() in thread pool
        # 3. Parse output and return SummaryResult
    
    def close(self) -> None:
        """Unload model and free memory."""
        # del self._llm; gc.collect()
```

#### Key Design Decisions

- **Thread offloading**: `summarize()` runs `llm.create_completion()` in `asyncio.to_thread()` to avoid blocking the event loop
- **Lazy init**: Model loads in background; `_is_ready` flag controls endpoint availability
- **Prompt template**: Gemma 3 chat format with system instructions for financial analysis
- **Separate prompts file**: Prompt templates are stored in `app/services/prompts.py` for maintainability

#### Prompt Format

The detailed prompt is defined in `app/services/prompts.py` (`FINANCIAL_SUMMARIZER_PROMPT`). It instructs the model to act as a **Senior Equity Research Analyst** and generate reports with:

- Opening Statement: Brief professional assessment
- Executive Summary: High-level overview (Revenue, PAT trends)
- Section 1: Revenue & Income Trends (QoQ/YoY % changes)
- Section 2: Expense Analysis (cost drivers)
- Section 3: Profitability & Margins (Markdown table)
- Section 4: Key Financial Ratios (EBITDA, Net Profit Margins)
- Section 5: Investor Perspective (YoY growth, equity, debt)
- Closing: Offer to calculate additional metrics

Uses **LaTeX** for formulas (e.g., `$\frac{A}{B}$`) and **bold** for key figures.

---

## API Endpoint

### File: `app/routers/ai_summarizer.py`

#### POST `/api/ai/summarize`

**Request Body**:
```json
{
  "text": "Quarterly financial statement text...",
  "max_tokens": 512
}
```

**Response (200)**:
```json
{
  "summary": "Generated summary text...",
  "input_tokens": 1234,
  "output_tokens": 456,
  "model": "gemma-3-4b-it-Q4_K_M.gguf"
}
```

**Error Responses**:
| Status | Condition |
|--------|-----------|
| 400 | Empty or missing `text` field |
| 413 | Input text exceeds ~24,000 characters (token limit) |
| 503 | Model not yet loaded (startup in progress) |
| 500 | Inference error |

---

## Lifespan Integration

### File: `main.py`

#### Startup (Non-Blocking)

```python
from app.services.ai_summarizer import ai_summarizer

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    
    # Start model loading in background (non-blocking)
    load_task = asyncio.create_task(
        asyncio.to_thread(ai_summarizer.initialize)
    )
    
    yield
    
    # ... existing shutdown ...
    
    # Cancel load task if still running
    if not load_task.done():
        load_task.cancel()
        try:
            await load_task
        except asyncio.CancelledError:
            pass
    
    # Clean shutdown
    ai_summarizer.close()
```

**Behavior**:
- App starts immediately and serves all existing endpoints
- `/api/ai/summarize` returns 503 until model finishes loading (~10-30s on first run)
- Subsequent runs are instant (cached model)

#### Clean Shutdown

- Cancel background load task if still pending
- Call `ai_summarizer.close()` to unload model and free memory
- Uses `gc.collect()` for cross-platform memory cleanup

---

## Data Flow

```
HTTP Request
    │
    ▼
app/routers/ai_summarizer.py
    │
    ├──► validate request (400 if empty)
    │
    ├──► check ai_summarizer._is_ready
    │       │
    │       └──► False → return 503
    │
    ▼
app/services/ai_summarizer.summarize()
    │
    ├──► asyncio.to_thread() ──► Llama.create_completion()
    │                               │
    │                               ▼
    │                           GGUF model (Q4_K_M)
    │                               │
    ▼                               │
parse JSON output ◄─────────────────┘
    │
    ▼
SummaryResult (pydantic model)
    │
    ▼
HTTP Response (200)
```

---

## File Changes Summary

| Action | File |
|--------|------|
| Modify | `pyproject.toml` — add `llama-cpp-python`, `huggingface-hub` |
| Modify | `app/config.py` — add `ai_model_path` |
| Create | `app/schemas/ai_summarizer.py` — `SummarizeRequest`, `SummaryResult` |
| Create | `app/services/prompts.py` — `FINANCIAL_SUMMARIZER_PROMPT`, `build_summarizer_prompt()` |
| Create | `app/services/ai_summarizer.py` — `AISummarizer` class |
| Create | `app/routers/ai_summarizer.py` — `POST /api/ai/summarize` |
| Modify | `app/routers/__init__.py` — export `ai_summarizer_router` |
| Modify | `main.py` — lifespan integration |

---

## Testing

### Manual Test

```bash
# Start server (model will download on first run)
uvicorn main:app --reload --port 8000

# Wait for model to load (check logs for "AI summarizer ready")

# Test endpoint
curl -X POST http://127.0.0.1:8000/api/ai/summarize \
  -H "Content-Type: application/json" \
  -d '{"text": "Q3 FY25: Revenue grew 15% YoY to Rs. 5,000 Cr. Net profit up 12%. Strategic risk: regulatory changes in export markets.", "max_tokens": 256}'
```

### Expected Response

```json
{
  "summary": "1. Revenue & Earnings: Q3 FY25 revenue of Rs. 5,000 Cr, up 15% YoY...",
  "input_tokens": 85,
  "output_tokens": 120,
  "model": "gemma-3-4b-it-Q4_K_M.gguf"
}
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| HF download fails | Log error, keep `_is_ready = False`, endpoint returns 503 |
| Llama init fails | Log error, keep `_is_ready = False`, endpoint returns 503 |
| Inference fails | Return 500 with error message |
| Empty text | Return 400 |
| Text too long | Return 413 (cap at ~24,000 chars) |

---

## Performance Considerations

- **First startup**: ~10-30s to download 2.7 GB model
- **Subsequent startups**: Instant (cached in `~/.cache/huggingface/`)
- **Inference speed**: ~20-50 tokens/sec on Apple Silicon (M1/M2/M3)
- **Memory usage**: ~4-5 GB RAM during inference
- **Max input**: ~6,000 tokens (~24,000 chars) with `n_ctx=8192`

---

## Future Enhancements

- [ ] Add Metal acceleration support (via `CMAKE_ARGS` at install time)
- [ ] Add streaming response support
- [ ] Add caching of summaries by input hash
- [ ] Support other GGUF models (via config)
- [ ] Add rate limiting for API endpoint
