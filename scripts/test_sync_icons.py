import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from sync_github import sync
from sync_icons import MAX_ICON_SIZE, download_icon, sync_icons


class IconSyncTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / "upstreams.json"
        self.source = self.root / "source.json"
        self.target = self.root / "assets/app.png"
        self.target.parent.mkdir()
        self.target.write_bytes(b"old image")
        self.url = "https://example.com/assets/app.png"
        self.config.write_text(json.dumps({"repositories": [{
            "repo": "example/app", "iconURL": self.url,
            "iconSource": {"url": "https://example.com/new.png", "path": "assets/app.png",
                           "bundleIdentifier": "com.example.app"},
        }]}))
        self.source.write_text(json.dumps({"apps": [{
            "bundleIdentifier": "com.example.app", "iconURL": self.url,
            "localizedDescription": "Description", "versions": [{"version": "1"}],
        }]}))

    def snapshot(self):
        return [p.read_bytes() for p in (self.config, self.source, self.target)]

    def test_icons_update_even_without_release_and_are_idempotent(self):
        with patch("sync_icons.download_icon", return_value=b"new image"), \
                patch("sync_github.latest_release", return_value=None), \
                patch("sync_github.add_app") as add:
            sync(self.config, self.source)
            add.assert_not_called()
            app = json.loads(self.source.read_text())["apps"][0]
            entry = json.loads(self.config.read_text())["repositories"][0]
            self.assertEqual(self.target.read_bytes(), b"new image")
            self.assertEqual(app["iconURL"], entry["iconURL"])
            self.assertTrue(app["iconURL"].startswith(self.url + "?v="))
            self.assertEqual(app["versions"], [{"version": "1"}])
            self.assertEqual(app["localizedDescription"], "Description")
            state = self.snapshot()
            times = [p.stat().st_mtime_ns for p in (self.config, self.source, self.target)]
            sync(self.config, self.source)
            self.assertEqual(state, self.snapshot())
            self.assertEqual(times, [p.stat().st_mtime_ns for p in (self.config, self.source, self.target)])
        with patch("sync_icons.download_icon", return_value=b"newer image"):
            sync_icons(self.config, self.source)
        self.assertNotEqual(app["iconURL"], json.loads(self.source.read_text())["apps"][0]["iconURL"])

    def test_failed_download_preserves_existing_files(self):
        before = self.snapshot()
        with patch("sync_icons.download_icon", side_effect=urllib.error.URLError("offline")):
            sync_icons(self.config, self.source)
        self.assertEqual(before, self.snapshot())

    def test_rejects_paths_outside_assets(self):
        config = json.loads(self.config.read_text())
        config["repositories"][0]["iconSource"]["path"] = "../outside.png"
        self.config.write_text(json.dumps(config))
        before = self.snapshot()
        with patch("sync_icons.download_icon") as download:
            sync_icons(self.config, self.source)
            download.assert_not_called()
        self.assertEqual(before, self.snapshot())

    def test_download_validation(self):
        real_png = (Path(__file__).resolve().parents[1] / "assets/tube.png").read_bytes()
        for data, valid in [(real_png, True), (b"<html>error</html>", False),
                            (real_png[:-12], False), (b"x" * (MAX_ICON_SIZE + 1), False)]:
            with self.subTest(valid=valid, size=len(data)):
                response = io.BytesIO(data)
                response.url = "https://example.com/image.png"
                with patch("sync_icons.urllib.request.urlopen", return_value=response):
                    if valid:
                        self.assertEqual(download_icon(response.url), data)
                    else:
                        with self.assertRaises(ValueError):
                            download_icon(response.url)


if __name__ == "__main__":
    unittest.main()
