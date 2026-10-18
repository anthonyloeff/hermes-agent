"""API browser lanes must survive internal transcript rotation and tool threads (Anthony-local; port of 771e273824 + 86a39d4361)."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from gateway.browser_control_broker import (
    BrowserControlBroker, ControllerScope, ControllerUnavailable,
)
from gateway.platforms.api_server import APIServerAdapter
from gateway.session_context import clear_session_vars, get_session_env, set_current_session_id
from tools.browser_extension_router import extension_controller_available, routed_browser_handler
from tools.thread_context import propagate_context_to_thread


@pytest.fixture
def lane(monkeypatch):
    broker = BrowserControlBroker(command_timeout=0.1)
    scope = ControllerScope(
        principal_id="principal-test", profile_id="default", session_id="pwa-topic-test",
        controller_id="controller-test", browser_profile_id="browser-test",
        transport_family="local-api", capabilities=frozenset({"browser_navigate"}),
    )
    calls = []
    def send(frame):
        calls.append(frame)
        command_id = frame["params"]["command_id"]
        # A guessed command id from another principal/family cannot complete it.
        for override in ({"principal_id": "wrong-principal"},
                         {"transport_family": "wrong-family"}):
            assert broker.complete(command_id, scope=replace(scope, **override),
                                   ok=True, result="wrong-controller") is False
        assert broker.complete(command_id, scope=scope, ok=True,
                               result={"source": "controller-result"}) is True
        assert broker.complete(command_id, scope=scope, ok=True,
                               result="duplicate") is False
    broker.attach(scope, send, owner="socket-test")
    monkeypatch.setattr("gateway.browser_control_broker.browser_control_enabled", lambda: True)
    monkeypatch.setattr("gateway.browser_control_broker.get_browser_control_broker", lambda: broker)

    tokens = APIServerAdapter._bind_api_server_session(
        session_id="pwa-topic-test", browser_control_principal="principal-test",
        browser_control_transport_family="local-api",
    )
    # Same public API used by transcript compression/adoption.
    set_current_session_id("internal-compressed-child")
    yield broker, scope, calls
    clear_session_vars(tokens)
    broker.reset()


@pytest.mark.parametrize("threaded", [False, True])
def test_registry_navigate_uses_bound_lane_after_rotation(lane, monkeypatch, threaded):
    from tools import browser_tool
    from tools.registry import registry
    monkeypatch.setattr(browser_tool, "browser_navigate", lambda **kw: pytest.fail("legacy backend used"))
    def execute():
        assert get_session_env("HERMES_SESSION_ID") == "internal-compressed-child"
        return registry.dispatch("browser_navigate", {"url": "https://example.test"},
                                 session_id="internal-compressed-child", task_id="pwa-topic-test")
    if threaded:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(propagate_context_to_thread(execute)).result()
    else:
        result = execute()
    assert isinstance(result, str)
    assert json.loads(result) == {"source": "controller-result"}
    assert len(lane[2]) == 1
    frame = lane[2][0]
    assert frame["method"] == "browser.controller.command"
    assert frame["params"]["controller_id"] == lane[1].controller_id
    assert frame["params"]["browser_profile_id"] == lane[1].browser_profile_id
    assert frame["params"]["action"] == "browser_navigate"
    assert frame["params"]["arguments"] == {"url": "https://example.test"}
    assert lane[0].pending_count == 0


def test_availability_uses_bound_lane_after_rotation(lane):
    assert extension_controller_available("browser_navigate") is True


def test_router_default_and_explicit_override(lane):
    result = routed_browser_handler("browser_navigate", {}, fallback=lambda: "legacy")
    assert json.loads(result) == {"source": "controller-result"}
    # An explicit router override remains explicit, unlike the generic registry's
    # transcript session_id, which is not a browser-lane override.
    with pytest.raises(ControllerUnavailable):
        routed_browser_handler("browser_navigate", {}, session_id="other-unregistered",
                               fallback=lambda: pytest.fail("legacy backend used"))


def test_disconnect_after_rotation_fails_closed(lane, monkeypatch):
    from tools import browser_tool
    from tools.registry import registry
    monkeypatch.setattr(browser_tool, "browser_navigate", lambda **kw: pytest.fail("legacy backend used"))
    lane[0].disconnect_owner("socket-test")
    assert extension_controller_available("browser_navigate") is False
    result = registry.dispatch("browser_navigate", {}, session_id="internal-compressed-child")
    assert "bound browser controller" in result
    assert lane[2] == []


def test_clear_drops_bound_browser_session(lane):
    clear_session_vars([])
    assert get_session_env("HERMES_BROWSER_CONTROL_SESSION_ID") == ""
    assert extension_controller_available("browser_navigate") is False


@pytest.mark.parametrize("override", [{"principal_id": "wrong-principal"},
                                     {"transport_family": "wrong-family"}])
def test_stable_session_does_not_bypass_identity_checks(lane, override):
    with pytest.raises(ControllerUnavailable):
        routed_browser_handler("browser_navigate", {},
                               fallback=lambda: pytest.fail("legacy backend used"),
                               **override)
    assert lane[2] == []


def test_worker_capture_isolated_from_next_api_request(lane):
    worker = propagate_context_to_thread(lambda: (
        get_session_env("HERMES_BROWSER_CONTROL_SESSION_ID"),
        extension_controller_available("browser_navigate"),
    ))
    APIServerAdapter._bind_api_server_session(
        session_id="other-topic", browser_control_principal="principal-test",
        browser_control_transport_family="local-api",
    )
    assert extension_controller_available("browser_navigate") is False
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(worker).result() == ("pwa-topic-test", True)
    assert get_session_env("HERMES_BROWSER_CONTROL_SESSION_ID") == "other-topic"


@pytest.mark.parametrize("threaded", [False, True])
def test_reset_after_rotation_never_falls_back(lane, monkeypatch, threaded):
    from tools import browser_tool
    from tools.registry import registry

    monkeypatch.setattr(browser_tool, "browser_navigate",
                        lambda **kw: pytest.fail("legacy backend used"))
    assert extension_controller_available("browser_navigate") is True
    # Capture before reset, like an already-scheduled tool worker.
    execute = propagate_context_to_thread(lambda: registry.dispatch(
        "browser_navigate", {}, session_id="internal-compressed-child"))
    lane[0].reset()
    assert not lane[0].lane_registered(session_id=lane[1].session_id,
                                     principal_id=lane[1].principal_id,
                                     transport_family=lane[1].transport_family)
    assert extension_controller_available("browser_navigate") is False
    if threaded:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(execute).result()
    else:
        result = execute()
    assert "bound browser controller" in result
    assert lane[2] == []
    assert lane[0].pending_count == 0


def test_disabled_config_does_not_release_required_lane(lane, monkeypatch):
    monkeypatch.setattr("gateway.browser_control_broker.browser_control_enabled", lambda: False)
    lane[0].reset()
    with pytest.raises(ControllerUnavailable, match="disabled"):
        routed_browser_handler("browser_navigate", {},
                               fallback=lambda: pytest.fail("legacy backend used"))


def test_unsupported_action_does_not_release_required_lane(lane):
    with pytest.raises(ControllerUnavailable, match="browser_cdp"):
        routed_browser_handler("browser_cdp", {},
                               fallback=lambda: pytest.fail("legacy backend used"))
    assert lane[2] == []


@pytest.mark.parametrize("principal,family", [("", "local-api"), ("principal-test", ""), ("", "")])
def test_incomplete_required_identity_fails_closed(lane, principal, family):
    APIServerAdapter._bind_api_server_session(
        session_id=lane[1].session_id, browser_control_principal=principal,
        browser_control_transport_family=family)
    with pytest.raises(ControllerUnavailable):
        routed_browser_handler("browser_navigate", {},
                               fallback=lambda: pytest.fail("legacy backend used"))


def test_generic_api_started_with_feature_disabled_keeps_legacy(lane, monkeypatch):
    monkeypatch.setattr("gateway.browser_control_broker.browser_control_enabled", lambda: False)
    APIServerAdapter._bind_api_server_session(
        session_id="ordinary-api", browser_control_principal="principal-test",
        browser_control_transport_family="local-api")
    assert get_session_env("HERMES_BROWSER_CONTROL_SESSION_ID") == ""
    assert routed_browser_handler("browser_navigate", {}, fallback=lambda: "legacy") == "legacy"


def test_generic_api_started_with_feature_enabled_requires_controller(lane):
    # The global feature flag opts all API clients in, not just a PWA.
    APIServerAdapter._bind_api_server_session(
        session_id="ordinary-api", browser_control_principal="principal-test",
        browser_control_transport_family="local-api")
    assert get_session_env("HERMES_BROWSER_CONTROL_SESSION_ID") == "ordinary-api"
    assert extension_controller_available("browser_navigate") is False
    with pytest.raises(ControllerUnavailable):
        routed_browser_handler("browser_navigate", {},
                               fallback=lambda: pytest.fail("legacy backend used"))
    assert lane[2] == []


def test_broker_import_failure_does_not_release_required_lane(lane, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "gateway.browser_control_broker", None)
    with pytest.raises(RuntimeError, match="bound browser controller"):
        routed_browser_handler("browser_navigate", {},
                               fallback=lambda: pytest.fail("legacy backend used"))


def test_direct_router_cannot_opt_required_lane_out(lane):
    from tools.browser_extension_router import route_browser_tool

    with pytest.raises(ControllerUnavailable, match="disabled"):
        route_browser_tool("browser_navigate", {}, broker=lane[0], enabled=False,
                           fallback=lambda: pytest.fail("legacy backend used"))


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("platform", ["", "telegram", "desktop"])
def test_non_api_unregistered_lane_keeps_ordinary_backend(lane, monkeypatch, enabled, platform):
    from gateway.session_context import set_session_vars

    lane[0].reset()
    set_session_vars(platform=platform, session_id="ordinary-session",
                     browser_control_principal="principal-test",
                     browser_control_transport_family="local-api")
    monkeypatch.setattr("gateway.browser_control_broker.browser_control_enabled", lambda: enabled)
    calls = []
    assert routed_browser_handler("browser_navigate", {},
                                  fallback=lambda: calls.append(True) or "legacy") == "legacy"
    assert calls == [True]
    assert lane[2] == []
