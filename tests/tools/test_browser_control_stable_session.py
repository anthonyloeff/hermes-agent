"""API browser lanes must survive internal transcript rotation and tool threads."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from gateway.browser_control_broker import BrowserControlBroker, ControllerScope
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
    broker.attach(scope, lambda frame: None, owner="socket-test")
    monkeypatch.setattr("gateway.browser_control_broker.browser_control_enabled", lambda: True)
    monkeypatch.setattr("gateway.browser_control_broker.get_browser_control_broker", lambda: broker)
    calls = []
    def dispatch(selected_scope, **kwargs):
        calls.append((selected_scope, kwargs))
        return "controller-result"
    monkeypatch.setattr(broker, "dispatch", dispatch)
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
    assert result == "controller-result"
    assert lane[2][0][0] == lane[1]


def test_availability_uses_bound_lane_after_rotation(lane):
    assert extension_controller_available("browser_navigate") is True


def test_router_default_and_explicit_override(lane):
    assert routed_browser_handler("browser_navigate", {}, fallback=lambda: "legacy") == "controller-result"
    # An explicit router override remains explicit, unlike the generic registry's
    # transcript session_id, which is not a browser-lane override.
    assert routed_browser_handler("browser_navigate", {}, session_id="other-unregistered",
                                  fallback=lambda: "legacy") == "legacy"


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
    assert routed_browser_handler("browser_navigate", {}, fallback=lambda: "legacy",
                                  **override) == "legacy"
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
