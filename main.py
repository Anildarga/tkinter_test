import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_NAME = "SampleApp"
APP_VERSION = "1.0.2"
APP_MESSAGE = "Online updater test - Version 3"
GITHUB_REPOSITORY = "Anildarga/tkinter_test"
API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
REQUEST_TIMEOUT = 20
CHUNK_SIZE = 1024 * 1024


def request(url):
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
    )
    return urlopen(req, timeout=REQUEST_TIMEOUT)


def parse_version(value):
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise ValueError(f"Unsupported release version: {value}")
    return tuple(int(part) for part in match.groups())


def get_latest_release():
    with request(API_URL) as response:
        release = json.load(response)

    tag = release.get("tag_name", "")
    latest_version = parse_version(tag)
    if latest_version <= parse_version(APP_VERSION):
        return None

    assets = {
        asset.get("name"): asset.get("browser_download_url")
        for asset in release.get("assets", [])
    }
    exe_url = assets.get(f"{APP_NAME}.exe")
    checksum_url = assets.get(f"{APP_NAME}.exe.sha256")
    if not exe_url or not checksum_url:
        raise ValueError(
            f"Release {tag} must include {APP_NAME}.exe and "
            f"{APP_NAME}.exe.sha256."
        )

    return tag, exe_url, checksum_url


def download_and_verify(exe_url, checksum_url):
    with request(checksum_url) as response:
        checksum_text = response.read(4096).decode("ascii").strip()

    expected_hash = checksum_text.split()[0] if checksum_text else ""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise ValueError("The release checksum file is invalid.")

    temp_dir = Path(tempfile.mkdtemp(prefix="SampleApp-update-"))
    downloaded = temp_dir / f"{APP_NAME}.exe"
    digest = hashlib.sha256()

    try:
        with request(exe_url) as response, downloaded.open("wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                output.write(chunk)
                digest.update(chunk)

        if digest.hexdigest().lower() != expected_hash.lower():
            raise ValueError("The downloaded update failed SHA-256 verification.")
        return downloaded
    except Exception:
        downloaded.unlink(missing_ok=True)
        temp_dir.rmdir()
        raise


def run_update(events, release):
    _, exe_url, checksum_url = release
    events.put(("status", f"Downloading {release[0]}..."))

    def worker():
        try:
            downloaded = download_and_verify(exe_url, checksum_url)
            app_path = Path(sys.executable).resolve()
            updater = app_path.with_name("Updater.exe")
            if not updater.is_file():
                raise FileNotFoundError(
                    f"Updater.exe must be installed beside {app_path.name}."
                )
            subprocess.Popen(
                [str(updater), str(app_path), str(downloaded), str(os.getpid())],
                cwd=str(app_path.parent),
            )
            events.put(("close", None))
        except (OSError, ValueError, HTTPError, URLError) as error:
            events.put(("status", f"Update failed: {error}"))

    threading.Thread(target=worker, daemon=True).start()


def check_for_updates(events):
    events.put(("status", "Checking for updates..."))

    def worker():
        try:
            release = get_latest_release()
            if release is None:
                events.put(("status", "You have the latest version."))
                return

            events.put(("offer", release))
        except (OSError, ValueError, HTTPError, URLError, json.JSONDecodeError) as error:
            events.put(("status", f"Update check failed: {error}"))

    threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("420x270")
    root.resizable(False, False)

    tk.Label(root, text=APP_NAME, font=("Segoe UI", 18, "bold")).pack(pady=(30, 8))
    tk.Label(root, text=f"Version: {APP_VERSION}", font=("Segoe UI", 12)).pack(pady=5)
    tk.Label(root, text=APP_MESSAGE, font=("Segoe UI", 10)).pack(pady=8)
    status = tk.Label(root, text="Starting...", font=("Segoe UI", 9), wraplength=380)
    status.pack(pady=10)
    events = queue.Queue()

    def process_ui_events():
        try:
            while True:
                event, payload = events.get_nowait()
                if event == "status":
                    status.config(text=payload)
                elif event == "offer":
                    tag, _, _ = payload
                    if messagebox.askyesno(
                        "Update available",
                        f"{tag} is available. You are running v{APP_VERSION}.\n"
                        "Download and install the update?",
                        parent=root,
                    ):
                        run_update(events, payload)
                    else:
                        status.config(text=f"Update {tag} is available.")
                elif event == "close":
                    root.destroy()
                    return
        except queue.Empty:
            pass
        root.after(100, process_ui_events)

    tk.Button(
        root,
        text="Check for updates",
        command=lambda: check_for_updates(events),
    ).pack(pady=8)

    root.after(100, process_ui_events)
    root.after(500, lambda: check_for_updates(events))
    root.mainloop()


if __name__ == "__main__":
    main()
