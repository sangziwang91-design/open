import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
OUTPUT = ROOT / "dist" / "agentbridge-chat-loop.zip"
REQUIRED = {
    "manifest.json",
    "background.js",
    "brain-prompt.txt",
    "bridge-core.js",
    "chatgpt-adapter.js",
    "content.js",
    "options.html",
    "options.js",
}


def package_extension(output: Path = OUTPUT) -> Path:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != 3:
        raise ValueError("extension must use Manifest V3")
    missing = sorted(name for name in REQUIRED if not (EXTENSION / name).is_file())
    if missing:
        raise FileNotFoundError(f"extension files are missing: {', '.join(missing)}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(EXTENSION.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.name == "README.md":
                continue
            info = zipfile.ZipInfo(path.name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return output


if __name__ == "__main__":
    print(package_extension())
