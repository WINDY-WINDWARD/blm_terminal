"""AI Summarizer service using llama-cpp-python with Gemma 3 GGUF."""

import gc
import logging
import os
from pathlib import Path

from llama_cpp import Llama

from app.config import settings
from app.schemas.ai_summarizer import SummaryResult
from app.services.prompts import build_summarizer_prompt

logger = logging.getLogger("app.services.ai_summarizer")
logger.setLevel(logging.DEBUG)

_MODEL_URL = "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf?download=true"
_MODEL_FILENAME = "gemma3-4b-it-Q4_K_M.gguf"
_MAX_INPUT_CHARS = 24000


class AISummarizer:
    """Financial statement summarizer using GGUF inference."""

    def __init__(self) -> None:
        self._model_path: str | None = None
        self._llm: Llama | None = None
        self._is_ready: bool = False
        self._model_name = _MODEL_FILENAME

    @property
    def is_ready(self) -> bool:
        """Check if model is loaded and ready."""
        return self._is_ready

    def _resolve_model_path(self) -> str:
        """Resolve model path: use local path if set, otherwise download from HF."""
        import requests
        
        if settings.ai_model_path:
            path = Path(settings.ai_model_path).resolve()
            print(f">>> Checking AI_MODEL_PATH: {path}")
            if path.is_dir():
                gguf_files = list(path.glob("*.gguf"))
                if gguf_files:
                    model_file = gguf_files[0]
                    logger.info(f"Using local AI model from directory: {model_file}")
                    print(f">>> Found GGUF file: {model_file}")
                    return str(model_file)
                logger.warning(f"No .gguf files found in {path}, will download from HF")
            elif path.exists() and path.is_file():
                logger.info(f"Using local AI model: {path}")
                print(f">>> Using local AI model: {path}")
                return str(path)
            else:
                logger.warning(f"AI_MODEL_PATH set but file not found: {path}, will download from HF")
                print(f">>> AI_MODEL_PATH not found: {path}, will download")

        # Download directly from HuggingFace
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Use the file ID from the URL path
        downloaded_path = cache_dir / f"models--unsloth--gemma-3-4b-it-GGUF" / "snapshots" / "main" / _MODEL_FILENAME
        
        # Check if already cached
        if downloaded_path.exists():
            logger.info(f"Using cached model: {downloaded_path}")
            return str(downloaded_path)
        
        # Create directory structure
        downloaded_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading GGUF model from: {_MODEL_URL}")
        print(f">>> Downloading model from {_MODEL_URL}")
        
        # Download with streaming
        response = requests.get(_MODEL_URL, stream=True, timeout=300)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        print(f">>> Download size: {total_size / (1024*1024*1024):.2f} GB")
        
        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks
        
        with open(downloaded_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        if downloaded % (50 * 1024 * 1024) == 0:  # Print every 50MB
                            print(f">>> Downloaded: {downloaded / (1024*1024*1024):.2f} GB ({progress:.1f}%)")
        
        print(f">>> Download complete: {downloaded_path}")
        logger.info(f"Model downloaded to: {downloaded_path}")
        return str(downloaded_path)

    def initialize(self) -> None:
        """Download (if needed) and load the GGUF model."""
        print(">>> ai_summarizer.initialize() started")
        try:
            print(">>> Resolving model path...")
            self._model_path = self._resolve_model_path()
            print(f">>> Model path resolved: {self._model_path}")

            print(">>> Creating Llama instance (this may take a while)...")
            self._llm = Llama(
                model_path=self._model_path,
                n_ctx=settings.ai_n_ctx,
                n_threads=os.cpu_count() or 4,
                verbose=True,
            )

            self._is_ready = True
            print(">>> AI summarizer ready!")
            logger.info("AI summarizer ready")

        except Exception as e:
            print(f">>> ERROR in initialize: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"Failed to initialize AI summarizer: {e}")
            self._is_ready = False
            raise

    def _build_prompt(self, text: str) -> str:
        """Build the prompt for financial analysis."""
        return build_summarizer_prompt(text)

    def summarize(self, text: str, max_tokens: int = 512) -> SummaryResult:
        """Run inference on financial text."""
        if not self._is_ready or self._llm is None:
            raise RuntimeError("AI summarizer not ready")

        if not text or len(text.strip()) == 0:
            raise ValueError("Text cannot be empty")

        if len(text) > _MAX_INPUT_CHARS:
            raise ValueError(f"Input text too long (max {_MAX_INPUT_CHARS} characters)")

        prompt = self._build_prompt(text)

        try:
            response = self._llm.create_completion(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=0.3,
                top_p=0.9,
                repeat_penalty=1.1,
            )

            summary = response["choices"][0]["text"].strip()
            usage = response.get("usage", {})

            return SummaryResult(
                summary=summary,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                model=self._model_name,
            )

        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise RuntimeError(f"Inference failed: {e}")

    def close(self) -> None:
        """Unload model and free memory."""
        logger.info("Closing AI summarizer...")
        if self._llm is not None:
            del self._llm
            self._llm = None
        gc.collect()
        self._is_ready = False
        logger.info("AI summarizer closed")


ai_summarizer = AISummarizer()
