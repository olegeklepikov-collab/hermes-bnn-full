"""Required pre-loss callback runs at commit, never on a no-op pruning probe."""
import copy
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from agent.context_compressor import ContextCompressor
from agent.history_preservation import prune_with_checkpoint
from agent.conversation_compression import CompressionCheckpointUnavailable


def compressor():
    with patch('agent.context_compressor.get_model_context_length',return_value=1_000_000):
        return ContextCompressor(model='offline',quiet_mode=True,protect_first_n=1,protect_last_n=2,
            proactive_prune_tokens=100,proactive_prune_min_reclaim_tokens=1,
            proactive_prune_min_result_chars=1000)


def history():
    messages=[{'role':'system','content':'Keep original constraints'}]
    for index in range(8):
        messages.extend([{'role':'assistant','tool_calls':[{'id':str(index),'type':'function','function':{'name':'fixture','arguments':'{}'}}]},
                         {'role':'tool','tool_call_id':str(index),'content':str(index)*9000}])
    return messages


def test_pre_loss_failure_leaves_source_and_rearm_unchanged():
    engine=compressor();messages=history();original=copy.deepcopy(messages)
    before=engine._proactive_prune_rearm_tokens
    callback=Mock(side_effect=OSError('synthetic checkpoint failure'))
    with pytest.raises(OSError):engine.prune_tool_results_only(messages,120000,before_history_loss=callback)
    callback.assert_called_once_with()
    assert messages==original
    assert engine._proactive_prune_rearm_tokens==before


def test_required_callback_is_before_publish_and_noop_does_not_checkpoint():
    engine=compressor();messages=history();original=copy.deepcopy(messages);observed=[]
    before=engine._proactive_prune_rearm_tokens
    def preserve():
        assert messages==original
        assert engine._proactive_prune_rearm_tokens==before
        observed.append(copy.deepcopy(messages))
    result,count=engine.prune_tool_results_only(messages,120000,before_history_loss=preserve)
    assert count>0 and result!=messages and observed==[original]
    callback=Mock()
    same,count=engine.prune_tool_results_only(result,1,before_history_loss=callback)
    assert same is result and count==0
    callback.assert_not_called()


def test_required_checkpoint_refuses_an_unqualified_engine_before_call():
    prune=Mock(return_value=([],1))
    agent=SimpleNamespace(context_compressor=SimpleNamespace(prune_tool_results_only=prune),compression_checkpoint_required=True)
    messages=history()
    with pytest.raises(CompressionCheckpointUnavailable):prune_with_checkpoint(agent,messages,120000)
    prune.assert_not_called()
    class PluginCompressor(ContextCompressor):
        def _prune_old_tool_results(self, *args, **kwargs):
            raise AssertionError('unqualified plugin must not execute')
    agent.context_compressor=object.__new__(PluginCompressor)
    with pytest.raises(CompressionCheckpointUnavailable):prune_with_checkpoint(agent,messages,120000)


def test_required_callback_precedes_actual_sqlite_archive(tmp_path):
    from hermes_state import SessionDB
    db=SessionDB(db_path=tmp_path/'state.db');db.create_session('synthetic',source='telegram')
    db.append_messages_batch('synthetic',history())
    engine=compressor();engine._session_db=db;engine._session_id='synthetic'
    messages=db.get_messages_as_conversation('synthetic');original=copy.deepcopy(messages)
    count=len(db.get_messages('synthetic',include_inactive=True))
    def unavailable():raise OSError('synthetic disk failure')
    with pytest.raises(OSError):engine.prune_tool_results_only(messages,120000,before_history_loss=unavailable)
    assert db.get_messages_as_conversation('synthetic')==original
    assert len(db.get_messages('synthetic',include_inactive=True))==count
    observed=[]
    def preserve():
        assert db.get_messages_as_conversation('synthetic')==original
        observed.append(copy.deepcopy(messages))
    result,reduced=engine.prune_tool_results_only(messages,120000,before_history_loss=preserve)
    assert reduced>0 and observed==[original]
    assert [m.get('content') for m in db.get_messages_as_conversation('synthetic')]==[m.get('content') for m in result]
    db.close()
