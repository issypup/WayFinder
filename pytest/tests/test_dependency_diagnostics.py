"""Provide test dependency diagnostics support."""
from wayfinder.app.core.source_layout import combined_app_source
from pathlib import Path

from wayfinder.runtime import dependency_manager as dm


def test_dependency_report_requires_success_flag(tmp_path):
    """Handle test dependency report requires success flag."""
    report = tmp_path / "dependencies.json"
    report.write_text('{"install_success": false}', encoding="utf-8")
    assert dm.dependency_report_ok(report) is False
    report.write_text('{"install_success": true}', encoding="utf-8")
    assert dm.dependency_report_ok(report) is True


def test_installer_records_failure_details_and_continues(tmp_path, monkeypatch):
    """Handle test installer records failure details and continues."""
    ap_root = tmp_path / "ap"
    target = tmp_path / "packages"
    report = tmp_path / "dependencies.json"
    (ap_root / "worlds" / "Alpha").mkdir(parents=True)
    (ap_root / "worlds" / "Beta").mkdir(parents=True)
    (ap_root / "worlds" / "Alpha" / "requirements.txt").write_text("alpha-pkg\n", encoding="utf-8")
    (ap_root / "worlds" / "Beta" / "requirements.txt").write_text("beta-pkg\n", encoding="utf-8")

    calls = []

    def fake_install(self, requirements, constraints=()):
        calls.append(list(requirements))
        if requirements[0].name == "alpha-pkg":
            raise RuntimeError("No compatible wheel for alpha-pkg")

    monkeypatch.setattr(dm.WheelInstaller, "install", fake_install)
    code = dm.install_all_dependencies(ap_root, target, report)
    data = dm.load_dependency_report(report)

    assert code == 1
    assert len(calls) == 2
    assert data["install_success"] is False
    assert data["failed_count"] == 1
    failed = [item for item in data["results"] if item["status"] == "failed"][0]
    assert failed["owner"] == "Alpha"
    assert failed["diagnosis"] == "Compatible wheel unavailable"
    assert "alpha-pkg" in failed["output"]
    assert dm.dependency_report_ok(report) is False


def test_dependency_progress_callback_receives_unit_updates(tmp_path, monkeypatch):
    """Handle test dependency progress callback receives unit updates."""
    ap_root = tmp_path / "ap"
    target = tmp_path / "packages"
    report = tmp_path / "dependencies.json"
    ap_root.mkdir(parents=True)
    (ap_root / "requirements.txt").write_text("example-package\n", encoding="utf-8")
    monkeypatch.setattr(dm.WheelInstaller, "install", lambda self, requirements, constraints=(): None)
    updates = []
    assert dm.install_all_dependencies(ap_root, target, report, progress_callback=lambda c, t, l: updates.append((c, t, l))) == 0
    assert updates[0][0] == 0
    assert updates[-1][0] == updates[-1][1] == 1


def test_gui_dependency_install_runs_on_worker_thread():
    """Handle test gui dependency install runs on worker thread."""
    source = combined_app_source()
    section = source[source.index("def _install_world_dependencies"):source.index("def _ensure_local_runtime_started")]
    assert "threading.Thread" in section
    assert "WayFinderDependencyInstaller" in section
    assert "self.root.after(100, poll_progress)" in section
    assert "ttk.Progressbar" in section


def test_source_dependency_failure_preserves_report_and_progress(tmp_path):
    root = tmp_path / "ap"
    root.mkdir()
    (root / "requirements.txt").write_text("demo @ git+https://example.org/demo")
    report = tmp_path / "report.json"
    updates = []
    assert dm.install_all_dependencies(root, tmp_path / "packages", report,
        progress_callback=lambda *args: updates.append(args)) == 1
    data = dm.load_dependency_report(report)
    assert data["results"][0]["diagnosis"] == "Source dependency unsupported"
    assert not data["install_success"]
    assert updates[-1][:2] == (1, 1)
    assert "Installer output" in dm.format_dependency_failure_report(data)


def test_runtime_installer_has_no_process_or_bootstrap_dependency():
    from wayfinder.runtime import wheel_installer
    source = Path(wheel_installer.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "import pip" not in source
    assert "import uv" not in source
    root = Path(__file__).resolve().parents[2]
    assert not (root / "managed_runtime_payload").exists()
    assert not (root / "wayfinder/runtime/managed_python.py").exists()


def test_requirement_parse_error_is_not_misdiagnosed_as_checksum_error():
    diagnosis, explanation = dm._classify_install_failure('Invalid or unsupported requirement: demo --hash=sha256:bad')
    assert diagnosis == 'Requirements syntax unsupported'
    assert 'no checksum comparison' in explanation


def test_declared_source_is_not_replaced_by_inferred_unpinned_source(tmp_path, monkeypatch):
    root = tmp_path / 'ap'
    root.mkdir()
    requirement = root / 'requirements.txt'
    requirement.write_text('gclib @ git+https://github.com/LagoLunatic/gclib.git@abc123')
    work = tmp_path / 'scan'
    work.mkdir()
    scan = dm.DependencyScan([str(requirement)], [], [], ['gclib'], 1, 0)
    monkeypatch.setattr(dm, 'scan_dependencies', lambda *args: (scan, work))
    calls = []
    monkeypatch.setattr(dm.WheelInstaller, 'install', lambda self, requirements, constraints: calls.append(requirements))
    assert dm.install_all_dependencies(root, tmp_path / 'packages') == 0
    assert len(calls) == 1


def test_audited_source_preflight_checks_provenance(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from wayfinder.runtime.apworld_compatibility import dependency_preflight
    from wayfinder.runtime.source_recipes import RECIPES
    recipe = RECIPES['zilliandomizer']
    dist = tmp_path / 'zilliandomizer-0.9.1.dist-info'
    dist.mkdir()
    (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: zilliandomizer\nVersion: 0.9.1\n')
    provenance = {'url': 'https://github.com/' + recipe['repo'],
                  'vcs_info': {'commit_id': recipe['commit']}, 'wayfinder_archive_sha256': recipe['sha256']}
    path = dist / 'direct_url.json'
    path.write_text(json.dumps(provenance))
    record = SimpleNamespace(requirements=[dict(owner='Demo', requirement='zilliandomizer @ git+https://github.com/beauxq/zilliandomizer@' + recipe['commit'])])
    assert dependency_preflight(record, tmp_path)[0]['state'] == 'Ready'
    provenance['vcs_info']['commit_id'] = 'bad'
    path.write_text(json.dumps(provenance))
    assert dependency_preflight(record, tmp_path)[0]['state'] != 'Ready'
