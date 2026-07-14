"""Sync the generated replay-aggregate site to a DigitalOcean Spaces bucket.

`tools/rebuild_aggregates.py` writes a static HTML + JSON tree to `aggregate/` at the repo
root - a global index over every corpus plus one `<corpus>/` subtree each (its own index,
player-count modes `1v1/`, `2v2/`, ..., and per-faction pages under `factions/`). This script
pushes that tree to a DigitalOcean Spaces bucket (an S3-compatible object store) so it can be
served publicly, and keeps it in sync on repeat runs rather than re-uploading everything every
time. Keys mirror the local tree under `--prefix` (default `aggregates`), so a corpus lands at
`<bucket>/aggregates/<corpus>/...` and the global index at `<bucket>/aggregates/index.html`.

Sync is a simple diff against the bucket's current contents: list every remote object under
`--prefix`, and for each local file compare its MD5 against the object's ETag. A Space's
single-part-upload ETag is the quoted MD5 hex, so a match means the content is unchanged and
the upload is skipped; a multipart-upload ETag contains a dash and can never match, so a file
that was previously uploaded as multipart just gets re-uploaded (harmless - it converges to a
single-part object and matches next time). New and changed files are uploaded with a
`public-read` ACL, a guessed `Content-Type`, and a short `Cache-Control` since the site is
regenerated in place rather than versioned. With `--delete`, remote objects under the prefix
with no local counterpart are removed too.

Credentials come from the environment: `DO_SPACES_KEY` / `DO_SPACES_SECRET`, falling back to
the standard `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (a DigitalOcean Space accepts the
same access-key/secret-key pair shape as S3). Nothing is read from the repo or from disk beyond
the synced folder itself.

Usage:
  python tools/upload_aggregates.py --bucket my-space --region fra1
  python tools/upload_aggregates.py --bucket my-space --region fra1 --delete
  python tools/upload_aggregates.py --bucket my-space --region fra1 --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO / "aggregate"

# mimetypes' guess is platform-dependent (it also consults the OS registry on Windows); this
# fallback covers the extensions the aggregate site actually emits so Content-Type is stable
# across machines. Anything not listed here still falls through to mimetypes, then to
# application/octet-stream.
FALLBACK_TYPES = {
    ".html": "text/html",
    ".htm": "text/html",
    ".json": "application/json",
    ".css": "text/css",
    ".js": "application/javascript",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".txt": "text/plain",
}

CACHE_CONTROL = "max-age=300"
CHUNK_SIZE = 1024 * 1024


def content_type(path: Path) -> str:
    """The `Content-Type` to upload `path` with, charset-qualified for text types."""
    guessed, _ = mimetypes.guess_type(path.name)
    ctype = guessed or FALLBACK_TYPES.get(path.suffix.lower()) or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/json", "application/javascript"):
        ctype += "; charset=utf-8"
    return ctype


def md5_hex(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_files(root: Path, prefix: str) -> dict[str, Path]:
    """Every file under `root`, keyed by its bucket key (forward-slashed, `prefix`-joined)."""
    files: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            key = f"{prefix}/{rel}" if prefix else rel
            files[key] = path
    return files


def remote_objects(client, bucket: str, prefix: str) -> dict[str, str]:
    """Every object under `prefix` in `bucket`, keyed by its key, mapped to its ETag with the
    surrounding quotes stripped."""
    objects: dict[str, str] = {}
    paginator = client.get_paginator("list_objects_v2")
    list_prefix = f"{prefix}/" if prefix else ""
    for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
        for obj in page.get("Contents", []):
            objects[obj["Key"]] = obj["ETag"].strip('"')
    return objects


def unchanged(local_md5: str, etag: str) -> bool:
    """Whether a remote object with this ETag already holds `local_md5`'s content. A multipart
    upload's ETag contains a dash and is never equal to a plain MD5 hex, so it always compares
    as changed - the file gets re-uploaded as a single part, which is harmless and makes future
    comparisons exact again."""
    return etag == local_md5


def resolve_endpoint(args: argparse.Namespace) -> str:
    if args.endpoint:
        return args.endpoint
    return f"https://{args.region}.digitaloceanspaces.com"


def resolve_credentials() -> tuple[str, str]:
    key = os.environ.get("DO_SPACES_KEY") or os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("DO_SPACES_SECRET") or os.environ.get("AWS_SECRET_ACCESS_KEY")
    if not key or not secret:
        print(
            "missing credentials: set DO_SPACES_KEY / DO_SPACES_SECRET "
            "(or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)",
            file=sys.stderr,
        )
        sys.exit(1)
    return key, secret


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="Space name")
    parser.add_argument("--region", required=True, help="Space region, e.g. fra1, nyc3")
    parser.add_argument(
        "--endpoint",
        default=None,
        help="full endpoint URL, overriding the https://<region>.digitaloceanspaces.com default",
    )
    parser.add_argument(
        "--prefix",
        default="aggregates",
        help="key prefix inside the bucket, so the site lives at "
        "<bucket>/<prefix>/<corpus>/... (default: aggregates)",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DIR,
        help=f"local folder to sync (default: {DEFAULT_DIR})",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete remote objects under --prefix that have no local counterpart",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the actions that would be taken and exit"
    )
    args = parser.parse_args(argv)

    if not args.dir.is_dir():
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 1

    # Deferred past argument parsing so --help (and any argparse usage error) works without
    # boto3 installed - it is not a repo dependency, just this script's.
    try:
        import boto3  # noqa: PLC0415
        from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415
    except ImportError:
        print("boto3 is required for this script: pip install boto3", file=sys.stderr)
        return 1

    key_id, secret = resolve_credentials()
    endpoint = resolve_endpoint(args)
    prefix = args.prefix.strip("/")

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=args.region,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )

    files = local_files(args.dir, prefix)
    print(f"{len(files)} local file(s) under {args.dir}")

    try:
        remote = remote_objects(client, args.bucket, prefix)
    except (ClientError, BotoCoreError) as exc:
        print(f"failed to list {args.bucket}: {exc}", file=sys.stderr)
        return 1
    print(f"{len(remote)} remote object(s) under {prefix or '(root)'} in {args.bucket}")

    uploaded = unchanged_count = deleted = 0
    uploaded_bytes = 0

    for key in sorted(files):
        path = files[key]
        digest = md5_hex(path)
        if key in remote and unchanged(digest, remote[key]):
            print(f"skip    {key}")
            unchanged_count += 1
            continue

        size = path.stat().st_size
        print(f"upload  {key} ({size} bytes)")
        if not args.dry_run:
            try:
                client.put_object(
                    Bucket=args.bucket,
                    Key=key,
                    Body=path.read_bytes(),
                    ACL="public-read",
                    ContentType=content_type(path),
                    CacheControl=CACHE_CONTROL,
                )
            except (ClientError, BotoCoreError) as exc:
                print(f"failed to upload {key}: {exc}", file=sys.stderr)
                return 1
        uploaded += 1
        uploaded_bytes += size

    if args.delete:
        stale = sorted(set(remote) - set(files))
        for key in stale:
            print(f"delete  {key}")
        if stale and not args.dry_run:
            for i in range(0, len(stale), 1000):
                batch = stale[i : i + 1000]
                try:
                    client.delete_objects(
                        Bucket=args.bucket,
                        Delete={"Objects": [{"Key": key} for key in batch]},
                    )
                except (ClientError, BotoCoreError) as exc:
                    print(f"failed to delete {len(batch)} object(s): {exc}", file=sys.stderr)
                    return 1
        deleted = len(stale)

    action = "would sync" if args.dry_run else "synced"
    print(
        f"{action}: {uploaded} uploaded ({uploaded_bytes} bytes), "
        f"{unchanged_count} unchanged, {deleted} deleted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
