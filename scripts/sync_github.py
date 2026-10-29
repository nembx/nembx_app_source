#!/usr/bin/env python3
"""Track the latest stable GitHub releases listed in upstreams.json."""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from add_app import ROOT, add_app


def latest_release(repo):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("无效的 GitHub 仓库名")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nembx-app-source/1.0"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(f"{repo}：暂无可读取的正式 Release")
            return None
        raise


def sync(config_path, source_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    changed = False
    for entry in config["repositories"]:
        release = latest_release(entry["repo"])
        if not release or release.get("draft") or release.get("prerelease"):
            continue
        pattern = entry.get("assetPattern", "*.ipa").replace("{tag}", release["tag_name"])
        assets = [asset for asset in release.get("assets", [])
                  if asset["name"].lower().endswith(".ipa")
                  and fnmatch.fnmatchcase(asset["name"], pattern)]
        if not assets:
            print(f"{entry['repo']}：最新 Release 尚无匹配的 IPA，下次检查重试")
            continue
        if len(assets) != 1:
            raise ValueError(f"{entry['repo']}：存在多个 IPA，请缩小 assetPattern 的范围")
        asset = assets[0]
        fingerprint = {"tag": release["tag_name"], "assetId": asset["id"],
                       "updatedAt": asset["updated_at"], "size": asset["size"]}
        source = json.loads(source_path.read_text(encoding="utf-8"))
        present = any(
            (app["versions"][0].get("downloadURL") if app.get("versions")
             else app.get("downloadURL")) == asset["browser_download_url"]
            for app in source["apps"]
        )
        if entry.get("lastRelease") == fingerprint and present:
            print(f"{entry['repo']}：已是最新版本 {release['tag_name']}")
            continue
        add_app(argparse.Namespace(
            url=asset["browser_download_url"], ipa=None, download_url=None, source=source_path,
            icon_url=entry.get("iconURL"), name=entry.get("name"),
            developer=entry.get("developer"), description=entry.get("description"),
            subtitle=entry.get("subtitle"),
            date=release["published_at"], version_description=release.get("body") or None,
        ))
        entry["lastRelease"] = fingerprint
        changed = True
    if changed:
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "upstreams.json")
    parser.add_argument("--source", type=Path, default=ROOT / "source.json")
    args = parser.parse_args()
    sync(args.config, args.source)
