"""Provide test compact run overview support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path
APP=Path(__file__).resolve().parents[2]/"wayfinder"/"app"/"app.py"

def test_run_overview_is_compact_card_not_large_labelframe():
    """Handle test run overview is compact card not large labelframe."""
    source=combined_app_source()
    start=source.index("def _build_dashboard(self):")
    end=source.index("def _build_search",start)
    block=source[start:end]
    assert 'ttk.LabelFrame(p,text="Run overview"' not in block
    assert 'overview=ttk.Frame(p,style="Card.TFrame"' in block
    assert 'text="RUN OVERVIEW"' in block
    assert 'run_actions=ttk.Frame(overview,style="Card.TFrame")' in block
    assert 'self.refresh_btn=ttk.Button(run_actions' in block
