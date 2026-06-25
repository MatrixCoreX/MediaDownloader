import sys
import unittest
from unittest import mock

import media_downloader as dd


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

    def test_x_compatible_is_enabled_by_default(self) -> None:
        self.assertTrue(dd.parse_args([]).x_compatible)
        self.assertFalse(dd.parse_args(["--no-x-compatible"]).x_compatible)

    def test_platform_defaults_to_auto(self) -> None:
        self.assertEqual(dd.parse_args([]).platform, "auto")

    def test_timestamp_output_name(self) -> None:
        with mock.patch("media_downloader.time.strftime", return_value="20260624_153012"):
            self.assertEqual(dd.timestamp_output_name(), "20260624_153012.mp4")


if __name__ == "__main__":
    unittest.main()
