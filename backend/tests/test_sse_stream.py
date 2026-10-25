"""Unit tests for parse_sse_chunk and StreamAccumulator."""

import json
from app.services.llm_provider import parse_sse_chunk, StreamAccumulator


def test_parse_sse_chunk_blank_line():
    assert parse_sse_chunk("") is None
    assert parse_sse_chunk("   \n\r") is None
    assert parse_sse_chunk(": keep-alive comment") is None


def test_parse_sse_chunk_done():
    assert parse_sse_chunk("[DONE]") is None
    assert parse_sse_chunk("data: [DONE]") is None
    assert parse_sse_chunk("data: [DONE]\n") is None


def test_parse_sse_chunk_malformed_json():
    assert parse_sse_chunk("data: {malformed_json") is None
    assert parse_sse_chunk("{malformed_json") is None
    assert parse_sse_chunk("data: not-json") is None


def test_parse_sse_chunk_valid_json_with_and_without_prefix():
    payload = {"choices": [{"delta": {"content": "hello"}}]}
    raw_json = json.dumps(payload)
    parsed_without_prefix = parse_sse_chunk(raw_json)
    parsed_with_prefix = parse_sse_chunk(f"data: {raw_json}\n")

    assert parsed_without_prefix == payload
    assert parsed_with_prefix == payload


def test_stream_accumulator_normal_content_delta():
    acc = StreamAccumulator()
    chunk1 = {"choices": [{"delta": {"content": "Hello, "}}]}
    chunk2 = {"choices": [{"delta": {"content": "world!"}}]}

    ev1 = acc.apply(chunk1)
    assert ev1 == {"type": "token", "text": "Hello, "}
    ev2 = acc.apply(chunk2)
    assert ev2 == {"type": "token", "text": "world!"}

    summary = acc.finalize()
    assert summary["content"] == "Hello, world!"
    assert summary["finish_reason"] is None
    assert summary["tool_calls_map"] == {}


def test_stream_accumulator_reasoning_delta():
    acc = StreamAccumulator()
    chunk = {"choices": [{"delta": {"reasoning_content": "thinking..."}}]}
    ev = acc.apply(chunk)
    assert ev is None
    summary = acc.finalize()
    assert summary["reasoning"] == "thinking..."


def test_stream_accumulator_tool_call_fragment_sequence_across_3_chunks():
    acc = StreamAccumulator()
    chunk1 = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_123",
                    "type": "function",
                    "function": {"name": "get_stock_quote", "arguments": "{\""},
                }]
            }
        }]
    }
    chunk2 = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": "symbol\": \""},
                }]
            }
        }]
    }
    chunk3 = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": "TCS\"}"},
                }]
            }
        }]
    }

    assert acc.apply(chunk1) is None
    assert acc.apply(chunk2) is None
    assert acc.apply(chunk3) is None

    summary = acc.finalize()
    tc_map = summary["tool_calls_map"]
    assert 0 in tc_map
    assert tc_map[0]["id"] == "call_123"
    assert tc_map[0]["function"]["name"] == "get_stock_quote"
    assert tc_map[0]["function"]["arguments"] == '{"symbol": "TCS"}'


def test_stream_accumulator_finish_reason_with_tool_call_fragment():
    acc = StreamAccumulator()
    chunk1 = {
        "choices": [{
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "id": "call_abc",
                    "function": {"name": "lookup", "arguments": "{\"id\": 1"},
                }]
            }
        }]
    }
    chunk_finish = {
        "choices": [{
            "finish_reason": "tool_calls",
            "delta": {
                "tool_calls": [{
                    "index": 0,
                    "function": {"arguments": "}"},
                    "extra_content": "thought_sig_xyz",
                }]
            },
        }]
    }

    acc.apply(chunk1)
    acc.apply(chunk_finish)

    summary = acc.finalize()
    assert summary["finish_reason"] == "tool_calls"
    assert summary["tool_calls_map"][0]["id"] == "call_abc"
    assert summary["tool_calls_map"][0]["function"]["arguments"] == '{"id": 1}'
    assert summary["tool_calls_map"][0]["extra_content"] == "thought_sig_xyz"
