import base64
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import InvalidVersion, Version


class UpdateError(Exception):
    """Raised when release metadata or an update package is invalid."""


def canonical_manifest(manifest):
    unsigned = {key: value for key, value in manifest.items() if key != "signature"}
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def verify_manifest(raw, public_key_b64):
    if not public_key_b64 or "PASTE_PUBLIC_KEY_HERE" in public_key_b64:
        raise UpdateError(
            "Configure PUBLIC_KEY_B64 in update_public_key.py before building."
        )

    try:
        manifest = json.loads(raw)
        required = {"version", "url", "sha256", "signature", "notes", "min_version"}
        if not isinstance(manifest, dict) or not required.issubset(manifest):
            raise UpdateError("The update manifest is missing required fields.")

        version = Version(manifest["version"])
        minimum = Version(manifest["min_version"])
        if version <= minimum:
            raise UpdateError("Release version must be newer than minimum version.")
        if not isinstance(manifest["url"], str) or not manifest["url"].startswith(
            "https://"
        ):
            raise UpdateError("The package URL must use HTTPS.")
        if not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]):
            raise UpdateError("The package SHA-256 value is invalid.")
        if not isinstance(manifest["notes"], str):
            raise UpdateError("Release notes must be text.")

        signature = base64.b64decode(manifest["signature"], validate=True)
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True)
        )
        public_key.verify(signature, canonical_manifest(manifest))
    except UpdateError:
        raise
    except (ValueError, TypeError, KeyError, InvalidVersion, InvalidSignature) as error:
        raise UpdateError("The update manifest is invalid or its signature is invalid.") from error

    return manifest


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def extract_update(archive_path, destination, app_executable):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total_size = 0
    max_total_size = 4 * 1024 * 1024 * 1024
    max_entries = 20_000

    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > max_entries:
                raise UpdateError("The update package contains too many files.")

            for member in members:
                raw_name = member.filename.replace("\\", "/")
                posix_name = PurePosixPath(raw_name)
                windows_name = PureWindowsPath(raw_name)
                if (
                    not raw_name
                    or posix_name.is_absolute()
                    or windows_name.is_absolute()
                    or windows_name.drive
                    or not posix_name.parts
                    or any(part in ("", ".", "..") for part in posix_name.parts)
                ):
                    raise UpdateError("The update package contains an unsafe path.")

                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UpdateError("The update package contains a symbolic link.")

                target = (destination / Path(*posix_name.parts)).resolve()
                if not target.is_relative_to(destination):
                    raise UpdateError("The update package contains an unsafe path.")

                total_size += member.file_size
                if total_size > max_total_size:
                    raise UpdateError("The extracted update exceeds the size limit.")

                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
    except zipfile.BadZipFile as error:
        raise UpdateError("The downloaded package is not a valid ZIP file.") from error

    if not (destination / app_executable).is_file():
        raise UpdateError(f"The package is missing {app_executable}.")
    if not (destination / "Updater.exe").is_file():
        raise UpdateError("The package is missing Updater.exe.")
