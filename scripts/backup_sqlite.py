"""Private, consistent SQLite snapshots; never overwrites a backup or source."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

def backup_database(source, destination, allowed_root):
    source=Path(source).resolve();destination=Path(destination).resolve();allowed_root=Path(allowed_root).resolve()
    for path in (source,destination):
        if not path.is_relative_to(allowed_root):
            raise ValueError("Database and backup must stay inside the specified project root")
    if source==destination:
        raise ValueError("Backup must not replace the source database")
    if not source.is_file():
        raise FileNotFoundError("Source database does not exist")
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro",uri=True)) as reader:
            with closing(sqlite3.connect(destination)) as writer:
                reader.backup(writer)
                if writer.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                    raise RuntimeError("Backup integrity check did not pass")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    digest=hashlib.sha256(destination.read_bytes()).hexdigest()
    return {"path":str(destination),"bytes":destination.stat().st_size,"sha256":digest,"quick_check":"ok"}

def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();parser.add_argument("--database",default=str(root/"backend/resolveai.db"));parser.add_argument("--output");args=parser.parse_args()
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination=Path(args.output) if args.output else root/".local/backups"/("resolveai-"+stamp+".sqlite3")
    if not destination.resolve().is_relative_to((root/".local").resolve()):
        raise ValueError("CLI backups must stay in the private .local directory")
    print(json.dumps(backup_database(args.database,destination,root),ensure_ascii=False,indent=2))

if __name__=="__main__":main()
