from pathlib import Path


def test_single_exe_bundles_python_stable_abi_dll():
    root = Path(__file__).resolve().parents[2]
    text = (root / "BUILD-SINGLE-EXE.bat").read_text(encoding="utf-8")
    assert "python3.dll" in text
    assert '--add-binary "%PYTHON3_DLL%;."' in text
