import argparse
import base64
import getpass
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from update_core import canonical_manifest, verify_manifest
from update_public_key import PUBLIC_KEY_B64


def main():
    parser = argparse.ArgumentParser(description="Sign an update manifest with Ed25519.")
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    password = os.environ.get("UPDATE_SIGNING_PASSPHRASE")
    if password is None:
        password = getpass.getpass("Private-key passphrase: ")

    try:
        key_bytes = args.private_key.read_bytes()
        private_key = serialization.load_pem_private_key(
            key_bytes,
            password=password.encode("utf-8"),
        )
    except (OSError, ValueError, TypeError) as error:
        parser.error(f"Could not load the encrypted private key: {error}")
    if not isinstance(private_key, Ed25519PrivateKey):
        parser.error("The private key must be Ed25519.")

    manifest = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or "signature" in manifest:
        parser.error("Input must be an unsigned manifest JSON object.")
    signature = private_key.sign(canonical_manifest(manifest))
    manifest["signature"] = base64.b64encode(signature).decode("ascii")
    verify_manifest(
        json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        PUBLIC_KEY_B64,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Signed manifest written to: {args.output}")


if __name__ == "__main__":
    main()
