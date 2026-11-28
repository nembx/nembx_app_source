#!/usr/bin/env python3
"""Track configured GitHub releases, using stable releases by default."""

import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

from add_app import ROOT, add_app
from sync_icons import replace_file, sync_icons


def matching_assets(entry, release):
    pattern = entry.get("assetPattern", "*.ipa").replace("{tag}", release["tag_name"])
    return [asset for asset in release.get("assets", [])
            if asset["name"].lower().endswith(".ipa") and fnmatch.fnmatchcase(asset["name"], pattern)]


def latest_release(entry):
    repo = entry["repo"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("无效的 GitHub 仓库名")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "nembx-app-source/1.0"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    endpoint = f"https://api.github.com/repos/{repo}/releases"
    include_prereleases = entry.get("includePrereleases", False)
    page = 1
    try:
        while True:
            url = f"{endpoint}?per_page=100&page={page}" if include_prereleases else f"{endpoint}/latest"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                result = json.load(response)
            if not include_prereleases:
                return result if not result.get("draft") and not result.get("prerelease") else None
            for release in result:
                if not release.get("draft") and matching_assets(entry, release):
                    return release
            if len(result) < 100:
                return None
            page += 1
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(f"{repo}：暂无可读取的 Release")
            return None
        raise


def latest_download_url(app):
    versions = app.get("versions")
    return versions[0].get("downloadURL") if versions else app.get("downloadURL")


def keep_latest_only(source_path, source, entry, latest_app):
    release_prefix = f"https://github.com/{entry['repo']}/releases/download/".lower()
    apps = [
        app for app in source["apps"]
        if app is latest_app or not any(
            (version.get("downloadURL") or "").lower().startswith(release_prefix)
            for version in (app.get("versions") or [app])
        )
    ]
    versions = latest_app.get("versions", [])
    if len(apps) != len(source["apps"]) or len(versions) > 1:
        if len(versions) > 1:
            latest_app["versions"] = versions[:1]
        source["apps"] = apps
        output = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
        replace_file(source_path, output.encode("utf-8"))

    icon_source = entry.get("iconSource")
    if icon_source and icon_source["bundleIdentifier"] != latest_app["bundleIdentifier"]:
        icon_source["bundleIdentifier"] = latest_app["bundleIdentifier"]
        return True
    return False


def sync(config_path, source_path):
    sync_icons(config_path, source_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    changed = False
    for entry in config["repositories"]:
        release = latest_release(entry)
        if not release:
            continue
        assets = matching_assets(entry, release)
        if not assets:
            print(f"{entry['repo']}：最新 Release 尚无匹配的 IPA，下次检查重试")
            continue
        if len(assets) != 1:
            raise ValueError(f"{entry['repo']}：存在多个 IPA，请缩小 assetPattern 的范围")
        asset = assets[0]
        fingerprint = {"tag": release["tag_name"], "assetId": asset["id"],
                       "updatedAt": asset["updated_at"], "size": asset["size"]}
        source = json.loads(source_path.read_text(encoding="utf-8"))
        download_url = asset["browser_download_url"]
        latest_app = next(
            (app for app in source["apps"] if latest_download_url(app) == download_url), None
        )
        if entry.get("lastRelease") == fingerprint and latest_app is not None:
            print(f"{entry['repo']}：已是最新版本 {release['tag_name']}")
        else:
            bundle_id = add_app(argparse.Namespace(
                url=download_url, ipa=None, download_url=None, source=source_path,
                icon_url=entry.get("iconURL"), name=entry.get("name"),
                developer=entry.get("developer"), description=entry.get("description"),
                subtitle=entry.get("subtitle"),
                date=release["published_at"], version_description=release.get("body") or None,
            ))
            entry["lastRelease"] = fingerprint
            changed = True
            if entry.get("latestOnly"):
                source = json.loads(source_path.read_text(encoding="utf-8"))
                latest_app = next(app for app in source["apps"] if app["bundleIdentifier"] == bundle_id)
        if entry.get("latestOnly") and keep_latest_only(source_path, source, entry, latest_app):
            changed = True
    if changed:
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "upstreams.json")
    parser.add_argument("--source", type=Path, default=ROOT / "source.json")
    args = parser.parse_args()
    sync(args.config, args.source)
