"""Managed source runtimes refuse mutation before updater side effects."""
import json
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize("invalid", [False, True])
def test_external_manager_refuses_direct_apply_before_backup(tmp_path, monkeypatch, invalid):
    from hermes_cli import update_cmd
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "runtime-manager.json").write_text("broken" if invalid else json.dumps({
        "version": 1, "manager": "fixture", "update_command": "reviewed-stage-command"}))
    marker = tmp_path / "updater_side_effect"
    monkeypatch.setattr(update_cmd, "_resolve_update_options", lambda *args: marker.write_text("changed"))
    with pytest.raises(SystemExit):
        update_cmd._cmd_update_impl(SimpleNamespace(), False)
    assert not marker.exists()


def test_runtime_manager_follows_actual_profile_context(tmp_path, monkeypatch):
    from hermes_cli.update_contract import evaluate_update_admission
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(); b.mkdir(); monkeypatch.setenv("HERMES_HOME", str(a))
    (a / "runtime-manager.json").write_text(json.dumps({"version": 1, "manager": "A", "update_command": "A-stage"}))
    monkeypatch.setattr("hermes_cli.image_provenance.read_image_provenance", lambda: None)
    monkeypatch.setattr("hermes_cli.config.detect_install_method", lambda *_: "git")
    for home, expected in [(a, "A-stage"), (b, None), (a, "A-stage")]:
        token = set_hermes_home_override(home)
        try:
            result = evaluate_update_admission(tmp_path)
            assert (result.update_command if result else None) == expected
        finally:
            reset_hermes_home_override(token)
