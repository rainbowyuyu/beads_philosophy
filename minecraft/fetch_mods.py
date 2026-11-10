"""Download the locked official mod files, verifying SHA-512 before saving.

This never launches Minecraft or installs files into an existing game profile.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request


def download_locked(lock_path, destination):
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    for mod in lock["mods"]:
        file = mod["file"]
        filename = file["filename"]
        if Path(filename).name != filename or not filename.endswith(".jar"):
            raise ValueError("Invalid locked filename")
        parsed = urllib.parse.urlparse(file["url"])
        if parsed.scheme != "https" or parsed.hostname != "cdn.modrinth.com":
            raise ValueError("Only HTTPS downloads from the official Modrinth CDN are allowed")
        path = destination / filename
        expected = file["hashes"]["sha512"]
        if path.exists():
            if hashlib.sha512(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"Existing file has the wrong hash: {path}; preserved without overwriting")
            result.append({"file": filename, "status": "already_verified"})
            continue
        request = urllib.request.Request(file["url"], headers={"User-Agent": "beads-philosophy/0.1 (official mod resource downloader)"})
        descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=destination)
        try:
            hasher = hashlib.sha512()
            size = 0
            with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(request, timeout=60) as response:
                if urllib.parse.urlparse(response.url).hostname != "cdn.modrinth.com":
                    raise ValueError("Unexpected download redirect")
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > file["size"]:
                        raise ValueError(f"File exceeds locked byte count: {filename}")
                    output.write(chunk)
                    hasher.update(chunk)
            if size != file["size"] or hasher.hexdigest() != expected:
                raise ValueError(f"Download verification failed: {filename}")
            # Hard link gives atomic create-if-absent; never replace an existing JAR.
            os.link(temporary, path)
            result.append({"file": filename, "status": "downloaded_verified", "bytes": size})
        finally:
            Path(temporary).unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("mods.lock.json"))
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("downloads"))
    args = parser.parse_args()
    print(json.dumps(download_locked(args.lock, args.out), ensure_ascii=False, indent=2))
