"""Verify an extracted Wasm delivery and its bundled Python HTTP server.

Usage: python verify_wasm_delivery.py --delivery <extracted folder> --out <report.json>
Only the output report is written. The temporary server binds to loopback on an
OS-assigned port, and only the process started by this verifier is stopped.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import subprocess
import sys
import threading
import time
from urllib.parse import quote


class VerificationError(Exception):
    pass


def contained_path(root: Path, name: str) -> Path:
    """Reject traversal, Windows aliases/streams and links leaving the delivery."""
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise VerificationError(f"Invalid manifest path: {name!r}")
    parts = name.split("/")
    if PurePosixPath(name).is_absolute() or any(
        part in ("", ".", "..") or part.endswith((" ", "."))
        or any(ord(char) < 32 for char in part)
        or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)
        for part in parts
    ):
        raise VerificationError(f"Unsafe manifest path: {name!r}")
    resolved = root.joinpath(*parts).resolve()
    if not resolved.is_relative_to(root):
        raise VerificationError(f"Manifest path escapes delivery: {name!r}")
    return resolved


def verify_manifest(root: Path, report: dict) -> dict[str, dict]:
    manifest = contained_path(root, "file-manifest.json")
    records = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if not isinstance(records, list) or not records:
        raise VerificationError("file-manifest.json must be a nonempty array")
    entries, seen, errors = {}, set(), []
    checked_bytes = 0
    for record in records:
        try:
            if not isinstance(record, dict):
                raise VerificationError("Manifest entry must be an object")
            name, size, digest = record.get("path"), record.get("size"), record.get("sha256")
            path = contained_path(root, name)
            if name.casefold() in seen:
                raise VerificationError(f"Duplicate manifest path: {name}")
            seen.add(name.casefold())
            if type(size) is not int or size < 0:
                raise VerificationError(f"Invalid file size: {name}")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise VerificationError(f"Invalid SHA256: {name}")
            if not path.is_file():
                raise VerificationError(f"Missing file: {name}")
            actual_size = path.stat().st_size
            if actual_size != size:
                raise VerificationError(f"Size mismatch: {name} (expected {size}, got {actual_size})")
            checksum = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
            if checksum.hexdigest() != digest.lower():
                raise VerificationError(f"SHA256 mismatch: {name}")
            checked_bytes += size
            entries[name] = {"path": path, "size": size}
        except (OSError, ValueError, VerificationError) as error:
            errors.append(str(error))
    required = ("Runtime/python.exe", "serve.py", "Wasm/index.html")
    for name in required:
        if name not in entries:
            errors.append(f"Required verified file missing: {name}")
    report["manifest"] = {"passed": not errors, "listed_files": len(records),
                          "verified_files": len(entries), "verified_bytes": checked_bytes,
                          "errors": errors}
    if errors:
        raise VerificationError(f"Manifest verification failed ({len(errors)} errors)")
    return entries


def process_options(root: Path) -> dict:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    return {"cwd": str(root), "env": environment,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def verify_runtime(root: Path, report: dict) -> None:
    program = (
        "import sys,ssl,json,http.server; print(json.dumps({"
        "'executable':sys.executable,'prefix':sys.prefix,'version':sys.version,"
        "'modules':[ssl.__file__,json.__file__,http.server.__file__]}))"
    )
    result = subprocess.run([str(root / "Runtime/python.exe"), "-I", "-B", "-c", program],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=30, **process_options(root))
    if result.returncode:
        raise VerificationError(f"Bundled Python failed: {result.stderr.strip()}")
    info = json.loads(result.stdout)
    runtime = (root / "Runtime").resolve()
    for name in [info["executable"], info["prefix"], *info["modules"]]:
        if not Path(name).resolve().is_relative_to(runtime):
            raise VerificationError(f"Bundled Python depends on an external location: {name}")
    report["runtime"] = {"passed": True, **info}


def start_server(root: Path, report: dict):
    command = [str(root / "Runtime/python.exe"), "-I", "-B", "-u", str(root / "serve.py"),
               "--root", str(root / "Wasm"), "--bind", "127.0.0.1", "--port", "0"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               **process_options(root))
    lines, messages = deque(maxlen=100), queue.Queue()

    def read_output():
        for line in process.stdout:
            lines.append(line.rstrip())
            messages.put(line)
        messages.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    report["server"] = {"pid": process.pid, "command": command, "stopped": False}
    return process, reader, lines, messages


def wait_for_server(process, messages, report: dict) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            line = messages.get(timeout=min(1, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        match = re.match(r"serve: http://127\.0\.0\.1:(\d+)/ from ", line)
        if match:
            port = int(match.group(1))
            if 0 < port <= 65535:
                report["server"]["url"] = f"http://127.0.0.1:{port}/"
                return port
    raise VerificationError(f"Bundled server did not become ready (exit={process.poll()})")


def request(port: int, path: str, *, headers=None, limit=16 * 1024 * 1024):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        connection.request("GET", "/" + quote(path, safe="/"),
                           headers={"Accept-Encoding": "identity", **(headers or {})})
        response = connection.getresponse()
        body = response.read(limit + 1)
        if len(body) > limit:
            raise VerificationError(f"HTTP response exceeded verification limit: {path}")
        return response.status, {key.lower(): value for key, value in response.getheaders()}, body
    finally:
        connection.close()


def check_response(report: dict, label: str, path: str, response, status: int, mime: str) -> bytes:
    code, headers, body = response
    errors = []
    if code != status:
        errors.append(f"Expected HTTP {status}, received {code}")
    if headers.get("content-type", "").split(";", 1)[0].strip().lower() != mime:
        errors.append(f"Expected MIME {mime}, received {headers.get('content-type')}")
    for header, expected in {"cross-origin-opener-policy": "same-origin",
                             "cross-origin-embedder-policy": "require-corp",
                             "cross-origin-resource-policy": "same-origin"}.items():
        if headers.get(header) != expected:
            errors.append(f"Expected {header}: {expected}")
    report["http"].append({"check": label, "path": path, "passed": not errors,
                           "status": code, "headers": headers, "received_bytes": len(body),
                           "errors": errors})
    if errors:
        raise VerificationError(f"{label}: {'; '.join(errors)}")
    return body


def verify_http(port: int, entries: dict, report: dict) -> None:
    report["http"] = []
    index = check_response(report, "index", "index.html", request(port, "index.html"), 200, "text/html")
    if index != entries["Wasm/index.html"]["path"].read_bytes():
        report["http"][-1]["passed"] = False
        raise VerificationError("HTTP index content differs from the verified delivery")
    css = sorted(name for name in entries if name.startswith("Wasm/") and name.endswith(".css"))
    wasm = sorted(name for name in entries if name.startswith("Wasm/") and name.endswith(".wasm"))
    if not css or not wasm:
        raise VerificationError("Delivery must include at least one CSS file and one .wasm file")
    for name in css:
        check_response(report, "css_mime", name[5:], request(port, name[5:]), 200, "text/css")
    for name in wasm:
        entry = entries[name]
        if entry["size"] < 8:
            raise VerificationError(f"Wasm file is too small: {name}")
        count = min(16, entry["size"])
        response = request(port, name[5:], headers={"Range": f"bytes=0-{count - 1}",
                                                   "Accept-Encoding": "br, identity"}, limit=4096)
        body = check_response(report, "wasm_range", name[5:], response, 206, "application/wasm")
        expected_range = f"bytes 0-{count - 1}/{entry['size']}"
        with entry["path"].open("rb") as stream:
            expected = stream.read(count)
        if (response[1].get("content-range") != expected_range or
                response[1].get("content-encoding", "identity") != "identity" or body != expected):
            report["http"][-1]["passed"] = False
            raise VerificationError(f"Wasm Range headers or content mismatch: {name}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delivery", type=Path, required=True, help="Extracted delivery root")
    parser.add_argument("--out", type=Path, required=True, help="JSON verification report")
    args = parser.parse_args(argv)
    root, output = args.delivery.resolve(), args.out.resolve()
    report = {"passed": False, "delivery": str(root),
              "started_utc": datetime.now(timezone.utc).isoformat()}
    process = reader = lines = None
    started = time.monotonic()
    try:
        # A report must not overwrite any part of the package being verified.
        if output.is_relative_to(root):
            raise VerificationError("--out must be outside the extracted delivery directory")
        if not root.is_dir():
            raise VerificationError(f"Delivery directory does not exist: {root}")
        entries = verify_manifest(root, report)
        verify_runtime(root, report)
        process, reader, lines, messages = start_server(root, report)
        port = wait_for_server(process, messages, report)
        verify_http(port, entries, report)
        if process.poll() is not None:
            raise VerificationError("Bundled server exited unexpectedly")
        report["passed"] = True
    except (Exception, KeyboardInterrupt) as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            reader.join(timeout=2)
            report["server"].update(stopped=process.poll() is not None,
                                     returncode=process.returncode, output=list(lines))
            process.stdout.close()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        # Rejecting an output inside the delivery must also avoid writing there.
        if not output.is_relative_to(root):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(output),
                      "verified_files": report.get("manifest", {}).get("verified_files", 0),
                      "http": [{"check": item["check"], "path": item["path"],
                                "passed": item["passed"], "status": item["status"]}
                               for item in report.get("http", [])],
                      "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
