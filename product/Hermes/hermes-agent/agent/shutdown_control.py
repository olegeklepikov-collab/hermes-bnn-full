"""Call the native background-review cancellation protocol before owner teardown."""
def cancel_and_acknowledge_review(agent):
    from agent.background_review import cancel_background_review_for_live_turn
    run=getattr(agent,'_background_review_run',None)
    legacy=getattr(agent,'_background_review_agent',None)
    if run is None and legacy is None:return
    cancel_background_review_for_live_turn(agent,message='owning agent is closing',tool_reason='owner shutdown')
    if run is None and legacy is not None:
        raise RuntimeError('legacy_background_review_has_no_acknowledgement; outcome unknown')
    if run is not None and not run.request_done.is_set():
        raise RuntimeError('background_review_shutdown_not_acknowledged; usage remains unsettled')
