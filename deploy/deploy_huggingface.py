"""Publish VITRA to a Hugging Face Docker Space.

Run from the repository root, in your own terminal:

    backend/.venv/bin/python deploy/deploy_huggingface.py --space <your-hf-username>/vitra

It asks for your Hugging Face token (write access) if you are not logged in, and for the
VITRA sign-in password. The password is stored only as a Space secret, never in the repository.
"""
from __future__ import annotations

import argparse
import getpass
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, get_token, login

ROOT = Path(__file__).resolve().parents[1]
SPACE_CARD = ROOT / "deploy" / "huggingface" / "README.md"


def tracked_files() -> list[str]:
    output = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    return [name for name in output.decode().split("\0") if name and (ROOT / name).is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", required=True, help="Space id, for example your-name/vitra")
    parser.add_argument("--username", default="admin", help="VITRA sign-in username (default: admin)")
    parser.add_argument("--private", action="store_true", help="Create the Space as private instead of public")
    parser.add_argument("--keep-secrets", action="store_true", help="Do not change the Space's existing password secrets")
    args = parser.parse_args()

    if not get_token():
        print("Log in with a Hugging Face token that has write access.")
        login()
    api = HfApi()

    api.create_repo(args.space, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)

    if not args.keep_secrets:
        password = getpass.getpass("Choose the VITRA sign-in password (at least 12 characters): ")
        if len(password) < 12 or password != getpass.getpass("Repeat the password: "):
            print("Passwords must match and be at least 12 characters.", file=sys.stderr)
            return 1
        api.add_space_variable(args.space, "AUTH_USERNAME", args.username)
        api.add_space_secret(args.space, "AUTH_PASSWORD", password)
        api.add_space_secret(args.space, "SESSION_SECRET", secrets.token_hex(32))

    with tempfile.TemporaryDirectory(prefix="vitra-space-") as staging:
        target = Path(staging)
        for name in tracked_files():
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        shutil.copy2(SPACE_CARD, target / "README.md")
        api.upload_folder(folder_path=target, repo_id=args.space, repo_type="space",
                          commit_message="Deploy VITRA from GitHub", delete_patterns=["*"])

    host = args.space.replace("/", "-").replace("_", "-").replace(".", "-").lower()
    print(f"\nUploaded. The image now builds on Hugging Face (about 10-15 minutes the first time).")
    print(f"Space page: https://huggingface.co/spaces/{args.space}")
    print(f"Direct app: https://{host}.hf.space")
    print(f"Sign in as '{args.username}' with the password you just chose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
