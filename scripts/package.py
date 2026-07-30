from pathlib import Path
import zipfile


EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    ".venv",
    "venv",
    "data",
}
EXCLUDED_NAMES = {"agentbridge.db", "sz-agentbridge.zip"}


def create_zip(root: Path, output: Path) -> Path:
    root = root.resolve()
    output = output.resolve()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.resolve() == output:
                continue
            relative = path.relative_to(root)
            if any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative.parts):
                continue
            if path.name in EXCLUDED_NAMES or path.suffix in {".pyc", ".pyo"}:
                continue
            archive.write(path, relative.as_posix())
    return output


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = create_zip(project_root, project_root / "sz-agentbridge.zip")
    print(result)
