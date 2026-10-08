---
name: transcribe
description: Free, local transcription of audio/video on Apple Silicon (Whisper large-v3-turbo via MLX, the same models MacWhisper uses). Outputs plain text, timecoded text, paper-edit Markdown, broadcast-style SRT/VTT subtitles or word-level JSON. Use when the user says "/transcribe", "transcribe", "transkript et", "deşifre et", "yazıya dök", "altyazı çıkar", "srt", "subtitles", or hands over an audio/video file or folder and wants its content as text.
---

# Transcribe

Local Whisper (mlx-whisper). Internet only for the first model download (~1.6 GB into `~/.cache/huggingface`). No API, no cost.

## Run

```bash
uv run ~/.claude/skills/transcribe/transcribe.py "<FILE_OR_FOLDER>" --mode <MODE> [--lang tr] [--prompt "Names"] [--out DIR]
```

- In Claude Code run it with the sandbox disabled (model download + HF cache). Long files: `timeout: 600000`; very long or whole folders: `run_in_background: true`.
- A folder processes every audio/video file inside it; files that already have output are skipped (`--force` redoes them).

## Pick the mode (don't ask; infer)

| User says | `--mode` | Output |
|---|---|---|
| nothing / "text" / "düz yazı" | `plain` | paragraphed `.txt` |
| "timecodes", "time kodlu" | `timed` | `[00:01:23] line` → `.timed.txt` |
| "paper edit", "for editing", "röportaj deşifresi" | `md` | timecoded paragraphs + header → `.md` |
| "subtitles", "srt", Premiere/Resolve | `srt` | ≤2 lines, ≤42 chars/line, ≤7 s cues |
| web subtitles | `vtt` | same, WebVTT |
| "words", data, further processing | `json` | segments + word timestamps |
| "everything" | `all` | all of the above |

Comma lists work: `--mode md,srt`.

## Options

- `--lang tr` — set it when known; more reliable than auto-detect.
- `--prompt "Name A, Place B"` — fixes spelling of names/terms.
- `--model` — `turbo` (default), `large` (most accurate, slower), `medium`, `small`.
- `--tc-start 01:00:00:00 --fps 25` — camera/source timecode: timestamps become `HH:MM:SS:FF` that match the NLE timeline.
- `--max-chars 37` — tighter subtitle lines (e.g. vertical video).
- `--out DIR` — output folder. Default: next to the source. If the source folder is read-only, always pass a writable `--out`; never write into source media folders the user marked read-only.

## After

Report output paths and show the first lines. If names look wrong, offer a rerun with `--prompt`. Known Whisper hallucinations on silence ("Altyazı M.K.", "Thanks for watching", repeated loops) are filtered automatically.
