# transcribe — free local transcription skill for Claude Code

A [Claude Code](https://claude.com/claude-code) skill that transcribes audio and video **on your Mac, for free**. It uses Whisper large-v3-turbo running on Apple Silicon through [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper), the same family of models behind apps like MacWhisper.

Hand Claude a file or a folder and say "transcribe this", "give me subtitles" or "transkript et". It picks the output format, runs the model locally and writes the results next to your media.

## What it does

| Mode | Output | For |
|---|---|---|
| `plain` | paragraphed `.txt` | reading, notes |
| `timed` | `[00:01:23] line` `.timed.txt` | quick lookup |
| `md` | timecoded paragraphs `.md` | interview logs, paper edits |
| `srt` / `vtt` | subtitles | Premiere, Resolve, YouTube, web |
| `json` | segments + word timestamps | your own tooling |
| `all` | everything | |

Features beyond a basic Whisper call:

- **Subtitles shaped like broadcast subtitles.** Cues are rebuilt from word timestamps: at most 2 lines, 42 characters per line (`--max-chars`), 7 seconds per cue, and a new cue at sentence ends and pauses. Raw Whisper segments often run long and break mid-phrase.
- **Source timecode.** `--tc-start 01:00:00:00 --fps 25` offsets every timestamp to match camera or timeline timecode and writes `HH:MM:SS:FF`. Logs then line up with the edit.
- **Hallucination filter.** Whisper sometimes makes up lines over silence or music, such as "Altyazı M.K.", "Thanks for watching" or the same line repeated. These are removed by phrase matching, the low-confidence/high-compression check and silence-aware decoding.
- **Batch folders.** Point it at a folder and it handles every audio and video file inside. Files that already have output are skipped, so you can rerun after an interruption.
- **Vocabulary prompt.** `--prompt "Names, Places"` gets proper nouns spelled right.
- **Read-only source safe.** If the source folder isn't writable, output goes elsewhere (`--out`). The script never touches your media.

## Requirements

- Apple Silicon Mac (M1 or later)
- [uv](https://docs.astral.sh/uv/) (`brew install uv`). It installs the Python dependencies on first run.
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)
- About 1.6 GB of disk for the turbo model, downloaded once to `~/.cache/huggingface`

## Install

```bash
git clone https://github.com/junglebased/transcribe-skill ~/.claude/skills/transcribe
```

Restart Claude Code. The skill shows up as `/transcribe` and also triggers on natural requests.

## Use without Claude

```bash
uv run transcribe.py interview.mp4 --mode md,srt --lang tr
uv run transcribe.py ./footage --mode srt --tc-start 01:00:00:00 --fps 25 --out ./subs
uv run transcribe.py talk.m4a --model large --prompt "Ada Lovelace, Kadıköy"
```

| Flag | Default | |
|---|---|---|
| `--mode` | `plain` | `plain,timed,md,srt,vtt,json,all`; comma lists work |
| `--model` | `turbo` | `turbo`, `large`, `medium`, `small` or any mlx-community Hugging Face repo |
| `--lang` | auto | e.g. `tr`, `en`. Setting it is more reliable than auto-detect |
| `--prompt` | — | names or terms to spell correctly |
| `--out` | next to source | output folder |
| `--tc-start` / `--fps` | — / 25 | source timecode offset |
| `--max-chars` | 42 | subtitle characters per line |
| `--force` | off | redo files that already have output |

## Roadmap

- Speaker labels (diarization) without a gated model token
- Optional DOCX export

## License

MIT
