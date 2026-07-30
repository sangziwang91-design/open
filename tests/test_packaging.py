from pathlib import Path
import zipfile

from scripts.package import create_zip


def test_package_excludes_runtime_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "x.py").write_text("x=1")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"x")
    (root / "agentbridge.db").write_text("db")
    output = tmp_path / "out.zip"
    create_zip(root, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["src/x.py"]
