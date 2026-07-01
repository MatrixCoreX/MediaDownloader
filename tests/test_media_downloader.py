import argparse
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import media_downloader as dd


class FakeReadline:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.history_length: int | None = None
        self.read_path: str | None = None
        self.write_path: str | None = None
        self.completer = None
        self.completer_delims: str | None = None
        self.bindings: list[str] = []
        self.line_buffer = ""
        self.begidx = 0
        self.endidx = 0

    def read_history_file(self, path: str) -> None:
        self.read_path = path
        self.items = [line.rstrip("\n") for line in Path(path).read_text(encoding="utf-8").splitlines()]

    def write_history_file(self, path: str) -> None:
        self.write_path = path
        Path(path).write_text("\n".join(self.items) + ("\n" if self.items else ""), encoding="utf-8")

    def set_history_length(self, length: int) -> None:
        self.history_length = length

    def get_current_history_length(self) -> int:
        return len(self.items)

    def get_history_item(self, index: int) -> str | None:
        if index <= 0 or index > len(self.items):
            return None
        return self.items[index - 1]

    def add_history(self, item: str) -> None:
        self.items.append(item)

    def set_completer(self, completer) -> None:
        self.completer = completer

    def set_completer_delims(self, delimiters: str) -> None:
        self.completer_delims = delimiters

    def parse_and_bind(self, binding: str) -> None:
        self.bindings.append(binding)

    def get_line_buffer(self) -> str:
        return self.line_buffer

    def get_begidx(self) -> int:
        return self.begidx

    def get_endidx(self) -> int:
        return self.endidx


class DouyinDownloaderTests(unittest.TestCase):
    def test_extract_urls_from_share_text(self) -> None:
        text = "复制这条消息，打开抖音看看 https://v.douyin.com/abc123/，更多内容"
        self.assertEqual(dd.extract_urls(text), ["https://v.douyin.com/abc123/"])

    def test_extract_aweme_id(self) -> None:
        self.assertEqual(dd.extract_aweme_id("https://www.douyin.com/video/7441234567890123456"), "7441234567890123456")
        self.assertEqual(dd.extract_aweme_id("https://www.douyin.com/?modal_id=7441234567890123456"), "7441234567890123456")

    def test_detect_platform(self) -> None:
        self.assertEqual(dd.detect_platform("https://v.douyin.com/abc123/"), "douyin")
        self.assertEqual(dd.detect_platform("https://v.kuaishou.com/abc123"), "kuaishou")
        self.assertEqual(dd.detect_platform("https://xhslink.com/a/abc123"), "xiaohongshu")
        self.assertEqual(
            dd.detect_platform("https://www.tiktok.com/@li_viaris/video/7654516637915188498"),
            "tiktok",
        )

    def test_extract_tiktok_id(self) -> None:
        self.assertEqual(
            dd.extract_tiktok_id(
                "https://www.tiktok.com/@li_viaris/video/7654516637915188498?is_from_webapp=1"
            ),
            "7654516637915188498",
        )

    def test_extract_kuaishou_candidates_from_json(self) -> None:
        payload = {
            "photo": {
                "mainMvUrls": [
                    {"url": "https://txmov2.a.kwimgs.com/upic/abc.mp4"},
                ]
            }
        }
        candidates = dd.extract_kuaishou_candidates_from_json(payload)
        self.assertEqual(candidates[0].url, "https://txmov2.a.kwimgs.com/upic/abc.mp4")

    def test_extract_xiaohongshu_candidates_from_json(self) -> None:
        payload = {
            "note": {
                "video": {
                    "media": {
                        "stream": {
                            "h264": [
                                {
                                    "masterUrl": "https://sns-video-hw.xhscdn.com/stream/abc",
                                    "backupUrls": ["https://sns-video-bd.xhscdn.com/stream/abc"],
                                }
                            ]
                        }
                    }
                }
            }
        }
        candidates = dd.extract_xiaohongshu_candidates_from_json(payload)
        self.assertEqual(candidates[0].url, "https://sns-video-hw.xhscdn.com/stream/abc")

    def test_xiaohongshu_video_detection_rejects_static_assets(self) -> None:
        self.assertFalse(dd.looks_like_xiaohongshu_video_url("https://fe-video-qc.xhscdn.com/fe-platform/icon.ico"))
        self.assertFalse(dd.looks_like_xiaohongshu_video_url("https://sns-video-qc.xhscdn.com"))
        self.assertTrue(dd.looks_like_xiaohongshu_video_url("https://sns-video-hw.xhscdn.com/stream/abc.mp4"))

    def test_tiktok_video_detection_rejects_page_and_static_assets(self) -> None:
        self.assertFalse(
            dd.looks_like_tiktok_video_url("https://www.tiktok.com/@li_viaris/video/7654516637915188498")
        )
        self.assertFalse(dd.looks_like_tiktok_video_url("https://p16-sign.tiktokcdn-us.com/tos/image.jpg"))
        self.assertTrue(
            dd.looks_like_tiktok_video_url(
                "https://v16m.tiktokcdn-us.com/123abc/video.mp4?mime_type=video_mp4"
            )
        )

    def test_extract_tiktok_candidates_from_json(self) -> None:
        payload = {
            "ItemModule": {
                "7654516637915188498": {
                    "video": {
                        "playAddr": "https://v16m.tiktokcdn-us.com/path/video.mp4?mime_type=video_mp4",
                        "bitrateInfo": [
                            {
                                "PlayAddr": {
                                    "UrlList": [
                                        "https://v16m.tiktokcdn-us.com/path/720.mp4?mime_type=video_mp4"
                                    ]
                                }
                            }
                        ],
                    }
                }
            }
        }
        candidates = dd.extract_tiktok_candidates_from_json(payload)
        self.assertEqual(
            candidates[0].url,
            "https://v16m.tiktokcdn-us.com/path/720.mp4?mime_type=video_mp4",
        )

    def test_extract_json_from_state_script(self) -> None:
        html = '<script>window.__INITIAL_STATE__={"video":{"url":"https://sns-video-hw.xhscdn.com/stream/abc"}};</script>'
        payloads = dd.extract_json_from_html(html)
        self.assertEqual(payloads[0]["video"]["url"], "https://sns-video-hw.xhscdn.com/stream/abc")

    def test_should_start_interactive_for_empty_tty(self) -> None:
        args = dd.parse_args([])
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            self.assertTrue(dd.should_start_interactive(args))

    def test_should_not_start_interactive_with_share_arg(self) -> None:
        args = dd.parse_args(["https://v.douyin.com/abc123/"])
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            self.assertFalse(dd.should_start_interactive(args))

    def test_x_compatible_requires_explicit_flag(self) -> None:
        self.assertFalse(dd.parse_args([]).x_compatible)
        self.assertTrue(dd.parse_args(["--x-compatible"]).x_compatible)

    def test_interactive_x_compatible_requires_explicit_flag(self) -> None:
        self.assertFalse(dd.parse_args(["--interactive"]).x_compatible)
        self.assertTrue(dd.parse_args(["--interactive", "--x-compatible"]).x_compatible)

    def test_audio_and_transcription_require_explicit_flags(self) -> None:
        self.assertFalse(dd.parse_args([]).extract_audio)
        self.assertFalse(dd.parse_args([]).transcribe)
        self.assertTrue(dd.parse_args(["--extract-audio"]).extract_audio)
        self.assertTrue(dd.parse_args(["--transcribe"]).transcribe)
        self.assertEqual(dd.parse_args([]).transcribe_engine, dd.video_transcriber.DEFAULT_TRANSCRIBE_ENGINE)
        self.assertEqual(dd.parse_args(["--transcribe-engine", "funasr"]).transcribe_engine, "funasr")
        self.assertFalse(dd.parse_args([]).funasr_rich_text)
        self.assertTrue(dd.parse_args(["--funasr-rich-text"]).funasr_rich_text)

    def test_image_ocr_is_enabled_by_default(self) -> None:
        self.assertTrue(dd.parse_args([]).ocr_images)
        self.assertFalse(dd.parse_args(["--no-ocr-images"]).ocr_images)
        self.assertTrue(dd.parse_args(["--ocr-images"]).ocr_images)
        self.assertEqual(dd.parse_args([]).ocr_language, dd.image_ocr.DEFAULT_LANGUAGE)
        self.assertEqual(dd.parse_args(["--ocr-language", "eng"]).ocr_language, "eng")
        self.assertEqual(dd.parse_args([]).ocr_psm, dd.image_ocr.DEFAULT_PSM)
        self.assertTrue(dd.parse_args([]).ocr_preprocess)
        self.assertFalse(dd.parse_args(["--no-ocr-preprocess"]).ocr_preprocess)
        self.assertTrue(dd.parse_args(["--ocr-preprocess"]).ocr_preprocess)

    def test_browser_fallback_is_enabled_by_default(self) -> None:
        self.assertTrue(dd.parse_args([]).browser_fallback)
        self.assertFalse(dd.parse_args(["--no-browser-fallback"]).browser_fallback)
        self.assertEqual(dd.parse_args([]).browser_timeout, dd.DEFAULT_BROWSER_TIMEOUT)

    def test_finds_non_google_chromium_browser(self) -> None:
        def fake_which(executable: str) -> str | None:
            return "/usr/bin/microsoft-edge" if executable == "microsoft-edge" else None

        with mock.patch("media_downloader.shutil.which", side_effect=fake_which):
            self.assertEqual(dd.find_chrome_executable(), "/usr/bin/microsoft-edge")

    def test_missing_browser_error_mentions_optional_fallback(self) -> None:
        args = dd.parse_args(["https://v.douyin.com/abc123/"])
        logs = ["Browser fallback skipped: no Chromium-compatible browser was found."]
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("douyin", "7441234567890123456", [], [], logs),
        ):
            with mock.patch("sys.stderr", new_callable=io.StringIO):
                with self.assertRaises(dd.DouyinDownloadError) as raised:
                    dd.handle_share_text(args, args.share, None)
        self.assertIn("optional browser fallback was unavailable", str(raised.exception))

    def test_handle_share_text_retries_parse_error_and_prints_attempts(self) -> None:
        args = dd.parse_args(["--print-url", "https://v.douyin.com/abc123/"])
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            side_effect=[
                dd.DouyinDownloadError("temporary parse failure"),
                ("douyin", "7441234567890123456", [candidate], [], []),
            ],
        ) as gather:
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertEqual(gather.call_count, 2)
        message = stderr.getvalue()
        self.assertIn("parse_attempt: 1/4", message)
        self.assertIn("parse_failed: attempt 1/4: temporary parse failure", message)
        self.assertIn("parse_attempt: 2/4", message)

    def test_handle_share_text_retries_empty_parse_results_three_times(self) -> None:
        args = dd.parse_args(["https://v.douyin.com/abc123/"])
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("douyin", "7441234567890123456", [], [], []),
        ) as gather:
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                with self.assertRaises(dd.DouyinDownloadError):
                    dd.handle_share_text(args, args.share, None)

        self.assertEqual(gather.call_count, dd.PARSE_RETRY_COUNT + 1)
        message = stderr.getvalue()
        self.assertIn("parse_attempt: 1/4", message)
        self.assertIn("parse_attempt: 4/4", message)
        self.assertEqual(message.count("no downloadable media found"), dd.PARSE_RETRY_COUNT)

    def test_interactive_loop_prints_parse_attempts(self) -> None:
        args = dd.parse_args(["--interactive", "--print-url"])
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        responses = iter(["https://v.douyin.com/abc123/", "q"])
        with mock.patch("builtins.input", side_effect=lambda _prompt: next(responses)), mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("douyin", "7441234567890123456", [candidate], [], []),
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.interactive_loop(args, None), 0)

        self.assertIn("parse_attempt: 1/4", stderr.getvalue())

    def test_interactive_command_toggles_and_sets_options(self) -> None:
        args = dd.parse_args(["--interactive"])
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            keep_running, cookie = dd.handle_interactive_command(args, ":on transcribe", None)
            self.assertTrue(keep_running)
            self.assertIsNone(cookie)
            self.assertTrue(args.transcribe)

            keep_running, cookie = dd.handle_interactive_command(args, ":audio-output downloads/a.wav", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.audio_output, "downloads/a.wav")

            keep_running, cookie = dd.handle_interactive_command(args, ":platform titok", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.platform, "tiktok")

            keep_running, cookie = dd.handle_interactive_command(args, ":transcribe-engine funasr", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.transcribe_engine, "funasr")

            keep_running, cookie = dd.handle_interactive_command(args, ":funasr-device cpu", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.funasr_device, "cpu")

            keep_running, cookie = dd.handle_interactive_command(args, ":funasr-rich-text on", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.funasr_rich_text)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear funasr-rich-text", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.funasr_rich_text)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear transcribe-engine", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.transcribe_engine, dd.video_transcriber.DEFAULT_TRANSCRIBE_ENGINE)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear audio-output", cookie)
            self.assertTrue(keep_running)
            self.assertIsNone(args.audio_output)

            keep_running, cookie = dd.handle_interactive_command(args, ":transcribe off", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.transcribe)

            keep_running, cookie = dd.handle_interactive_command(args, ":whisper-progress off", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.whisper_progress)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear whisper-progress", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.whisper_progress)

            keep_running, cookie = dd.handle_interactive_command(args, ":browser-fallback off", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.browser_fallback)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear browser-fallback", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.browser_fallback)

            self.assertTrue(args.ocr_images)

            keep_running, cookie = dd.handle_interactive_command(args, ":ocr-images off", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.ocr_images)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear ocr-images", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.ocr_images)

            keep_running, cookie = dd.handle_interactive_command(args, ":ocr-language eng", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.ocr_language, "eng")

            keep_running, cookie = dd.handle_interactive_command(args, ":clear ocr-language", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.ocr_language, dd.image_ocr.DEFAULT_LANGUAGE)

            keep_running, cookie = dd.handle_interactive_command(args, ":ocr-preprocess off", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.ocr_preprocess)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear ocr-preprocess", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.ocr_preprocess)

            keep_running, cookie = dd.handle_interactive_command(args, ":whisper-fast on", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.whisper_fast)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear whisper-fast", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.whisper_fast)

    def test_interactive_status_prints_current_settings(self) -> None:
        args = dd.parse_args(["--interactive", "--transcribe", "--output-dir", "videos"])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            keep_running, cookie = dd.handle_interactive_command(args, ":status", None)

        self.assertTrue(keep_running)
        self.assertIsNone(cookie)
        output = stdout.getvalue()
        self.assertIn("interactive_settings:", output)
        self.assertIn("transcribe: on", output)
        self.assertIn("output-dir: videos", output)

    def test_interactive_command_can_update_cookie(self) -> None:
        args = dd.parse_args(["--interactive"])
        with tempfile.TemporaryDirectory() as tmpdir:
            cookie_path = Path(tmpdir) / "cookies.txt"
            cookie_path.write_text("session=abc\n", encoding="utf-8")
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                keep_running, cookie = dd.handle_interactive_command(args, f":set cookie {cookie_path}", None)

        self.assertTrue(keep_running)
        self.assertEqual(args.cookie, str(cookie_path))
        self.assertEqual(cookie, "session=abc")

    def test_interactive_loop_applies_commands_before_download(self) -> None:
        args = dd.parse_args(["--interactive"])
        responses = iter(
            [
                ":transcribe on",
                ":set audio-output downloads/custom.wav",
                "https://v.douyin.com/abc123/",
                ":quit",
            ]
        )
        calls: list[tuple[bool, str | None, str, str | None]] = []

        def fake_handle_share_text(
            current_args: object,
            share_text: str,
            cookie: str | None,
        ) -> int:
            assert isinstance(current_args, argparse.Namespace)
            calls.append((current_args.transcribe, current_args.audio_output, share_text, cookie))
            return 0

        with mock.patch("builtins.input", side_effect=lambda _prompt: next(responses)), mock.patch(
            "media_downloader.handle_share_text",
            side_effect=fake_handle_share_text,
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.interactive_loop(args, None), 0)

        self.assertEqual(calls, [(True, "downloads/custom.wav", "https://v.douyin.com/abc123/", None)])

    def test_interactive_history_loads_prints_and_saves(self) -> None:
        fake_readline = FakeReadline()
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "history.txt"
            history_path.write_text(":status\n", encoding="utf-8")
            with mock.patch.object(dd, "readline", fake_readline), mock.patch.object(
                sys.stdin,
                "isatty",
                return_value=True,
            ), mock.patch.dict(dd.os.environ, {dd.INTERACTIVE_HISTORY_ENV: str(history_path)}, clear=False):
                loaded_path = dd.setup_interactive_history()
                dd.add_interactive_history(":status")
                dd.add_interactive_history(":transcribe on")
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                    dd.print_interactive_history()
                dd.save_interactive_history(loaded_path)

            self.assertEqual(loaded_path, history_path)
            self.assertEqual(fake_readline.history_length, dd.INTERACTIVE_HISTORY_LIMIT)
            self.assertEqual(fake_readline.items, [":status", ":transcribe on"])
            self.assertIn(":transcribe on", stdout.getvalue())
            self.assertEqual(history_path.read_text(encoding="utf-8"), ":status\n:transcribe on\n")

    def test_interactive_loop_records_history_when_tty_history_is_available(self) -> None:
        args = dd.parse_args(["--interactive"])
        fake_readline = FakeReadline()
        responses = iter([":status", "q"])
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "history.txt"
            with mock.patch.object(dd, "readline", fake_readline), mock.patch.object(
                sys.stdin,
                "isatty",
                return_value=True,
            ), mock.patch.dict(dd.os.environ, {dd.INTERACTIVE_HISTORY_ENV: str(history_path)}, clear=False), mock.patch(
                "builtins.input",
                side_effect=lambda _prompt: next(responses),
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.interactive_loop(args, None), 0)

            self.assertEqual(fake_readline.items, [":status", "q"])
            self.assertEqual(history_path.read_text(encoding="utf-8"), ":status\nq\n")

    def test_interactive_completion_candidates(self) -> None:
        self.assertIn(":transcribe ", dd.interactive_completion_candidates(":tr", 1, 3))
        self.assertIn("whisper-model ", dd.interactive_completion_candidates(":set whi", 5, 8))
        self.assertIn("funasr-model ", dd.interactive_completion_candidates(":set fun", 5, 8))
        self.assertIn("funasr-rich-text ", dd.interactive_completion_candidates(":set fun", 5, 8))
        self.assertIn("ocr-images ", dd.interactive_completion_candidates(":set ocr", 5, 8))
        self.assertIn("ocr-preprocess ", dd.interactive_completion_candidates(":set ocr", 5, 8))
        self.assertIn("douyin ", dd.interactive_completion_candidates(":set platform d", 14, 15))
        self.assertIn("funasr ", dd.interactive_completion_candidates(":set transcribe-engine f", 23, 24))
        self.assertIn("on ", dd.interactive_completion_candidates(":set funasr-rich-text o", 22, 23))
        self.assertIn("off ", dd.interactive_completion_candidates(":transcribe o", 12, 13))

    def test_interactive_completion_is_registered_with_readline(self) -> None:
        fake_readline = FakeReadline()
        with mock.patch.object(dd, "readline", fake_readline):
            dd.setup_interactive_completion()

        self.assertIsNotNone(fake_readline.completer)
        self.assertEqual(fake_readline.completer_delims, " \t\n")
        self.assertIn("tab: complete", fake_readline.bindings)

        fake_readline.line_buffer = ":sta"
        fake_readline.begidx = 1
        fake_readline.endidx = 4
        self.assertEqual(fake_readline.completer("", 0), ":status ")

    def test_handle_share_text_prints_video_media_type(self) -> None:
        args = dd.parse_args(["--print-url", "https://v.douyin.com/abc123/"])
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("douyin", "7441234567890123456", [candidate], [], []),
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)
        self.assertIn("detected_media: video", stderr.getvalue())

    def test_handle_share_text_prints_kuaishou_video_media_type(self) -> None:
        args = dd.parse_args(["--print-url", "https://v.kuaishou.com/abc123"])
        candidate = dd.Candidate("https://txmov2.a.kwimgs.com/upic/abc.mp4", "test", 1)
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("kuaishou", "abc123", [candidate], [], []),
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)
        message = stderr.getvalue()
        self.assertIn("detected_media: video", message)
        self.assertIn("platform=kuaishou", message)

    def test_handle_share_text_prints_image_media_type(self) -> None:
        args = dd.parse_args(["--print-url", "https://www.xiaohongshu.com/discovery/item/abc"])
        image_candidate = dd.ImageCandidate("https://example.com/image.jpg", "test", 1)
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("xiaohongshu", "abc", [], [image_candidate], []),
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)
        self.assertIn("detected_media: images", stderr.getvalue())

    def test_handle_share_text_does_not_extract_audio_by_default(self) -> None:
        args = dd.parse_args(["https://v.douyin.com/abc123/"])
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
            ) as extract_audio:
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        extract_audio.assert_not_called()

    def test_handle_share_text_extracts_audio_and_transcribes_when_requested(self) -> None:
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "custom_audio.wav"
            transcript_path = Path(tmpdir) / "custom_text.txt"
            args = dd.parse_args(
                [
                    "--extract-audio",
                    "--transcribe",
                    "--audio-output",
                    str(audio_path),
                    "--text-output",
                    str(transcript_path),
                    "--whisper-bin",
                    "/bin/whisper-cli",
                    "--whisper-model",
                    "/models/ggml-small.bin",
                    "--whisper-threads",
                    "2",
                    "https://v.douyin.com/abc123/",
                ]
            )
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
                return_value=audio_path,
            ) as extract_audio, mock.patch(
                "media_downloader.video_transcriber.find_whisper_binary",
                return_value=Path("/bin/whisper-cli"),
            ) as find_whisper_binary, mock.patch(
                "media_downloader.video_transcriber.find_whisper_model",
                return_value=Path("/models/ggml-small.bin"),
            ) as find_whisper_model, mock.patch(
                "media_downloader.video_transcriber.transcribe_audio",
                return_value=transcript_path,
            ) as transcribe_audio:
                with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertEqual(extract_audio.call_args.args[:2], (saved_path, audio_path))
        self.assertEqual(extract_audio.call_args.kwargs["sample_rate"], dd.video_transcriber.DEFAULT_SAMPLE_RATE)
        self.assertEqual(extract_audio.call_args.kwargs["channels"], dd.video_transcriber.DEFAULT_CHANNELS)
        find_whisper_binary.assert_called_once_with("/bin/whisper-cli")
        find_whisper_model.assert_called_once_with("/models/ggml-small.bin")
        self.assertEqual(transcribe_audio.call_args.args[:2], (audio_path, transcript_path))
        self.assertEqual(transcribe_audio.call_args.kwargs["threads"], 2)
        self.assertTrue(transcribe_audio.call_args.kwargs["print_progress"])
        self.assertFalse(transcribe_audio.call_args.kwargs["fast"])
        output = stdout.getvalue()
        self.assertIn(f"audio: {audio_path}", output)
        self.assertIn(f"transcript: {transcript_path}", output)

    def test_handle_share_text_can_enable_fast_transcription(self) -> None:
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            args = dd.parse_args(["--transcribe", "--whisper-fast", "https://v.douyin.com/abc123/"])
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
                return_value=audio_path,
            ), mock.patch(
                "media_downloader.video_transcriber.find_whisper_binary",
                return_value=Path("/bin/whisper-cli"),
            ), mock.patch(
                "media_downloader.video_transcriber.find_whisper_model",
                return_value=Path("/models/ggml-small.bin"),
            ), mock.patch(
                "media_downloader.video_transcriber.transcribe_audio",
                return_value=transcript_path,
            ) as transcribe_audio:
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertTrue(transcribe_audio.call_args.kwargs["fast"])

    def test_handle_share_text_can_disable_transcription_progress(self) -> None:
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            args = dd.parse_args(["--transcribe", "--whisper-no-progress", "https://v.douyin.com/abc123/"])
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
                return_value=audio_path,
            ), mock.patch(
                "media_downloader.video_transcriber.find_whisper_binary",
                return_value=Path("/bin/whisper-cli"),
            ), mock.patch(
                "media_downloader.video_transcriber.find_whisper_model",
                return_value=Path("/models/ggml-small.bin"),
            ), mock.patch(
                "media_downloader.video_transcriber.transcribe_audio",
                return_value=transcript_path,
            ) as transcribe_audio:
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertFalse(transcribe_audio.call_args.kwargs["print_progress"])

    def test_handle_share_text_can_use_funasr_engine(self) -> None:
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            args = dd.parse_args(
                [
                    "--transcribe",
                    "--transcribe-engine",
                    "funasr",
                    "--funasr-model",
                    "iic/SenseVoiceSmall",
                    "--funasr-device",
                    "cpu",
                    "--funasr-rich-text",
                    "https://v.douyin.com/abc123/",
                ]
            )
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
                return_value=audio_path,
            ), mock.patch(
                "media_downloader.video_transcriber.find_whisper_binary",
            ) as find_whisper_binary, mock.patch(
                "media_downloader.video_transcriber.find_whisper_model",
            ) as find_whisper_model, mock.patch(
                "media_downloader.video_transcriber.transcribe_audio_with_engine",
                return_value=transcript_path,
            ) as transcribe:
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        find_whisper_binary.assert_not_called()
        find_whisper_model.assert_not_called()
        self.assertEqual(transcribe.call_args.kwargs["engine"], "funasr")
        self.assertEqual(transcribe.call_args.kwargs["funasr_model"], "iic/SenseVoiceSmall")
        self.assertEqual(transcribe.call_args.kwargs["funasr_device"], "cpu")
        self.assertTrue(transcribe.call_args.kwargs["funasr_rich_text"])

    def test_handle_share_text_extract_audio_does_not_transcribe_without_flag(self) -> None:
        args = dd.parse_args(["--extract-audio", "https://v.douyin.com/abc123/"])
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
                return_value=audio_path,
            ) as extract_audio, mock.patch(
                "media_downloader.video_transcriber.transcribe_audio",
            ) as transcribe_audio:
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        extract_audio.assert_called_once()
        transcribe_audio.assert_not_called()

    def test_handle_share_text_reuses_existing_default_audio_for_transcription(self) -> None:
        args = dd.parse_args(["--transcribe", "https://v.douyin.com/abc123/"])
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            audio_path = Path(tmpdir) / "video_audio.wav"
            transcript_path = Path(tmpdir) / "video_transcript.txt"
            saved_path.write_text("video", encoding="utf-8")
            audio_path.write_text("audio", encoding="utf-8")
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [candidate], [], []),
            ), mock.patch("media_downloader.download_candidate", return_value=saved_path), mock.patch(
                "media_downloader.video_transcriber.extract_audio",
                return_value=audio_path,
            ) as extract_audio, mock.patch(
                "media_downloader.video_transcriber.find_whisper_binary",
                return_value=Path("/bin/whisper-cli"),
            ), mock.patch(
                "media_downloader.video_transcriber.find_whisper_model",
                return_value=Path("/models/ggml-small.bin"),
            ), mock.patch(
                "media_downloader.video_transcriber.transcribe_audio",
                return_value=transcript_path,
            ):
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ):
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertTrue(extract_audio.call_args.kwargs["reuse_audio"])

    def test_audio_options_are_ignored_for_image_only_posts(self) -> None:
        args = dd.parse_args(["--transcribe", "--no-ocr-images", "https://www.xiaohongshu.com/discovery/item/abc"])
        image_candidate = dd.ImageCandidate("https://example.com/image.jpg", "test", 1)
        saved_paths = [Path("downloads/image.jpg")]
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("xiaohongshu", "abc", [], [image_candidate], []),
        ), mock.patch(
            "media_downloader.download_image_candidates",
            return_value=saved_paths,
        ) as download_images, mock.patch(
            "media_downloader.video_transcriber.extract_audio",
        ) as extract_audio:
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        download_images.assert_called_once()
        extract_audio.assert_not_called()
        self.assertIn("downloads/image.jpg", stdout.getvalue())

    def test_handle_share_text_ocr_images_by_default(self) -> None:
        args = dd.parse_args(
            [
                "--ocr-language",
                "eng",
                "--ocr-output",
                "downloads/post_text.txt",
                "https://www.xiaohongshu.com/discovery/item/abc",
            ]
        )
        image_candidate = dd.ImageCandidate("https://example.com/image.jpg", "test", 1)
        saved_paths = [Path("downloads/image.jpg")]
        ocr_path = Path("downloads/post_text.txt")
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("xiaohongshu", "abc", [], [image_candidate], []),
        ), mock.patch(
            "media_downloader.download_image_candidates",
            return_value=saved_paths,
        ), mock.patch(
            "media_downloader.image_ocr.ocr_images",
            return_value=ocr_path,
        ) as ocr_images:
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertEqual(ocr_images.call_args.args[0], saved_paths)
        self.assertEqual(ocr_images.call_args.kwargs["output"], "downloads/post_text.txt")
        self.assertEqual(ocr_images.call_args.kwargs["language"], "eng")
        self.assertEqual(ocr_images.call_args.kwargs["psm"], dd.image_ocr.DEFAULT_PSM)
        self.assertTrue(ocr_images.call_args.kwargs["preprocess"])
        self.assertIn(f"ocr: {ocr_path}", stdout.getvalue())

    def test_no_ocr_images_disables_default_ocr(self) -> None:
        args = dd.parse_args(["--no-ocr-images", "https://www.xiaohongshu.com/discovery/item/abc"])
        image_candidate = dd.ImageCandidate("https://example.com/image.jpg", "test", 1)
        saved_paths = [Path("downloads/image.jpg")]
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("xiaohongshu", "abc", [], [image_candidate], []),
        ), mock.patch(
            "media_downloader.download_image_candidates",
            return_value=saved_paths,
        ), mock.patch(
            "media_downloader.image_ocr.ocr_images",
        ) as ocr_images:
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        ocr_images.assert_not_called()

    def test_default_ocr_failure_does_not_fail_image_download(self) -> None:
        args = dd.parse_args(["https://www.xiaohongshu.com/discovery/item/abc"])
        image_candidate = dd.ImageCandidate("https://example.com/image.jpg", "test", 1)
        saved_paths = [Path("downloads/image.jpg")]
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("xiaohongshu", "abc", [], [image_candidate], []),
        ), mock.patch(
            "media_downloader.download_image_candidates",
            return_value=saved_paths,
        ), mock.patch(
            "media_downloader.image_ocr.ocr_images",
            side_effect=dd.image_ocr.ImageOcrError("tesseract is required but was not found in PATH."),
        ):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertIn("downloads/image.jpg", stdout.getvalue())
        self.assertIn("warning: Image OCR skipped", stderr.getvalue())

    def test_print_url_does_not_run_default_ocr(self) -> None:
        args = dd.parse_args(["--print-url", "https://www.xiaohongshu.com/discovery/item/abc"])
        image_candidate = dd.ImageCandidate("https://example.com/image.jpg", "test", 1)
        with mock.patch(
            "media_downloader.gather_candidates_for_request",
            return_value=("xiaohongshu", "abc", [], [image_candidate], []),
        ), mock.patch(
            "media_downloader.image_ocr.ocr_images",
        ) as ocr_images:
            with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout, mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        ocr_images.assert_not_called()
        self.assertIn("https://example.com/image.jpg", stdout.getvalue())

    def test_platform_defaults_to_auto(self) -> None:
        self.assertEqual(dd.parse_args([]).platform, "auto")

    def test_titok_platform_alias_is_accepted(self) -> None:
        args = dd.parse_args(["--platform", "titok", "https://www.tiktok.com/@u/video/7654516637915188498"])
        with mock.patch(
            "media_downloader.gather_web_platform_candidates",
            return_value=("7654516637915188498", [], [], []),
        ):
            with mock.patch(
                "media_downloader.gather_browser_candidates",
                return_value=("7654516637915188498", [], [], []),
            ):
                platform, _, _, _, _ = dd.gather_candidates_for_request(
                    args.share,
                    platform=args.platform,
                    browser_fallback=True,
                )
        self.assertEqual(platform, "tiktok")

    def test_download_candidate_uses_candidate_cookie_and_referer(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"content-type": "video/mp4"}

            def __init__(self) -> None:
                self.sent = False

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def read(self, size: int = -1) -> bytes:
                if self.sent:
                    return b""
                self.sent = True
                return b"video"

        candidate = dd.Candidate(
            "https://v16m.tiktokcdn-us.com/path/video.mp4?mime_type=video_mp4",
            "test",
            1,
            "ttwid=abc; msToken=def",
            "https://www.tiktok.com/@u/video/7654516637915188498",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.mp4"
            with mock.patch("media_downloader.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
                dd.download_candidate(candidate, output_path)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Cookie"), "ttwid=abc; msToken=def")
        self.assertEqual(request.get_header("Referer"), "https://www.tiktok.com/@u/video/7654516637915188498")

    def test_candidate_metadata_excludes_download_cookie(self) -> None:
        candidate = dd.Candidate("https://example.com/video.mp4", "test", 1, "secret=cookie", "https://example.com/")
        self.assertEqual(
            dd.candidate_metadata(candidate),
            {"url": "https://example.com/video.mp4", "source": "test", "priority": 1},
        )

    def test_timestamp_output_name(self) -> None:
        with mock.patch("media_downloader.time.strftime", return_value="20260624_153012"):
            self.assertEqual(dd.timestamp_output_name(), "20260624_153012.mp4")

    def test_douyin_browser_video_url_detection(self) -> None:
        self.assertTrue(
            dd.looks_like_douyin_browser_video_url(
                "https://v26-web.douyinvod.com/a/video/tos/cn/item/?bt=1123&mime_type=video_mp4"
            )
        )
        self.assertFalse(
            dd.looks_like_douyin_browser_video_url("https://www.douyinstatic.com/video/tos/poster.mp4")
        )

    def test_extract_browser_candidates_from_netlog_payload_prefers_higher_bitrate(self) -> None:
        low = "https://v26-web.douyinvod.com/a/video/tos/cn/item/?bt=492&mime_type=video_mp4"
        high = "https://v26-web.douyinvod.com/a/video/tos/cn/item/?bt=1123&mime_type=video_mp4"
        static = "https://www.douyinstatic.com/video/tos/poster.mp4"
        payload = {
            "events": [
                {"params": {"url": low}},
                {"params": {"url": static}},
                {"params": {"line": f"GET /x HTTP/1.1\r\nReferer: https://douyin.com\r\n{high}"}},
            ]
        }
        candidates = dd.extract_browser_candidates_from_netlog_payload(payload, "douyin")
        self.assertEqual([candidate.url for candidate in candidates], [high, low])

    def test_extract_douyin_image_candidates_prefers_signed_non_watermark_images(self) -> None:
        signed = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/image-a"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images\\u0026x-signature=abc%3D"
        )
        unsigned = (
            "https://p9-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/image-a"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images"
        )
        watermarked = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/image-a"
            "~tplv-dy-water-v2:mark:1080:1549.webp?biz_tag=aweme_images\\u0026x-signature=water"
        )
        comment = (
            "https://p3-sign.douyinpic.com/tos-cn-i-p14/comment"
            "~tplv-p14lwwcsbr-1.image?biz_tag=aweme_comment\\u0026x-signature=comment"
        )
        html = f'<img src="{signed}"><script>window.x="{unsigned} {watermarked} {comment}"</script>'
        candidates = dd.extract_douyin_image_candidates_from_text(html)
        self.assertEqual(len(candidates), 1)
        self.assertIn("x-signature=abc", candidates[0].url)
        self.assertNotIn("dy-water", candidates[0].url)

    def test_extract_xiaohongshu_image_candidates_prefers_default_image(self) -> None:
        preview = (
            "http:\\u002F\\u002Fsns-webpic-qc.xhscdn.com\\u002F202606260823\\u002Fpreview-hash"
            "\\u002Fimage-file!nd_prv_wlteh_jpg_3"
        )
        default = (
            "http:\\u002F\\u002Fsns-webpic-qc.xhscdn.com\\u002F202606260823\\u002Fdefault-hash"
            "\\u002Fimage-file!nd_dft_wlteh_jpg_3"
        )
        avatar = "https:\\u002F\\u002Fsns-avatar-qc.xhscdn.com\\u002Favatar\\u002Fimage-file"
        html = f'<script>window.__INITIAL_STATE__={{"imageList":[{{"urlPre":"{preview}","urlDefault":"{default}","avatar":"{avatar}"}}]}}</script>'
        candidates = dd.extract_xiaohongshu_image_candidates_from_text(html)
        self.assertEqual(len(candidates), 1)
        self.assertIn("nd_dft", candidates[0].url)
        self.assertNotIn("sns-avatar", candidates[0].url)


if __name__ == "__main__":
    unittest.main()
