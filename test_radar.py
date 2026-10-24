import copy
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import radar
import magazine


class RadarTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.runtime = Path(self.temporary.name)
        self.db = radar.database(self.runtime)
        self.config = tomllib.loads((radar.ROOT / "config.toml").read_text())

    def tearDown(self):
        self.db.close()
        self.temporary.cleanup()

    def insert(self, video="sample", language="de-confirmed", state="selected"):
        self.db.execute("""INSERT INTO videos VALUES
            (?, 'channel', 'Testkanal', 'Testserie Folge 1', '', ?, ?, ?, 'Test',
             'Testserie', ?, 'Redaktioneller Test, keine echten Aufrufzahlen.', 1)""",
                        (video, radar.iso(radar.now()), radar.iso(radar.now()), language, state))
        self.db.commit()

    def test_growth_uses_actual_interval_and_preserves_negative_corrections(self):
        self.insert()
        current = radar.now()
        for hours, views in [(50, 100), (25, 300), (0, 280)]:
            self.db.execute("INSERT INTO samples VALUES (?,?,?)",
                            ("sample", radar.iso(current - timedelta(hours=hours)), views))
        views, delta, hours, _ = radar.measurements(self.db, "sample")
        self.assertEqual((views, delta, hours), (280, -20, 25.0))

    def test_no_fabricated_growth_with_only_one_sample(self):
        self.insert()
        self.db.execute("INSERT INTO samples VALUES (?,?,?)", ("sample", radar.iso(radar.now()), 100))
        self.assertEqual(radar.measurements(self.db, "sample")[:3], (100, None, None))

    def test_language_requires_evidence_or_review(self):
        self.assertEqual(radar.language_status({"title": "Deutscher Titel"}), "review")
        self.assertEqual(radar.language_status({"defaultAudioLanguage": "en"}), "other")
        self.assertEqual(radar.language_status({"defaultAudioLanguage": "de-AT"}), "de-metadata")
        self.assertEqual(radar.language_status({}, trusted=True), "de-confirmed")

    def test_magazine_uses_editorial_hooks_and_handles_unknown_formats(self):
        self.insert()
        directory = radar.weekly(self.db, self.config, self.runtime)
        episode = json.loads((directory / "episode.json").read_text())
        plan = magazine.build_plan(episode, self.config)
        self.assertEqual([s["kind"] for s in plan], ["intro", "item", "outro"])
        self.assertIn("Testserie", plan[1]["speech"])
        episode["items"][0]["id"] = "aqAHH0Mh11k"
        plan = magazine.build_plan(episode, self.config)
        self.assertEqual(plan[1]["heading"], "GANZ EUROPA ALS VERSTECK?!")
        self.assertIn("Kontinent", plan[1]["speech"])

    def test_public_export_excludes_private_notes_and_non_german_results(self):
        self.insert("public")
        self.insert("pending", "review")
        self.insert("foreign", "other")
        self.db.execute("UPDATE videos SET note='PRIVATE-EDITORIAL-NOTE', title='<b>Serie</b>'")
        output = self.runtime / "results.html"
        radar.export_results(self.db, output)
        page = output.read_text()
        self.assertIn("watch?v=public", page)
        self.assertIn("&lt;b&gt;Serie&lt;/b&gt;", page)
        self.assertNotIn("watch?v=pending", page)
        self.assertNotIn("watch?v=foreign", page)
        self.assertNotIn("PRIVATE-EDITORIAL-NOTE", page)

    def test_collector_discovers_and_tracks_seed_channels(self):
        config = copy.deepcopy(self.config)
        config["seed_video_ids"] = ["seed"]
        config["queries"] = ["Survival"]
        calls = []

        def fake_api(resource, **params):
            calls.append((resource, params))
            if resource == "search":
                return {"items": [{"id": {"videoId": "found"}}]}
            if resource == "playlistItems":
                return {"items": []}
            if resource == "videos":
                return {"items": [{"id": vid, "snippet": {
                    "channelId": "channel", "channelTitle": "Testkanal", "title": "Serie Folge 1",
                    "publishedAt": radar.iso(radar.now()), "defaultAudioLanguage": "de"},
                    "statistics": {"viewCount": "250"}} for vid in params["id"].split(",")]}
            if resource == "channels":
                return {"items": [{"id": "channel", "snippet": {"title": "Testkanal"},
                                  "contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]}
            self.fail(resource)

        with patch.object(radar, "api", fake_api):
            radar.collect(self.db, config)
            radar.collect(self.db, config, discover=False)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM videos").fetchone()[0], 2)
        self.assertTrue(any(r == "playlistItems" for r, _ in calls))
        self.assertEqual(self.db.execute("SELECT german FROM channels").fetchone()[0], 1)
        self.assertEqual(self.db.execute("SELECT language FROM videos WHERE id='seed'").fetchone()[0],
                         "de-confirmed")

    def test_weekly_excludes_unconfirmed_ignored_and_unavailable(self):
        self.insert("good")
        self.insert("pending", "review")
        self.insert("english", "other")
        self.insert("ignored", state="ignored")
        self.insert("missing")
        self.db.execute("UPDATE videos SET available=0 WHERE id='missing'")
        directory = radar.weekly(self.db, self.config, self.runtime)
        episode = json.loads((directory / "episode.json").read_text())
        self.assertEqual([item["id"] for item in episode["items"]], ["good"])
        self.assertIn("https://www.youtube.com/watch?v=good", episode["description"])
        self.assertIn("Noch kein Vergleich", episode["description"])
        self.assertNotIn("None Aufrufe", (directory / "script.txt").read_text())

    def test_upload_checks_channel_records_result_and_skips_duplicates(self):
        self.insert()
        directory = radar.weekly(self.db, self.config, self.runtime)
        video = directory / "weekly.mp4"
        video.write_bytes(b"mock-video-not-a-real-mp4")
        manifest = {
            "episode_sha256": radar.hashlib.sha256((directory / "episode.json").read_bytes()).hexdigest(),
            "video_sha256": radar.hashlib.sha256(video.read_bytes()).hexdigest()}
        (directory / "render.json").write_text(json.dumps(manifest))
        self.config["youtube"]["channel_id"] = "UCexpected"
        service = MagicMock()
        service.channels().list().execute.return_value = {"items": [{"id": "UCexpected"}]}
        service.videos().insert().next_chunk.return_value = (None, {"id": "uploaded-id"})
        service.videos().list().execute.return_value = {"items": [{"status": {
            "privacyStatus": "private", "uploadStatus": "uploaded"}}]}
        modules = {"googleapiclient": SimpleNamespace(),
                   "googleapiclient.discovery": SimpleNamespace(build=MagicMock(return_value=service)),
                   "googleapiclient.http": SimpleNamespace(MediaFileUpload=MagicMock())}
        with patch.dict(sys.modules, modules), patch.object(radar, "credentials", return_value=object()):
            radar.upload(self.db, self.config, self.runtime, directory)
            self.assertEqual(self.db.execute("SELECT youtube_id FROM uploads").fetchone()[0], "uploaded-id")
            service.reset_mock()
            radar.upload(self.db, self.config, self.runtime, directory)
            service.videos.assert_not_called()
            self.db.execute("DELETE FROM uploads")
            service.channels().list().execute.return_value = {"items": [{"id": "UCwrong"}]}
            with self.assertRaisesRegex(RuntimeError, "entspricht nicht"):
                radar.upload(self.db, self.config, self.runtime, directory)

    def test_dashboard_escapes_notes_and_rejects_forged_edit(self):
        import socket
        self.insert()
        self.db.execute("UPDATE videos SET note='<script>evil()</script>'")
        self.db.commit()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable, str(radar.ROOT / "radar.py"),
                                    "--runtime", str(self.runtime), "serve", "--port", str(port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        page = response.read().decode()
                    break
                except URLError:
                    time.sleep(0.05)
            else:
                self.fail("Dashboard hat nicht gestartet")
            self.assertIn("&lt;script&gt;evil()&lt;/script&gt;", page)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(f"http://127.0.0.1:{port}/edit", data=urlencode({
                    "csrf": "forged", "id": "sample", "state": "ignored"}).encode()))
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(self.db.execute("SELECT state FROM videos").fetchone()[0], "selected")
        finally:
            process.terminate()
            process.wait(timeout=5)

    @unittest.skipUnless(os.environ.get("RADAR_RENDER_TEST"), "RADAR_RENDER_TEST=1 für FFmpeg-Integration")
    def test_real_ffmpeg_render(self):
        self.insert()
        self.config["video"]["slide_seconds"] = 1
        directory = radar.weekly(self.db, self.config, self.runtime)
        radar.render(directory, self.config, silent=True)
        output = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
            str(directory / "weekly.mp4")], text=True))
        video = next(s for s in output["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["codec_name"], video["width"], video["height"]), ("h264", 1920, 1080))
        self.assertTrue(any(s["codec_type"] == "audio" for s in output["streams"]))
        self.assertGreater(float(output["format"]["duration"]), 3)
        self.assertTrue((directory / "render.json").exists())


if __name__ == "__main__":
    unittest.main()
