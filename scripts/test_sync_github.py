import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sync_github import sync


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config_path = Path(self.directory.name) / "upstreams.json"
        self.source_path = Path(self.directory.name) / "source.json"
        self.asset = {
            "id": 123, "name": "app.ipa", "updated_at": "2026-10-29T00:00:00Z",
            "size": 100, "browser_download_url": "https://example.com/app.ipa",
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

    def run_sync(self, source=None, release=None):
        self.config_path.write_text(json.dumps(self.config))
        self.source_path.write_text(json.dumps(source or self.source))
        original_config = self.config_path.read_bytes()
        original_source = self.source_path.read_bytes()
        with patch("sync_github.latest_release", return_value=release or self.release), \
                patch("sync_github.add_app") as add:
            sync(self.config_path, self.source_path)
        self.assertEqual(self.source_path.read_bytes(), original_source)
        return add, original_config

    def test_unchanged_nested_version_skips_download_and_writes(self):
        add, original_config = self.run_sync()
        add.assert_not_called()
        self.assertEqual(self.config_path.read_bytes(), original_config)

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


if __name__ == "__main__":
    unittest.main()
