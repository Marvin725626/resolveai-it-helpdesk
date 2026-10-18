"""Download checksum-locked official BANKING77 data into the ignored local directory."""
import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "source_manifest.json").read_text(encoding="utf-8"))
    target = root / ".local" / "data"
    target.mkdir(parents=True, exist_ok=True)
    for name, entry in manifest["files"].items():
        path = target / name
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise RuntimeError("Existing data checksum mismatch: " + name)
            print("Verified existing " + name)
            continue
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "ResolveAI-public-benchmark"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError("Downloaded data checksum mismatch: " + name)
        path.write_bytes(data)
        print("Downloaded and verified " + name)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
