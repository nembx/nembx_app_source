#!/usr/bin/env python3
"""Read IPA metadata and add/update an app in a SideStore source (stdlib only)."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import plistlib
import tempfile
import urllib.parse
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MAX_DOWNLOAD = 2 * 1024**3


def https_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("下载和图标地址必须是完整的 HTTPS 网址")
    return value


def read_metadata(ipa):
    with zipfile.ZipFile(ipa) as archive:
        candidates = [
            item for item in archive.infolist()
            if len(PurePosixPath(item.filename).parts) == 3
            and PurePosixPath(item.filename).parts[0] == "Payload"
            and PurePosixPath(item.filename).parts[1].endswith(".app")
            and PurePosixPath(item.filename).name == "Info.plist"
        ]
        if len(candidates) != 1:
            raise ValueError("IPA 必须包含唯一的 Payload/*.app/Info.plist")
        if candidates[0].file_size > 4 * 1024**2:
            raise ValueError("Info.plist 超过 4 MiB，停止读取")
        info = plistlib.loads(archive.read(candidates[0]))
    for key in ("CFBundleIdentifier", "CFBundleShortVersionString"):
        if not isinstance(info.get(key), str) or not info[key].strip():
            raise ValueError(f"IPA 缺少有效的 {key}")
    return info


def update_source(args, ipa, download_url):
    info = read_metadata(ipa)
    source = json.loads(args.source.read_text(encoding="utf-8"))
    bundle_id = info["CFBundleIdentifier"]
    app = next((a for a in source["apps"] if a["bundleIdentifier"] == bundle_id), None)
    if app is None:
        app = {
            "name": args.name or info.get("CFBundleDisplayName") or info.get("CFBundleName") or bundle_id,
            "bundleIdentifier": bundle_id,
            "developerName": args.developer or "未填写",
            "localizedDescription": args.description or "暂无介绍。",
            "iconURL": args.icon_url or source["iconURL"],
            "versions": [],
        }
        source["apps"].append(app)
    else:
        for field, value in (("name", args.name), ("developerName", args.developer),
                             ("localizedDescription", args.description), ("iconURL", args.icon_url)):
            if value:
                app[field] = value
    version = {
        "version": info["CFBundleShortVersionString"],
        "date": args.date or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "downloadURL": download_url,
        "size": ipa.stat().st_size,
    }
    if info.get("MinimumOSVersion"):
        version["minOSVersion"] = info["MinimumOSVersion"]
    if args.version_description:
        version["localizedDescription"] = args.version_description
    # The newly submitted IPA becomes the latest release; replace duplicate versions.
    app["versions"] = [version] + [
        v for v in app["versions"] if v["version"] != version["version"]
    ]
    # Keep legacy fields in sync for clients that do not read the versions array.
    for field in ("version", "versionDate", "downloadURL", "size", "minOSVersion"):
        app.pop(field, None)
    app.update({
        "version": version["version"], "versionDate": version["date"],
        "downloadURL": download_url, "size": version["size"],
    })
    if "minOSVersion" in version:
        app["minOSVersion"] = version["minOSVersion"]
    output = json.dumps(source, ensure_ascii=False, indent=2) + "\n"
    # Replace only after metadata parsing and serialization both succeed.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.source.parent,
                                     prefix=".source-", suffix=".json", delete=False) as temp:
        temp.write(output)
        temporary_path = Path(temp.name)
    temporary_path.replace(args.source)
    print(f"已收录：{app['name']} {version['version']} ({bundle_id})")


def add_app(args):
    download_url = https_url(args.download_url or args.url or "")
    if args.icon_url:
        https_url(args.icon_url)
    if args.ipa:
        update_source(args, args.ipa, download_url)
        return
    https_url(args.url)
    request = urllib.request.Request(args.url, headers={"User-Agent": "nembx-app-source/1.0"})
    with tempfile.TemporaryDirectory(prefix="nembx-ipa-") as directory:
        ipa = Path(directory) / "app.ipa"
        with urllib.request.urlopen(request, timeout=60) as response, ipa.open("wb") as target:
            https_url(response.url)
            size = 0
            while chunk := response.read(1024**2):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError("IPA 超过 2 GiB，停止下载")
                target.write(chunk)
        update_source(args, ipa, download_url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--url", help="IPA 的 HTTPS 下载直链")
    location.add_argument("--ipa", type=Path, help="本地 IPA；同时提供 --download-url")
    parser.add_argument("--download-url", help="本地 IPA 对应的公开 HTTPS 下载网址")
    parser.add_argument("--source", type=Path, default=ROOT / "source.json")
    parser.add_argument("--icon-url", help="应用图标的 HTTPS 网址；默认使用源图标")
    parser.add_argument("--name", help="自定义显示名称")
    parser.add_argument("--developer", help="应用开发者名称")
    parser.add_argument("--description", help="应用介绍")
    parser.add_argument("--date", help="版本发布日期（ISO 8601，默认当前 UTC 时间）")
    parser.add_argument("--version-description", help="本次版本更新说明")
    args = parser.parse_args()
    try:
        add_app(args)
    except Exception as error:
        parser.exit(1, f"添加失败：{error}\n")


if __name__ == "__main__":
    main()
