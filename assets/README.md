# TrendsDE-Kanaldesign

- `channel-logo.png`: 800 × 800 Pixel, für den runden YouTube-Profilbildzuschnitt.
- `channel-banner.png`: 2560 × 1440 Pixel. Identität und Text liegen innerhalb der
  mittleren 1546 × 423 Pixel (x=507..2053, y≈509..931).
- Die gleichnamigen SVG-Dateien sind die editierbaren Vorlagen.
- Farben: Nachtblau `#0b1020`, Neongrün `#b6ff42`, Pink `#ff427a`, Weiß.
- Schrift: DejaVu Sans Bold, passend zu den Magazin-Videos.

PNG-Dateien reproduzierbar aus SVG erzeugen (CairoSVG nur als Designwerkzeug):

```bash
trend-radar/.venv/bin/python -m pip install cairosvg
trend-radar/.venv/bin/python -c "import cairosvg; from pathlib import Path; p=Path('trend-radar/assets'); [cairosvg.svg2png(url=str(p/(n+'.svg')),write_to=str(p/(n+'.png'))) for n in ('channel-logo','channel-banner')]"
kubectl apply --server-side -k trend-radar
```

Downloads und Vorschau: https://trendsde.b.eumel.de/branding.html
In YouTube Studio unter Anpassung → Profil hochladen und veröffentlichen.

Für Deployments `--server-side` verwenden: Die Website-ConfigMap enthält jetzt
PNG-Dateien; eine clientseitige Last-Applied-Annotation überschreitet damit das
Kubernetes-Annotationslimit.
