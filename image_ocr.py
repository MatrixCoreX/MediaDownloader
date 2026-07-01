#!/usr/bin/env python3
"""
Run OCR on local image files with the Tesseract command-line engine.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DOWNLOAD_DIR = "downloads"
DEFAULT_LANGUAGE = "chi_sim"
DEFAULT_PSM = 6
DEFAULT_PREPROCESS = True
DEFAULT_SUFFIX = "_ocr"
PREPROCESS_SCALE = 2
PREPROCESS_CONTRAST = 2.0
PREPROCESS_THRESHOLD = 180
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
    ".avif",
}


class ImageOcrError(RuntimeError):
    """Raised when image OCR cannot be completed."""


@dataclass(frozen=True)
class OcrResult:
    path: Path
    text: str


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise ImageOcrError(f"{name} is required but was not found in PATH.")
    return binary


def latest_image(directory: Path) -> Path:
    if not directory.exists():
        raise ImageOcrError(f"Directory does not exist: {directory}")
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not candidates:
        raise ImageOcrError(f"No image files found in {directory}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def normalize_ocr_text(text: str) -> str:
    text = text.replace("\f", "")
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def build_tesseract_command(
    tesseract_bin: Path | str,
    image_path: Path,
    *,
    language: str,
    psm: int | None = None,
) -> list[str]:
    command = [str(tesseract_bin), str(image_path), "stdout", "-l", language]
    if psm is not None:
        command.extend(["--psm", str(psm)])
    return command


def _lanczos_resampling(image_module: object) -> object:
    resampling = getattr(image_module, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return getattr(image_module, "LANCZOS")


def preprocess_image_for_ocr(image_path: Path, output_dir: Path, *, verbose: bool = False) -> Path:
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        if verbose:
            print("Pillow is not available; OCR preprocessing skipped.", file=sys.stderr)
        return image_path

    try:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            if width > 0 and height > 0:
                image = image.resize(
                    (width * PREPROCESS_SCALE, height * PREPROCESS_SCALE),
                    _lanczos_resampling(Image),
                )
            grayscale = ImageOps.grayscale(image)
            enhanced = ImageEnhance.Contrast(grayscale).enhance(PREPROCESS_CONTRAST)
            prepared = enhanced.point(
                lambda pixel: 0 if pixel < PREPROCESS_THRESHOLD else 255,
                mode="1",
            )
            output_path = output_dir / f"{image_path.stem}_ocr_preprocessed.png"
            prepared.save(output_path)
            return output_path
    except Exception as exc:
        if verbose:
            print(f"OCR preprocessing skipped for {image_path}: {exc}", file=sys.stderr)
        return image_path


def output_path_for(
    image_paths: list[Path],
    output: str | None,
    output_dir: str | None,
    *,
    output_stem: str | None = None,
    suffix: str = DEFAULT_SUFFIX,
) -> Path:
    if output:
        path = Path(output).expanduser()
        if path.suffix.lower() != ".txt":
            path = path.with_suffix(".txt")
        return path

    if not image_paths:
        raise ImageOcrError("No image files were provided.")
    parent = Path(output_dir).expanduser() if output_dir else image_paths[0].parent
    if output_stem:
        stem = Path(output_stem).stem
    elif len(image_paths) == 1:
        stem = image_paths[0].stem
    else:
        stem = "images"
    return parent / f"{stem}{suffix}.txt"


def tesseract_ocr_image(
    image_path: Path,
    *,
    tesseract_bin: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    psm: int | None = DEFAULT_PSM,
    preprocess: bool = DEFAULT_PREPROCESS,
    verbose: bool = False,
) -> OcrResult:
    if not image_path.exists():
        raise ImageOcrError(f"Input image does not exist: {image_path}")

    executable = Path(tesseract_bin).expanduser() if tesseract_bin else Path(require_binary("tesseract"))
    if tesseract_bin and not executable.exists():
        found = shutil.which(tesseract_bin)
        if not found:
            raise ImageOcrError(f"tesseract binary was not found: {tesseract_bin}")
        executable = Path(found)

    with ExitStack() as stack:
        tesseract_image_path = image_path
        if preprocess:
            temp_dir = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            tesseract_image_path = preprocess_image_for_ocr(image_path, temp_dir, verbose=verbose)

        command = build_tesseract_command(executable, tesseract_image_path, language=language, psm=psm)
        if verbose:
            print(" ".join(command), file=sys.stderr)
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        raise ImageOcrError(
            f"tesseract failed for {image_path} with exit code {completed.returncode}"
            + (f": {detail}" if detail else "")
        )
    return OcrResult(image_path, normalize_ocr_text(completed.stdout))


def render_ocr_results(results: list[OcrResult]) -> str:
    if not results:
        return ""
    if len(results) == 1:
        text = results[0].text.strip()
        return f"{text}\n" if text else ""

    chunks: list[str] = []
    for result in results:
        chunks.append(f"## {result.path}")
        if result.text.strip():
            chunks.append(result.text.strip())
        chunks.append("")
    return "\n".join(chunks).rstrip() + "\n"


def ocr_images(
    image_paths: list[Path],
    *,
    output: str | None = None,
    output_dir: str | None = None,
    output_stem: str | None = None,
    tesseract_bin: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    psm: int | None = DEFAULT_PSM,
    preprocess: bool = DEFAULT_PREPROCESS,
    overwrite: bool = False,
    verbose: bool = False,
) -> Path:
    if not image_paths:
        raise ImageOcrError("No image files were provided.")
    output_path = output_path_for(image_paths, output, output_dir, output_stem=output_stem)
    if output_path.exists() and not overwrite:
        raise ImageOcrError(f"OCR output already exists, pass --overwrite to replace it: {output_path}")

    results = [
        tesseract_ocr_image(
            path,
            tesseract_bin=tesseract_bin,
            language=language,
            psm=psm,
            preprocess=preprocess,
            verbose=verbose,
        )
        for path in image_paths
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_ocr_results(results), encoding="utf-8")
    return output_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OCR on local image files with Tesseract.")
    parser.add_argument("input", nargs="*", help="Input image files. Defaults to latest image in downloads/.")
    parser.add_argument(
        "--downloads-dir",
        default=DEFAULT_DOWNLOAD_DIR,
        help="Directory used when input is omitted. Default: downloads",
    )
    parser.add_argument("-o", "--output", help="Output TXT path. Default: image stem plus _ocr.txt")
    parser.add_argument("--output-dir", help="Directory for default OCR output. Default: input image directory")
    parser.add_argument("--tesseract-bin", help="Path or executable name for tesseract.")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, help=f"Tesseract language list. Default: {DEFAULT_LANGUAGE}")
    parser.add_argument(
        "--psm",
        type=int,
        default=DEFAULT_PSM,
        help=f"Tesseract page segmentation mode. Default: {DEFAULT_PSM}",
    )
    preprocess_group = parser.add_mutually_exclusive_group()
    preprocess_group.add_argument(
        "--preprocess",
        dest="preprocess",
        action="store_true",
        default=DEFAULT_PREPROCESS,
        help="Enhance images before OCR. Default: enabled",
    )
    preprocess_group.add_argument(
        "--no-preprocess",
        dest="preprocess",
        action="store_false",
        help="Disable image enhancement before OCR.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite OCR output if it already exists.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print the tesseract command.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        image_paths = [Path(path).expanduser() for path in args.input]
        if not image_paths:
            image_paths = [latest_image(Path(args.downloads_dir).expanduser())]
        output_path = ocr_images(
            image_paths,
            output=args.output,
            output_dir=args.output_dir,
            tesseract_bin=args.tesseract_bin,
            language=args.language,
            psm=args.psm,
            preprocess=args.preprocess,
            overwrite=args.overwrite,
            verbose=args.verbose,
        )
        print(f"ocr: {output_path}")
        return 0
    except (ImageOcrError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
