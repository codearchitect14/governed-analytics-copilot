"""Download the Olist Brazilian E-Commerce dataset from Kaggle and extract it.

Credentials are read from KAGGLE_USERNAME and KAGGLE_KEY, or from ~/.kaggle/kaggle.json.
The archive is verified against dataset/checksums.sha256. On the first download the
checksum is recorded so later downloads can be verified.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from olist_schema import (
    CHECKSUM_FILE,
    DATASET_ROOT,
    KAGGLE_DATASET,
    KAGGLE_DOWNLOAD_URL,
    RAW_DIR,
    SOURCE_FILE_NAMES,
)

DOWNLOAD_DIR = DATASET_ROOT / "downloads"
ARCHIVE_NAME = "brazilian-ecommerce.zip"
MANUAL_STEPS = f"""
Manual download (no Kaggle credentials found):
  1. Create a free Kaggle account and an API token at https://www.kaggle.com/settings
  2. Either set KAGGLE_USERNAME and KAGGLE_KEY in .env, or save kaggle.json to ~/.kaggle/
  3. Re-run: make data
  Alternative: download https://www.kaggle.com/datasets/{KAGGLE_DATASET} in the browser,
  place the zip at {DOWNLOAD_DIR / ARCHIVE_NAME} and re-run this script.
"""


def load_credentials() -> tuple[str, str] | None:
    """Return (username, key) from the environment or ~/.kaggle/kaggle.json, if present."""
    username = os.environ.get("KAGGLE_USERNAME", "").strip()
    key = os.environ.get("KAGGLE_KEY", "").strip()
    if username and key:
        return username, key

    token_file = Path.home() / ".kaggle" / "kaggle.json"
    if token_file.is_file():
        data = json.loads(token_file.read_text(encoding="utf-8"))
        if data.get("username") and data.get("key"):
            return str(data["username"]), str(data["key"])
    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_checksums() -> dict[str, str]:
    if not CHECKSUM_FILE.exists():
        return {}
    entries: dict[str, str] = {}
    for line in CHECKSUM_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            entries[name.strip()] = digest
    return entries


def write_checksum(name: str, digest: str) -> None:
    entries = read_checksums()
    entries[name] = digest
    lines = [f"{value}  {key}" for key, value in sorted(entries.items())]
    CHECKSUM_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def download_archive(username: str, key: str, destination: Path) -> None:
    token = base64.b64encode(f"{username}:{key}".encode()).decode("ascii")
    request = urllib.request.Request(  # noqa: S310 - fixed https URL
        KAGGLE_DOWNLOAD_URL,
        headers={"Authorization": f"Basic {token}"},
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".part")
    with (
        urllib.request.urlopen(request, timeout=120) as response,  # noqa: S310
        partial.open("wb") as out,
    ):
        shutil.copyfileobj(response, out, length=1024 * 1024)
    partial.replace(destination)


def verify_or_record(archive: Path) -> None:
    digest = sha256_of(archive)
    recorded = read_checksums().get(ARCHIVE_NAME)
    if recorded is None:
        write_checksum(ARCHIVE_NAME, digest)
        print(f"Recorded checksum for {ARCHIVE_NAME}: {digest}")
    elif recorded != digest:
        raise SystemExit(
            f"Checksum mismatch for {archive.name}: expected {recorded}, got {digest}. "
            "Delete the archive and re-download, or update dataset/checksums.sha256 "
            "after verifying the new release."
        )
    else:
        print(f"Checksum verified for {ARCHIVE_NAME}")


def extract_tables(archive: Path, target: Path) -> None:
    """Extract only the nine Olist CSV files that the loader expects."""
    wanted = set(SOURCE_FILE_NAMES.values())
    target.mkdir(parents=True, exist_ok=True)
    extracted: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            name = Path(member).name
            if name in wanted:
                with bundle.open(member) as source, (target / name).open("wb") as out:
                    shutil.copyfileobj(source, out, length=1024 * 1024)
                extracted.add(name)
    missing = sorted(wanted - extracted)
    if missing:
        raise SystemExit(f"Archive is missing expected files: {', '.join(missing)}")
    print(f"Extracted {len(extracted)} files into {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--archive",
        type=Path,
        help="Use an archive already downloaded manually instead of calling the Kaggle API",
    )
    parser.add_argument("--force", action="store_true", help="Re-extract even if files exist")
    args = parser.parse_args(argv)

    raw_present = all((RAW_DIR / name).exists() for name in SOURCE_FILE_NAMES.values())
    if raw_present and not args.force:
        print(f"Raw files already present in {RAW_DIR}. Use --force to re-extract.")
        return 0

    archive = args.archive or DOWNLOAD_DIR / ARCHIVE_NAME
    if args.archive is None and not archive.exists():
        credentials = load_credentials()
        if credentials is None:
            print(MANUAL_STEPS, file=sys.stderr)
            return 2
        print(f"Downloading {KAGGLE_DATASET} from Kaggle")
        try:
            download_archive(*credentials, destination=archive)
        except urllib.error.HTTPError as error:
            print(
                f"Kaggle returned HTTP {error.code}. Check the credentials and that the "
                f"dataset terms are accepted on the Kaggle website.{MANUAL_STEPS}",
                file=sys.stderr,
            )
            return 1

    if not archive.exists():
        print(f"Archive not found: {archive}", file=sys.stderr)
        return 2

    verify_or_record(archive)
    extract_tables(archive, RAW_DIR)
    print("Olist tables are ready. Next: make data (loads them into PostgreSQL).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
