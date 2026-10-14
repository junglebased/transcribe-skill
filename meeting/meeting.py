# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = []
# ///
"""Record a Google Meet / Zoom call locally, transcribe it with transcribe.py, publish to Notion.

No bot joins the call: system audio (others) and microphone (me) are captured on this Mac
with ScreenCaptureKit, then transcribed separately so the transcript has "Me / Others" labels.

Usage:
  uv run meeting.py start [--title T] [--platform meet|zoom|other] [--url URL]
  uv run meeting.py stop  [--lang tr] [--prompt "Names"] [--no-transcribe]
  uv run meeting.py status
  uv run meeting.py publish DIR [--summary-file F]   # needs NOTION_TOKEN + NOTION_DB_ID

Recordings live in $MEETINGS_DIR (default ~/Meetings/<YYYYMMDD-HHMM>/).
"""
import argparse
import difflib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRANSCRIBE = HERE.parent / "transcribe.py"
BASE = Path(os.environ.get("MEETINGS_DIR", "~/Meetings")).expanduser()
STATE = BASE / ".current.json"
HELPER = Path("~/.cache/transcribe-skill/audiocap").expanduser()


def load_env():
    for p in (HERE.parent / ".env", HERE / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() and not k.startswith("#") and v:
                    os.environ.setdefault(k.strip(), v.strip().strip('"'))


def build_helper():
    src = HERE / "audiocap.swift"
    if HELPER.exists() and HELPER.stat().st_mtime >= src.stat().st_mtime:
        return
    HELPER.parent.mkdir(parents=True, exist_ok=True)
    print("compiling audiocap helper (one time)…", file=sys.stderr)
    subprocess.run(["swiftc", "-O", str(src), "-o", str(HELPER)], check=True)


def detect_platform():
    if subprocess.run(["pgrep", "-x", "CptHost"], capture_output=True).returncode == 0:
        return "Zoom"  # Zoom spawns CptHost only while in a meeting
    return "Google Meet"


def cmd_start(a):
    if STATE.exists():
        sys.exit(f"already recording: {json.loads(STATE.read_text())['dir']}")
    build_helper()
    now = datetime.now()
    d = BASE / now.strftime("%Y%m%d-%H%M")
    d.mkdir(parents=True, exist_ok=True)
    platform = {"meet": "Google Meet", "zoom": "Zoom", "other": "Other"}.get(a.platform) or detect_platform()
    meta = {"title": a.title or f"{platform} {now:%Y-%m-%d %H:%M}", "platform": platform,
            "url": a.url, "start": now.isoformat(timespec="seconds"), "participants": a.participants or []}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    log = open(d / "audiocap.log", "w")
    p = subprocess.Popen([str(HELPER), str(d)], stdout=log, stderr=log, start_new_session=True)
    time.sleep(2)
    if p.poll() is not None:
        sys.exit((d / "audiocap.log").read_text())
    STATE.write_text(json.dumps({"pid": p.pid, "dir": str(d)}))
    print(f"recording → {d}\nstop: uv run {Path(__file__)} stop")


def transcribe(wav: Path, a):
    cmd = ["uv", "run", str(TRANSCRIBE), str(wav), "--mode", "json", "--out", str(wav.parent), "--force"]
    if a.lang: cmd += ["--lang", a.lang]
    if a.prompt: cmd += ["--prompt", a.prompt]
    subprocess.run(cmd, check=True)
    j = wav.with_suffix(".json")
    return json.loads(j.read_text())["segments"] if j.exists() else []


def merge(me, others):
    """Label segments; drop mic segments that are just the speakers bleeding into the mic."""
    def bleed(s):
        for o in others:
            if o["start"] < s["end"] + 1 and s["start"] < o["end"] + 1:
                if difflib.SequenceMatcher(None, s["text"].lower(), o["text"].lower()).ratio() > 0.6:
                    return True
        return False
    segs = [dict(s, who="Others") for s in others] + [dict(s, who="Me") for s in me if not bleed(s)]
    return sorted(segs, key=lambda s: s["start"])


def hms(sec):
    sec = int(sec); return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def render(segs, meta):
    out, cur = [f"# {meta['title']}\n", f"{meta['platform']} · {meta['start'].replace('T', ' ')} · {hms(meta.get('duration', 0))}\n"], None
    for s in segs:
        if s["who"] != cur:
            out.append(f"\n\n**{s['who']}** [{hms(s['start'])}]\n")
            cur = s["who"]
        out.append(s["text"].strip() + " ")
    return "".join(out).rstrip() + "\n"


def duration(f: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except ValueError: return 0.0


def cmd_stop(a):
    if not STATE.exists():
        sys.exit("not recording")
    st = json.loads(STATE.read_text())
    d = Path(st["dir"])
    try:
        os.kill(st["pid"], signal.SIGINT)
        while True:
            os.kill(st["pid"], 0); time.sleep(0.3)
    except ProcessLookupError:
        pass
    STATE.unlink()
    finish(d, a)


def finish(d: Path, a):
    meta = json.loads((d / "meta.json").read_text())
    me, others = d / "me.wav", d / "others.wav"
    srcs = [f for f in (me, others) if f.exists()]
    if not srcs:
        sys.exit(f"no audio captured, see {d / 'audiocap.log'}")
    # one compact file for keeping/sharing: stereo L=me, R=others
    if len(srcs) == 2:
        mix = ["-i", str(me), "-i", str(others), "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]"]
    else:
        mix = ["-i", str(srcs[0])]
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *mix, "-c:a", "aac", "-b:a", "96k",
                    str(d / "recording.m4a")], check=True)
    meta["duration"] = max(duration(f) for f in srcs)
    meta["recording"] = str(d / "recording.m4a")
    if not a.no_transcribe:
        segs = merge(transcribe(me, a) if me.exists() else [], transcribe(others, a) if others.exists() else [])
        (d / "transcript.json").write_text(json.dumps(segs, ensure_ascii=False, indent=1))
        (d / "transcript.md").write_text(render(segs, meta), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"DIR={d}")


# ---------- Notion ----------

def notion(method, path, body=None):
    req = urllib.request.Request(f"https://api.notion.com/v1/{path}", method=method,
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
                                          "Notion-Version": "2022-06-28", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def rt(text):
    return [{"type": "text", "text": {"content": text[i:i + 2000]}} for i in range(0, len(text), 2000)][:100]


def para(text, bold=False):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [dict(t, annotations={"bold": bold}) for t in rt(text)]}}


def cmd_publish(a):
    load_env()
    for k in ("NOTION_TOKEN", "NOTION_DB_ID"):
        if not os.environ.get(k):
            sys.exit(f"{k} missing: copy .env.example to .env (or let Claude publish via the Notion MCP)")
    d = Path(a.dir)
    meta = json.loads((d / "meta.json").read_text())
    summary = json.loads(Path(a.summary_file).read_text()) if a.summary_file else {}
    segs = json.loads((d / "transcript.json").read_text()) if (d / "transcript.json").exists() else []
    title = summary.get("title") or meta["title"]
    props = {
        "Title": {"title": rt(title)},
        "Date": {"date": {"start": meta["start"]}},
        "Platform": {"select": {"name": meta["platform"]}},
        "Participants": {"multi_select": [{"name": p[:100]} for p in summary.get("participants", meta.get("participants", []))]},
        "Duration (min)": {"number": round(meta.get("duration", 0) / 60, 1)},
        "Summary": {"rich_text": rt(summary.get("summary", ""))},
        "Action items": {"rich_text": rt("\n".join(f"• {x}" for x in summary.get("action_items", [])))},
        "Recording": {"url": summary.get("recording_url") or meta.get("url") or None},
    }
    blocks = [{"object": "block", "type": "heading_2", "heading_2": {"rich_text": rt("Transcript")}}]
    cur = None
    for s in segs:
        if s["who"] != cur:
            blocks.append(para(f"{s['who']} [{hms(s['start'])}]", bold=True)); cur = s["who"]
            blocks.append(para(""))
        last = blocks[-1]["paragraph"]["rich_text"]
        text = ("".join(t["text"]["content"] for t in last) + " " + s["text"].strip()).strip()
        if len(text) > 1900:
            blocks.append(para(s["text"].strip()))
        else:
            blocks[-1] = para(text)
    page = notion("POST", "pages", {"parent": {"database_id": os.environ["NOTION_DB_ID"]},
                                     "properties": props, "children": blocks[:100]})
    for i in range(100, len(blocks), 100):
        notion("PATCH", f"blocks/{page['id']}/children", {"children": blocks[i:i + 100]})
    meta["notion_url"] = page["url"]
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(page["url"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--title"); s.add_argument("--platform", choices=["meet", "zoom", "other"]); s.add_argument("--url")
    s.add_argument("--participants", nargs="*")
    for name in ("stop", "finish"):
        s = sub.add_parser(name)
        if name == "finish": s.add_argument("dir")
        s.add_argument("--lang"); s.add_argument("--prompt"); s.add_argument("--no-transcribe", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("publish"); s.add_argument("dir"); s.add_argument("--summary-file")
    a = ap.parse_args()
    if a.cmd == "start": cmd_start(a)
    elif a.cmd == "stop": cmd_stop(a)
    elif a.cmd == "finish": finish(Path(a.dir), a)
    elif a.cmd == "status": print(STATE.read_text() if STATE.exists() else "idle")
    elif a.cmd == "publish": cmd_publish(a)


if __name__ == "__main__":
    main()
