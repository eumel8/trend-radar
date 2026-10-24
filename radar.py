#!/usr/bin/env python3
"""YouTube discovery, local editorial dashboard, weekly video and OAuth upload."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import textwrap
import tomllib
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def database(runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(runtime / "radar.sqlite3", timeout=60)
    db.row_factory = sqlite3.Row
    db.executescript("""
      CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY, title TEXT NOT NULL, uploads TEXT NOT NULL,
        german INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, channel TEXT NOT NULL,
        title TEXT NOT NULL, description TEXT NOT NULL, published TEXT NOT NULL,
        discovered TEXT NOT NULL, language TEXT NOT NULL, reason TEXT NOT NULL,
        series TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'new',
        note TEXT NOT NULL DEFAULT '', available INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS samples (
        video_id TEXT NOT NULL, captured TEXT NOT NULL, views INTEGER NOT NULL,
        PRIMARY KEY(video_id, captured));
      CREATE TABLE IF NOT EXISTS uploads (
        fingerprint TEXT PRIMARY KEY, youtube_id TEXT NOT NULL, uploaded TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS runs (
        completed TEXT NOT NULL, searches INTEGER NOT NULL);
    """)
    return db


def api(resource, **params):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY fehlt. API-Schlüssel als Umgebungsvariable setzen.")
    params["key"] = key
    try:
        with urlopen("https://www.googleapis.com/youtube/v3/" + resource + "?" +
                     urlencode(params), timeout=45) as response:
            return json.load(response)
    except HTTPError as error:
        # Do not expose the request URL containing the API key.
        raise RuntimeError(f"YouTube API: HTTP {error.code}; API-Freischaltung/Quota prüfen.") from None


def pages(resource, limit, **params):
    for _ in range(limit):
        data = api(resource, **params)
        yield from data.get("items", [])
        token = data.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token


def chunks(values, size=50):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def format_name(title):
    # Editable in the dashboard: titles alone cannot reliably identify a series.
    return re.split(r"\s*[-–|:]?\s*\b(?:Folge|Episode|Teil)\s*\d+", title,
                    flags=re.IGNORECASE)[0].strip(" -–|:") or title


def language_status(snippet, trusted=False):
    language = snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage", "")
    if trusted:
        return "de-confirmed"
    if language.lower().split("-")[0] == "de":
        return "de-metadata"
    if language:
        return "other"
    return "review"


def collect(db, config, discover=True):
    captured = iso(now())
    cutoff = iso(now() - timedelta(days=config["lookback_days"]))
    candidates = {v: "Nutzerbeispiel" for v in config["seed_video_ids"]}
    for channel in db.execute("SELECT * FROM channels WHERE german=1").fetchall():
        # Upload playlists, rather than search, reliably expose channel uploads.
        for item in pages("playlistItems", 3, part="snippet,contentDetails",
                          playlistId=channel["uploads"], maxResults=50):
            detail = item["contentDetails"]
            if detail.get("videoPublishedAt", "") >= cutoff:
                candidates[detail["videoId"]] = "Beobachteter Kanal"
    searches = 0
    if discover:
        for query in config["queries"]:
            token = None
            for _ in range(config["max_search_pages"]):
                params = dict(part="snippet", type="video", q=query,
                              relevanceLanguage="de", publishedAfter=cutoff,
                              maxResults=50, order="date")
                if token:
                    params["pageToken"] = token
                result = api("search", **params)
                searches += 1
                for item in result.get("items", []):
                    video_id = item.get("id", {}).get("videoId")
                    if video_id:
                        candidates.setdefault(video_id, "Suche: " + query)
                token = result.get("nextPageToken")
                if not token:
                    break
    # Keep measuring recent discoveries and editorial selections.
    for row in db.execute("SELECT id FROM videos WHERE published>=? OR state='selected'", (cutoff,)):
        candidates.setdefault(row["id"], "Messhistorie")
    trusted = {r[0] for r in db.execute("SELECT id FROM channels WHERE german=1")}
    seed_channels = set()
    for batch in chunks(candidates):
        result = api("videos", part="snippet,statistics", id=",".join(batch))
        returned = set()
        for item in result.get("items", []):
            vid, snippet = item["id"], item["snippet"]
            returned.add(vid)
            channel_id = snippet["channelId"]
            seed = vid in config["seed_video_ids"]
            if seed:
                seed_channels.add(channel_id)
            language = language_status(snippet, seed or channel_id in trusted)
            with db:
                db.execute("""INSERT INTO videos
                  (id,channel_id,channel,title,description,published,discovered,language,reason,series)
                  VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,description=excluded.description,
                  channel=excluded.channel,available=1,
                  language=CASE WHEN videos.language='de-confirmed' THEN videos.language
                                ELSE excluded.language END""",
                           (vid, channel_id, snippet["channelTitle"], snippet["title"],
                            snippet.get("description", ""), snippet["publishedAt"], captured,
                            language, candidates[vid], format_name(snippet["title"])))
                views = item.get("statistics", {}).get("viewCount")
                if views is not None:
                    db.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?)",
                               (vid, captured, int(views)))
        with db:
            for missing in set(batch) - returned:
                db.execute("UPDATE videos SET available=0 WHERE id=?", (missing,))
    channel_ids = seed_channels | {r[0] for r in db.execute(
        "SELECT DISTINCT channel_id FROM videos WHERE language LIKE 'de-%'")}
    for batch in chunks(channel_ids):
        for item in api("channels", part="snippet,contentDetails", id=",".join(batch)).get("items", []):
            with db:
                db.execute("""INSERT INTO channels VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title, uploads=excluded.uploads,
                  german=MAX(channels.german,excluded.german)""",
                           (item["id"], item["snippet"]["title"],
                            item["contentDetails"]["relatedPlaylists"]["uploads"],
                            int(item["id"] in seed_channels)))
    with db:
        db.execute("INSERT INTO runs VALUES (?,?)", (captured, searches))
    print(f"Sammlung abgeschlossen: {len(candidates)} Kandidaten, {searches} Suchabfragen.")


def measurements(db, vid):
    latest = db.execute("SELECT * FROM samples WHERE video_id=? ORDER BY captured DESC LIMIT 1",
                        (vid,)).fetchone()
    if latest is None:
        return None, None, None, None
    # Closest observation at least 24h old, with actual interval clearly reported.
    cutoff = iso(datetime.fromisoformat(latest["captured"].replace("Z", "+00:00")) - timedelta(hours=24))
    previous = db.execute("""SELECT * FROM samples WHERE video_id=? AND captured<=?
                          ORDER BY captured DESC LIMIT 1""", (vid, cutoff)).fetchone()
    if previous is None:
        return latest["views"], None, None, latest["captured"]
    hours = (datetime.fromisoformat(latest["captured"].replace("Z", "+00:00")) -
             datetime.fromisoformat(previous["captured"].replace("Z", "+00:00"))).total_seconds() / 3600
    return latest["views"], latest["views"] - previous["views"], hours, latest["captured"]


def entries(db):
    result = []
    for row in db.execute("SELECT * FROM videos ORDER BY discovered DESC"):
        entry = dict(row)
        entry["views"], entry["growth"], entry["hours"], entry["captured"] = measurements(db, row["id"])
        result.append(entry)
    return result


def number(value):
    return "–" if value is None else f"{value:,}".replace(",", ".")


def growth_text(item):
    if item["growth"] is None:
        return "Noch kein Vergleich über mindestens 24 Stunden"
    return f'{number(item["growth"])} Aufrufe in {item["hours"]:.1f} Stunden'


def export_results(db, output):
    """Publish only public video facts, never editorial notes or credentials."""
    items = [item for item in entries(db) if item["language"].startswith("de-")
             and item["available"] and item["state"] != "ignored"]
    items.sort(key=lambda item: item["views"] if item["views"] is not None else -1,
               reverse=True)
    latest = db.execute("SELECT completed FROM runs ORDER BY completed DESC LIMIT 1").fetchone()
    escape = lambda value: html.escape(str(value), quote=True)
    cards = []
    for item in items:
        cards.append(f'''<article class="card"><h2><a href="https://www.youtube.com/watch?v={escape(item['id'])}">{escape(item['title'])}</a></h2>
          <p>{escape(item['channel'])} · Veröffentlicht: {escape(item['published'][:10])}</p>
          <p><strong>{number(item['views'])} Aufrufe</strong><br>{escape(growth_text(item))}</p>
          <p>Messstand (UTC): {escape(item['captured'])}</p></article>''')
    page = f'''<!doctype html><html lang="de"><head><meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Ergebnisse – TrendsDE</title><link rel="stylesheet" href="/style.css"></head>
      <body><header><a class="brand" href="/">TrendsDE</a><nav><a href="/">Projekt</a>
      <a href="/privacy.html">Datenschutz</a></nav></header><main>
      <h1>Entdeckte deutschsprachige Videos</h1>
      <p class="lead">{len(items)} Treffer · Letzte vollständige Sammlung (UTC): {escape(latest[0]) if latest else 'Noch keine'}</p>
      <p class="notice">Momentaufnahme aus den beobachteten Kanälen und thematischen Suchabfragen.
      Sortiert nach Gesamtaufrufen, keine vollständige Trend-Rangliste. Sprachmetadaten sind noch
      nicht für alle Treffer redaktionell geprüft. Suchtreffer können thematisch unpassend sein.
      Wachstum erscheint erst mit Vergleichsmessungen über mindestens 24 Stunden.</p>
      {''.join(cards) or '<p>Noch keine Ergebnisse.</p>'}</main><footer>
      <a href="/privacy.html">Datenschutz</a><a href="/terms.html">Nutzungsbedingungen</a>
      <a href="/contact.html">Kontakt</a></footer></body></html>'''
    temporary = output.with_suffix(".tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(output)
    print(f"Ergebnisübersicht: {output} ({len(items)} Videos)")


def serve(db, config, port):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            cards = []
            tab = """<nav><button onclick="filter('all')">Alle deutschen Treffer</button>
              <button onclick="filter('new')">Neue Formate</button>
              <button onclick="filter('growth')">Wächst gerade</button>
              <button onclick="filter('selected')">Redaktionsauswahl</button>
              <button onclick="filter('review')">Sprache prüfen</button></nav>"""
            for item in entries(db):
                if item["state"] == "ignored" or item["language"] == "other":
                    continue
                e = {k: html.escape(str(v), quote=True) for k, v in item.items()}
                pending = item["language"] == "review"
                growth = item["growth"] is not None and item["growth"] > 0
                cards.append(f"""<article data-state="{e['state']}" data-review="{int(pending)}"
                  data-growth="{int(growth)}"><h2>{e['series']}</h2>
                  <a target="_blank" rel="noopener" href="https://www.youtube.com/watch?v={e['id']}">{e['title']}</a>
                  <p>{e['channel']} · Veröffentlicht: {e['published'][:10]}</p>
                  <p><strong>{number(item['views'])} Aufrufe</strong> · {html.escape(growth_text(item))}</p>
                  <p>Messstand: {e['captured']} · Entdeckt: {e['discovered'][:10]}</p>
                  <p>{e['reason']} · Sprache: {e['language']} · Status: {e['state']}
                  {' · Video nicht verfügbar' if not item['available'] else ''}</p>
                  <form method="post" action="/edit"><input type="hidden" name="csrf" value="{csrf}">
                  <input type="hidden" name="id" value="{e['id']}">
                  <label>Serientitel <input name="series" value="{e['series']}" required maxlength="300"></label>
                  <label>Redaktionsnotiz <textarea name="note" maxlength="3000">{e['note']}</textarea></label>
                  <select name="state">{''.join(f'<option value="{s}" {"selected" if s == item["state"] else ""}>{label}</option>' for s, label in [('new','Neu'),('watch','Beobachten'),('selected','Für Wochenvideo'),('ignored','Irrelevant')])}</select>
                  <label><input type="checkbox" name="german" {'checked' if item['language']=='de-confirmed' else ''}> Deutschsprachigkeit bestätigt</label>
                  <button>Speichern</button></form></article>""")
            latest = db.execute("SELECT completed FROM runs ORDER BY completed DESC LIMIT 1").fetchone()
            body = f"""<!doctype html><html lang="de"><meta charset="utf-8">
              <meta name="viewport" content="width=device-width,initial-scale=1">
              <title>{html.escape(config['title'])}</title><style>
              body{{font:16px system-ui;max-width:1000px;margin:30px auto;padding:0 20px;background:#101827;color:#eef}}
              a{{color:#7dd3fc}} article{{background:#1e293b;padding:22px;margin:18px 0;border-radius:12px}}
              input:not([type=checkbox]),textarea{{display:block;width:95%;padding:8px;margin:5px 0 12px}}
              button,select{{padding:9px;margin:5px}} label{{display:block}}nav{{position:sticky;top:0;background:#101827}}
              </style><h1>{html.escape(config['title'])}</h1>
              <p>Letzte vollständige Sammlung: {html.escape(latest[0]) if latest else 'Noch keine'}</p>
              <p>Trends unter beobachteten Formaten. Wachstum gilt für das angegebene Messintervall.
              Zuordnung zu Serien bitte redaktionell prüfen. Sprachoffene Treffer erscheinen nur unter „Sprache prüfen“.</p>
              {tab}<main>{''.join(cards) or '<p>Noch keine Treffer. Zuerst collect ausführen.</p>'}</main>
              <script>function filter(t){{document.querySelectorAll('article').forEach(e=>{{
              e.hidden=t==='review'?e.dataset.review!=='1':e.dataset.review==='1'||
              (t==='selected'&&e.dataset.state!=='selected')||(t==='new'&&e.dataset.state!=='new')||
              (t==='growth'&&e.dataset.growth!=='1');}});}}filter('all');</script></html>"""
            encoded = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if self.path != "/edit" or not 0 < size < 16000:
                self.send_error(400)
                return
            fields = parse_qs(self.rfile.read(size).decode(), keep_blank_values=True)
            field = lambda name: fields.get(name, [""])[0]
            if not secrets.compare_digest(field("csrf"), csrf):
                self.send_error(403)
                return
            if field("state") not in {"new", "watch", "selected", "ignored"}:
                self.send_error(400)
                return
            row = db.execute("SELECT * FROM videos WHERE id=?", (field("id"),)).fetchone()
            if not row or not field("series").strip():
                self.send_error(400)
                return
            language = "de-confirmed" if field("german") else (
                "review" if row["language"] == "de-confirmed" else row["language"])
            with db:
                db.execute("UPDATE videos SET series=?,note=?,state=?,language=? WHERE id=?",
                           (field("series")[:300], field("note")[:3000], field("state"),
                            language, field("id")))
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    print(f"Webübersicht: http://127.0.0.1:{port}")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def weekly(db, config, runtime, selected_items=None):
    selected = selected_items if selected_items is not None else [
        i for i in entries(db) if i["state"] == "selected" and
        i["language"].startswith("de-") and i["available"]]
    # One representative per channel + editorial series name.
    grouped = {}
    for item in selected:
        key = (item["channel_id"], item["series"].casefold())
        if key not in grouped or item["published"] < grouped[key]["published"]:
            grouped[key] = item
    items = sorted(grouped.values(), key=lambda i: (
        i["growth"] / i["hours"] if i["growth"] is not None else -1), reverse=True)
    items = items[:config["video"]["max_items"]]
    if not items:
        raise RuntimeError("Keine verfügbaren deutschsprachigen Videos in der Redaktionsauswahl.")
    stamp = now().strftime("%G-W%V")
    edition = config["video"].get("edition", "")
    directory = runtime / "episodes" / stamp / edition if edition else runtime / "episodes" / stamp
    directory.mkdir(parents=True, exist_ok=True)
    title = f'{config["video"]["title_prefix"]} – {stamp}'
    slides = [{"heading": title, "body": "Neue Serien und spannende Creator-Formate.\nDeutschsprachig. Redaktionell ausgewählt.",
               "speech": "Willkommen zu unseren deutschsprachigen YouTube-Formaten der Woche. Hier ist unsere aktuelle Auswahl."}]
    for item in items:
        facts = f'{item["channel"]}\n{number(item["views"])} Aufrufe · Stand {(item["captured"] or "unbekannt")[:10]}\n{growth_text(item)}'
        slides.append({"heading": item["series"], "body": facts + "\n\n" + item["note"],
                       "speech": f'{item["series"]}. Ein Format von {item["channel"]}. ' +
                       (f'Das ausgewählte Video hat zum Messstand {int(item["views"])} Aufrufe. ' if item["views"] is not None else '') +
                       (f'Im gemessenen Zeitraum von {item["hours"]:.0f} Stunden kamen {item["growth"]} Aufrufe hinzu. ' if item["growth"] is not None else '') + item["note"]})
    slides.append({"heading": "Was schaut ihr als Nächstes?", "body": "Alle Originalvideos sind in der Beschreibung verlinkt.\n\nAuswahl aus beobachteten Formaten, keine vollständige YouTube-Rangliste.",
                   "speech": "Alle Originalvideos findet ihr in der Beschreibung. Unsere Auswahl stammt aus den beobachteten Formaten und ist keine vollständige YouTube-Rangliste. Bis nächste Woche."})
    description = "Deutschsprachige YouTube-Formate der Woche.\nRedaktionelle Auswahl aus beobachteten Formaten, keine vollständige Rangliste.\n\n"
    for item in items:
        description += (f'{item["series"]} – {item["channel"]}\nhttps://www.youtube.com/watch?v={item["id"]}\n'
                        f'{number(item["views"])} Aufrufe; {growth_text(item)}; Messstand: {item["captured"]}\n\n')
    episode = {"title": title, "description": description, "created": iso(now()),
               "items": items, "slides": slides}
    (directory / "episode.json").write_text(json.dumps(episode, ensure_ascii=False, indent=2))
    (directory / "description.txt").write_text(description)
    (directory / "script.txt").write_text("\n\n".join(s["speech"] for s in slides))
    print(f"Wochenauswahl: {directory}")
    return directory


def run(command, cwd=None):
    subprocess.run(command, check=True, cwd=cwd)


def render(directory, config, silent=False):
    if config["video"].get("style") == "magazine" and not silent:
        import magazine
        magazine.render(directory, config)
        return
    episode = json.loads((directory / "episode.json").read_text())
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    clips = []
    for index, slide in enumerate(episode["slides"]):
        heading = textwrap.fill(slide["heading"], 48)
        body = "\n".join(textwrap.fill(line, 76) for line in slide["body"].splitlines())
        y = 140 + 78 * len(heading.splitlines())
        if (y + len(body.splitlines()) * 45 > 950
                or len(heading.splitlines()) > 3):
            raise RuntimeError("Text zu lang für eine Tafel. Serientitel oder Redaktionsnotiz kürzen.")
        heading_file = f"heading-{index:02}.txt"
        body_file = f"body-{index:02}.txt"
        footer_file = f"footer-{index:02}.txt"
        (directory / heading_file).write_text(heading)
        (directory / body_file).write_text(body)
        (directory / footer_file).write_text(
            f'{index + 1}/{len(episode["slides"])}  ·  Quellen in der Videobeschreibung')
        # Text files + expansion=none prevent titles/notes being parsed as FFmpeg expressions.
        filters = ("drawbox=x=0:y=0:w=28:h=1080:color=0x38bdf8:t=fill,"
                   f"drawtext=fontfile={font_path}:textfile={heading_file}:expansion=none:"
                   "x=110:y=110:fontsize=54:fontcolor=white:line_spacing=14,"
                   f"drawtext=fontfile={font_path}:textfile={body_file}:expansion=none:"
                   f"x=110:y={y}:fontsize=32:fontcolor=0xcbd5e1:line_spacing=13,"
                   f"drawtext=fontfile={font_path}:textfile={footer_file}:expansion=none:"
                   "x=110:y=1000:fontsize=23:fontcolor=0x7dd3fc,format=yuv420p")
        clip = directory / f"clip-{index:02}.mp4"
        audio = directory / f"speech-{index:02}.mp3"
        duration = max(config["video"]["slide_seconds"], len(slide["body"].split()) / 2.5)
        if not silent:
            import edge_tts
            asyncio.run(edge_tts.Communicate(slide["speech"], config["video"]["voice"]).save(str(audio)))
            probe = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)], text=True)
            duration = max(duration, float(probe) + 1)
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                   "-i", "color=c=0x101827:s=1920x1080:r=25"]
        command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"] if silent else ["-i", str(audio)]
        command += ["-t", str(duration), "-vf", filters, "-c:v", "libx264", "-threads", "2",
                    "-preset", "veryfast", "-tune", "stillimage", "-c:a", "aac", "-ar", "48000",
                    "-ac", "2", "-af", "apad", str(clip)]
        run(command, cwd=directory)
        clips.append(clip.name)
    concat = directory / "concat.txt"
    concat.write_text("".join(f"file '{name}'\n" for name in clips))
    output = directory / "weekly.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "1",
         "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(output)])
    # Tie the upload metadata to the exact video rendered from it.
    (directory / "render.json").write_text(json.dumps({
        "episode_sha256": hashlib.sha256((directory / "episode.json").read_bytes()).hexdigest(),
        "video_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "silent": silent}))
    print(f"Video erstellt: {output}")


def credentials(runtime, client_secret=None):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    path = Path(os.environ.get("YOUTUBE_TOKEN_FILE", runtime / "token.json"))
    if client_secret:
        creds = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES).run_local_server(port=0)
    elif path.exists():
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
    else:
        raise RuntimeError("Zuerst auth --client-secret /Pfad/client_secret.json ausführen.")
    if not creds.valid:
        raise RuntimeError("YouTube-Autorisierung ungültig. auth erneut ausführen.")
    # Create with restricted permissions from the first write, including token refreshes.
    if not os.environ.get("YOUTUBE_TOKEN_FILE"):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(creds.to_json())
    return creds


def upload(db, config, runtime, directory, privacy=None):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    expected = config["youtube"]["channel_id"]
    if not expected:
        raise RuntimeError("Zielkanal fehlt: youtube.channel_id in config.toml setzen.")
    episode_path, video = directory / "episode.json", directory / "weekly.mp4"
    episode = json.loads(episode_path.read_text())
    manifest = json.loads((directory / "render.json").read_text())
    fingerprint = hashlib.sha256(video.read_bytes()).hexdigest()
    if (manifest["episode_sha256"] != hashlib.sha256(episode_path.read_bytes()).hexdigest()
            or manifest["video_sha256"] != fingerprint):
        raise RuntimeError("Video oder Metadaten seit Render verändert. render erneut ausführen.")
    previous = db.execute("SELECT youtube_id FROM uploads WHERE fingerprint=?", (fingerprint,)).fetchone()
    if previous:
        print(f"Bereits hochgeladen: https://www.youtube.com/watch?v={previous[0]}")
        return
    if len(episode["title"]) > 100 or len(episode["description"].encode()) > 5000:
        raise RuntimeError("YouTube-Titel (100 Zeichen) oder Beschreibung (5000 Bytes) zu lang.")
    service = build("youtube", "v3", credentials=credentials(runtime))
    channels = service.channels().list(part="id", mine=True).execute().get("items", [])
    if expected not in [channel["id"] for channel in channels]:
        raise RuntimeError("Autorisierter Kanal entspricht nicht youtube.channel_id.")
    status = privacy or config["youtube"]["privacy"]
    if status not in {"private", "unlisted", "public"}:
        raise RuntimeError("Ungültige Sichtbarkeit.")
    request = service.videos().insert(part="snippet,status", body={
        "snippet": {"title": episode["title"], "description": episode["description"],
                    "categoryId": "24", "defaultLanguage": "de", "defaultAudioLanguage": "de"},
        "status": {"privacyStatus": status, "selfDeclaredMadeForKids": False}},
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True))
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=3)
    video_id = response["id"]
    with db:
        db.execute("INSERT INTO uploads VALUES (?,?,?)", (fingerprint, video_id, iso(now())))
    result = service.videos().list(part="status,snippet", id=video_id).execute()
    (directory / "upload.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("items"):
        raise RuntimeError(f"Upload-ID {video_id} erhalten, Abruf zur Verifikation noch ohne Ergebnis.")
    actual = result["items"][0]["status"]
    if actual["privacyStatus"] != status:
        raise RuntimeError(f"Upload-Sichtbarkeit {actual['privacyStatus']} entspricht nicht {status}.")
    print(f"Upload verifiziert: https://www.youtube.com/watch?v={video_id} "
          f"(Sichtbarkeit: {actual['privacyStatus']}; Verarbeitung: {actual.get('uploadStatus')})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--refresh-only", action="store_true")
    sub.add_parser("serve").add_argument("--port", type=int, default=8090)
    sub.add_parser("weekly")
    sub.add_parser("export").add_argument("--output", type=Path, default=ROOT / "site/results.html")
    renderer = sub.add_parser("render")
    renderer.add_argument("directory", type=Path)
    renderer.add_argument("--silent", action="store_true", help="Textvideo ohne Sprecher, z.B. für lokale Vorschau")
    sub.add_parser("auth").add_argument("--client-secret", type=Path, required=True)
    uploader = sub.add_parser("upload")
    uploader.add_argument("directory", type=Path)
    uploader.add_argument("--privacy", choices=["private", "unlisted", "public"])
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    db = database(args.runtime)
    try:
        if args.command == "collect":
            collect(db, config, not args.refresh_only)
        elif args.command == "serve":
            serve(db, config, args.port)
        elif args.command == "weekly":
            weekly(db, config, args.runtime)
        elif args.command == "export":
            export_results(db, args.output)
        elif args.command == "render":
            render(args.directory.resolve(), config, args.silent)
        elif args.command == "auth":
            credentials(args.runtime, args.client_secret)
            print("YouTube-Autorisierung gespeichert.")
        elif args.command == "upload":
            upload(db, config, args.runtime, args.directory.resolve(), args.privacy)
    except ModuleNotFoundError as error:
        parser.exit(1, f"Fehlendes Python-Modul: {error.name}. Zusatzpakete installieren mit:\n"
                    f"{ROOT / '.venv/bin/python'} -m pip install -r {ROOT / 'requirements.txt'}\n"
                    "Danach radar.py mit demselben Python aus .venv/bin/python starten.\n")
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Fehler: {error}\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
