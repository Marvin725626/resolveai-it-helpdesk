"""Offline SQLite plus private attachment backup bundles and safe restores.

This deliberately does not stop services or claim a live, cross-file snapshot.
Stop application writers before backing up and pass --offline-confirmed.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

FORMAT = "resolveai-recovery-bundle"
BUNDLE_VERSION = 1
DATABASE_NAME = "database.sqlite3"
MANIFEST_NAME = "manifest.json"
ATTACHMENT_TABLE = "resolveai_ticket_attachments"
KEY_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _is_junction(path):
    check = getattr(path, "is_junction", None)
    return bool(check and check())


def _reject_link_components(path, root):
    """Reject symlinks/junctions from the trusted root through path, including the leaf."""
    root_input = Path(root).absolute()
    if root_input.is_symlink() or _is_junction(root_input):
        raise ValueError("Allowed root cannot be a symlink or junction")
    resolved_root = root_input.resolve()
    path_input = Path(path).absolute()
    if ".." in path_input.parts:
        raise ValueError("Path traversal is not allowed")
    resolved_path = path_input.resolve(strict=False)
    if not resolved_path.is_relative_to(resolved_root):
        raise ValueError("Path escapes the allowed project root")
    # On Windows, temp paths may use an 8.3 alias while the root uses its long name.
    # Walk the caller's original components until reaching the same resolved root.
    current = path_input
    found_root = False
    while True:
        if current.is_symlink() or _is_junction(current):
            raise ValueError("Symlinks and junctions are not allowed in recovery paths")
        if current.resolve(strict=False) == resolved_root:
            found_root = True
            break
        if current.parent == current:
            break
        current = current.parent
    if not found_root:
        raise ValueError("Path must stay inside the allowed project root")
    return resolved_path


def _ensure_private_parent(path, root, folder_name):
    path = Path(path).absolute()
    root = Path(root).resolve()
    expected_parent = root / ".local" / folder_name
    resolved_path = _reject_link_components(path, root)
    if resolved_path.parent != expected_parent:
        raise ValueError(f"Target must be a direct child of .local/{folder_name}")
    _reject_link_components(expected_parent, root)
    expected_parent.mkdir(parents=True, exist_ok=True)
    _reject_link_components(expected_parent, root)
    return resolved_path


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_checks(path):
    with closing(sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        if integrity != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise ValueError("SQLite foreign key check failed")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if ATTACHMENT_TABLE not in tables:
            return None, []
        schema_version = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
            schema_version = row[0] if row else None
        rows = connection.execute(f"SELECT storage_key,size_bytes,sha256 FROM {ATTACHMENT_TABLE} WHERE deleted_at IS NULL").fetchall()
        for key, size, digest in rows:
            if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
                raise ValueError("Database contains an invalid private attachment key")
            if not isinstance(size, int) or size < 0 or not re.fullmatch(r"[0-9a-f]{64}", digest or ""):
                raise ValueError("Database contains invalid attachment metadata")
        return schema_version, rows


def _staging_dir(parent, prefix):
    path = parent / f".{prefix}.staging-{uuid.uuid4().hex}"
    path.mkdir(mode=0o700)
    marker = parent / (path.name + ".owner")
    token = uuid.uuid4().hex
    try:
        with marker.open("x", encoding="ascii") as stream:
            stream.write(token)
    except Exception:
        path.rmdir()
        raise
    return path, marker, token


def _cleanup_staging(path, parent, marker, token, root):
    """Delete only this operation's verified staging directory."""
    path, parent, marker = Path(path), Path(parent), Path(marker)
    if path.parent != parent or not re.fullmatch(r"\..+\.staging-[0-9a-f]{32}", path.name):
        return False
    try:
        _reject_link_components(path, root)
        if marker.parent != parent or marker.name != path.name + ".owner" or marker.is_symlink() or not marker.is_file():
            return False
        if marker.read_text(encoding="ascii") != token:
            return False
        shutil.rmtree(path)
        marker.unlink()
        return True
    except (OSError, ValueError):
        return False


def _read_manifest(bundle, root):
    bundle = _reject_link_components(bundle, root)
    if not bundle.is_dir():
        raise ValueError("Bundle directory does not exist")
    entries = {item.name: item for item in bundle.iterdir()}
    if set(entries) != {MANIFEST_NAME, DATABASE_NAME, "attachments"}:
        raise ValueError("Bundle contains unexpected or missing entries")
    for entry in entries.values():
        _reject_link_components(entry, root)
    manifest_path = entries[MANIFEST_NAME]
    if not manifest_path.is_file() or manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Invalid bundle manifest")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Manifest contains duplicate keys")
            result[key] = value
        return result
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(manifest, dict) or set(manifest) != {"format", "bundle_version", "created_at", "schema_version", "database", "attachments"}:
        raise ValueError("Manifest fields are not recognized")
    if manifest["format"] != FORMAT or manifest["bundle_version"] != BUNDLE_VERSION:
        raise ValueError("Unsupported recovery bundle format")
    dbinfo = manifest["database"]
    if not isinstance(dbinfo, dict) or set(dbinfo) != {"path", "bytes", "sha256"} or dbinfo["path"] != DATABASE_NAME:
        raise ValueError("Invalid database manifest entry")
    dbfile = entries[DATABASE_NAME]
    if not dbfile.is_file() or dbfile.stat().st_size != dbinfo["bytes"] or _sha256(dbfile) != dbinfo["sha256"]:
        raise ValueError("Database hash or size does not match the manifest")
    attachments = manifest["attachments"]
    if not isinstance(attachments, list):
        raise ValueError("Invalid attachment manifest")
    declared = set()
    for item in attachments:
        if not isinstance(item, dict) or set(item) != {"storage_key", "bytes", "sha256"}:
            raise ValueError("Invalid attachment manifest entry")
        key = item["storage_key"]
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key) or key in declared:
            raise ValueError("Attachment manifest contains an invalid or duplicate UUID key")
        if not isinstance(item["bytes"], int) or item["bytes"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"] or ""):
            raise ValueError("Attachment manifest contains invalid size or hash")
        declared.add(key)
        path = entries["attachments"].joinpath(*key.split("/"))
        _reject_link_components(path, root)
        if not path.is_file() or path.stat().st_size != item["bytes"] or _sha256(path) != item["sha256"]:
            raise ValueError("Attachment hash or size does not match the manifest")
    attachment_root = entries["attachments"]
    if not attachment_root.is_dir():
        raise ValueError("Invalid attachments directory")
    actual = set()
    actual_folders = set()
    for folder in attachment_root.iterdir():
        _reject_link_components(folder, root)
        if not folder.is_dir() or not re.fullmatch(r"[0-9a-f-]{36}", folder.name):
            raise ValueError("Bundle contains an unexpected attachment directory")
        actual_folders.add(folder.name)
        for file in folder.iterdir():
            _reject_link_components(file, root)
            if not file.is_file() or not re.fullmatch(r"[0-9a-f-]{36}", file.name):
                raise ValueError("Bundle contains an unexpected attachment file")
            actual.add(folder.name + "/" + file.name)
    if actual != declared:
        raise ValueError("Bundle attachment files do not match the manifest")
    if actual_folders != {key.split("/", 1)[0] for key in declared}:
        raise ValueError("Bundle contains an unexpected empty attachment directory")
    schema_version, db_attachments = _sqlite_checks(dbfile)
    db_keys = {row[0] for row in db_attachments}
    if db_keys != declared:
        raise ValueError("Bundle attachment list does not match active database references")
    by_key = {item["storage_key"]: item for item in attachments}
    for key, size, digest in db_attachments:
        if by_key[key]["bytes"] != size or by_key[key]["sha256"] != digest:
            raise ValueError("Bundle attachment metadata disagrees with the database")
    if manifest["schema_version"] != schema_version:
        raise ValueError("Bundle schema version disagrees with the database")
    return manifest, dbfile, attachment_root


def backup_bundle(source_database, source_attachments, destination, allowed_root, *, offline_confirmed=False):
    if not offline_confirmed:
        raise ValueError("Stop all application writers and pass offline_confirmed=True before bundling SQLite and attachments")
    root = Path(allowed_root).resolve()
    source_database = _reject_link_components(source_database, root)
    source_attachments = _reject_link_components(source_attachments, root)
    destination = _ensure_private_parent(destination, root, "backups")
    if source_database == destination or not source_database.is_file():
        raise ValueError("Source database must be an existing file distinct from the bundle destination")
    if os.path.lexists(destination):
        raise FileExistsError("Refusing to overwrite an existing recovery bundle")
    parent = destination.parent
    staging, marker, token = _staging_dir(parent, destination.name)
    try:
        staged_db = staging / DATABASE_NAME
        with closing(sqlite3.connect(source_database.as_uri() + "?mode=ro", uri=True)) as reader:
            with closing(sqlite3.connect(staged_db)) as writer:
                reader.backup(writer)
                writer.commit()
        schema_version, attachments = _sqlite_checks(staged_db)
        declared = []
        for key, expected_size, expected_hash in attachments:
            source_file = _reject_link_components(source_attachments.joinpath(*key.split("/")), root)
            if not source_file.is_file() or source_file.stat().st_size != expected_size or _sha256(source_file) != expected_hash:
                raise ValueError("Active attachment is missing or does not match its database metadata")
            target_file = staging / "attachments" / key
            target_file.parent.mkdir(parents=True, exist_ok=True)
            _reject_link_components(target_file.parent, root)
            with source_file.open("rb") as src, target_file.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            declared.append({"storage_key": key, "bytes": expected_size, "sha256": expected_hash})
        (staging / "attachments").mkdir(exist_ok=True)
        manifest = {"format": FORMAT, "bundle_version": BUNDLE_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "schema_version": schema_version,
            "database": {"path": DATABASE_NAME, "bytes": staged_db.stat().st_size, "sha256": _sha256(staged_db)},
            "attachments": declared}
        with (staging / MANIFEST_NAME).open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        # Validate the finished bundle before making it visible at its final path.
        _read_manifest(staging, root)
        if os.path.lexists(destination):
            raise FileExistsError("Refusing to overwrite an existing recovery bundle")
        os.rename(staging, destination)
        marker.unlink(missing_ok=True)
        return {"path": str(destination), "database_bytes": manifest["database"]["bytes"],
            "attachment_count": len(declared), "bundle_version": BUNDLE_VERSION}
    except Exception:
        _cleanup_staging(staging, parent, marker, token, root)
        raise


def restore_bundle(bundle, destination, allowed_root):
    root = Path(allowed_root).resolve()
    bundle = _reject_link_components(bundle, root)
    if bundle.parent != root / ".local" / "backups":
        raise ValueError("Restore bundle must be a direct child of .local/backups")
    restore_target = _ensure_private_parent(destination, root, "restores")
    if os.path.lexists(restore_target):
        raise FileExistsError("Restore destination must not already exist")
    manifest, dbfile, attachment_root = _read_manifest(bundle, root)
    staging, marker, token = _staging_dir(restore_target.parent, restore_target.name)
    try:
        shutil.copyfile(dbfile, staging / DATABASE_NAME)
        shutil.copytree(attachment_root, staging / "attachments", dirs_exist_ok=True)
        with (staging / MANIFEST_NAME).open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        _read_manifest(staging, root)
        if os.path.lexists(restore_target):
            raise FileExistsError("Restore destination must not already exist")
        os.rename(staging, restore_target)
        marker.unlink(missing_ok=True)
        return {"path": str(restore_target), "database": str(restore_target / DATABASE_NAME),
            "attachments": str(restore_target / "attachments"), "attachment_count": len(manifest["attachments"])}
    except Exception:
        _cleanup_staging(staging, restore_target.parent, marker, token, root)
        raise


def main(argv=None):
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Private offline SQLite and attachment recovery bundles")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="create an offline-confirmed bundle")
    backup.add_argument("--database", default=str(project_root / "backend" / "resolveai.db"))
    backup.add_argument("--attachments", default=str(project_root / ".local" / "attachments"))
    backup.add_argument("--output")
    backup.add_argument("--offline-confirmed", action="store_true", help="confirm all app writers are stopped")
    restore = commands.add_parser("restore", help="validate and restore into a new private directory")
    restore.add_argument("--bundle", required=True)
    restore.add_argument("--destination", required=True, help="new direct child directory under .local/restores")
    args = parser.parse_args(argv)
    if args.command == "backup":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = args.output or str(project_root / ".local" / "backups" / ("resolveai-" + stamp))
        result = backup_bundle(args.database, args.attachments, output, project_root,
            offline_confirmed=args.offline_confirmed)
    else:
        result = restore_bundle(args.bundle, args.destination, project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
