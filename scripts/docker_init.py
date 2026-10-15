"""Create private local Docker configuration once. Never prints credentials."""
import argparse
import os
from pathlib import Path
import re
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".local" / "docker" / ".env"


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        account = subprocess.check_output(["whoami"], text=True).strip()
        subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", account + ":(OI)(CI)F"],
                       check=True, stdout=subprocess.DEVNULL)
    else:
        path.chmod(0o700)


def initialize(project="resolveai-local", api_port=8114, web_port=5184):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,45}", project):
        raise ValueError("Project name must contain 2–46 lowercase letters, digits, underscores or hyphens")
    if any(not 1024 <= port <= 65535 for port in (api_port, web_port)) or api_port == web_port:
        raise ValueError("Choose distinct unprivileged API and web ports")
    if ENV_FILE.exists():
        raise FileExistsError("Private Docker configuration already exists; preserve it for existing volumes")
    private_directory(ENV_FILE.parent)
    # Hex values are URL/env safe; there is no reusable password fallback.
    content = {"RESOLVEAI_COMPOSE_PROJECT": project, "RESOLVEAI_DOCKER_API_PORT": str(api_port),
               "RESOLVEAI_DOCKER_WEB_PORT": str(web_port), "POSTGRES_PASSWORD": secrets.token_hex(32),
               "AUTH_SECRET": secrets.token_hex(48), "IT_DEMO_PASSWORD": secrets.token_hex(24) + "Aa1!"}
    descriptor = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
        target.write("".join(key + "=" + value + "\n" for key, value in content.items()))
    print("Created private .local/docker/.env. Credentials were not printed. Keep this file with your backups.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="resolveai-local")
    parser.add_argument("--api-port", type=int, default=8114)
    parser.add_argument("--web-port", type=int, default=5184)
    args = parser.parse_args()
    try:
        initialize(args.project, args.api_port, args.web_port)
    except (FileExistsError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
