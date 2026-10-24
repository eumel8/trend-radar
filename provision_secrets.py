"""One-time secret import; never print credentials or store them in manifests."""
import base64
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parent


def put(name, data, kind="Opaque"):
    resource = {"apiVersion": "v1", "kind": "Secret", "metadata": {
        "name": name, "namespace": "trendsde"}, "type": kind,
        "data": {key: base64.b64encode(value).decode() for key, value in data.items()}}
    subprocess.run(["kubectl", "--context", "kubernetes-admin@kubernetes", "apply", "-f", "-"],
                   input=json.dumps(resource), text=True, check=True, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-registry", action="store_true",
                        help="Zusätzlich die frühere eigene Registry konfigurieren")
    args = parser.parse_args()
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise SystemExit("YOUTUBE_API_KEY fehlt")
    put("trendsde-api", {"api-key": key.encode()})
    put("trendsde-oauth", {"token.json": (ROOT / "runtime/token.json").read_bytes()})
    if os.environ.get("OPENAI_API_KEY"):
        put("trendsde-openai", {"api-key": os.environ["OPENAI_API_KEY"].encode()})
    if not args.legacy_registry:
        print("API- und OAuth-Secrets eingerichtet.")
        return
    directory = ROOT / "runtime/registry-auth"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "config.json"
    if path.exists():
        config = json.loads(path.read_text())
        encoded = config["auths"]["trendsde.b.eumel.de"]["auth"]
        user, password = base64.b64decode(encoded).decode().split(":", 1)
    else:
        user, password = "trendsde", secrets.token_urlsafe(32)
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        config = {"auths": {"trendsde.b.eumel.de": {"auth": encoded}}}
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle)
    # htpasswd bcrypt is provided by the existing Python environment's system crypt library.
    import crypt
    hashed = crypt.crypt(password, crypt.mksalt(crypt.METHOD_BLOWFISH))
    put("trendsde-registry-auth", {"htpasswd": f"{user}:{hashed}\n".encode()})
    put("trendsde-registry-pull", {".dockerconfigjson": json.dumps(config).encode()},
        "kubernetes.io/dockerconfigjson")
    print("API-, OAuth- und Registry-Secrets eingerichtet.")


if __name__ == "__main__":
    main()
