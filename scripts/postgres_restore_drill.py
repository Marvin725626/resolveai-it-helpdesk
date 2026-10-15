"""Disposable PostgreSQL dump/restore drill for the isolated Docker demonstration.

Requires a successful live-check fixture. Stops only this deployment's app writers,
restores to a new UUID database and temporary attachment directory, verifies both,
then removes only that newly created database and resumes the app. Not a production
restore/cutover tool; the original database and attachment volume are never replaced.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from docker_deploy import ROOT, compose_configuration
from recovery_bundle import KEY_PATTERN, _ensure_private_parent, _reject_link_components, _sha256


def run(args, *, environment=None, data=None):
    result = subprocess.run(args, cwd=ROOT, env=environment, input=data, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=240)
    if result.returncode:
        # Commands contain no passwords. Avoid exposing connection/DB exception text.
        raise RuntimeError("Recovery operation failed: " + args[0] + " (exit " + str(result.returncode) + ")")
    return result.stdout.strip()


def drill(*, offline_confirmed=False):
    if not offline_confirmed:
        raise ValueError("Use --offline-confirmed to allow a brief stop of this isolated Docker app")
    compose, environment, _ = compose_configuration()
    fixture_path = _reject_link_components(ROOT / ".local/docker/deployment-fixture.json", ROOT)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not KEY_PATTERN.fullmatch(fixture.get("storage_key", "")):
        raise ValueError("Run live-check first; a valid synthetic deployment fixture is required")
    def service_id(service):
        identity = run(compose + ["ps", "--all", "--quiet", service], environment=environment)
        if not re.fullmatch(r"[0-9a-f]{12,64}", identity):
            raise ValueError("Expected exactly one existing deployment container for " + service)
        return identity
    postgres, backend = service_id("postgres"), service_id("backend")
    marker = uuid4().hex
    database = "resolveai_restore_" + marker
    remote_dump = "/tmp/resolveai-recovery-" + marker + ".dump"
    remote_files = "/tmp/resolveai-recovery-" + marker
    bundle = _ensure_private_parent(ROOT / ".local/backups" / ("pg-" + marker), ROOT, "backups")
    restored = _ensure_private_parent(ROOT / ".local/restores" / ("pg-" + marker), ROOT, "restores")
    if bundle.exists() or restored.exists():
        raise FileExistsError("Recovery output must be new")
    bundle.mkdir(mode=0o700); restored.mkdir(mode=0o700)
    created_database = False
    stopped = False
    report = None
    def pg(*args):
        return run(["docker", "exec", postgres, *args], environment=environment)
    try:
        run(compose + ["stop", "frontend", "backend"], environment=environment)
        stopped = True
        if run(["docker", "inspect", "--format", "{{.State.Running}}", backend], environment=environment) != "false":
            raise RuntimeError("Deployment writers must be stopped before backup")
        rows = json.loads(pg("psql", "-U", "resolveai", "-d", "resolveai", "-tA", "-c",
            "SELECT COALESCE(json_agg(json_build_object('storage_key',storage_key,'sha256',sha256,'bytes',size_bytes)), '[]'::json) FROM resolveai_ticket_attachments WHERE deleted_at IS NULL"))
        pg("pg_dump", "-U", "resolveai", "-d", "resolveai", "--format=custom", "--no-owner", "--no-privileges", "--file=" + remote_dump)
        dump = bundle / "database.dump"
        run(["docker", "cp", postgres + ":" + remote_dump, str(dump)], environment=environment)
        for row in rows:
            key = row["storage_key"]
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError("Invalid private attachment key")
            target = bundle / "attachments" / key
            target.parent.mkdir(parents=True, exist_ok=True)
            run(["docker", "cp", backend + ":/var/lib/resolveai/attachments/" + key, str(target)], environment=environment)
            _reject_link_components(target, ROOT)
            if target.is_symlink() or target.stat().st_size != row["bytes"] or _sha256(target) != row["sha256"]:
                raise ValueError("Snapshot attachment differs from database metadata")
        (bundle / "attachments").mkdir(exist_ok=True)
        manifest = {"format":"resolveai-postgres-drill-v1", "database":{"bytes":dump.stat().st_size,"sha256":_sha256(dump)}, "attachments":rows, "fixture":fixture}
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        # Independent local copies are the attachment side of the restore.
        import shutil
        shutil.copytree(bundle / "attachments", restored / "attachments")
        for row in rows:
            if _sha256(restored / "attachments" / row["storage_key"]) != row["sha256"]:
                raise ValueError("Restored attachment hash mismatch")
        if _sha256(dump) != manifest["database"]["sha256"]:
            raise ValueError("Dump checksum mismatch")
        pg("createdb", "-U", "resolveai", database)
        created_database = True
        pg("pg_restore", "-U", "resolveai", "--dbname=" + database, "--no-owner", "--no-privileges", "--exit-on-error", remote_dump)
        run(["docker", "cp", str(restored), backend + ":" + remote_files], environment=environment)
        run(compose + ["up", "--detach", "--wait", "--wait-timeout", "240", "backend", "frontend"], environment=environment)
        stopped = False
        program = ("import os,sys,runpy; from sqlalchemy.engine import make_url; "
            "os.environ['DATABASE_URL']=make_url(os.environ['DATABASE_URL']).set(database=sys.argv[1]).render_as_string(hide_password=False); "
            "os.environ['IT_ATTACHMENT_ROOT']=sys.argv[2]; "
            "runpy.run_path('/app/scripts/verify_deployment_fixture.py',run_name='__main__')")
        output = run(["docker", "exec", "--interactive", backend, "python", "-c", program, database, remote_files + "/attachments"],
                     environment=environment, data=json.dumps(fixture))
        verified = json.loads(output.splitlines()[-1])
        if verified.get("fixture_verified") is not True:
            raise RuntimeError("Restored fixture verification failed")
        report = {"postgres_dump_restore_passed":True, "attachment_count":len(rows),
            "attachment_sha256_match":True, "restored_closed_ticket_rating_and_published_vectors":True,
            "source_database_untouched":True, "temporary_restore_database_removed":False,
            "private_backup":str(bundle), "verification":verified}
    finally:
        if created_database:
            if not re.fullmatch(r"resolveai_restore_[0-9a-f]{32}", database):
                raise ValueError("Refusing cleanup outside the disposable restore database")
            pg("dropdb", "-U", "resolveai", "--force", database)
            if report is not None: report["temporary_restore_database_removed"] = True
        pg("rm", "-f", "--", remote_dump)
        if not stopped:
            cleanup = "import pathlib,re,shutil,sys; p=pathlib.Path(sys.argv[1]); assert p.parent==pathlib.Path('/tmp') and re.fullmatch('resolveai-recovery-[0-9a-f]{32}',p.name); shutil.rmtree(p,ignore_errors=True)"
            run(["docker","exec","--user","0",backend,"python","-c",cleanup,remote_files],environment=environment)
        if stopped:
            run(compose + ["up", "--detach", "--wait", "--wait-timeout", "240", "backend", "frontend"],environment=environment)
    if report is not None:
        (restored / "verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-confirmed",action="store_true")
    args=parser.parse_args()
    print(json.dumps(drill(offline_confirmed=args.offline_confirmed),indent=2))
