import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import editor
import radar


class EditorTests(unittest.TestCase):
    def test_clean_description_removes_ads_and_links(self):
        result = editor.clean_description("Werbung Rabattcode X\nhttps://example.org\nEine Reise durch Europa.")
        self.assertEqual(result, "Eine Reise durch Europa.")

    def test_selection_skips_historical_channel_and_games(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            db = radar.database(runtime)
            config = tomllib.loads((radar.ROOT / "config.toml").read_text())
            editor.previous_features(db, runtime)
            db.execute("INSERT INTO featured VALUES ('old','seen','Serie','upload','date')")
            base = dict(available=1, language="de-confirmed", state="new", published=radar.iso(radar.now()),
                        views=10000, growth=None, hours=None, description="Reise", channel="Kanal")
            items = [dict(base, id="a", channel_id="seen", title="Neue Reise Folge 1"),
                     dict(base, id="b", channel_id="new", title="Neue Reise Folge 1"),
                     dict(base, id="c", channel_id="game", title="Minecraft Folge 1")]
            with patch.object(radar, "entries", return_value=items):
                result = editor.eligible_candidates(db, config, runtime)
            self.assertEqual([i["id"] for i in result], ["b"])
            self.assertIn("noch keine 24h", result[0]["selection_reason"])
            db.close()

    def test_fallback_validates_and_rejects_changed_ids(self):
        episode = {"title": "Testfolge der Woche", "items": [{"id": "source", "series": "Testformat",
                   "channel": "Testkanal", "description": "Eine Reise."}]}
        script = editor.fallback(episode)
        editor.validate_script(script, episode)
        script["items"][0]["id"] = "invented"
        with self.assertRaises(ValueError):
            editor.validate_script(script, episode)

    def test_missing_key_uses_saved_templates_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            episode = {"title": "Testfolge der Woche", "items": [{"id": "source", "series": "Testformat",
                       "channel": "Testkanal", "description": "Eine Reise."}]}
            (directory / "episode.json").write_text(json.dumps(episode))
            with patch.dict(editor.os.environ, {}, clear=True), patch.object(editor, "urlopen") as network:
                result = editor.generate(directory, {"ai": {"enabled": True}})
            self.assertEqual(result["provider"], "templates")
            network.assert_not_called()
            self.assertTrue((directory / "ai-script.json").exists())


if __name__ == "__main__":
    unittest.main()
