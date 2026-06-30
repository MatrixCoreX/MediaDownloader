import io
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import video_transcriber as vt


class VideoTranscriberTests(unittest.TestCase):
    def test_latest_media_picks_newest_supported_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            older = directory / "older.mp4"
            newer = directory / "newer.mkv"
            ignored = directory / "note.txt"
            older.write_text("old", encoding="utf-8")
            newer.write_text("new", encoding="utf-8")
            ignored.write_text("ignored", encoding="utf-8")
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))
            os.utime(ignored, (300, 300))

            self.assertEqual(vt.latest_media(directory), newer)

    def test_latest_media_prefers_source_video_over_generated_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            video = directory / "clip.mp4"
            generated_audio = directory / "clip_audio.wav"
            video.write_text("video", encoding="utf-8")
            generated_audio.write_text("audio", encoding="utf-8")
            os.utime(video, (100, 100))
            os.utime(generated_audio, (200, 200))

            self.assertEqual(vt.latest_media(directory), video)

    def test_output_paths_add_expected_suffixes(self) -> None:
        input_path = Path("downloads/video.mp4")

        self.assertEqual(
            vt.output_path_for(input_path, None, None, vt.DEFAULT_AUDIO_SUFFIX, ".wav"),
            Path("downloads/video_audio.wav"),
        )
        self.assertEqual(
            vt.output_path_for(input_path, None, "out", vt.DEFAULT_TRANSCRIPT_SUFFIX, ".txt"),
            Path("out/video_transcript.txt"),
        )
        self.assertEqual(
            vt.output_path_for(input_path, "custom", None, vt.DEFAULT_AUDIO_SUFFIX, ".wav"),
            Path("custom.wav"),
        )
        self.assertEqual(
            vt.transcript_output_path_for(Path("downloads/video_audio.wav"), None, None),
            Path("downloads/video_transcript.txt"),
        )

    def test_default_whisper_threads_uses_cpu_count_with_cap(self) -> None:
        with mock.patch("video_transcriber.os.cpu_count", return_value=32):
            self.assertEqual(vt.default_whisper_threads(), vt.DEFAULT_MAX_THREADS)
        with mock.patch("video_transcriber.os.cpu_count", return_value=2):
            self.assertEqual(vt.default_whisper_threads(), 2)
        with mock.patch("video_transcriber.os.cpu_count", return_value=None):
            self.assertEqual(vt.default_whisper_threads(), 4)

    def test_render_progress_bar_clamps_percent(self) -> None:
        self.assertIn("  0%", vt.render_progress_bar(-10))
        self.assertIn("100%", vt.render_progress_bar(3030))
        self.assertIn("[###############...............]", vt.render_progress_bar(50))

    def test_print_progress_bar_overwrites_line_for_tty(self) -> None:
        stderr = io.StringIO()
        with mock.patch("video_transcriber.sys.stderr", stderr):
            vt.print_progress_bar(25, interactive=True)
            vt.finish_progress_bar(interactive=True)

        self.assertTrue(stderr.getvalue().startswith("\rtranscribe_progress:"))
        self.assertTrue(stderr.getvalue().endswith("\n"))

    def test_print_progress_bar_uses_newlines_for_non_tty(self) -> None:
        stderr = io.StringIO()
        with mock.patch("video_transcriber.sys.stderr", stderr):
            vt.print_progress_bar(25, interactive=False)
            vt.print_progress_bar(50, interactive=False)

        self.assertNotIn("\r", stderr.getvalue())
        self.assertEqual(len(stderr.getvalue().splitlines()), 2)

    def test_build_extract_audio_command_uses_whisper_friendly_wav(self) -> None:
        command = vt.build_extract_audio_command(
            "ffmpeg",
            Path("input.mp4"),
            Path("input_audio.wav"),
            overwrite=False,
            sample_rate=16000,
            channels=1,
        )

        self.assertEqual(command[:6], ["ffmpeg", "-hide_banner", "-n", "-i", "input.mp4", "-map"])
        self.assertIn("0:a:0", command)
        self.assertIn("pcm_s16le", command)
        self.assertIn("16000", command)
        self.assertEqual(command[-1], "input_audio.wav")

    def test_build_whisper_command_writes_txt_output(self) -> None:
        command = vt.build_whisper_command(
            Path("/bin/whisper-cli"),
            Path("models/ggml-small.bin"),
            Path("input_audio.wav"),
            Path("input_transcript"),
            language="auto",
            threads=4,
            translate=False,
            no_gpu=True,
            no_timestamps=True,
        )

        self.assertEqual(command[0], "/bin/whisper-cli")
        self.assertIn("-otxt", command)
        self.assertIn("-of", command)
        self.assertIn("input_transcript", command)
        self.assertIn("--no-gpu", command)
        self.assertIn("--no-timestamps", command)
        self.assertIn("--print-progress", command)
        self.assertIn("4", command)

    def test_build_whisper_command_can_disable_progress(self) -> None:
        command = vt.build_whisper_command(
            Path("/bin/whisper-cli"),
            Path("models/ggml-small.bin"),
            Path("input_audio.wav"),
            Path("input_transcript"),
            language="auto",
            threads=4,
            translate=False,
            no_gpu=False,
            no_timestamps=True,
            print_progress=False,
        )

        self.assertNotIn("--print-progress", command)

    def test_build_whisper_command_fast_mode_uses_greedy_decoding(self) -> None:
        command = vt.build_whisper_command(
            Path("/bin/whisper-cli"),
            Path("models/ggml-small.bin"),
            Path("input_audio.wav"),
            Path("input_transcript"),
            language="auto",
            threads=4,
            translate=False,
            no_gpu=False,
            no_timestamps=True,
            fast=True,
        )

        self.assertIn("--best-of", command)
        self.assertIn("--beam-size", command)
        self.assertIn("--no-fallback", command)

    def test_find_whisper_binary_uses_rustclaw_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            binary = root / "data/vendor/whisper.cpp/build/bin/whisper-cli"
            binary.parent.mkdir(parents=True)
            binary.write_text("", encoding="utf-8")
            env = {
                "RUSTCLAW_HOME": str(root),
                "WHISPER_BIN": "",
                "WHISPER_CPP_BIN": "",
                "WHISPER_CLI": "",
            }
            with mock.patch.dict(os.environ, env, clear=False), mock.patch("video_transcriber.shutil.which", return_value=None):
                self.assertEqual(vt.find_whisper_binary(), binary)

    def test_find_whisper_model_uses_rustclaw_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            model = root / "data/models/whisper.cpp/ggml-small.bin"
            model.parent.mkdir(parents=True)
            model.write_text("", encoding="utf-8")
            env = {
                "RUSTCLAW_HOME": str(root),
                "WHISPER_MODEL": "",
                "WHISPER_MODEL_PATH": "",
                "WHISPER_CPP_MODEL": "",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                self.assertEqual(vt.find_whisper_model(), model)

    def test_extract_audio_reuses_existing_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            input_path.write_text("video", encoding="utf-8")
            audio_path.write_text("audio", encoding="utf-8")
            with mock.patch("video_transcriber.subprocess.run") as run:
                self.assertEqual(vt.extract_audio(input_path, audio_path, reuse_audio=True), audio_path)
            run.assert_not_called()

    def test_extract_audio_rejects_existing_audio_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            input_path.write_text("video", encoding="utf-8")
            audio_path.write_text("audio", encoding="utf-8")

            with self.assertRaises(vt.VideoTranscribeError):
                vt.extract_audio(input_path, audio_path)

    def test_transcribe_audio_requires_output_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            audio_path.write_text("audio", encoding="utf-8")
            transcript_path.write_text("old", encoding="utf-8")

            with self.assertRaises(vt.VideoTranscribeError):
                vt.transcribe_audio(
                    audio_path,
                    transcript_path,
                    whisper_bin=Path("/bin/whisper-cli"),
                    model_path=Path("ggml-small.bin"),
                )

    def test_transcribe_audio_writes_expected_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            audio_path.write_text("audio", encoding="utf-8")

            def fake_run(command: list[str], *, verbose: bool, stream_output: bool = False) -> subprocess.CompletedProcess[str]:
                transcript_path.write_text("hello", encoding="utf-8")
                self.assertTrue(stream_output)
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch("video_transcriber.run_command", side_effect=fake_run):
                self.assertEqual(
                    vt.transcribe_audio(
                        audio_path,
                        transcript_path,
                        whisper_bin=Path("/bin/whisper-cli"),
                        model_path=Path("ggml-small.bin"),
                    ),
                    transcript_path,
                )

    def test_extract_funasr_text_handles_common_result_shapes(self) -> None:
        self.assertEqual(vt.extract_funasr_text("hello"), "hello")
        self.assertEqual(vt.extract_funasr_text({"text": "hello"}), "hello")
        self.assertEqual(vt.extract_funasr_text([{"text": "hello"}, {"text": "world"}]), "hello\nworld")

    def test_postprocess_funasr_text_uses_rich_postprocess_when_available(self) -> None:
        fake_funasr = types.ModuleType("funasr")
        fake_funasr.__path__ = []  # type: ignore[attr-defined]
        fake_utils = types.ModuleType("funasr.utils")
        fake_utils.__path__ = []  # type: ignore[attr-defined]
        fake_postprocess = types.ModuleType("funasr.utils.postprocess_utils")
        fake_postprocess.rich_transcription_postprocess = lambda text: "处理后文本"  # type: ignore[attr-defined]

        modules = {
            "funasr": fake_funasr,
            "funasr.utils": fake_utils,
            "funasr.utils.postprocess_utils": fake_postprocess,
        }
        with mock.patch.dict("sys.modules", modules):
            self.assertEqual(vt.postprocess_funasr_text("<|zh|>原始文本"), "处理后文本")

    def test_transcribe_audio_with_funasr_writes_text(self) -> None:
        calls: dict[str, object] = {}

        class FakeAutoModel:
            def __init__(self, **kwargs: object) -> None:
                calls["model_kwargs"] = kwargs

            def generate(self, **kwargs: object) -> list[dict[str, str]]:
                calls["generate_kwargs"] = kwargs
                return [{"text": "<|zh|><|NEUTRAL|>你好，世界。"}]

        fake_funasr = types.ModuleType("funasr")
        fake_funasr.__path__ = []  # type: ignore[attr-defined]
        fake_funasr.AutoModel = FakeAutoModel  # type: ignore[attr-defined]
        fake_utils = types.ModuleType("funasr.utils")
        fake_utils.__path__ = []  # type: ignore[attr-defined]
        fake_postprocess = types.ModuleType("funasr.utils.postprocess_utils")
        fake_postprocess.rich_transcription_postprocess = lambda text: text.replace("你好", "您好")  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            audio_path.write_text("audio", encoding="utf-8")
            modules = {
                "funasr": fake_funasr,
                "funasr.utils": fake_utils,
                "funasr.utils.postprocess_utils": fake_postprocess,
            }
            with mock.patch.dict("sys.modules", modules):
                self.assertEqual(
                    vt.transcribe_audio_with_funasr(
                        audio_path,
                        transcript_path,
                        model="iic/SenseVoiceSmall",
                        device="cpu",
                        vad_model="fsmn-vad",
                        punc_model=None,
                    ),
                    transcript_path,
                )

            self.assertEqual(transcript_path.read_text(encoding="utf-8"), "您好，世界。\n")
            self.assertEqual(
                calls["model_kwargs"],
                {"model": "iic/SenseVoiceSmall", "device": "cpu", "vad_model": "fsmn-vad"},
            )
            self.assertEqual(
                calls["generate_kwargs"],
                {"input": str(audio_path), "batch_size_s": vt.DEFAULT_FUNASR_BATCH_SIZE_S, "use_itn": True},
            )

    def test_transcribe_audio_with_engine_dispatches_funasr(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            audio_path.write_text("audio", encoding="utf-8")
            with mock.patch(
                "video_transcriber.transcribe_audio_with_funasr",
                return_value=transcript_path,
            ) as funasr:
                self.assertEqual(
                    vt.transcribe_audio_with_engine(
                        audio_path,
                        transcript_path,
                        engine="funasr",
                        funasr_model="local-model",
                        funasr_device="cpu",
                    ),
                    transcript_path,
                )

            self.assertEqual(funasr.call_args.args[:2], (audio_path, transcript_path))
            self.assertEqual(funasr.call_args.kwargs["model"], "local-model")
            self.assertEqual(funasr.call_args.kwargs["device"], "cpu")

    def test_main_transcribes_wav_input_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            audio_path.write_text("audio", encoding="utf-8")
            with mock.patch("video_transcriber.extract_audio") as extract_audio, mock.patch(
                "video_transcriber.find_whisper_binary",
                return_value=Path("/bin/whisper-cli"),
            ), mock.patch(
                "video_transcriber.find_whisper_model",
                return_value=Path("ggml-small.bin"),
            ), mock.patch(
                "video_transcriber.transcribe_audio",
                return_value=transcript_path,
            ) as transcribe_audio, mock.patch("sys.stdout"):
                self.assertEqual(vt.main([str(audio_path)]), 0)

            extract_audio.assert_not_called()
            self.assertEqual(transcribe_audio.call_args.args[:2], (audio_path, transcript_path))

    def test_main_reuses_existing_default_audio_when_transcribing_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            video_path.write_text("video", encoding="utf-8")
            audio_path.write_text("audio", encoding="utf-8")
            with mock.patch(
                "video_transcriber.extract_audio",
                return_value=audio_path,
            ) as extract_audio, mock.patch(
                "video_transcriber.find_whisper_binary",
                return_value=Path("/bin/whisper-cli"),
            ), mock.patch(
                "video_transcriber.find_whisper_model",
                return_value=Path("ggml-small.bin"),
            ), mock.patch(
                "video_transcriber.transcribe_audio",
                return_value=transcript_path,
            ), mock.patch("sys.stdout"):
                self.assertEqual(vt.main([str(video_path)]), 0)

            self.assertTrue(extract_audio.call_args.kwargs["reuse_audio"])


if __name__ == "__main__":
    unittest.main()
