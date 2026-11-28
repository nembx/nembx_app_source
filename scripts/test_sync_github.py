import copy
import io
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from add_app import add_app
from sync_github import latest_release, sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config_path = Path(self.directory.name) / "upstreams.json"
        self.source_path = Path(self.directory.name) / "source.json"
        self.asset = {
            "id": 123, "name": "app.ipa", "updated_at": "2026-10-29T00:00:00Z",
            "size": 100, "browser_download_url": "https://github.com/example/app/releases/download/v1/app.ipa",
        }
        self.release = {
            "tag_name": "v1", "published_at": "2026-10-29T00:00:00Z",
            "assets": [self.asset],
        }
        self.config = {"repositories": [{
            "repo": "example/app", "lastRelease": {
                "tag": "v1", "assetId": 123,
                "updatedAt": self.asset["updated_at"], "size": 100,
            },
        }]}
        self.source = {"apps": [{"versions": [{
            "version": "1", "downloadURL": self.asset["browser_download_url"],
        }]}]}

    def run_sync(self, source=None, release=None, expected_source=None):
        self.config_path.write_text(json.dumps(self.config))
        self.source_path.write_text(json.dumps(source or self.source))
        original_config = self.config_path.read_bytes()
        original_source = self.source_path.read_bytes()
        with patch("sync_github.latest_release", return_value=release or self.release), \
                patch("sync_github.add_app") as add:
            sync(self.config_path, self.source_path)
        if expected_source is None:
            self.assertEqual(self.source_path.read_bytes(), original_source)
        else:
            self.assertEqual(json.loads(self.source_path.read_text()), expected_source)
        return add, original_config

    def test_unchanged_nested_version_skips_download_and_writes(self):
        add, original_config = self.run_sync()
        add.assert_not_called()
        self.assertEqual(self.config_path.read_bytes(), original_config)

    def test_default_channel_uses_latest_stable_endpoint(self):
        entry = self.config["repositories"][0]
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(self.release).encode())) as fetch:
            self.assertEqual(latest_release(entry), self.release)
        self.assertEqual(fetch.call_args.args[0].full_url, "https://api.github.com/repos/example/app/releases/latest")

    def test_prerelease_channel_skips_drafts_and_android_only_releases(self):
        entry = {"repo": "example/app", "includePrereleases": True, "assetPattern": "*-unsigned.ipa"}
        preview = {**self.release, "prerelease": True, "assets": [{"name": "app-unsigned.ipa"}]}
        android_only = {**self.release, "assets": [{"name": "app.apk"}]}
        pages = [[{**preview, "draft": True}] + [android_only] * 99, [preview, self.release]]
        with patch("urllib.request.urlopen", side_effect=[io.BytesIO(json.dumps(page).encode()) for page in pages]) as fetch:
            self.assertEqual(latest_release(entry), preview)
        self.assertTrue(fetch.call_args.args[0].full_url.endswith("&page=2"))

    def test_replaced_asset_at_same_url_is_processed(self):
        release = copy.deepcopy(self.release)
        release["assets"][0]["id"] = 456
        add, _ = self.run_sync(release=release)
        add.assert_called_once()
        config = json.loads(self.config_path.read_text())
        self.assertEqual(config["repositories"][0]["lastRelease"]["assetId"], 456)

    def test_url_only_in_history_does_not_skip_latest(self):
        source = copy.deepcopy(self.source)
        source["apps"][0]["versions"].insert(0, {
            "version": "2", "downloadURL": "https://example.com/other.ipa",
        })
        add, _ = self.run_sync(source=source)
        add.assert_called_once()

    def test_latest_only_prunes_stale_bundles_and_history_without_redownloading(self):
        entry = self.config["repositories"][0]
        entry["latestOnly"] = True
        entry["iconSource"] = {"bundleIdentifier": "com.example.old"}
        previous = {"version": "0", "downloadURL":
                    "https://github.com/Example/App/releases/download/v0/app.ipa"}
        stale = {"name": "App", "bundleIdentifier": "com.example.old", "versions": [previous]}
        other = {"name": "App", "bundleIdentifier": "com.example.other", "versions": [
            {"version": "1", "downloadURL": "https://github.com/example/app-other/releases/download/v1/app.ipa"},
            {"version": "0"},
        ]}
        latest = {"name": "App", "bundleIdentifier": "com.example.new",
                  "versions": self.source["apps"][0]["versions"]}
        latest_with_history = {**latest, "versions": latest["versions"] + [previous]}
        with patch("sync_github.sync_icons"):
            add, _ = self.run_sync(source={"apps": [stale, other, latest_with_history]},
                                   expected_source={"apps": [other, latest]})
        add.assert_not_called()
        config = json.loads(self.config_path.read_text())
        self.assertEqual(config["repositories"][0]["iconSource"]["bundleIdentifier"], "com.example.new")

    def test_latest_only_keeps_the_bundle_from_a_replacement_ipa_at_the_same_url(self):
        self.config["repositories"][0]["latestOnly"] = True
        self.source["apps"][0]["bundleIdentifier"] = "com.example.old"
        self.source["iconURL"] = "https://example.com/icon.png"
        self.config_path.write_text(json.dumps(self.config))
        self.source_path.write_text(json.dumps(self.source))
        ipa = self.source_path.with_suffix(".ipa")
        with zipfile.ZipFile(ipa, "w") as archive:
            archive.writestr("Payload/App.app/Info.plist", plistlib.dumps({
                "CFBundleIdentifier": "com.example.new", "CFBundleShortVersionString": "1",
            }))
        release = copy.deepcopy(self.release)
        release["assets"][0]["id"] = 456

        def add_local_ipa(args):
            args.ipa = ipa
            return add_app(args)

        with patch("sync_github.latest_release", return_value=release), \
                patch("sync_github.add_app", side_effect=add_local_ipa):
            sync(self.config_path, self.source_path)
        apps = json.loads(self.source_path.read_text())["apps"]
        self.assertEqual([app["bundleIdentifier"] for app in apps], ["com.example.new"])
        self.assertEqual([version["version"] for version in apps[0]["versions"]], ["1"])


if __name__ == "__main__":
    unittest.main()
