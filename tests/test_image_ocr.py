import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import image_ocr


class ImageOcrTests(unittest.TestCase):
    def test_parse_args_uses_chinese_preprocessed_defaults(self) -> None:
        args = image_ocr.parse_args([])
        self.assertEqual(args.language, "chi_sim")
        self.assertEqual(args.psm, image_ocr.DEFAULT_PSM)
        self.assertTrue(args.preprocess)
        self.assertFalse(image_ocr.parse_args(["--no-preprocess"]).preprocess)

    def test_normalize_ocr_text_strips_form_feed_and_outer_blank_lines(self) -> None:
        self.assertEqual(image_ocr.normalize_ocr_text("\n  hello  \nworld\f\n\n"), "  hello\nworld")

    def test_output_path_for_single_image(self) -> None:
        self.assertEqual(
            image_ocr.output_path_for([Path("downloads/post.jpg")], None, None),
            Path("downloads/post_ocr.txt"),
        )
        self.assertEqual(
            image_ocr.output_path_for([Path("downloads/post.jpg")], "custom", None),
            Path("custom.txt"),
        )
        self.assertEqual(
            image_ocr.output_path_for([Path("downloads/post_01.jpg")], None, "out", output_stem="post"),
            Path("out/post_ocr.txt"),
        )

    def test_build_tesseract_command(self) -> None:
        command = image_ocr.build_tesseract_command(
            "/usr/bin/tesseract",
            Path("input.jpg"),
            language="chi_sim+eng",
            psm=6,
        )
        self.assertEqual(
            command,
            ["/usr/bin/tesseract", "input.jpg", "stdout", "-l", "chi_sim+eng", "--psm", "6"],
        )

    def test_tesseract_ocr_image_returns_normalized_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.jpg"
            image_path.write_bytes(b"image")
            completed = subprocess.CompletedProcess(
                ["/usr/bin/tesseract"],
                0,
                "hello\f\n",
                "",
            )
            with mock.patch("image_ocr.shutil.which", return_value="/usr/bin/tesseract"), mock.patch(
                "image_ocr.subprocess.run",
                return_value=completed,
            ) as run:
                result = image_ocr.tesseract_ocr_image(image_path, language="eng", psm=6)

        self.assertEqual(result.text, "hello")
        self.assertIn("--psm", run.call_args.args[0])

    def test_preprocess_image_for_ocr_writes_temporary_png(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.jpg"
            output_dir = Path(tmpdir) / "prepared"
            output_dir.mkdir()
            Image.new("RGB", (20, 20), "white").save(image_path)

            prepared = image_ocr.preprocess_image_for_ocr(image_path, output_dir)

            self.assertNotEqual(prepared, image_path)
            self.assertEqual(prepared.suffix, ".png")
            self.assertTrue(prepared.exists())

    def test_render_ocr_results_combines_multiple_images(self) -> None:
        rendered = image_ocr.render_ocr_results(
            [
                image_ocr.OcrResult(Path("one.jpg"), "hello"),
                image_ocr.OcrResult(Path("two.jpg"), "world"),
            ]
        )
        self.assertIn("## one.jpg\nhello", rendered)
        self.assertIn("## two.jpg\nworld", rendered)

    def test_ocr_images_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.jpg"
            image_path.write_bytes(b"image")
            output_path = Path(tmpdir) / "out.txt"
            with mock.patch(
                "image_ocr.tesseract_ocr_image",
                return_value=image_ocr.OcrResult(image_path, "hello"),
            ):
                self.assertEqual(image_ocr.ocr_images([image_path], output=str(output_path)), output_path)

            self.assertEqual(output_path.read_text(encoding="utf-8"), "hello\n")

    def test_ocr_images_writes_multiple_images_to_one_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.jpg"
            second = Path(tmpdir) / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            output_path = Path(tmpdir) / "combined.txt"

            def fake_ocr(path: Path, **_kwargs: object) -> image_ocr.OcrResult:
                return image_ocr.OcrResult(path, path.stem)

            with mock.patch("image_ocr.tesseract_ocr_image", side_effect=fake_ocr):
                self.assertEqual(image_ocr.ocr_images([first, second], output=str(output_path)), output_path)

            text = output_path.read_text(encoding="utf-8")
            self.assertIn(f"## {first}\nfirst", text)
            self.assertIn(f"## {second}\nsecond", text)

    def test_ocr_images_passes_preprocess_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.jpg"
            image_path.write_bytes(b"image")
            output_path = Path(tmpdir) / "out.txt"
            with mock.patch(
                "image_ocr.tesseract_ocr_image",
                return_value=image_ocr.OcrResult(image_path, "hello"),
            ) as ocr_image:
                image_ocr.ocr_images([image_path], output=str(output_path), preprocess=False)

            self.assertFalse(ocr_image.call_args.kwargs["preprocess"])


if __name__ == "__main__":
    unittest.main()
