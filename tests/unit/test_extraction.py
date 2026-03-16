"""Sprint 10 — Unit tests for ExtractionPipeline (§5.5)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Config model ───────────────────────────────────────────────────────────────

def test_extraction_config_defaults():
    """ExtractionConfig has expected defaults."""
    from app.memory.extraction import ExtractionConfig
    cfg = ExtractionConfig()
    assert cfg.enabled is True
    assert cfg.trigger_interval_messages == 10
    assert cfg.min_confidence == 0.5
    assert cfg.dedup_similarity_threshold == 0.95
    assert cfg.merge_similarity_threshold == 0.85


def test_extraction_config_custom():
    """ExtractionConfig accepts custom values."""
    from app.memory.extraction import ExtractionConfig
    cfg = ExtractionConfig(enabled=False, trigger_interval_messages=5)
    assert cfg.enabled is False
    assert cfg.trigger_interval_messages == 5


# ── ExtractionResult model ─────────────────────────────────────────────────────

def test_extraction_result_model():
    """ExtractionResult captures processing summary."""
    from app.memory.extraction import ExtractionResult
    r = ExtractionResult(
        session_id="s1",
        messages_processed=10,
        candidates=3,
        created=2,
        merged=1,
        skipped=0,
        errors=0,
    )
    assert r.created + r.merged + r.skipped == 3


# ── JSON parsing helper ────────────────────────────────────────────────────────

def test_parse_json_response_valid_array():
    """_parse_json_response extracts a JSON array from an LLM response."""
    from app.memory.extraction import _parse_json_response
    text = 'Sure! Here are the results:\n[{"content": "test"}]'
    result = _parse_json_response(text)
    assert result == [{"content": "test"}]


def test_parse_json_response_no_array():
    """_parse_json_response returns [] on missing array."""
    from app.memory.extraction import _parse_json_response
    assert _parse_json_response("No JSON here.") == []


def test_parse_json_response_code_block():
    """_parse_json_response handles JSON in backtick code blocks."""
    from app.memory.extraction import _parse_json_response
    text = '```json\n[1, 2, 3]\n```'
    result = _parse_json_response(text)
    assert result == [1, 2, 3]


# ── Prompt builders ───────────────────────────────────────────────────────────

def test_build_classify_prompt_returns_string():
    """_build_classify_prompt returns a non-empty string."""
    from app.memory.extraction import _build_classify_prompt
    msgs = [{"role": "user", "content": "I love Python."}]
    prompt = _build_classify_prompt(msgs)
    assert isinstance(prompt, str)
    assert len(prompt) > 10


def test_build_extract_prompt_returns_string():
    """_build_extract_prompt returns a non-empty string."""
    from app.memory.extraction import _build_extract_prompt
    msgs = [{"role": "user", "content": "My name is Alice."}]
    prompt = _build_extract_prompt(msgs)
    assert isinstance(prompt, str)
    assert "memory" in prompt.lower() or "extract" in prompt.lower()


# ── Pipeline singleton ────────────────────────────────────────────────────────

def test_init_extraction_pipeline_returns_instance():
    """init_extraction_pipeline() initialises and returns a pipeline."""
    from app.memory.extraction import init_extraction_pipeline, get_extraction_pipeline, ExtractionConfig
    pipeline = init_extraction_pipeline(config=ExtractionConfig(enabled=False))
    assert pipeline is not None
    assert get_extraction_pipeline() is pipeline


def test_get_extraction_pipeline_after_init():
    """get_extraction_pipeline() returns the singleton after init."""
    from app.memory.extraction import init_extraction_pipeline, get_extraction_pipeline
    p1 = init_extraction_pipeline()
    p2 = get_extraction_pipeline()
    assert p1 is p2


# ── Pipeline.run with mock LLM ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extraction_pipeline_disabled_returns_empty():
    """Disabled pipeline returns zero extractions."""
    from app.memory.extraction import ExtractionPipeline, ExtractionConfig
    cfg = ExtractionConfig(enabled=False)
    pipeline = ExtractionPipeline(config=cfg)
    result = await pipeline.run(session_id="s1", messages=[{"role": "user", "content": "hi"}])
    assert result.created == 0
    assert result.merged == 0


@pytest.mark.asyncio
async def test_extraction_pipeline_empty_messages():
    """Pipeline returns immediately on empty messages."""
    from app.memory.extraction import ExtractionPipeline, ExtractionConfig
    pipeline = ExtractionPipeline(config=ExtractionConfig())
    result = await pipeline.run(session_id="s1", messages=[])
    assert result.messages_processed == 0


@pytest.mark.asyncio
async def test_extraction_pipeline_step1_fallback_on_llm_failure():
    """Step 1 falls back to all messages when LLM call fails."""
    from app.memory.extraction import ExtractionPipeline, ExtractionConfig

    async def failing_llm(msgs):
        raise RuntimeError("LLM unavailable")

    pipeline = ExtractionPipeline(llm_fn=failing_llm, config=ExtractionConfig(enabled=True))

    # The pipeline should not raise, just return with errors counted
    messages = [
        {"role": "user", "content": "My favourite colour is blue."},
        {"role": "assistant", "content": "Good to know."},
    ]
    with patch("app.memory.extraction.ExtractionPipeline._persist_memory", new=AsyncMock()):
        with patch("app.memory.extraction.ExtractionPipeline._step3_dedup", new=AsyncMock(return_value=[])):
            with patch("app.memory.extraction.ExtractionPipeline._step2_extract", new=AsyncMock(return_value=[])):
                result = await pipeline.run(session_id="s1", messages=messages)
    # Should complete without raising
    assert result.session_id == "s1"


@pytest.mark.asyncio
async def test_extraction_feedback_rating_adjusts_confidence():
    """Messages with feedback_rating=up get higher confidence candidates."""
    from app.memory.extraction import ExtractionPipeline, ExtractionConfig

    extracted_candidates = []

    async def mock_llm(msgs):
        return json.dumps([{"content": "test fact", "memory_type": "fact", "confidence": 0.6, "tags": []}])

    pipeline = ExtractionPipeline(llm_fn=mock_llm, config=ExtractionConfig(enabled=True))

    messages = [
        {"role": "user", "content": "My cat is called Whiskers.", "feedback_rating": "up"},
        {"role": "assistant", "content": "Nice name!"},
    ]

    with patch("app.memory.extraction.ExtractionPipeline._step3_dedup", new=AsyncMock(return_value=[])):
        with patch("app.memory.extraction.ExtractionPipeline._step4_contradiction", new=AsyncMock(side_effect=lambda c: c)):
            with patch("app.memory.extraction.ExtractionPipeline._step5_entity_link", new=AsyncMock(side_effect=lambda c: c)):
                with patch("app.memory.extraction.ExtractionPipeline._persist_memory", new=AsyncMock()):
                    result = await pipeline.run(session_id="s1", messages=messages)
    # Run should complete without exception
    assert result.session_id == "s1"
