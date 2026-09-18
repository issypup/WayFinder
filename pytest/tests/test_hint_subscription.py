"""Provide test hint subscription support."""
from wayfinder.runtime.server import NativeRuntime


class DummyContext:
    """Provide dummy context behavior."""
    def __init__(self):
        """Handle init."""
        self.team = 0
        self.slot = 1
        self.slot_info = {1: object(), 2: object(), 3: object()}
        self.calls = []

    def set_notify(self, *keys):
        """Handle set notify."""
        self.calls.append(keys)


def test_subscribe_hint_storage_watches_all_visible_slots():
    """Handle test subscribe hint storage watches all visible slots."""
    runtime = NativeRuntime.__new__(NativeRuntime)
    runtime.ctx = DummyContext()
    runtime.send_log = lambda _message: None
    runtime._subscribe_hint_storage()
    assert runtime.ctx.calls == [("_read_hints_0_1", "_read_hints_0_2", "_read_hints_0_3")]
