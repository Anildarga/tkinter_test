import argparse
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from update_core import UpdateError, extract_update, sha256_file

PROCESS_SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
ERROR_INVALID_PARAMETER = 87
BACKUP_PREFIX = "SampleApp.backup-"


def wait_for_process(pid):
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return
        raise ctypes.WinError(error)

    try:
        result = kernel32.WaitForSingleObject(handle, 120_000)
        if result == WAIT_TIMEOUT:
            raise TimeoutError("The application did not close within 120 seconds.")
        if result != WAIT_OBJECT_0:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def remove_old_backups(parent, keep):
    for candidate in Path(parent).glob(f"{BACKUP_PREFIX}*"):
        if candidate == keep or not candidate.is_dir() or candidate.is_symlink():
            continue
        if candidate.parent.resolve() == Path(parent).resolve():
            shutil.rmtree(candidate)


def install_update(app_dir, archive, pid, app_executable, expected_sha256):
    app_dir = Path(app_dir).resolve()
    archive = Path(archive).resolve()
    parent = app_dir.parent
    if not app_dir.is_dir():
        raise FileNotFoundError(f"Installed application folder not found: {app_dir}")
    if not archive.is_file():
        raise FileNotFoundError(f"Update package not found: {archive}")
    if app_dir == parent or app_dir.name != "SampleApp":
        raise ValueError("Install the app in a folder named SampleApp.")
    if Path(app_executable).name != app_executable or not app_executable.endswith(
        ".exe"
    ):
        raise ValueError("Application executable must be a filename ending in .exe.")
    if not expected_sha256 or sha256_file(archive) != expected_sha256.lower():
        raise UpdateError("Update package SHA-256 verification failed.")
    if pid <= 0:
        raise ValueError("Process ID must be a positive integer.")

    wait_for_process(pid)
    token = uuid.uuid4().hex
    stage = parent / f"SampleApp.new-{token}"
    backup = parent / f"{BACKUP_PREFIX}{token}"
    try:
        extract_update(archive, stage, app_executable)
        os.replace(app_dir, backup)
        try:
            os.replace(stage, app_dir)
        except Exception:
            os.replace(backup, app_dir)
            raise

        launched = subprocess.Popen(
            [str(app_dir / app_executable)],
            cwd=str(app_dir),
            close_fds=True,
        )
        time.sleep(3)
        if launched.poll() is not None:
            raise RuntimeError(
                "The updated application exited during startup; restoring backup."
            )
        remove_old_backups(parent, backup)
        print(f"Update installed. Previous version backed up to: {backup}")
    except Exception:
        if app_dir.exists() and backup.exists():
            shutil.rmtree(app_dir)
        if backup.exists() and not app_dir.exists():
            os.replace(backup, app_dir)
            fallback = app_dir / app_executable
            if fallback.is_file():
                subprocess.Popen([str(fallback)], cwd=str(app_dir), close_fds=True)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        try:
            archive.unlink(missing_ok=True)
            archive.parent.rmdir()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Install a signed, SHA-256-verified SampleApp update package."
    )
    parser.add_argument("app_dir")
    parser.add_argument("archive")
    parser.add_argument("process_id", type=int)
    parser.add_argument("app_executable")
    parser.add_argument("sha256")
    args = parser.parse_args()
    install_update(
        args.app_dir,
        args.archive,
        args.process_id,
        args.app_executable,
        args.sha256,
    )


def report_error(message):
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        None,
        message,
        "SampleApp update failed",
        0x10,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TimeoutError, RuntimeError, UpdateError) as error:
        message = f"Updater failed: {error}"
        if sys.stderr and not sys.stderr.closed:
            print(message, file=sys.stderr)
        if sys.platform == "win32":
            report_error(message)
        raise SystemExit(1) from None
