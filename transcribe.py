# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["mlx-whisper"]
# ///
"""Free, local transcription for Apple Silicon (mlx-whisper, same Whisper models MacWhisper uses).

Usage:
  uv run transcribe.py PATH [PATH...] [--mode plain|timed|md|srt|vtt|json|all]
                       [--model turbo|large|medium|small|<hf-repo>] [--lang tr]
                       [--prompt "Names, Terms"] [--out DIR] [--tc-start 01:00:00:00 --fps 25]
                       [--max-chars 42] [--force]

PATH can be a file or a folder (all audio/video inside is processed).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

MODELS = {
    "turbo": "mlx-community/whisper-large-v3-turbo",
    "large": "mlx-community/whisper-large-v3-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
}
MEDIA_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff", ".aif",
             ".mp4", ".mov", ".mkv", ".webm", ".avi", ".mxf", ".m4v"}

# Phrases Whisper invents on silence/music (YouTube-subtitle training artifacts).
HALLUCINATIONS = [
    r"altyaz[ıi] m\.?k\.?", r"izledi[ğg]iniz i[çc]in te[şs]ekk[üu]r", r"abone ol",
    r"thanks? (you )?for watching", r"subtitles? by", r"amara\.org", r"please subscribe",
    r"untertitel", r"sous-titres", r"\[m[üu]zik\]", r"\[music\]",
]
HALLU_RE = re.compile("|".join(HALLUCINATIONS), re.I)


# ---------- time helpers ----------
def parse_tc(tc, fps):
    h, m, s, f = (int(x) for x in re.split(r"[:;]", tc))
    return h * 3600 + m * 60 + s + f / fps


def ts(sec, sep="."):
    sec = max(sec, 0)
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    ms = int(round((sec - int(sec)) * 1000)) % 1000
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def tc_frames(sec, fps):
    total = int(round(sec * fps))
    f = total % fps
    s = total // fps
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


# ---------- cleanup ----------
def clean_segments(segs):
    out, prev, repeats = [], None, 0
    for s in segs:
        t = s["text"].strip()
        if not t or HALLU_RE.search(t):
            continue
        if s.get("compression_ratio", 0) > 2.6 and s.get("avg_logprob", 0) < -1.0:
            continue
        repeats = repeats + 1 if t == prev else 0
        if repeats >= 2:  # same line 3+ times in a row = loop
            continue
        prev = t
        out.append({**s, "text": t})
    return out


def all_words(segs):
    words = []
    for s in segs:
        for w in s.get("words") or []:
            if w["word"].strip():
                words.append({"w": w["word"].strip(), "start": w["start"], "end": w["end"]})
    return words


# ---------- subtitle cues (Netflix-style: <=2 lines, <=max_chars/line, <=7s) ----------
def build_cues(segs, max_chars=42, max_dur=7.0, gap_break=0.8):
    words = all_words(segs)
    if not words:
        return [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segs]
    limit = max_chars * 2
    cues, cur = [], []

    def flush():
        if cur:
            cues.append({"start": cur[0]["start"], "end": cur[-1]["end"],
                         "text": " ".join(x["w"] for x in cur)})
            cur.clear()

    for w in words:
        if cur:
            cand = " ".join(x["w"] for x in cur) + " " + w["w"]
            text_len = len(cand)
            last = cur[-1]
            if (text_len > limit or not fits(cand, max_chars) or w["end"] - cur[0]["start"] > max_dur
                    or w["start"] - last["end"] > gap_break
                    or (last["w"][-1] in ".!?…" and text_len > max_chars * 0.6)):
                flush()
        cur.append(w)
    flush()
    for c in cues:
        c["text"] = wrap2(c["text"], max_chars)
    return cues


def fits(text, max_chars):
    return all(len(line) <= max_chars for line in wrap2(text, max_chars).split("\n"))


def wrap2(text, max_chars):
    if len(text) <= max_chars:
        return text
    mid, best = len(text) / 2, None
    for i, ch in enumerate(text):
        if ch == " ":
            # prefer breaking after punctuation, near the middle
            over = max(i, len(text) - i - 1) > max_chars  # a line would exceed the limit
            score = over * 1000 + abs(i - mid) - (8 if i > 0 and text[i - 1] in ",;:.!?" else 0)
            if best is None or score < best[0]:
                best = (score, i)
    return text if best is None else text[:best[1]] + "\n" + text[best[1] + 1:]


# ---------- paragraphs ----------
def paragraphs(segs, gap=2.0, max_len=900):
    paras, cur = [], []
    for s in segs:
        if cur and (s["start"] - cur[-1]["end"] > gap or sum(len(x["text"]) for x in cur) > max_len):
            paras.append(cur)
            cur = []
        cur.append(s)
    if cur:
        paras.append(cur)
    return [{"start": p[0]["start"], "end": p[-1]["end"], "text": " ".join(x["text"] for x in p)}
            for p in paras]


# ---------- writers ----------
def write_outputs(result, segs, base: Path, modes, a, src: Path):
    off = parse_tc(a.tc_start, a.fps) if a.tc_start else 0.0
    tc = (lambda s: tc_frames(s + off, a.fps)) if a.tc_start else (lambda s: ts(s + off)[:8])
    written = []
    for m in modes:
        if m == "plain":
            p = base.with_suffix(".txt")
            p.write_text("\n\n".join(x["text"] for x in paragraphs(segs)) + "\n", encoding="utf-8")
        elif m == "timed":
            p = base.with_name(base.name + ".timed.txt")
            p.write_text("".join(f"[{tc(s['start'])}] {s['text']}\n" for s in segs), encoding="utf-8")
        elif m == "md":
            p = base.with_suffix(".md")
            dur = segs[-1]["end"] if segs else 0
            head = (f"# {src.name}\n\n"
                    f"- Language: {result.get('language')}\n- Duration: {ts(dur)[:8]}\n"
                    f"- Model: {a.model}\n\n---\n\n")
            body = "".join(f"**[{tc(x['start'])}]** {x['text']}\n\n" for x in paragraphs(segs))
            p.write_text(head + body, encoding="utf-8")
        elif m in ("srt", "vtt"):
            cues = build_cues(segs, a.max_chars)
            if m == "srt":
                p = base.with_suffix(".srt")
                p.write_text("".join(
                    f"{i}\n{ts(c['start'] + off, ',')} --> {ts(c['end'] + off, ',')}\n{c['text']}\n\n"
                    for i, c in enumerate(cues, 1)), encoding="utf-8")
            else:
                p = base.with_suffix(".vtt")
                p.write_text("WEBVTT\n\n" + "".join(
                    f"{ts(c['start'] + off)} --> {ts(c['end'] + off)}\n{c['text']}\n\n" for c in cues),
                    encoding="utf-8")
        elif m == "json":
            p = base.with_suffix(".json")
            p.write_text(json.dumps({
                "file": str(src), "language": result.get("language"), "model": a.model,
                "segments": [{"start": s["start"], "end": s["end"], "text": s["text"],
                              "words": [{"word": w["word"].strip(), "start": w["start"], "end": w["end"]}
                                        for w in s.get("words") or []]} for s in segs],
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(p)
    return written


def collect(paths):
    files = []
    for p in paths:
        p = Path(p).expanduser().resolve()
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in MEDIA_EXT and not f.name.startswith("._"))
        elif p.exists():
            files.append(p)
        else:
            print(f"!! not found: {p}", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description="Local Whisper transcription (Apple Silicon)")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--mode", default="plain", help="plain,timed,md,srt,vtt,json,all (comma list ok)")
    ap.add_argument("--model", default="turbo")
    ap.add_argument("--lang", default=None)
    ap.add_argument("--prompt", default=None, help="names/terms to spell correctly")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tc-start", default=None, help="source timecode of 0s, e.g. 01:00:00:00")
    ap.add_argument("--fps", type=int, default=25)
    ap.add_argument("--max-chars", type=int, default=42, help="subtitle chars per line")
    ap.add_argument("--force", action="store_true", help="redo files that already have output")
    a = ap.parse_args()

    modes = ["plain", "timed", "md", "srt", "vtt", "json"] if a.mode == "all" else a.mode.split(",")
    files = collect(a.paths)
    if not files:
        sys.exit("no media files found")

    import mlx_whisper

    repo = MODELS.get(a.model, a.model)
    for i, src in enumerate(files, 1):
        out_dir = Path(a.out).expanduser() if a.out else src.parent
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if not os.access(out_dir, os.W_OK):
            out_dir = Path.cwd()
        base = out_dir / src.stem
        first = base.with_suffix(".txt") if modes[0] == "plain" else None
        if first and first.exists() and not a.force:
            print(f"-- skip (exists): {first}", file=sys.stderr)
            continue
        print(f">> [{i}/{len(files)}] {src.name}  [{a.model}, lang={a.lang or 'auto'}]", file=sys.stderr)
        result = mlx_whisper.transcribe(
            str(src), path_or_hf_repo=repo, language=a.lang, initial_prompt=a.prompt,
            word_timestamps=True, condition_on_previous_text=False,
            hallucination_silence_threshold=2.0, verbose=False,
        )
        segs = clean_segments(result["segments"])
        for p in write_outputs(result, segs, base, modes, a, src):
            print(f"OK {p}")
        print(f"   language: {result.get('language')}  segments: {len(segs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
