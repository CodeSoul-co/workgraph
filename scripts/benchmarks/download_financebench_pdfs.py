#!/usr/bin/env python3
"""Download the FinanceBench PDFs referenced by the open-source sample."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINANCE_DIR = ROOT / "data" / "raw" / "benchmarks" / "financebench"
JSONL_PATH = FINANCE_DIR / "financebench_merged.jsonl"
PDF_DIR = FINANCE_DIR / "pdfs"
META_DIR = FINANCE_DIR / "meta"
GITHUB_CONTENTS_URL = "https://api.github.com/repos/patronus-ai/financebench/contents/pdfs"


def request_json(url: str) -> object:
  if shutil.which("gh"):
    api_path = url.replace("https://api.github.com/", "")
    output = subprocess.check_output(["gh", "api", api_path], text=True)
    return json.loads(output)

  req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
  token = os.environ.get("GITHUB_TOKEN")
  if token:
    req.add_header("Authorization", f"Bearer {token}")
  with urllib.request.urlopen(req, timeout=60) as response:
    return json.loads(response.read().decode("utf-8"))


def download(url: str, target: Path, retries: int) -> None:
  target.parent.mkdir(parents=True, exist_ok=True)
  tmp = target.with_suffix(target.suffix + ".part")
  for attempt in range(1, retries + 1):
    try:
      with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
        while True:
          chunk = response.read(1024 * 1024)
          if not chunk:
            break
          out.write(chunk)
      tmp.replace(target)
      return
    except (urllib.error.URLError, TimeoutError) as exc:
      if tmp.exists():
        tmp.unlink()
      if attempt == retries:
        raise RuntimeError(f"failed to download {url}: {exc}") from exc
      time.sleep(2 * attempt)


def load_needed_docs() -> set[str]:
  if not JSONL_PATH.exists():
    raise FileNotFoundError(f"missing FinanceBench JSONL: {JSONL_PATH}")
  docs: set[str] = set()
  with JSONL_PATH.open("r", encoding="utf-8") as handle:
    for line in handle:
      if line.strip():
        row = json.loads(line)
        docs.add(f"{row['doc_name']}.pdf")
  return docs


def build_manifest() -> list[dict[str, object]]:
  needed = load_needed_docs()
  items = request_json(GITHUB_CONTENTS_URL)
  if not isinstance(items, list):
    raise RuntimeError("unexpected GitHub API response for FinanceBench PDFs")

  by_name = {item["name"]: item for item in items if isinstance(item, dict)}
  missing = sorted(needed - set(by_name))
  if missing:
    raise RuntimeError(f"missing referenced PDFs in GitHub repository: {missing}")

  manifest: list[dict[str, object]] = []
  for name in sorted(needed):
    item = by_name[name]
    local_path = PDF_DIR / name
    manifest.append(
      {
        "name": name,
        "size": item["size"],
        "sha": item["sha"],
        "download_url": item["download_url"],
        "local_path": str(local_path.relative_to(ROOT)),
        "downloaded": local_path.exists() and local_path.stat().st_size == item["size"],
      }
    )
  return manifest


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--manifest-only", action="store_true")
  parser.add_argument("--retries", type=int, default=3)
  args = parser.parse_args()

  PDF_DIR.mkdir(parents=True, exist_ok=True)
  META_DIR.mkdir(parents=True, exist_ok=True)

  manifest = build_manifest()
  if not args.manifest_only:
    for item in manifest:
      target = ROOT / str(item["local_path"])
      if item["downloaded"]:
        continue
      print(f"downloading {item['name']}", flush=True)
      download(str(item["download_url"]), target, args.retries)

  manifest = build_manifest()
  manifest_path = META_DIR / "financebench_pdf_manifest.json"
  manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

  downloaded = sum(1 for item in manifest if item["downloaded"])
  total_bytes = sum(int(item["size"]) for item in manifest)
  print(f"FinanceBench PDFs: {downloaded}/{len(manifest)} downloaded, {total_bytes} bytes referenced")
  return 0 if downloaded == len(manifest) or args.manifest_only else 1


if __name__ == "__main__":
  sys.exit(main())
