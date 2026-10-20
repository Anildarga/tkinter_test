import argparse
import base64
import getpass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PROJECT_ROOT = Path(__file__).resolve().parent
PUBLIC_KEY_FILE = PROJECT_ROOT / "update_public_key.py"


def main():
    parser = argparse.ArgumentParser(
        description="Generate an Ed25519 update-signing keypair."
    )
    parser.add_argument(
        "--private-key",
        required=True,
        help="Path outside the project to store the encrypted private PEM.",
    )
    args = parser.parse_args()

    private_path = Path(args.private_key).expanduser().resolve()
    try:
        private_path.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    else:
        parser.error("Store the private key outside the project directory.")

    if private_path.exists():
        parser.error(f"Refusing to overwrite existing file: {private_path}")
    if not PUBLIC_KEY_FILE.exists():
        parser.error(f"Public-key config not found: {PUBLIC_KEY_FILE}")

    password = getpass.getpass("Private-key passphrase (12+ characters): ")
    confirmation = getpass.getpass("Confirm passphrase: ")
    if password != confirmation:
        parser.error("Passphrases do not match.")
    if len(password) < 12:
        parser.error("Use a passphrase with at least 12 characters.")

    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(
            password.encode("utf-8")
        ),
    )
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")

    private_path.parent.mkdir(parents=True, exist_ok=True)
    with private_path.open("xb") as private_file:
        private_file.write(private_pem)

    public_source = f'PUBLIC_KEY_B64 = "{public_b64}"\n'
    current = PUBLIC_KEY_FILE.read_text(encoding="utf-8")
    if "PASTE_PUBLIC_KEY_HERE" not in current:
        private_path.unlink(missing_ok=True)
        parser.error(
            f"{PUBLIC_KEY_FILE.name} already contains a configured key; "
            "back up the private key and update the config manually."
        )
    PUBLIC_KEY_FILE.write_text(public_source, encoding="utf-8")

    print(f"Encrypted private key saved to: {private_path}")
    print(f"Public key written to: {PUBLIC_KEY_FILE}")
    print("Never commit or upload the private key. Back it up securely.")
    print(
        "For GitHub Actions, store the base64-encoded private PEM and its "
        "passphrase as repository secrets."
    )
    print(
        "PowerShell encoding command: "
        f"[Convert]::ToBase64String([IO.File]::ReadAllBytes('{private_path}'))"
    )


if __name__ == "__main__":
    main()
