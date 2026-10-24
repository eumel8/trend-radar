"""Thumbnail-based magazine: animated branding, editorial voice and ducked music."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import textwrap
from urllib.error import HTTPError
from urllib.request import urlopen

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG = "0x0b1020"
LIME = "0xb6ff42"
PINK = "0xff427a"


def run(command, directory):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *command],
                   check=True, cwd=directory)


def duration(path):
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True))


def thumbnail(video_id, directory):
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise RuntimeError("Ungültige YouTube-Video-ID für Thumbnail.")
    path = directory / f"thumbnail-{video_id}.jpg"
    for quality in ("maxresdefault", "sddefault", "hqdefault"):
        try:
            with urlopen(f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg", timeout=30) as response:
                content = response.read(5_000_001)
            if len(content) > 5_000_000:
                raise RuntimeError("Thumbnail unerwartet groß.")
            path.write_bytes(content)
            return path
        except HTTPError as error:
            if error.code != 404:
                raise RuntimeError(f"Thumbnail-Abruf: HTTP {error.code}") from None
    raise RuntimeError(f"Kein Thumbnail für {video_id} verfügbar.")


def text(directory, name, value, x, y, size, color="white", bold=False, extra=""):
    (directory / f"{name}.txt").write_text(value, encoding="utf-8")
    font = BOLD if bold else FONT
    return (f"drawtext=fontfile={font}:textfile={name}.txt:expansion=none:"
            f"x={x}:y={y}:fontsize={size}:fontcolor={color}:line_spacing=12" + extra)


def brand(directory, name):
    return [
        f"drawbox=x=72:y=55:w=310:h=62:color={BG}@0.92:t=fill",
        f"drawbox=x=294:y=55:w=88:h=62:color={LIME}:t=fill",
        text(directory, name + "brand", "TRENDS", 88, 64, 37, bold=True),
        text(directory, name + "de", "DE", 308, 64, 37, BG, bold=True),
    ]


def speech(text_value, path, voice, silent=False):
    if silent:
        run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2",
             "-c:a", "libmp3lame", str(path)], path.parent)
    else:
        import edge_tts
        asyncio.run(edge_tts.Communicate(text_value, voice, rate="+8%").save(str(path)))


def build_plan(episode, config):
    generated = episode.get("generated_script")
    if generated:
        return [{"kind": "intro", **generated["intro"]}, *[
            {"kind": "item", "item": item, "rank": index + 1, **scene}
            for index, (item, scene) in enumerate(zip(episode["items"], generated["items"]))],
                {"kind": "outro", **generated["outro"]}]
    items = episode["items"]
    plan = [{"kind": "intro", "heading": "DEIN NÄCHSTER\nYOUTUBE-RABBIT-HOLE.",
             "tag": "DER FORMAT-CHECK", "speech":
             f"Neue Serien, große Abenteuer und akute Flucht aus dem Büro. Wir haben {len(items)} deutschsprachige Formate für eure Watchlist. Das ist Trends D E. Los geht's!"}]
    for index, item in enumerate(items):
        editorial = config.get("editorial", {}).get(item["id"], {})
        fallback = (f"{item['series']}. Ein Format von {item['channel']}. " +
                    (item["note"] or "Der Auftakt steht auf unserer Watchlist. Schaut rein und bildet euch selbst ein Urteil."))
        heading = editorial.get("headline", item["series"].upper())
        if len(heading) > 120:
            heading = heading[:117] + "..."
        plan.append({"kind": "item", "item": item, "rank": index + 1,
                     "heading": heading, "tag": editorial.get("tag", "AUF UNSERER WATCHLIST"),
                     "speech": editorial.get("speech", fallback)})
    plan.append({"kind": "outro", "heading": "WAS KOMMT AUF\nDEINE WATCHLIST?", "tag": "DU BIST DRAN", "speech":
                 "Welches Format schauen wir als Nächstes? Schreibt euren Favoriten in die Kommentare. Alle Originale sind unten verlinkt. Abonniert Trends D E für den nächsten Format-Check. Wir suchen weiter, ihr spart euch das Scrollen!"})
    return plan


def render(directory, config, silent=False):
    directory = directory.resolve()
    episode_path = directory / "episode.json"
    episode = json.loads(episode_path.read_text())
    if (directory / "ai-script.json").exists():
        from editor import validate_script
        episode["generated_script"] = validate_script(
            json.loads((directory / "ai-script.json").read_text())["script"], episode)
    music = Path(config["video"]["music_file"])
    if not music.is_file():
        raise RuntimeError(f"Hintergrundmusik fehlt: {music}")
    plan = build_plan(episode, config)
    (directory / "magazine-script.txt").write_text("\n\n".join(p["speech"] for p in plan))
    timeline, offset, clips = [], 0.0, []
    for index, scene in enumerate(plan):
        audio = directory / f"mag-voice-{index:02}.mp3"
        speech(scene["speech"], audio, config["video"]["voice"], silent=silent)
        seconds = duration(audio) + 0.7
        frames = int(seconds * 25) + 1
        name = f"mag-{index:02}"
        if scene["kind"] == "item":
            item = scene["item"]
            image = thumbnail(item["id"], directory)
            # Alternating pan direction and a slow zoom provide motion without source-video downloads.
            x = "iw/2-iw/zoom/2" if index % 2 else "(iw-iw/zoom)*(1-on/" + str(frames) + ")"
            zoom = (f"scale=2200:1238:force_original_aspect_ratio=increase,crop=2200:1238,"
                    f"zoompan=z='1.02+0.10*on/{frames}':x='{x}':y='ih/2-ih/zoom/2':"
                    "d=1:s=1920x1080:fps=25")
            command = ["-loop", "1", "-framerate", "25", "-i", str(image), "-i", str(audio)]
            filters = [zoom, "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.16:t=fill",
                       f"drawbox=x=0:y=700:w=iw:h=380:color={BG}@0.92:t=fill",
                       f"drawbox=x=72:y=677:w=180:h=10:color={LIME}:t=fill"]
            heading = textwrap.fill(scene["heading"], 40)
            filters += [text(directory, name + "head", heading, 76, 733, 57, bold=True),
                        text(directory, name + "channel", f"{item['series']}  /  {item['channel']}",
                             78, 904, 29, "0xd2dbed"),
                        f"drawbox=x=1585:y=55:w=260:h=62:color={PINK}:t=fill",
                        text(directory, name + "count", f"CHECK {scene['rank']:02}", 1610, 65, 35, bold=True)]
            filters += [text(directory, name + "tag", scene["tag"], 80, 637, 28, LIME, bold=True),
                        text(directory, name + "source", "ANIMIERTES ORIGINAL-THUMBNAIL  /  QUELLE IN DER BESCHREIBUNG",
                             78, 1028, 20, "0xc7d3e8")]
            views = "–" if item["views"] is None else f"{item['views']:,}".replace(",", ".")
            filters += [text(directory, name + "views", f"{views} AUFRUFE  |  STAND {(item['captured'] or '')[:10]}",
                             78, 965, 25, LIME)]
        else:
            command = ["-f", "lavfi", "-i", f"color=c={BG}:s=1920x1080:r=25", "-i", str(audio)]
            filters = [
                f"drawbox=x=1540:y=0:w=380:h=1080:color={LIME}:t=fill",
                f"drawbox=x=1500:y=0:w=30:h=1080:color={PINK}:t=fill",
                text(directory, name + "bigde", "DE", "1560+12*sin(t*2)", 420, 165, BG, bold=True),
                text(directory, name + "tag", scene["tag"], 92, 270, 33, LIME, bold=True),
                text(directory, name + "headline", textwrap.fill(scene["heading"], 26), "92+12*sin(t*1.4)", 375, 70, bold=True),
                text(directory, name + "footer", "NEUE FORMATE. GROSSE IDEEN. KURZER CHECK.", 92, 870, 30, "0xc7d3e8"),
            ]
        filters += brand(directory, name)
        # Smooth scene entries/exits, plus an animated lower progress bar.
        filters += [f"drawbox=x=0:y=1071:w=1920:h=9:color={PINK}:t=fill",
                    "format=yuv420p", "fade=t=in:st=0:d=0.18",
                    f"fade=t=out:st={seconds - 0.2:.3f}:d=0.2"]
        clip = directory / f"{name}.mp4"
        run([*command, "-t", str(seconds), "-vf", ",".join(filters),
             "-af", "apad,loudnorm=I=-16:TP=-1.5:LRA=9", "-c:v", "libx264", "-threads", "2",
             "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-ar", "48000", "-ac", "2",
             str(clip)], directory)
        timeline.append({"start": offset, "heading": scene["heading"].replace("\n", " "),
                         "duration": duration(clip)})
        offset += timeline[-1]["duration"]
        clips.append(clip.name)
    (directory / "mag-concat.txt").write_text("".join(f"file '{clip}'\n" for clip in clips))
    joined = directory / "mag-joined.mp4"
    run(["-f", "concat", "-safe", "1", "-i", "mag-concat.txt", "-c", "copy", str(joined)], directory)
    output = directory / "weekly.mp4"
    # Side-chain compression automatically lowers the music under narration.
    mix = ("[0:a]asplit=2[voice][side];"
           "[1:a]volume=0.14,afade=t=in:st=0:d=1,"
           f"afade=t=out:st={max(0, offset - 2):.3f}:d=2[music];"
           "[music][side]sidechaincompress=threshold=0.025:ratio=8:attack=15:release=350[ducked];"
           "[voice][ducked]amix=inputs=2:duration=first:normalize=0,"
           "alimiter=limit=0.95[audio]")
    run(["-i", str(joined), "-stream_loop", "-1", "-i", str(music.resolve()),
         "-filter_complex", mix, "-map", "0:v:0", "-map", "[audio]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-t", str(offset), "-movflags", "+faststart", str(output)], directory)
    (directory / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2))
    if not episode.get("generated_script"):
        episode["title"] = f"Europa als Versteck?! 4 Formate für deine Watchlist | TrendsDE {episode['created'][:10]}" if len(episode["items"]) == 4 and any(i["id"] == "aqAHH0Mh11k" for i in episode["items"]) else episode["title"]
    episode["description"] += ("\nBildmaterial: animierte Original-Thumbnails der oben verlinkten Videos; "
                               "keine Ausschnitte aus den Originalvideos.\nMusik: Tidal Pulse (vom Betreiber bereitgestellt)."
                                "\nModeration: synthetische deutsche Stimme.\n")
    if episode.get("script_provider") == "openai":
        episode["description"] += "Moderationstext: KI-gestützt aus öffentlichen Videometadaten erstellt; keine Rezension der Originalvideos.\n"
    episode_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2))
    (directory / "description.txt").write_text(episode["description"])
    (directory / "render.json").write_text(json.dumps({
        "episode_sha256": hashlib.sha256(episode_path.read_bytes()).hexdigest(),
        "video_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "style": "magazine",
        "music_sha256": hashlib.sha256(music.read_bytes()).hexdigest(), "silent": silent}))
    print(f"Magazin erstellt: {output} ({offset:.1f} Sekunden)")
