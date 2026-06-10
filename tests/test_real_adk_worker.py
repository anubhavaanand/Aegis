from __future__ import annotations

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from adapters.adk_adapter import ADKAdapter, WorkerResult
from adapters.real_adk_worker import RealADKWorker, AegisTracingSetup, HAS_ADK_DEPS

@pytest.mark.skipif(not HAS_ADK_DEPS, reason="ADK and OpenTelemetry deps not installed")
def test_convert_span():
    worker = RealADKWorker(agent_id="test-worker")
    
    # Mock a span object from opentelemetry-sdk
    mock_span = MagicMock()
    mock_span.name = "test_span"
    mock_span.context.span_id = 0x1234567890abcdef
    mock_span.context.trace_id = 0x0123456789abcdef0123456789abcdef
    
    mock_parent = MagicMock()
    mock_parent.span_id = 0xfedcba9876543210
    mock_span.parent = mock_parent
    
    from opentelemetry.trace import StatusCode
    mock_span.status.status_code = StatusCode.OK
    mock_span.status.description = "Operation successful"
    mock_span.attributes = {"openinference.span.kind": "TOOL", "tool.name": "add"}
    mock_span.start_time = 1000
    mock_span.end_time = 2000
    
    converted = worker._convert_span(mock_span)
    
    assert converted["name"] == "test_span"
    assert converted["context"]["span_id"] == "1234567890abcdef"
    assert converted["context"]["trace_id"] == "0123456789abcdef0123456789abcdef"
    assert converted["parent_id"] == "fedcba9876543210"
    assert converted["status"]["status_code"] == "OK"
    assert converted["status"]["description"] == "Operation successful"
    assert converted["attributes"]["openinference.span.kind"] == "TOOL"
    assert converted["attributes"]["tool.name"] == "add"
    assert converted["start_time"] == 1000
    assert converted["end_time"] == 2000

@pytest.mark.skipif(not HAS_ADK_DEPS, reason="ADK and OpenTelemetry deps not installed")
@pytest.mark.asyncio
async def test_real_adk_worker_mock_run():
    # Mock google.adk components
    mock_agent = MagicMock()
    mock_session = MagicMock()
    mock_session.id = "mock-session-id"
    
    mock_session_service = MagicMock()
    mock_session_service.create_session = AsyncMock(return_value=mock_session)
    
    mock_runner = MagicMock()
    
    # Mock event stream returned by runner.run_async
    mock_event = MagicMock()
    mock_event.is_final_response = MagicMock(return_value=True)
    mock_event.content.parts = [MagicMock(text="Calculated 15 + 27 = 42")]
    
    async def mock_async_generator(*args, **kwargs):
        yield mock_event
        
    mock_runner.run_async = mock_async_generator
    
    with patch("google.adk.agents.Agent", return_value=mock_agent), \
         patch("google.adk.runners.Runner", return_value=mock_runner), \
         patch("google.adk.sessions.InMemorySessionService", return_value=mock_session_service):
         
         worker = RealADKWorker(agent_id="mocked-real-worker")
         
         # Mock span collecting
         mock_span = {
             "name": "calculate_addition",
             "attributes": {
                 "openinference.span.kind": "TOOL",
                 "tool.name": "calculate_addition",
                 "input.value": "{'a': 15, 'b': 27}",
                 "output.value": "42"
             },
             "context": {
                 "span_id": "1",
                 "trace_id": "trace1"
             },
             "parent_id": None,
             "status": {"status_code": "OK", "description": ""},
             "start_time": 0,
             "end_time": 0
         }
         worker.collect_and_convert_spans = MagicMock(return_value=[mock_span])
         
         result = await worker.run_async("Add 15 and 27")
         
         assert result.agent_id == "mocked-real-worker"
         assert result.claimed_success is True
         assert "Calculated 15 + 27 = 42" in result.summary
         assert len(result.tool_calls) == 1
         assert result.tool_calls[0]["name"] == "calculate_addition"
         assert result.tool_calls[0]["input"] == "{'a': 15, 'b': 27}"
         assert result.tool_calls[0]["output"] == "42"
