"""Tests for checkpointing, coalescing, and desktop database settings."""
import pytest
from app.services.checkpoint_service import get_checkpoint, set_checkpoint, clear_checkpoint
from app.services.coalesce import coalesce
import asyncio


def test_checkpoint_lifecycle():
    task_name = "test_task_checkpoint"
    clear_checkpoint(task_name)
    sym, cursor = get_checkpoint(task_name)
    assert sym is None

    set_checkpoint(task_name, last_symbol="RELIANCE", cursor_info="idx:10")
    sym, cursor = get_checkpoint(task_name)
    assert sym == "RELIANCE"
    assert cursor == "idx:10"

    set_checkpoint(task_name, last_symbol="INFY", cursor_info="idx:20")
    sym, cursor = get_checkpoint(task_name)
    assert sym == "INFY"
    assert cursor == "idx:20"

    clear_checkpoint(task_name)
    sym, cursor = get_checkpoint(task_name)
    assert sym is None


@pytest.mark.asyncio
async def test_coalesce_concurrent_requests():
    call_count = 0

    async def _sample_fetch():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(
        coalesce("test_key", _sample_fetch),
        coalesce("test_key", _sample_fetch),
        coalesce("test_key", _sample_fetch),
    )

    assert results == ["result", "result", "result"]
    assert call_count == 1
