import io
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
        self.assertEqual(args.min_line_confidence, image_ocr.DEFAULT_MIN_LINE_CONFIDENCE)
        self.assertTrue(args.preprocess)
        self.assertFalse(image_ocr.parse_args(["--no-preprocess"]).preprocess)

    def test_normalize_ocr_text_strips_form_feed_and_outer_blank_lines(self) -> None:
        self.assertEqual(image_ocr.normalize_ocr_text("\n  hello  \nworld\f\n\n"), "  hello\nworld")

    def test_render_ocr_progress_bar_includes_percent_count_and_current_file(self) -> None:
        rendered = image_ocr.render_ocr_progress_bar(
            1,
            4,
            current=Path("downloads/two.jpg"),
        )
        self.assertIn(" 25%", rendered)
        self.assertIn("(1/4)", rendered)
        self.assertIn("processing=two.jpg", rendered)

    def test_ocr_progress_uses_interactive_prompt_stream(self) -> None:
        class ProgressStream(io.StringIO):
            def __init__(self) -> None:
                super().__init__()
                self.progress: list[str] = []
                self.finished = False

            def write_progress(self, line: str) -> None:
                self.progress.append(line)

            def finish_progress(self) -> None:
                self.finished = True

        stderr = ProgressStream()
        with mock.patch("image_ocr.sys.stderr", stderr):
            image_ocr.print_ocr_progress_bar(
                2,
                5,
                current=Path("three.jpg"),
                interactive=True,
            )
            image_ocr.finish_ocr_progress_bar(interactive=True)

        self.assertEqual(len(stderr.progress), 1)
        self.assertIn(" 40% (2/5) processing=three.jpg", stderr.progress[0])
        self.assertTrue(stderr.finished)
        self.assertEqual(stderr.getvalue(), "")

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

    def test_build_tesseract_command_with_accuracy_options(self) -> None:
        command = image_ocr.build_tesseract_command(
            "/usr/bin/tesseract",
            Path("input.jpg"),
            language="chi_sim",
            psm=6,
            oem=1,
            configs={"preserve_interword_spaces": "1"},
            output_format="tsv",
        )
        self.assertEqual(
            command,
            [
                "/usr/bin/tesseract",
                "input.jpg",
                "stdout",
                "-l",
                "chi_sim",
                "--oem",
                "1",
                "--psm",
                "6",
                "-c",
                "preserve_interword_spaces=1",
                "tsv",
            ],
        )

    def test_parse_tesseract_tsv_filters_low_confidence_noise_lines(self) -> None:
        tsv = "\n".join(
            [
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                "5\t1\t1\t1\t1\t1\t10\t10\t40\t40\t90\t有",
                "5\t1\t1\t1\t1\t2\t70\t10\t40\t40\t88\t钱",
                "5\t1\t1\t1\t2\t1\t30\t90\t20\t30\t6\t全",
                "5\t1\t1\t1\t2\t2\t70\t90\t20\t30\t0\t昌",
                "5\t1\t1\t1\t3\t1\t10\t150\t30\t40\t92\t1.",
                "5\t1\t1\t1\t3\t2\t70\t150\t30\t40\t85\t不",
                "5\t1\t1\t1\t3\t3\t110\t150\t60\t40\t33\t回应",
            ]
        )
        self.assertEqual(image_ocr.parse_tesseract_tsv(tsv), "有钱\n1. 不回应")

    def test_parse_tesseract_tsv_treats_quotes_as_plain_text(self) -> None:
        tsv = "\n".join(
            [
                "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                "5\t1\t1\t1\t1\t1\t10\t10\t40\t40\t90\t不止\"一",
                "5\t1\t1\t1\t1\t2\t60\t10\t40\t40\t91\t手",
                "5\t1\t1\t1\t2\t1\t10\t70\t40\t40\t92\t而是",
            ]
        )
        self.assertEqual(image_ocr.parse_tesseract_tsv(tsv), '不止"一手\n而是')

    def test_tesseract_ocr_image_returns_normalized_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.jpg"
            image_path.write_bytes(b"image")
            tsv = "\n".join(
                [
                    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
                    "5\t1\t1\t1\t1\t1\t10\t10\t40\t40\t90\thello",
                ]
            )
            completed = subprocess.CompletedProcess(
                ["/usr/bin/tesseract"],
                0,
                tsv,
                "",
            )
            with mock.patch("image_ocr.shutil.which", return_value="/usr/bin/tesseract"), mock.patch(
                "image_ocr.subprocess.run",
                return_value=completed,
            ) as run:
                result = image_ocr.tesseract_ocr_image(image_path, language="eng", psm=6)

        self.assertEqual(result.text, "hello")
        self.assertIn("--psm", run.call_args.args[0])
        self.assertIn("tsv", run.call_args.args[0])

    def test_tesseract_ocr_image_chooses_higher_confidence_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "input.jpg"
            prepared_path = Path(tmpdir) / "prepared.png"
            image_path.write_bytes(b"image")
            prepared_path.write_bytes(b"prepared")

            with mock.patch("image_ocr.shutil.which", return_value="/usr/bin/tesseract"), mock.patch(
                "image_ocr.preprocess_image_for_ocr",
                return_value=prepared_path,
            ), mock.patch(
                "image_ocr._run_tesseract_tsv",
                side_effect=[
                    image_ocr.ParsedOcrText("原图更准", 91),
                    image_ocr.ParsedOcrText("预处理较差", 52),
                ],
            ):
                result = image_ocr.tesseract_ocr_image(image_path)

        self.assertEqual(result.text, "原图更准")

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

    def test_ocr_images_prints_progress_from_zero_through_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first.jpg"
            second = Path(tmpdir) / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            output_path = Path(tmpdir) / "combined.txt"

            def fake_ocr(path: Path, **_kwargs: object) -> image_ocr.OcrResult:
                return image_ocr.OcrResult(path, path.stem)

            with mock.patch("image_ocr.tesseract_ocr_image", side_effect=fake_ocr), mock.patch(
                "image_ocr.sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                image_ocr.ocr_images(
                    [first, second],
                    output=str(output_path),
                    print_progress=True,
                )

            progress_lines = stderr.getvalue().splitlines()
            self.assertEqual(len(progress_lines), 3)
            self.assertIn("  0% (0/2) processing=first.jpg", progress_lines[0])
            self.assertIn(" 50% (1/2) processing=second.jpg", progress_lines[1])
            self.assertIn("100% (2/2)", progress_lines[2])

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
            self.assertEqual(
                ocr_image.call_args.kwargs["min_line_confidence"],
                image_ocr.DEFAULT_MIN_LINE_CONFIDENCE,
            )


if __name__ == "__main__":
    unittest.main()
