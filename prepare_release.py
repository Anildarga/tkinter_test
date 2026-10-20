import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from packaging.version import InvalidVersion, Version

APP_NAME = "SampleApp"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(
        description="Package the onedir app and write an unsigned update manifest."
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--minimum-version", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--repository", required=True, help="GitHub owner/repository")
    parser.add_argument("--app-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    try:
        version = Version(args.version)
        minimum = Version(args.minimum_version)
    except InvalidVersion as error:
        parser.error(f"Invalid release version: {error}")
    if version <= minimum:
        parser.error("Release version must be newer than its minimum supported version.")

    app_dir = args.app_dir.resolve()
    if not (app_dir / f"{APP_NAME}.exe").is_file():
        parser.error(f"Application executable missing from {app_dir}")
    if not (app_dir / "Updater.exe").is_file():
        parser.error(f"Updater.exe missing from {app_dir}")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    version_text = args.version.removeprefix("v")
    zip_path = output_dir / f"{APP_NAME}-{version_text}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(app_dir).as_posix())

    checksum = sha256_file(zip_path)
    (output_dir / f"{APP_NAME}-{version}.zip.sha256").write_text(
        f"{checksum}  {zip_path.name}\n",
        encoding="ascii",
    )
    tag = f"v{version_text}"
    manifest = {
        "version": version_text,
        "url": (
            f"https://github.com/{args.repository}/releases/download/"
            f"{tag}/{zip_path.name}"
        ),
        "sha256": checksum,
        "notes": args.notes,
        "min_version": str(minimum),
    }
    (output_dir / "latest-unsigned.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Package: {zip_path}")
    print(f"SHA-256: {checksum}")
    print(f"Unsigned manifest: {output_dir / 'latest-unsigned.json'}")


if __name__ == "__main__":
    main()
