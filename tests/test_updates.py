import base64
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import updater
import sign_manifest
from update_core import (
    UpdateError,
    canonical_manifest,
    extract_update,
    verify_manifest,
)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = base64.b64encode(
            self.private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        ).decode("ascii")

    def signed_manifest(self):
        manifest = {
            "version": "1.2.0rc1",
            "url": "https://github.com/example/app/releases/download/v1.2.0rc1/app.zip",
            "sha256": "a" * 64,
            "notes": "Release candidate",
            "min_version": "1.0.0",
        }
        manifest["signature"] = base64.b64encode(
            self.private_key.sign(canonical_manifest(manifest))
        ).decode("ascii")
        return manifest

    def test_accepts_valid_signature_and_prerelease(self):
        manifest = self.signed_manifest()
        verified = verify_manifest(json.dumps(manifest).encode(), self.public_key)
        self.assertEqual(verified["version"], "1.2.0rc1")

    def test_rejects_tampered_manifest(self):
        manifest = self.signed_manifest()
        manifest["notes"] = "Modified after signing"
        with self.assertRaises(UpdateError):
            verify_manifest(json.dumps(manifest).encode(), self.public_key)

    def test_rejects_unsigned_manifest(self):
        with self.assertRaises(UpdateError):
            verify_manifest(b'{"version":"1.2.0"}', self.public_key)

    def test_signing_script_writes_a_manifest_matching_embedded_key(self):
        private_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(b"test-passphrase"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            key_path = root / "private.pem"
            input_path = root / "unsigned.json"
            output_path = root / "latest.json"
            key_path.write_bytes(private_pem)
            input_path.write_text(
                json.dumps(
                    {
                        "version": "1.2.0",
                        "url": "https://github.com/example/app/releases/download/v1.2.0/app.zip",
                        "sha256": "b" * 64,
                        "notes": "Test",
                        "min_version": "1.0.0",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "sign_manifest.py",
                        "--private-key",
                        str(key_path),
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                    ],
                ),
                patch.dict(os.environ, {"UPDATE_SIGNING_PASSPHRASE": "test-passphrase"}),
                patch.object(sign_manifest, "PUBLIC_KEY_B64", self.public_key),
            ):
                sign_manifest.main()

            signed = output_path.read_bytes()
            self.assertEqual(verify_manifest(signed, self.public_key)["version"], "1.2.0")


class ArchiveTests(unittest.TestCase):
    def test_extracts_complete_app_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "update.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("SampleApp.exe", b"new-app")
                archive.writestr("Updater.exe", b"updater")
                archive.writestr("_internal/library.dll", b"library")
            destination = root / "staged"
            extract_update(archive_path, destination, "SampleApp.exe")
            self.assertEqual((destination / "SampleApp.exe").read_bytes(), b"new-app")
            self.assertEqual(
                (destination / "_internal/library.dll").read_bytes(),
                b"library",
            )

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../outside.txt", b"bad")
                archive.writestr("SampleApp.exe", b"app")
                archive.writestr("Updater.exe", b"updater")
            with self.assertRaises(UpdateError):
                extract_update(archive_path, root / "stage", "SampleApp.exe")
            self.assertFalse((root / "outside.txt").exists())


class InstallerTests(unittest.TestCase):
    def test_replaces_whole_folder_and_keeps_previous_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            app_dir = parent / "SampleApp"
            app_dir.mkdir()
            (app_dir / "SampleApp.exe").write_bytes(b"old-app")
            (app_dir / "Updater.exe").write_bytes(b"old-updater")

            archive = parent / "download.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("SampleApp.exe", b"new-app")
                bundle.writestr("Updater.exe", b"new-updater")
                bundle.writestr("_internal/new.dll", b"new-library")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()

            class RunningProcess:
                @staticmethod
                def poll():
                    return None

            with (
                patch.object(updater, "wait_for_process"),
                patch.object(updater.subprocess, "Popen", return_value=RunningProcess()),
                patch.object(updater.time, "sleep"),
            ):
                updater.install_update(
                    app_dir,
                    archive,
                    42,
                    "SampleApp.exe",
                    digest,
                )

            self.assertEqual((app_dir / "SampleApp.exe").read_bytes(), b"new-app")
            self.assertEqual(
                (app_dir / "_internal/new.dll").read_bytes(),
                b"new-library",
            )
            backups = list(parent.glob("SampleApp.backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "SampleApp.exe").read_bytes(), b"old-app")


if __name__ == "__main__":
    unittest.main()
