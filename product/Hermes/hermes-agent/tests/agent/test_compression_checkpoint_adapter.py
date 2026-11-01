"""Explicit child checkpoint adapter preserves normalized provider and full host contracts."""
from types import SimpleNamespace

import pytest

from agent.compression_checkpoint import register_child_checkpoint_adapter, current_checkpoint_input
from agent.conversation_compression import (
    _pre_compress_memory_context, CompressionCheckpointUnavailable, _warn_checkpoint_required_without_capable_provider,
)
from hermes_constants import set_hermes_home_override, reset_hermes_home_override


def child():
    return SimpleNamespace(session_id='child', _parent_session_id='parent', platform='subagent',
                           _memory_manager=None, _persist_disabled=True, _session_db=None)


def test_child_adapter_receives_full_history_and_cannot_leak_across_profiles(tmp_path):
    a, b = tmp_path / 'A', tmp_path / 'B'
    a.mkdir(); b.mkdir()
    messages = [{'role': 'user', 'content': 'original'}, {'role': 'tool', 'content': 'source'}]
    observed = []
    remove = register_child_checkpoint_adapter('fixture', lambda source, evidence: observed.append((source, evidence)) or 'durable receipt',
                                               profile_home=a)
    token = set_hermes_home_override(a)
    try:
        assert _pre_compress_memory_context(child(), messages, True) == 'durable receipt'
        assert observed[0][0].messages == messages
        assert observed[0][1] == messages[:1]
        assert current_checkpoint_input() is None
        foreign = set_hermes_home_override(b)
        try:
            with pytest.raises(CompressionCheckpointUnavailable): _pre_compress_memory_context(child(), messages, True)
        finally: reset_hermes_home_override(foreign)
        assert len(observed) == 1
    finally:
        reset_hermes_home_override(token)
        remove()


def test_required_detached_child_cannot_silently_skip_checkpoint(tmp_path):
    token = set_hermes_home_override(tmp_path)
    try:
        with pytest.raises(CompressionCheckpointUnavailable):
            _pre_compress_memory_context(child(), [{'role': 'user', 'content': 'original'}], True)
    finally: reset_hermes_home_override(token)


def test_empty_or_failed_child_adapter_receipt_stops_compression(tmp_path):
    token = set_hermes_home_override(tmp_path)
    remove = register_child_checkpoint_adapter('fixture', lambda source, evidence: '', profile_home=tmp_path)
    try:
        with pytest.raises(CompressionCheckpointUnavailable):
            _pre_compress_memory_context(child(), [{'role': 'user', 'content': 'original'}], True)
        assert current_checkpoint_input() is None
    finally:
        remove()
        reset_hermes_home_override(token)


def test_child_startup_diagnostic_recognizes_explicit_adapter(tmp_path, caplog):
    agent = child(); agent.compression_checkpoint_required = True
    token = set_hermes_home_override(tmp_path)
    remove = register_child_checkpoint_adapter('fixture', lambda source, evidence: 'receipt', profile_home=tmp_path)
    try:
        _warn_checkpoint_required_without_capable_provider(agent)
        assert 'does not implement checkpoint' not in caplog.text
        remove()
        _warn_checkpoint_required_without_capable_provider(agent)
        assert 'does not implement checkpoint' in caplog.text
    finally:
        remove()
        reset_hermes_home_override(token)
