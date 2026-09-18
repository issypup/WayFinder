"""Regression tests for WayFinder's single-app role dispatcher."""

import run_wayfinder


def test_native_runtime_role_dispatch(monkeypatch):
    """Handle test native runtime role dispatch."""
    calls=[]
    monkeypatch.setattr(run_wayfinder,"run_native_runtime",lambda argv:calls.append(("runtime",argv)))
    run_wayfinder.main(["WayFinder.exe","--native-runtime","55475","core","players"])
    assert calls and calls[0][0]=="runtime"


def test_default_mode_opens_wayfinder_directly(monkeypatch):
    """Handle test default mode opens wayfinder directly."""
    calls=[]
    monkeypatch.setattr(run_wayfinder,"allocate_ipc_port",lambda:55475)
    monkeypatch.setattr(run_wayfinder,"core_ready",lambda:False)
    monkeypatch.setattr(run_wayfinder,"run_gui",lambda:calls.append("wayfinder"))
    run_wayfinder.main(["WayFinder.exe"])
    assert calls==["wayfinder"]
