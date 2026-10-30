#!/usr/bin/env python3
"""Mirror configured upstream PNG icons independently of IPA releases."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.parse
import urllib.request

from add_app import ROOT, https_url


MAX_ICON_SIZE = 10 * 1024**2


def download_icon(url):
    request = urllib.request.Request(https_url(url), headers={"User-Agent": "nembx-app-source/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        https_url(response.url)
        data = response.read(MAX_ICON_SIZE + 1)
    if len(data) > MAX_ICON_SIZE:
        raise ValueError("图标超过 10 MiB")
    if (not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR"
            or not data.endswith(b"\x00\x00\x00\x00IEND\xaeB\x60\x82")):
        raise ValueError("上游没有返回完整 PNG 图标")
    return data


def replace_file(path, data):
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".icon-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def sync_icons(config_path, source_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    metadata_changed = False
    for entry in config["repositories"]:
        settings = entry.get("iconSource")
        if not settings:
            continue
        try:
            app = next((a for a in source["apps"]
                        if a["bundleIdentifier"] == settings["bundleIdentifier"]), None)
            if app is None:
                continue
            root = source_path.parent.resolve()
            target = (root / settings["path"]).resolve()
            if not target.is_relative_to(root / "assets") or target.suffix != ".png":
                raise ValueError("图标路径必须位于 assets 下且以 .png 结尾")
            base = urllib.parse.urlsplit(https_url(entry["iconURL"]))
            data = download_icon(settings["url"])
            digest = hashlib.sha256(data).hexdigest()
            query = [(k, v) for k, v in urllib.parse.parse_qsl(base.query) if k != "v"]
            query.append(("v", digest[:16]))
            icon_url = urllib.parse.urlunsplit(base._replace(query=urllib.parse.urlencode(query)))
            image_changed = replace_file(target, data)
            if entry["iconURL"] != icon_url or app.get("iconURL") != icon_url:
                entry["iconURL"] = app["iconURL"] = icon_url
                metadata_changed = True
            if image_changed:
                print(f"{entry['repo']}：图标已同步")
        except (OSError, ValueError, KeyError) as error:
            print(f"::warning::{entry['repo']} 图标同步失败，保留现有图标：{error}")
    if metadata_changed:
        for path, value in ((source_path, source), (config_path, config)):
            replace_file(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "upstreams.json")
    parser.add_argument("--source", type=Path, default=ROOT / "source.json")
    args = parser.parse_args()
    sync_icons(args.config, args.source)
