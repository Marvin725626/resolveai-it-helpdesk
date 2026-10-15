"""Repeatable Docker deployment; never deletes volumes or regenerates secrets."""
import argparse
import os
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".local" / "docker" / ".env"


def compose_configuration():
    values = dict(line.split("=", 1) for line in ENV_FILE.read_text(encoding="utf-8").splitlines() if "=" in line)
    project = values["RESOLVEAI_COMPOSE_PROJECT"]
    environment = {**os.environ, **values, "COMPOSE_PROJECT_NAME": project}
    command = ["docker", "compose", "--project-name", project, "--env-file", str(ENV_FILE), "-f", str(ROOT / "compose.resolveai.yml")]
    return command, environment, values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("up", "status", "stop", "postgres-check", "live-check", "recreate-check"), nargs="?", default="up")
    args = parser.parse_args()
    if not ENV_FILE.is_file():
        if args.action != "up":
            parser.error("Private deployment configuration is missing; run up or docker_init.py first")
        subprocess.run([sys.executable, str(ROOT / "scripts/docker_init.py")], check=True)
    command, environment, values = compose_configuration()
    operations = {"up": ["up", "--build", "--detach", "--wait", "--wait-timeout", "240"],
                  "status": ["ps"], "stop": ["stop"],
                  "postgres-check": ["exec", "-T", "backend", "python", "/app/scripts/postgres_smoke.py"],
                  "live-check": ["exec", "-T", "backend", "python", "/app/scripts/postgres_smoke.py", "--live"]}
    manifest_path=ENV_FILE.parent / "deployment-fixture.json"
    if args.action == "recreate-check":
        if not manifest_path.is_file():
            parser.error("Run live-check first to create the synthetic persistence fixture")
        manifest=manifest_path.read_text(encoding="utf-8")
        subprocess.run(command+["up","--detach","--force-recreate","--no-build","--wait","--wait-timeout","240"],cwd=ROOT,env=environment,check=True)
        subprocess.run(command+["exec","-T","backend","python","/app/scripts/verify_deployment_fixture.py"],input=manifest,text=True,cwd=ROOT,env=environment,check=True)
        print("Container recreation retained database, rating, published knowledge and attachment bytes.")
        return
    subprocess.run(command + operations[args.action], cwd=ROOT, env=environment, check=True)
    if args.action == "live-check":
        result=subprocess.run(command+["exec","-T","backend","cat","/tmp/resolveai-deployment-fixture.json"],cwd=ROOT,env=environment,check=True,capture_output=True,text=True)
        manifest=json.loads(result.stdout)
        descriptor=os.open(manifest_path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,"w",encoding="utf-8") as target:
            json.dump(manifest,target)
        print("Saved synthetic recovery manifest privately in .local/docker/deployment-fixture.json")
    if args.action == "up":
        print("ResolveAI Docker: http://127.0.0.1:" + values["RESOLVEAI_DOCKER_WEB_PORT"])
        print("Run the same command again to rebuild/restart while preserving database and attachments volumes.")


if __name__ == "__main__":
    main()
