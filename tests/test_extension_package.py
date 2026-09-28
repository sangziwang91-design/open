import json
import zipfile
from pathlib import Path

from scripts.package_extension import REQUIRED, package_extension

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_has_bounded_v3_permissions() -> None:
    manifest = json.loads(
        (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["manifest_version"] == 3
    assert manifest["permissions"] == ["storage"]
    assert manifest["content_scripts"][0]["matches"] == ["https://chatgpt.com/*"]
    assert all(
        origin.startswith(("http://127.0.0.1/", "http://localhost/"))
        for origin in manifest["host_permissions"]
    )
    background = (ROOT / "extension" / "background.js").read_text(encoding="utf-8")
    options = (ROOT / "extension" / "options.js").read_text(encoding="utf-8")
    content = (ROOT / "extension" / "content.js").read_text(encoding="utf-8")
    assert 'chrome.storage.local.get({ token: "" })' in background
    assert "chrome.storage.local.set({ token })" in options
    assert content.index("await Chat.insertAndMaybeSend") < content.index(
        "state.processed.add(key)"
    )
    handler = content[
        content.index("async function handleTask") : content.index("function scan")
    ]
    assert handler.index("state.busy = true") < handler.index(
        "const current = await config()"
    )


def test_extension_package_is_complete_and_reproducible(tmp_path: Path) -> None:
    first = package_extension(tmp_path / "first.zip")
    second = package_extension(tmp_path / "second.zip")
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert REQUIRED <= names
        assert "tests/core.test.js" not in names
