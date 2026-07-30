import zipfile
from pathlib import Path

from scripts.package import create_zip


def test_package_excludes_runtime_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "src" / "x.py").write_text("x=1")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"x")
    (root / "agentbridge.db").write_text("db")
    (root / ".env").write_text("SECRET=value")
    (root / ".env.local").write_text("SECRET=value")
    (root / ".env.example").write_text("SAFE=placeholder")
    (root / ".mypy_cache").mkdir()
    (root / ".mypy_cache" / "cache.json").write_text("{}")
    (root / "other.sqlite3").write_text("db")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    try:
        (root / "linked-secret.txt").symlink_to(outside)
    except OSError:
        pass
    output = tmp_path / "out.zip"
    create_zip(root, output)
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == [".env.example", "src/x.py"]
