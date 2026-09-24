from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.ini"

def read_version():
    text = MANIFEST.read_text(encoding="utf-8-sig")
    match = re.search(r"(?m)^\s*version\s*=\s*([^\r\n]+?)\s*$", text)
    if not match:
        raise RuntimeError("version not found in manifest.ini")
    return match.group(1).strip().strip('"').strip("'")

def add_tree(zf, base):
    if not base.exists():
        return
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        zf.write(path, path.relative_to(ROOT).as_posix())

def main():
    version = read_version()
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"eSpeakVoiceDesigner_{version}.nvda-addon"

    if out_file.exists():
        out_file.unlink()

    with zipfile.ZipFile(out_file, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(MANIFEST, "manifest.ini")
        if (ROOT / "LOCALIZATION_GUIDE.txt").exists():
            zf.write(ROOT / "LOCALIZATION_GUIDE.txt", "LOCALIZATION_GUIDE.txt")
        for folder in ("globalPlugins", "locale", "doc"):
            add_tree(zf, ROOT / folder)

    print(out_file)

if __name__ == "__main__":
    main()
