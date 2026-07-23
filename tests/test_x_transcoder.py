import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import x_transcoder as xt


def media_info(**overrides):
    values = {
        "path": Path("downloads/input.mp4"),
        "container": "mov,mp4,m4a,3gp,3g2,mj2",
        "size": 2_000_000,
        "duration": 10.0,
        "video_codec": "h264",
        "video_profile": "High",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "pixel_format": "yuv420p",
        "video_bit_rate": 1_000_000,
        "audio_codec": "aac",
        "audio_bit_rate": 128_000,
    }
    values.update(overrides)
    return xt.MediaInfo(**values)


class XTranscoderTests(unittest.TestCase):
    def test_h264_aac_mp4_is_compatible(self) -> None:
        result = xt.check_with_options(media_info(), xt.default_options())
        self.assertTrue(result.ok, result.reasons)

    def test_hevc_is_not_compatible(self) -> None:
        result = xt.check_with_options(media_info(video_codec="hevc"), xt.default_options())
        self.assertFalse(result.ok)
        self.assertTrue(any("video codec is hevc" in reason for reason in result.reasons))

    def test_target_dimensions_do_not_upscale(self) -> None:
        self.assertEqual(xt.target_dimensions(media_info(width=576, height=1024), (1920, 1080), (1080, 1920)), (576, 1024))

    def test_target_dimensions_scale_large_portrait(self) -> None:
        self.assertEqual(xt.target_dimensions(media_info(width=2160, height=3840), (1920, 1080), (1080, 1920)), (1080, 1920))

    def test_default_output_path_adds_suffix(self) -> None:
        path = xt.output_path_for(Path("downloads/a.mp4"), None, None, "_x")
        self.assertEqual(path, Path("downloads/a_x.mp4"))

    def test_time_named_output_path(self) -> None:
        with mock.patch("x_transcoder.time.strftime", return_value="20260624_153012"):
            path = xt.output_path_for(Path("downloads/a.mp4"), None, None, "_x", use_time_name=True)
        self.assertEqual(path, Path("downloads/20260624_153012_x.mp4"))

    def test_find_videos_recurses_and_excludes_generated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "nested"
            nested.mkdir()
            (root / "a.mp4").write_bytes(b"")
            (nested / "b.mkv").write_bytes(b"")
            (nested / "b_x.mp4").write_bytes(b"")
            (nested / "notes.txt").write_text("not a video", encoding="utf-8")

            self.assertEqual(
                xt.find_videos(root),
                [root / "a.mp4", nested / "b.mkv"],
            )
            self.assertEqual(
                xt.find_videos(root, recursive=False),
                [root / "a.mp4"],
            )

    def test_process_directory_checks_all_and_converts_only_incompatible_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compatible_path = root / "compatible.mp4"
            incompatible_path = root / "incompatible.webm"
            compatible_path.write_bytes(b"compatible")
            incompatible_path.write_bytes(b"incompatible")
            options = xt.default_options(
                check=False,
                # --force is a single-file option; folder mode must still skip
                # compatible originals instead of creating duplicates.
                force=True,
                output=None,
                output_dir=None,
                suffix="_x",
                recursive=True,
            )

            def fake_probe(path: Path):
                if path == incompatible_path:
                    return media_info(path=path, video_codec="vp9", container="webm")
                return media_info(path=path)

            with mock.patch("x_transcoder.probe_media", side_effect=fake_probe), mock.patch(
                "x_transcoder.transcode",
                side_effect=lambda _args, _input, output, _info: output,
            ) as transcode_mock, mock.patch("sys.stdout", new_callable=io.StringIO):
                summary = xt.process_directory(options, root)

            self.assertEqual(summary.total, 2)
            self.assertEqual(summary.compatible, 1)
            self.assertEqual(summary.incompatible, 1)
            self.assertEqual(summary.converted, 1)
            self.assertEqual(summary.failed, 0)
            self.assertEqual(transcode_mock.call_args.args[2], root / "incompatible_x.mp4")


if __name__ == "__main__":
    unittest.main()
