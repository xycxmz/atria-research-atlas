"""Run the frozen public demo. Never overwrite a different existing database."""
import gzip
import hashlib
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
EXPECTED = "0a9427476ea059be989bf7a0d6953d0d54e04939cba6bf708a65fa58e2d51660"

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def prepare():
    db = ROOT / "data" / "unified.db"
    if db.exists():
        if sha256(db) != EXPECTED:
            raise RuntimeError("Existing database differs. Back it up and move it aside; no file was overwritten.")
        return db
    archive = db.with_suffix(".db.gz")
    if not archive.is_file():
        raise RuntimeError("Missing data/unified.db.gz. Download the complete public repository.")
    temporary = db.with_suffix(".db.restoring")
    if temporary.exists():
        raise RuntimeError("A previous restore file exists. Inspect data/unified.db.restoring before retrying.")
    h = hashlib.sha256()
    with gzip.open(archive, "rb") as source, temporary.open("xb") as target:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
            target.write(chunk)
    if h.hexdigest() != EXPECTED:
        raise RuntimeError("Snapshot checksum mismatch; restored file was NOT installed.")
    temporary.replace(db)
    return db

if __name__ == "__main__":
    prepare()
    if "--prepare-only" in sys.argv:
        print("Snapshot verified.")
    else:
        port = sys.argv[1] if len(sys.argv) > 1 else "8000"
        print("Open http://127.0.0.1:" + port + "/ (Ctrl+C to stop)", flush=True)
        subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "serve_api.py"),
                        "--port", port, "--data-dir", str(ROOT / "data"),
                        "--static-dir", str(ROOT / "web" / "dist")], check=True)
