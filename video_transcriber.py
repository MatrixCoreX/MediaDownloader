#!/usr/bin/env python3
"""
Extract audio from a local media file and transcribe it with local whisper.cpp.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_DOWNLOAD_DIR = "downloads"
DEFAULT_AUDIO_SUFFIX = "_audio"
DEFAULT_TRANSCRIPT_SUFFIX = "_transcript"
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_LANGUAGE = "auto"
DEFAULT_MAX_THREADS = 8
MEDIA_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".mkv",
    ".webm",
    ".avi",
    ".flv",
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".flac",
    ".ogg",
}
WHISPER_BIN_ENV = ("WHISPER_BIN", "WHISPER_CPP_BIN", "WHISPER_CLI")
WHISPER_MODEL_ENV = ("WHISPER_MODEL", "WHISPER_MODEL_PATH", "WHISPER_CPP_MODEL")
RUSTCLAW_ENV = ("RUSTCLAW_HOME", "RUSTCLAW_ROOT")
WHISPER_PROGRESS_RE = re.compile(r"progress\s*=\s*(-?\d+)%")


class VideoTranscribeError(RuntimeError):
    """Raised when audio extraction or transcription cannot be completed."""


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise VideoTranscribeError(f"{name} is required but was not found in PATH.")
    return binary


def default_whisper_threads() -> int:
    cpu_count = os.cpu_count() or 4
    return max(1, min(cpu_count, DEFAULT_MAX_THREADS))


def latest_media(directory: Path) -> Path:
    if not directory.exists():
        raise VideoTranscribeError(f"Directory does not exist: {directory}")
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    ]
    preferred_candidates = [path for path in candidates if not is_generated_audio_output(path)]
    if preferred_candidates:
        candidates = preferred_candidates
    if not candidates:
        raise VideoTranscribeError(f"No media files found in {directory}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def path_from_env(names: Iterable[str]) -> Path | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return None


def rustclaw_roots() -> list[Path]:
    roots: list[Path] = []
    for name in RUSTCLAW_ENV:
        value = os.environ.get(name)
        if value:
            roots.append(Path(value).expanduser())
    roots.extend(
        [
            Path.home() / "rustclaw",
            Path("/home/guagua/rustclaw"),
        ]
    )
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        normalized = root.resolve() if root.exists() else root
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(root)
    return unique


def first_existing(paths: Iterable[Path]) -> Path | None:
    for path in paths:
        expanded = path.expanduser()
        if expanded.exists():
            return expanded
    return None


def find_whisper_binary(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path
        found = shutil.which(explicit)
        if found:
            return Path(found)
        raise VideoTranscribeError(f"whisper.cpp binary was not found: {explicit}")

    env_path = path_from_env(WHISPER_BIN_ENV)
    if env_path:
        if env_path.exists():
            return env_path
        found = shutil.which(str(env_path))
        if found:
            return Path(found)
        raise VideoTranscribeError(f"whisper.cpp binary from environment was not found: {env_path}")

    for executable in ("whisper-cli", "whisper.cpp"):
        found = shutil.which(executable)
        if found:
            return Path(found)

    known_paths: list[Path] = []
    for root in rustclaw_roots():
        bin_dir = root / "data" / "vendor" / "whisper.cpp" / "build" / "bin"
        known_paths.extend([bin_dir / "whisper-cli", bin_dir / "main"])
    found_path = first_existing(known_paths)
    if found_path:
        return found_path

    raise VideoTranscribeError(
        "whisper.cpp binary was not found. Pass --whisper-bin or set WHISPER_BIN."
    )


def whisper_model_candidates(root: Path) -> list[Path]:
    model_dir = root / "data" / "models" / "whisper.cpp"
    preferred = [
        "ggml-small.bin",
        "ggml-base.bin",
        "ggml-medium.bin",
        "ggml-tiny.bin",
        "ggml-large-v3.bin",
    ]
    candidates = [model_dir / name for name in preferred]
    if model_dir.exists():
        candidates.extend(sorted(model_dir.glob("ggml-*.bin")))
    return candidates


def find_whisper_model(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return path
        raise VideoTranscribeError(f"whisper.cpp model was not found: {explicit}")

    env_path = path_from_env(WHISPER_MODEL_ENV)
    if env_path:
        if env_path.exists():
            return env_path
        raise VideoTranscribeError(f"whisper.cpp model from environment was not found: {env_path}")

    known_paths: list[Path] = []
    for root in rustclaw_roots():
        known_paths.extend(whisper_model_candidates(root))
    found_path = first_existing(known_paths)
    if found_path:
        return found_path

    raise VideoTranscribeError(
        "whisper.cpp model was not found. Pass --model or set WHISPER_MODEL."
    )


def output_path_for(
    input_path: Path,
    output: str | None,
    output_dir: str | None,
    suffix: str,
    extension: str,
) -> Path:
    if output:
        path = Path(output).expanduser()
        if path.suffix.lower() != extension:
            path = path.with_suffix(extension)
        return path

    parent = Path(output_dir).expanduser() if output_dir else input_path.parent
    return parent / f"{input_path.stem}{suffix}{extension}"


def is_generated_audio_output(path: Path) -> bool:
    if path.suffix.lower() != ".wav" or not path.stem.endswith(DEFAULT_AUDIO_SUFFIX):
        return False
    source_stem = path.stem[: -len(DEFAULT_AUDIO_SUFFIX)]
    if not source_stem:
        return False
    return any((path.parent / f"{source_stem}{extension}").exists() for extension in MEDIA_EXTENSIONS)


def transcript_stem_for(input_path: Path) -> str:
    stem = input_path.stem
    if input_path.suffix.lower() == ".wav" and stem.endswith(DEFAULT_AUDIO_SUFFIX):
        stripped = stem[: -len(DEFAULT_AUDIO_SUFFIX)]
        if stripped:
            return stripped
    return stem


def transcript_output_path_for(input_path: Path, output: str | None, output_dir: str | None) -> Path:
    if output:
        return output_path_for(input_path, output, output_dir, DEFAULT_TRANSCRIPT_SUFFIX, ".txt")
    parent = Path(output_dir).expanduser() if output_dir else input_path.parent
    return parent / f"{transcript_stem_for(input_path)}{DEFAULT_TRANSCRIPT_SUFFIX}.txt"


def transcript_prefix_for(transcript_path: Path) -> Path:
    if transcript_path.suffix.lower() == ".txt":
        return transcript_path.with_suffix("")
    return transcript_path


def build_extract_audio_command(
    ffmpeg: str,
    input_path: Path,
    audio_path: Path,
    *,
    overwrite: bool,
    sample_rate: int,
    channels: int,
) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-y" if overwrite else "-n",
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]


def render_progress_bar(percent: int, *, width: int = 30) -> str:
    clamped = max(0, min(percent, 100))
    filled = round(width * clamped / 100)
    return f"transcribe_progress: [{'#' * filled}{'.' * (width - filled)}] {clamped:3d}%"


def print_progress_bar(percent: int, *, interactive: bool) -> None:
    line = render_progress_bar(percent)
    if interactive:
        print(f"\r{line}", end="", file=sys.stderr, flush=True)
        return
    print(line, file=sys.stderr, flush=True)


def finish_progress_bar(*, interactive: bool) -> None:
    if interactive:
        print(file=sys.stderr, flush=True)


def run_streaming_command(command: list[str], *, verbose: bool) -> subprocess.CompletedProcess[str]:
    output_parts: list[str] = []
    last_progress = 0
    interactive_progress = sys.stderr.isatty()
    print_progress_bar(0, interactive=interactive_progress)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        output_parts.append(line)
        match = WHISPER_PROGRESS_RE.search(line)
        if match:
            progress = max(0, min(int(match.group(1)), 100))
            if progress != last_progress:
                print_progress_bar(progress, interactive=interactive_progress)
                last_progress = progress
            continue
        if verbose:
            print(line, end="", file=sys.stderr, flush=True)

    returncode = process.wait()
    if returncode == 0 and last_progress < 100:
        print_progress_bar(100, interactive=interactive_progress)
    finish_progress_bar(interactive=interactive_progress)
    return subprocess.CompletedProcess(command, returncode, "", "".join(output_parts))


def run_command(command: list[str], *, verbose: bool, stream_output: bool = False) -> subprocess.CompletedProcess[str]:
    if verbose:
        print(" ".join(command), file=sys.stderr)
    if stream_output:
        return run_streaming_command(command, verbose=verbose)
    if verbose:
        return subprocess.run(command, check=False, text=True)
    return subprocess.run(command, check=False, capture_output=True, text=True)


def command_error(command_name: str, completed: subprocess.CompletedProcess[str]) -> VideoTranscribeError:
    stderr = (completed.stderr or "").strip()
    detail = f": {stderr}" if stderr else ""
    return VideoTranscribeError(f"{command_name} failed with exit code {completed.returncode}{detail}")


def extract_audio(
    input_path: Path,
    audio_path: Path,
    *,
    overwrite: bool = False,
    reuse_audio: bool = False,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
    verbose: bool = False,
) -> Path:
    if not input_path.exists():
        raise VideoTranscribeError(f"Input file does not exist: {input_path}")
    if audio_path.exists():
        if reuse_audio:
            return audio_path
        if not overwrite:
            raise VideoTranscribeError(f"Audio output already exists, pass --overwrite to replace it: {audio_path}")

    audio_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_extract_audio_command(
        require_binary("ffmpeg"),
        input_path,
        audio_path,
        overwrite=overwrite,
        sample_rate=sample_rate,
        channels=channels,
    )
    completed = run_command(command, verbose=verbose)
    if completed.returncode != 0:
        raise command_error("ffmpeg", completed)
    if not audio_path.exists():
        raise VideoTranscribeError(f"ffmpeg completed but did not create audio output: {audio_path}")
    return audio_path


def build_whisper_command(
    whisper_bin: Path,
    model_path: Path,
    audio_path: Path,
    transcript_prefix: Path,
    *,
    language: str,
    threads: int | None,
    translate: bool,
    no_gpu: bool,
    no_timestamps: bool,
    print_progress: bool = True,
    fast: bool = False,
) -> list[str]:
    command = [
        str(whisper_bin),
        "-m",
        str(model_path),
        "-f",
        str(audio_path),
        "-l",
        language,
        "-otxt",
        "-of",
        str(transcript_prefix),
    ]
    if threads:
        command.extend(["-t", str(threads)])
    if translate:
        command.append("--translate")
    if no_gpu:
        command.append("--no-gpu")
    if no_timestamps:
        command.append("--no-timestamps")
    if print_progress:
        command.append("--print-progress")
    if fast:
        command.extend(["--best-of", "1", "--beam-size", "1", "--no-fallback"])
    return command


def transcribe_audio(
    audio_path: Path,
    transcript_path: Path,
    *,
    whisper_bin: Path,
    model_path: Path,
    language: str = DEFAULT_LANGUAGE,
    threads: int | None = None,
    translate: bool = False,
    no_gpu: bool = False,
    no_timestamps: bool = False,
    print_progress: bool = True,
    fast: bool = False,
    overwrite: bool = False,
    verbose: bool = False,
) -> Path:
    if not audio_path.exists():
        raise VideoTranscribeError(f"Audio file does not exist: {audio_path}")
    if transcript_path.exists():
        if not overwrite:
            raise VideoTranscribeError(
                f"Transcript output already exists, pass --overwrite to replace it: {transcript_path}"
            )
        transcript_path.unlink()

    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_prefix = transcript_prefix_for(transcript_path)
    command = build_whisper_command(
        whisper_bin,
        model_path,
        audio_path,
        transcript_prefix,
        language=language,
        threads=threads,
        translate=translate,
        no_gpu=no_gpu,
        no_timestamps=no_timestamps,
        print_progress=print_progress,
        fast=fast,
    )
    completed = run_command(command, verbose=verbose, stream_output=print_progress)
    if completed.returncode != 0:
        raise command_error("whisper.cpp", completed)
    if not transcript_path.exists():
        raise VideoTranscribeError(f"whisper.cpp completed but did not create transcript: {transcript_path}")
    return transcript_path


def should_transcribe_input_directly(input_path: Path, audio_output: str | None) -> bool:
    return input_path.suffix.lower() == ".wav" and audio_output is None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract audio from a media file and transcribe it with local whisper.cpp.",
    )
    parser.add_argument("input", nargs="?", help="Input video/audio file. Defaults to latest media in downloads/.")
    parser.add_argument("--downloads-dir", default=DEFAULT_DOWNLOAD_DIR, help="Directory used when input is omitted. Default: downloads")
    parser.add_argument("--audio-output", help="Output WAV path. Default: input stem plus _audio.wav")
    parser.add_argument("--text-output", help="Output transcript TXT path. Default: input stem plus _transcript.txt")
    parser.add_argument("--output-dir", help="Directory for default audio/transcript outputs. Default: input file directory")
    parser.add_argument("--whisper-bin", help="Path or executable name for whisper.cpp whisper-cli.")
    parser.add_argument("--model", help="Path to a whisper.cpp ggml model.")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, help="Spoken language, or auto. Default: auto")
    parser.add_argument("--threads", type=int, default=default_whisper_threads(), help=f"Thread count passed to whisper.cpp. Default: auto, capped at {DEFAULT_MAX_THREADS}")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE, help="Audio sample rate for extracted WAV. Default: 16000")
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS, help="Audio channel count for extracted WAV. Default: 1")
    parser.add_argument("--translate", action="store_true", help="Ask whisper.cpp to translate speech to English.")
    parser.add_argument("--fast", action="store_true", help="Use faster greedy whisper.cpp decoding. May reduce transcription quality.")
    parser.add_argument("--no-gpu", action="store_true", help="Pass --no-gpu to whisper.cpp.")
    parser.add_argument("--timestamps", action="store_true", help="Keep timestamps in whisper.cpp text output.")
    parser.add_argument("--no-progress", dest="progress", action="store_false", default=True, help="Disable whisper.cpp progress output.")
    parser.add_argument("--extract-only", action="store_true", help="Only extract audio; do not run STT.")
    parser.add_argument("--reuse-audio", action="store_true", help="Reuse existing audio output instead of extracting again.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing audio/transcript outputs.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print ffmpeg and whisper.cpp commands.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        input_path = Path(args.input).expanduser() if args.input else latest_media(Path(args.downloads_dir).expanduser())
        audio_path = output_path_for(input_path, args.audio_output, args.output_dir, DEFAULT_AUDIO_SUFFIX, ".wav")
        transcript_path = transcript_output_path_for(
            input_path,
            args.text_output,
            args.output_dir,
        )
        if should_transcribe_input_directly(input_path, args.audio_output):
            if not input_path.exists():
                raise VideoTranscribeError(f"Input file does not exist: {input_path}")
            saved_audio = input_path
        else:
            auto_reuse_audio = not args.extract_only and args.audio_output is None and audio_path.exists()
            saved_audio = extract_audio(
                input_path,
                audio_path,
                overwrite=args.overwrite,
                reuse_audio=args.reuse_audio or auto_reuse_audio,
                sample_rate=args.sample_rate,
                channels=args.channels,
                verbose=args.verbose,
            )
        print(f"audio: {saved_audio}")
        if args.extract_only:
            return 0

        whisper_bin = find_whisper_binary(args.whisper_bin)
        model_path = find_whisper_model(args.model)
        transcript = transcribe_audio(
            saved_audio,
            transcript_path,
            whisper_bin=whisper_bin,
            model_path=model_path,
            language=args.language,
            threads=args.threads,
            translate=args.translate,
            no_gpu=args.no_gpu,
            no_timestamps=not args.timestamps,
            print_progress=args.progress,
            fast=args.fast,
            overwrite=args.overwrite,
            verbose=args.verbose,
        )
        print(f"transcript: {transcript}")
        return 0
    except (VideoTranscribeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
