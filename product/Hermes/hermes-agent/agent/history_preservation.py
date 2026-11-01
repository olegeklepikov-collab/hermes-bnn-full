"""Required checkpoint at native proactive-prune commit, never an observing hook."""
from __future__ import annotations


def prune_with_checkpoint(agent, messages, current_tokens):
    compressor = agent.context_compressor
    prune = getattr(compressor, 'prune_tool_results_only', None)
    if not callable(prune):
        return messages, 0
    if getattr(agent, 'compression_checkpoint_required', False) is not True:
        return prune(messages, current_tokens=current_tokens)
    # A generic **kwargs or a capability claim cannot prove a plugin calls the
    # gate before its side effect. Other engines retain full history until qualified.
    from agent.context_compressor import ContextCompressor
    from agent.conversation_compression import CompressionCheckpointUnavailable, _pre_compress_memory_context
    def preserve():
        receipt = _pre_compress_memory_context(agent, messages, True)
        if not isinstance(receipt, str) or not receipt.strip():
            raise CompressionCheckpointUnavailable('Required checkpoint returned no receipt; history retained')

    try:
        if type(compressor) is not ContextCompressor or getattr(prune, '__func__', None) is not ContextCompressor.prune_tool_results_only:
            raise CompressionCheckpointUnavailable('Required checkpoint: proactive prune engine is not qualified; history retained')
        result = prune(messages, current_tokens=current_tokens, before_history_loss=preserve)
    except Exception as exc:
        reason = str(exc) if isinstance(exc, CompressionCheckpointUnavailable) else type(exc).__name__
        if getattr(agent, '_last_prune_checkpoint_error', None) != reason:
            notify = getattr(agent, '_buffer_status', None)
            if callable(notify):
                notify('Исходную историю сохранить не удалось; предварительное сокращение отменено. '
                       'История сохранена в текущем сеансе. Требуется восстановить поставщика контрольных точек.')
        agent._last_prune_checkpoint_error = reason
        raise
    agent._last_prune_checkpoint_error = None
    return result
