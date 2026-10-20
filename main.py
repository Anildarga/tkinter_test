import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from update_core import UpdateError, verify_manifest
from update_public_key import PUBLIC_KEY_B64

APP_NAME = "SampleApp"
APP_VERSION = "1.1.1"
# APP_MESSAGE = "Signed, staged updates for the whole application folder."
APP_MESSAGE = "Signed, update testing."
MANIFEST_URL = "https://anildarga.github.io/tkinter_test/latest.json"
REQUEST_TIMEOUT = 20
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
CHECK_INTERVAL_SECONDS = 24 * 60 * 60


def request(url):
    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    return urlopen(req, timeout=REQUEST_TIMEOUT)


def read_manifest():
    with request(MANIFEST_URL) as response:
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise UpdateError("The update manifest is too large.")
    manifest = verify_manifest(raw, PUBLIC_KEY_B64)
    if Version(APP_VERSION) < Version(manifest["min_version"]):
        raise UpdateError(
            f"Version {APP_VERSION} is too old for update {manifest['version']}."
        )
    return manifest


def download_package(manifest):
    temp_dir = Path(tempfile.mkdtemp(prefix=f"{APP_NAME}-update-"))
    archive = temp_dir / f"{APP_NAME}.zip"
    digest = hashlib.sha256()
    total = 0

    try:
        with request(manifest["url"]) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise UpdateError("The update package exceeds the size limit.")
                digest.update(chunk)
                output.write(chunk)

        if digest.hexdigest().lower() != manifest["sha256"]:
            raise UpdateError("The downloaded package failed SHA-256 verification.")
        return archive
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def state_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise OSError("LOCALAPPDATA is not available.")
    directory = Path(local_app_data) / APP_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "update-check.json"


def check_is_due():
    try:
        last_check = float(json.loads(state_path().read_text("utf-8"))["last_check"])
        return time.time() - last_check >= CHECK_INTERVAL_SECONDS
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return True


def record_check():
    path = state_path()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"last_check": time.time()}), encoding="utf-8")
    os.replace(temp, path)


def version_is_newer(candidate):
    try:
        return Version(candidate) > Version(APP_VERSION)
    except InvalidVersion as error:
        raise UpdateError(f"Invalid release version: {candidate}") from error


def start_update(events, manifest):
    events.put(("status", f"Preparing version {manifest['version']}..."))

    def worker():
        archive = None
        try:
            archive = download_package(manifest)
            app_dir = Path(sys.executable).resolve().parent
            updater_source = app_dir / "Updater.exe"
            if not updater_source.is_file():
                raise FileNotFoundError("Updater.exe is missing from the app folder.")

            updater_copy = (
                Path(tempfile.gettempdir())
                / f"{APP_NAME}-Updater-{os.getpid()}-{time.time_ns()}.exe"
            )
            shutil.copy2(updater_source, updater_copy)
            subprocess.Popen(
                [
                    str(updater_copy),
                    str(app_dir),
                    str(archive),
                    str(os.getpid()),
                    "SampleApp.exe",
                    manifest["sha256"],
                ],
                cwd=str(app_dir.parent),
                close_fds=True,
            )
            events.put(("close", None))
        except (OSError, UpdateError, HTTPError, URLError) as error:
            if archive:
                shutil.rmtree(archive.parent, ignore_errors=True)
            events.put(("status", f"Update failed: {error}"))

    threading.Thread(target=worker, daemon=True).start()


def check_for_updates(events, manual=False):
    events.put(("status", "Checking for updates..."))

    def worker():
        try:
            if not manual and not check_is_due():
                events.put(("status", "Next automatic check is due tomorrow."))
                return
            record_check()
            manifest = read_manifest()
            if not version_is_newer(manifest["version"]):
                events.put(("status", "You have the latest version."))
                return
            events.put(("offer", manifest))
        except (OSError, ValueError, UpdateError, HTTPError, URLError) as error:
            events.put(("status", f"Update check unavailable: {error}"))

    threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("460x300")
    root.resizable(False, False)

    tk.Label(root, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(pady=(30, 8))
    tk.Label(root, text=f"Version: {APP_VERSION}", font=("Segoe UI", 12)).pack(pady=5)
    tk.Label(root, text=APP_MESSAGE, font=("Segoe UI", 10), wraplength=420).pack(pady=8)
    status = tk.Label(root, text="Ready", font=("Segoe UI", 9), wraplength=420)
    status.pack(pady=10)
    events = queue.Queue()

    def process_ui_events():
        try:
            while True:
                event, payload = events.get_nowait()
                if event == "status":
                    status.config(text=payload)
                elif event == "offer":
                    message = payload["notes"] or "A new version is available."
                    if messagebox.askyesno(
                        "Update available",
                        f"Version {payload['version']} is available.\n\n{message}\n\n"
                        "Download and install it?",
                        parent=root,
                    ):
                        start_update(events, payload)
                    else:
                        status.config(text="Update postponed.")
                elif event == "close":
                    root.destroy()
                    return
        except queue.Empty:
            pass
        root.after(100, process_ui_events)

    tk.Button(
        root,
        text="Check for updates",
        command=lambda: check_for_updates(events, manual=True),
    ).pack(pady=8)
    root.after(100, process_ui_events)
    root.after(500, lambda: check_for_updates(events))
    root.mainloop()


if __name__ == "__main__":
    main()
