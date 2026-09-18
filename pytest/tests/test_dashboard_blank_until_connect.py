"""Provide test dashboard blank until connect support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path


def _app_source() -> str:
    """Handle app source."""
    root = Path(__file__).resolve().parents[2]
    return combined_app_source()


def test_dashboard_text_is_blank_before_connect_request():
    """Handle test dashboard text is blank before connect request."""
    source = _app_source()
    assert 'self._user_connect_requested = False' in source
    assert 'self.dashboard_overview=tk.StringVar(value="")' in source
    assert 'self.dashboard_live_status=tk.StringVar(value="")' in source
    assert 'if not bool(getattr(self, "_user_connect_requested", False)):' in source
    assert 'self.dashboard_overview.set("")' in source
    assert 'self.dashboard_live_status.set("")' in source


def test_connect_request_enables_dashboard_details_only_after_validation():
    """Handle test connect request enables dashboard details only after validation."""
    source = _app_source()
    connect_method = source.split('def _connect_disconnect_clicked(self):', 1)[1].split('def _build_topbar', 1)[0]
    assert 'self._user_connect_requested = True' in connect_method
    assert connect_method.index('self._user_connect_requested = True') > connect_method.index('if not readiness["yaml_match"]:')
    assert 'self._user_connect_requested = False' in connect_method
