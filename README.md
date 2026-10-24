# Deutschsprachiger YouTube-Trend-Radar

Lokale Webübersicht und Redaktionswerkzeug für neue deutschsprachige YouTube-Formate.
Erfasst öffentliche Videodaten und Messhistorien, erstellt Wochenrückblicke mit FFmpeg
und kann diese über die offizielle YouTube API hochladen. Keine Benachrichtigungen.

## Veröffentlichung des Quellcodes

Der Projektordner enthält keine eingebauten API-Schlüssel oder OAuth-Zugangsdaten.
`runtime/`, `.venv/`, OAuth-Dateien, `.env`-Dateien, private Schlüssel und lokale
Datenbanken sind über `.gitignore` ausgeschlossen. `runtime/` enthält im Betrieb
vertrauliche Daten: insbesondere `token.json` und `registry-auth/config.json`.
Den Ordner deshalb weder vollständig als ZIP hochladen noch mit `git add -f`
aufnehmen. Für ein eigenständiges Repository nur Git-berücksichtigte Projektdateien
übernehmen und die enthaltene `.gitignore` beibehalten.

Bewusst öffentlich enthalten sind die Domain, Kanal-ID, Kontaktangaben, Deployment-
Namen, das eigene Branding und eine Ergebnis-Momentaufnahme mit öffentlichen
YouTube-Metadaten. Diese Konfiguration ist auf die TrendsDE-Installation zugeschnitten.
Die Musikdatei, heruntergeladene Thumbnails und gerenderte Videos liegen ausschließlich
unter dem ignorierten Runtime-Verzeichnis beziehungsweise auf dem Cluster-Volume.
Eine Open-Source-Lizenz ist noch nicht festgelegt.

## Einrichtung

### Öffentliche Projektseite im Kubernetes-Cluster

**Seit Aufnahme der Kanalgrafiken mit `kubectl apply --server-side -k trend-radar`
bereitstellen.** Die PNG-Dateien in der Website-ConfigMap überschreiten bei
clientseitigem Apply das Limit der Last-Applied-Annotation. Downloads:
https://trendsde.b.eumel.de/branding.html. Vorlagen und Renderanleitung unter `assets/`.

Ergebnisse als öffentliche Momentaufnahme exportieren und bereitstellen:

```bash
python3 trend-radar/radar.py export
kubectl --context kubernetes-admin@kubernetes apply -k trend-radar
```

Die Übersicht unter `/results.html` enthält ausschließlich öffentliche Videofakten,
keine internen Notizen oder Zugangsdaten. Sie wird nach Gesamtaufrufen sortiert und
ist ausdrücklich kein automatisch ermitteltes Trend-Ranking. Ein Export aktualisiert
die Momentaufnahme; der Server fragt dabei nicht selbst die YouTube API ab.

`site/` enthält die öffentliche Projektbeschreibung, Datenschutz, Nutzungsbedingungen
und Kontakt. Sie bildet den tatsächlichen Entwicklungsstand ab; die interne
Redaktionsoberfläche und OAuth-Dateien werden darüber nicht veröffentlicht.

```bash
kubectl --context kubernetes-admin@kubernetes apply -k trend-radar
kubectl --context kubernetes-admin@kubernetes -n trendsde rollout status deployment/trendsde-site
kubectl --context kubernetes-admin@kubernetes -n trendsde get certificate,ingress
```

Namespace: `trendsde`, Host: `https://trendsde.b.eumel.de`, Ingress-Klasse `nginx`,
ClusterIssuer `letsencrypt`. Die statischen Dateien liegen in einer versionierten
ConfigMap; Kustomize rollt Inhaltsänderungen über den ConfigMap-Hash aus.
Betreiber/Kontakt sind aus der vorhandenen Projektseite des Betreibers übernommen:
Frank Kloeker, `admin@eumelnet.de`. Eine Postanschrift wurde nicht angegeben.
Die Datenschutzerklärung benennt auch den aktuellen Stand der Datenaufbewahrung;
sie ersetzt keine Umsetzung noch fehlender Lösch-/Aufbewahrungsfunktionen.

### Lokale Recherche- und Videowerkzeuge

Python 3.11+, FFmpeg mit `drawtext`/libx264 sowie DejaVu Sans werden benötigt.
Die Sammlung, Webübersicht und stumme Videoerzeugung benötigen nur die Python-Standardbibliothek.
Die zusätzlichen Pakete sind für Sprachausgabe und OAuth-Upload erforderlich.

```bash
python3 -m venv trend-radar/.venv
trend-radar/.venv/bin/pip install -r trend-radar/requirements.txt
export YOUTUBE_API_KEY='...'
trend-radar/.venv/bin/python trend-radar/radar.py collect
trend-radar/.venv/bin/python trend-radar/radar.py serve
```

Die Übersicht läuft unter **http://127.0.0.1:8090**. Für entfernten Zugriff einen
SSH-Tunnel verwenden. Eine öffentliche Bereitstellung benötigt einen vorgeschalteten
Webserver mit Authentifizierung. SQLite, OAuth-Token und Videos liegen unter
`trend-radar/runtime/` und sind Git-ignoriert.

In Google Cloud die **YouTube Data API v3** aktivieren und einen API-Schlüssel
erstellen. Suchbegriffe, Beispieltitel-IDs und Zeitraum stehen in `config.toml`.
Die vier Nutzerbeispiele sind als deutschsprachig bestätigt. Ihre Kanäle werden
nach der ersten erfolgreichen Sammlung über Upload-Playlists beobachtet.
Weitere als deutschsprachig erkannte Treffer werden regelmäßig nachgemessen;
neue Kanal-Uploads werden zunächst für die vier bestätigten Ausgangskanäle gesucht.

Die deutschsprachige Suchpräferenz ist kein harter Sprachfilter: Treffer ohne
Sprachmetadaten erscheinen gesondert unter **Sprache prüfen**. Dort die tatsächliche
Sprache prüfen und bestätigen. Anderssprachig markierte Videos sind ausgeblendet.

## Redaktion und Wochenvideo

### Magazin-Gestaltung (aktuell)

`video.style = "magazine"` aktiviert `magazine.py`: TrendsDE-Wortmarke in
Nachtblau/Neongrün/Pink, animiertes Intro/Outro, formatbezogene Hooks und
Original-Thumbnails mit Zoom/Schwenks. Die Thumbnails werden einzeln von
`i.ytimg.com` geladen (maxres mit Qualitäts-Fallback). Originalvideodateien
werden dafür nicht heruntergeladen; animierte Thumbnails sind keine Videoausschnitte.
Quellen und diese Unterscheidung erscheinen in der Videobeschreibung.

Die vier Beispiele haben eigene Moderationstexte unter `[editorial.VIDEO_ID]`
in `config.toml`. Weitere Formate verwenden ihre Redaktionsnotiz als Sprechertext.
Titel und Aufrufzahlen sind keine Grundlage für behauptete Szenen oder Rezensionen:
Die Moderation ordnet den Serienstart ein, ohne vorzugeben, das Original gesehen zu haben.

`video.music_file` verweist im Cluster auf `/data/runtime/assets/tidal-pulse.m4a`.
Die vom Betreiber bereitgestellte Datei „Tidal Pulse.m4a“ wurde dort abgelegt.
Die Musik wird geloopt, ein-/ausgeblendet und unter der normalisierten Moderation
per Sidechain-Kompression automatisch abgesenkt. Originalmusik wird nicht ins
Container-Image oder öffentliche Webverzeichnis kopiert.

`video.edition = "magazine-v2"` trennt diese Fassung vom ersten Texttafel-Test:
Artefakte liegen in `episodes/JAHR-WKW/magazine-v2/`. Pro Kalenderwoche und Edition
wird nur ein Video hochgeladen. Für eine bewusst neue Testfassung eine neue
Edition setzen; anschließend `kubectl apply -k trend-radar` ausführen.
Das Worker-Image muss bei Python-Codeänderungen neu gebaut werden.

Zusätzliche Artefakte: `magazine-script.txt`, `timeline.json`, heruntergeladene
Thumbnails, Sprachdateien, einzelne Szenen, fertiges `weekly.mp4` und `upload.json`.
Das vektorbasierte Logo liegt unter `assets/logo.svg`; dieselbe Wortmarke wird
im Video durch FFmpeg gezeichnet.

1. Unter **Neue Formate** interessante Treffer sichten. Serientitel bei Bedarf
   korrigieren; Folgen werden im Wochenvideo anhand von Kanal + Serientitel gebündelt.
2. Mit **Für Wochenvideo** auswählen und einen eigenen kurzen Kommentar unter
   **Redaktionsnotiz** ergänzen. Die Notiz erscheint im Video und wird gesprochen.
3. Wochenauswahl erzeugen:

```bash
trend-radar/.venv/bin/python trend-radar/radar.py weekly
```

Ergebnis: `runtime/episodes/JAHR-WKW/` mit `episode.json`, `script.txt` und
`description.txt`. Die Auswahl umfasst bis zu fünf markierte Formate, geordnet
nach gemessenem Aufrufzuwachs pro Stunde, soweit Vergleichsdaten existieren.
Sie ist eine redaktionelle Auswahl, kein automatisches Gesamtranking von YouTube.
Markierungen bleiben bis zur manuellen Änderung erhalten, auch über Wochen hinweg.

```bash
# Verzeichnis durch den von weekly ausgegebenen Pfad ersetzen:
trend-radar/.venv/bin/python trend-radar/radar.py render trend-radar/runtime/episodes/2026-W43

# Offline-Vorschau ohne Sprecher:
python3 trend-radar/radar.py render trend-radar/runtime/episodes/2026-W43 --silent
```

FFmpeg erzeugt **1920×1080, H.264/AAC, 25 fps** mit Intro, eigenen Texttafeln und Outro.
Die deutsche Sprachausgabe über `edge-tts` benötigt Internet und übermittelt den
Sprechertext an den Sprachdienst. Originalvideos werden verlinkt. Der Rückblick
enthält eigene Grafiken, keine heruntergeladenen Originalclips.

`weekly` erneut auszuführen aktualisiert die Metadaten derselben Kalenderwoche.
Anschließend neu rendern: Der Upload prüft, ob Video und Metadaten zusammenpassen.

## YouTube autorisieren und hochladen

Im Google-Cloud-Projekt einen OAuth-Client vom Typ **Desktop-App** anlegen,
Zugriff auf die YouTube API einrichten und die Client-Datei lokal speichern.
Bei einem OAuth-Projekt im Testmodus muss das Upload-Konto als Testnutzer
eingetragen sein; solche Autorisierungen können nach sieben Tagen ablaufen.

```bash
trend-radar/.venv/bin/python trend-radar/radar.py auth --client-secret /pfad/client_secret.json
```

Der Browser-Login muss den gewünschten YouTube-Kanal auswählen. Bei einem Server
ohne lokalen Browser die Autorisierung auf einem Rechner mit Browser durchführen
und die Token-Datei geschützt in dessen Runtime-Verzeichnis übertragen.
`runtime/token.json` wird mit Dateirechten 0600 gespeichert.

In `config.toml` unter `[youtube]` dessen **Kanal-ID `UC...`** eintragen. Vor jedem
Upload wird geprüft, dass die Autorisierung zu diesem Kanal gehört.

```bash
trend-radar/.venv/bin/python trend-radar/radar.py upload trend-radar/runtime/episodes/2026-W43

# Sichtbarkeit explizit festlegen:
trend-radar/.venv/bin/python trend-radar/radar.py upload trend-radar/runtime/episodes/2026-W43 --privacy public
```

Standard ist `private`; die gewünschte Standardsichtbarkeit kann in der Konfiguration
gesetzt werden. YouTube kann Uploads nicht auditierter API-Projekte auf privat
beschränken. Nach dem Upload wird die tatsächliche Sichtbarkeit abgerufen und
ausgegeben. Die Verarbeitung durch YouTube kann danach noch laufen.
Identische Videodateien werden anhand ihres SHA-256-Hashes nicht erneut hochgeladen.
Bei einem Verbindungsabbruch nach erfolgreicher Annahme vor Speicherung der Upload-ID
zuerst im YouTube Studio prüfen, ob das Video bereits existiert.

## Regelmäßiger Betrieb

### Aktiver Clusterbetrieb

Im Namespace `trendsde` laufen die folgenden CronJobs (Zeitzone `Europe/Berlin`):

| CronJob | Zeit | Aufgabe |
|---|---|---|
| `trendsde-collector` | Täglich 07:00 | Acht Suchen, Kanal-Uploads, Messung und öffentliche Ergebnisübersicht |
| `trendsde-refresh` | Täglich 13:00 und 19:00 | Nachmessung und Veröffentlichung ohne Suchabfragen |
| `trendsde-video` | Sonntag 18:00 | Redaktionsauswahl rendern, mit deutscher Sprachausgabe, Upload **privat** |

Datenbank, Ergebnis-HTML und Videoartefakte liegen auf `trendsde-data` (5 GiB,
`local-path`). Der Webserver liefert `/results.html` direkt aus dem gemeinsamen
Volume aus. Weder Datenbank noch Videos oder OAuth-Dateien sind öffentlich abrufbar.
API-Schlüssel und OAuth-Datei liegen in separaten Kubernetes-Secrets; nur der
Videojob bekommt das OAuth-Secret. Ein Dateilock serialisiert alle Worker.

Der Videojob verarbeitet ausschließlich `selected` markierte Einträge. Für den
ersten End-to-End-Test wurden die vier Nutzerbeispiele ausgewählt und mit kurzen
eigenen Kommentaren versehen. Die Auswahl bleibt bestehen, bis sie geändert wird.
Ein erneuter Lauf nach erfolgreichem Upload derselben Kalenderwoche wird übersprungen;
fertige Renderartefakte werden nach einem Uploadfehler wiederverwendet.
Bei leerer Auswahl schlägt der Job mit einer verständlichen Meldung fehl.

Manuelle Läufe und Kontrolle:

```bash
kubectl -n trendsde create job --from=cronjob/trendsde-collector collector-manual-01
kubectl -n trendsde logs -f job/collector-manual-01
kubectl -n trendsde create job --from=cronjob/trendsde-video video-manual-01
kubectl -n trendsde logs -f job/video-manual-01
kubectl -n trendsde get cronjob,job,pvc
```

Für Wartung/Redaktionsänderungen kann vorübergehend der Pod aus
`deploy/bootstrap.yaml` gestartet werden. Er mountet das Datenvolume und wird nach
der Wartung gelöscht. Die initiale Datenbank wurde einmalig aus dem lokalen
Arbeitsverzeichnis übertragen. Neue Daten entstehen jetzt im Cluster; die lokale
Kopie ist keine fortlaufend synchronisierte Kopie mehr.

### GitHub Actions und GHCR

Der Workflow `.github/workflows/image.yaml` ist für das eigenständige Repository
**`eumel8/trend-radar`** ausgelegt. Dessen Wurzel muss dem Inhalt dieses
Projektordners entsprechen, einschließlich `.github/`, `.gitignore` und Dockerfile.
Solange der Ordner nur unter `k8s-agent/trend-radar/` liegt, führt GitHub diesen
verschachtelten Workflow nicht aus.

- Pull Requests nach `main`: Tests mit echtem FFmpeg-Render und Container-Build,
  ohne Image-Push und ohne YouTube-Zugangsdaten.
- Push nach `main`: Tests, Build und Push nach **`ghcr.io/eumel8/trend-radar`**.
- Versions-Tags mit oder ohne `v`, z. B. `0.0.1` oder `v1.2.0`: zusätzlicher Build
  mit Semver-Image-Tags wie `0.0.1` und `0.0` beziehungsweise `1.2.0` und `1.2`.
- Manueller Start über GitHub Actions ist ebenfalls möglich.
- Image-Tags: `main`, `latest` (nur main), `sha-<vollständiger Commit-SHA>` und
  gegebenenfalls Release-Tags. Zielplattform ist `linux/amd64`, passend zum Cluster.

Der Push verwendet den automatisch bereitgestellten `GITHUB_TOKEN` mit
`packages: write`. Eigene Registry-Passwörter oder YouTube-Secrets sind für die
Pipeline nicht erforderlich. Beim ersten Build unter GitHub Packages die
Sichtbarkeit des Pakets auf **Public** setzen, damit die Cluster-Jobs es ohne
Pull-Secret abrufen können. Bei bereits bestehendem Paket muss das Repository
Schreibzugriff auf dieses Paket haben.

Die Jobmanifeste verwenden `ghcr.io/eumel8/trend-radar:main` mit
`imagePullPolicy: Always`; damit bekommt jeder neue Job den aktuellen main-Build.
Für eine festgeschriebene Version einen SHA-Tag oder Digest verwenden.
Nach dem ersten erfolgreichen Push und einem anonymen Pull-Test auf GHCR umstellen:

```bash
nerdctl pull ghcr.io/eumel8/trend-radar:main
kubectl apply --server-side -k trend-radar
```

Im eigenständigen Repository stattdessen `kubectl apply --server-side -k .` verwenden.
Die Pipeline führt keinen automatischen Cluster-Deploy aus.

Die ursprünglichen Cluster-Testläufe verwenden noch die eigene Registry unter
`trendsde.b.eumel.de/v2/`. Sie wurde aus der Standard-Kustomization entfernt;
`deploy/registry.yaml` bleibt als Dokumentation der bisherigen Installation erhalten.
Die laufende Registry wird durch die Änderung an den Dateien nicht gelöscht.
Erst nach erfolgreichem GHCR-Test deren Deployment, Service und Ingress gezielt
entfernen; das PVC für einen Rückweg zunächst behalten.

`provision_secrets.py` übernimmt `YOUTUBE_API_KEY` und `runtime/token.json` ohne
Ausgabe der Inhalte in die Cluster-Secrets. Nur mit `--legacy-registry` werden
zusätzlich die bisherigen Registry-Zugangsdaten eingerichtet (dafür Python 3.12
mit `crypt` erforderlich). Eine spätere erneute OAuth-Anmeldung muss
auch in das Cluster-Secret übernommen werden. Der Refresh des Access-Tokens
erfolgt im laufenden Job; die gemountete Secret-Datei bleibt unverändert.
Eine automatische Artefaktbereinigung und ein Volume-Backup sind noch nicht eingerichtet.

### Alternative: lokaler Cronbetrieb

Erst nach erfolgreichem manuellen Durchlauf einen Zeitplan einrichten.
Beispiel für Cron; Pfade an den tatsächlichen Installationsort anpassen und den
API-Schlüssel geschützt in der Job-Umgebung hinterlegen:

```cron
# Täglich um 07:00 neue Inhalte entdecken und messen:
0 7 * * * /pfad/trend-radar/.venv/bin/python /pfad/trend-radar/radar.py collect
# Zusätzliche Messungen um 13:00 und 19:00, ohne neue Suchabfragen:
0 13,19 * * * /pfad/trend-radar/.venv/bin/python /pfad/trend-radar/radar.py collect --refresh-only
```

Suchaufrufe und Folgeseiten beanspruchen API-Quoten; vor Aktivierung das aktuelle
Projektlimit in Google Cloud prüfen. Acht Suchbegriffe und eine Seite ergeben
acht Suchaufrufe pro vollständigem Durchlauf, zusätzlich zu Playlist-/Statistikaufrufen.
Es gibt keine vollständige Erfassung aller YouTube-Formate. Pro beobachtetem Kanal
werden maximal 150 neueste Uploads betrachtet. Die erste Messung liefert noch
keinen Wachstumswert. Spätere Differenzen verwenden ein **mindestens 24 Stunden**
langes tatsächliches Messintervall, das in der Übersicht angegeben wird.

## Verifikation

```bash
python3 -m unittest discover -s trend-radar -v
RADAR_RENDER_TEST=1 python3 -m unittest discover -s trend-radar -v
```

Die zweite Variante erzeugt ein echtes FFmpeg-Testvideo mit künstlichen Testdaten
in einem temporären Verzeichnis und prüft anschließend Codec, Auflösung und Tonspur
mit ffprobe. API-Sammlung wird mit kontrollierten Antworten getestet; echte Sammlung,
Sprachausgabe und Upload benötigen Netzwerkzugriff und eigene Zugangsdaten.
