import argparse
import io
import sys
import tempfile
import threading
import time
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
        self.redisplay_calls = 0

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

    def redisplay(self) -> None:
        self.redisplay_calls += 1

    def get_line_buffer(self) -> str:
        return self.line_buffer

    def get_begidx(self) -> int:
        return self.begidx

    def get_endidx(self) -> int:
        return self.endidx


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class DouyinDownloaderTests(unittest.TestCase):
    def test_extract_urls_from_share_text(self) -> None:
        text = "复制这条消息，打开抖音看看 https://v.douyin.com/abc123/，更多内容"
        self.assertEqual(dd.extract_urls(text), ["https://v.douyin.com/abc123/"])

    def test_extracts_phone_app_share_url_without_trailing_copy_code(self) -> None:
        text = (
            "6.97 复制打开抖音，看看【Louie’oversea的图文作品】物质正在裹挟你吗 "
            "https://v.douyin.com/s3eZp4vFHeU/ H@I.ic :1pm teb:/ 11/29"
        )
        self.assertEqual(dd.extract_urls(text), ["https://v.douyin.com/s3eZp4vFHeU/"])
        self.assertEqual(dd.detect_platform(text), "douyin")

    def test_extract_aweme_id(self) -> None:
        self.assertEqual(dd.extract_aweme_id("https://www.douyin.com/video/7441234567890123456"), "7441234567890123456")
        self.assertEqual(dd.extract_aweme_id("https://www.douyin.com/?modal_id=7441234567890123456"), "7441234567890123456")

    def test_extract_douyin_profile_target(self) -> None:
        url = (
            "https://www.douyin.com/user/"
            "MS4wLjABAAAAR2Tbqlv2n-JBioEHUp25OCF7BGzWXTWFnQhG9CjkhCc?from_tab_name=main"
        )
        self.assertEqual(
            dd.extract_douyin_profile_target(f"主页：{url}"),
            (url, "MS4wLjABAAAAR2Tbqlv2n-JBioEHUp25OCF7BGzWXTWFnQhG9CjkhCc"),
        )
        self.assertIsNone(dd.extract_douyin_profile_target("https://www.douyin.com/video/7441234567890123456"))

    def test_extract_xiaohongshu_profile_target(self) -> None:
        url = (
            "https://www.xiaohongshu.com/user/profile/5e1d98150000000001007051"
            "?xsec_token=profile-token&xsec_source=pc_search"
        )
        self.assertEqual(
            dd.extract_xiaohongshu_profile_target(f"主页：{url}"),
            (url, "5e1d98150000000001007051"),
        )
        self.assertIsNone(
            dd.extract_xiaohongshu_profile_target(
                "https://www.xiaohongshu.com/explore/6a2ead47000000001c025f7d"
            )
        )

    def test_profile_options_accept_all_and_default_to_five_second_interval(self) -> None:
        args = dd.parse_args([])
        self.assertEqual(args.profile_limit, 100)
        self.assertEqual(args.profile_interval, 5.0)
        self.assertTrue(args.system_browser_cookies)
        configured = dd.parse_args(["--profile-limit", "12", "--profile-interval", "3.5"])
        self.assertEqual(configured.profile_limit, 12)
        self.assertEqual(configured.profile_interval, 3.5)
        self.assertEqual(dd.parse_args(["--profile-limit", "all"]).profile_limit, "all")
        self.assertFalse(dd.parse_args(["--no-system-browser-cookies"]).system_browser_cookies)

    def test_profile_cookie_header_is_converted_for_temporary_chrome(self) -> None:
        cookies = dd.cookie_params_for_douyin("sessionid=abc=123; ttwid=xyz")
        self.assertEqual(
            [(item["name"], item["value"]) for item in cookies],
            [("sessionid", "abc=123"), ("ttwid", "xyz")],
        )
        self.assertTrue(all(item["domain"] == ".douyin.com" for item in cookies))
        xhs_cookies = dd.cookie_params_for_xiaohongshu("a=1; b=2")
        self.assertTrue(all(item["domain"] == ".xiaohongshu.com" for item in xhs_cookies))

    def test_xiaohongshu_profile_payload_collects_video_and_image_notes(self) -> None:
        posts: dict[str, dd.XiaohongshuProfilePost] = {}
        username, has_more, cursor, added = dd.add_xiaohongshu_profile_payload(
            {
                "success": True,
                "data": {
                    "has_more": True,
                    "cursor": "next-page",
                    "notes": [
                        {
                            "note_id": "6a2ead47000000001c025f7d",
                            "xsec_token": "video-token",
                            "type": "video",
                            "user": {
                                "user_id": "5e1d98150000000001007051",
                                "nickname": "Miya",
                            },
                        },
                        {
                            "note_id": "68e45f4b000000000300f33d",
                            "xsec_token": "image-token",
                            "type": "normal",
                            "user": {
                                "user_id": "5e1d98150000000001007051",
                                "nickname": "Miya",
                            },
                        },
                    ],
                },
            },
            user_id="5e1d98150000000001007051",
            posts_by_id=posts,
            logs=[],
        )

        self.assertEqual(username, "Miya")
        self.assertTrue(has_more)
        self.assertEqual(cursor, "next-page")
        self.assertEqual(added, 2)
        self.assertEqual(posts["6a2ead47000000001c025f7d"].note_type, "video")
        self.assertEqual(posts["68e45f4b000000000300f33d"].note_type, "normal")
        self.assertEqual(
            posts["6a2ead47000000001c025f7d"].create_time,
            int("6a2ead47", 16),
        )

    def test_xiaohongshu_initial_state_preserves_first_page_before_hydration(self) -> None:
        page = (
            '<script>window.__INITIAL_STATE__={'
            '"global":{"unused":undefined},'
            '"user":{'
            '"userPageData":{"basicInfo":{"nickname":"Miya"}},'
            '"notes":[[{"noteCard":{'
            '"noteId":"6a2ead47000000001c025f7d",'
            '"xsecToken":"note-token","type":"video"}}],[],[],[],[]],'
            '"noteQueries":[{"hasMore":true,"cursor":"next"}]'
            '}}</script>'
        )

        username, notes, has_more = dd.extract_xiaohongshu_profile_initial_state(page)

        self.assertEqual(username, "Miya")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["noteCard"]["noteId"], "6a2ead47000000001c025f7d")
        self.assertTrue(has_more)

    def test_xiaohongshu_early_state_read_does_not_trigger_scrolling(self) -> None:
        self.assertIn("window.__INITIAL_STATE__", dd.XIAOHONGSHU_PROFILE_INFO_SCRIPT)
        self.assertNotIn("scrollTop", dd.XIAOHONGSHU_PROFILE_INFO_SCRIPT)
        self.assertNotIn("window.scrollTo", dd.XIAOHONGSHU_PROFILE_INFO_SCRIPT)
        self.assertIn("node.scrollTop = node.scrollHeight", dd.XIAOHONGSHU_PROFILE_STATE_SCRIPT)

    def test_system_browser_cookie_import_copies_only_douyin_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "google-chrome"
            source_profile = source_root / "Default"
            source_profile.mkdir(parents=True)
            (source_root / "Local State").write_text(
                dd.json.dumps({"profile": {"info_cache": {"Default": {}}}}),
                encoding="utf-8",
            )
            source_db = dd.sqlite3.connect(source_profile / "Cookies")
            source_db.execute("create table meta (key text primary key, value text)")
            source_db.execute(
                "create table cookies ("
                "host_key text, name text, value text, encrypted_value blob, last_access_utc integer)"
            )
            source_db.execute("insert into meta values ('version', '24')")
            source_db.executemany(
                "insert into cookies values (?, ?, ?, ?, ?)",
                [
                    (".douyin.com", "session", "", b"v11-secret-a", 30),
                    ("www.douyin.com", "token", "", b"v11-secret-b", 20),
                    ("www.xiaohongshu.com", "xhs-token", "", b"v11-secret-c", 40),
                    ("example.com", "unrelated", "do-not-copy", b"", 100),
                ],
            )
            source_db.commit()
            source_db.close()

            target_root = root / "temporary-browser"
            target_root.mkdir()
            imported = dd.import_system_douyin_cookies(
                target_root,
                "/usr/bin/google-chrome",
                user_data_roots=[source_root],
            )

            self.assertIsNotNone(imported)
            self.assertEqual(imported.cookie_count, 2)
            target_db = dd.sqlite3.connect(target_root / "Default" / "Cookies")
            copied_hosts = [row[0] for row in target_db.execute("select host_key from cookies")]
            target_db.close()
            self.assertEqual(copied_hosts, [".douyin.com", "www.douyin.com"])
            self.assertTrue((target_root / "Local State").is_file())

            xhs_target_root = root / "temporary-xhs-browser"
            xhs_target_root.mkdir()
            xhs_imported = dd.import_system_xiaohongshu_cookies(
                xhs_target_root,
                "/usr/bin/google-chrome",
                user_data_roots=[source_root],
            )
            self.assertIsNotNone(xhs_imported)
            self.assertEqual(xhs_imported.cookie_count, 1)
            xhs_target_db = dd.sqlite3.connect(xhs_target_root / "Default" / "Cookies")
            xhs_hosts = [row[0] for row in xhs_target_db.execute("select host_key from cookies")]
            xhs_target_db.close()
            self.assertEqual(xhs_hosts, ["www.xiaohongshu.com"])

    def test_profile_payload_includes_image_only_posts(self) -> None:
        image_url = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813c000-ce/profile-image"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images"
        )
        posts: dict[str, dd.DouyinProfilePost] = {}
        username, has_more, added = dd.add_douyin_profile_payload(
            {
                "has_more": 0,
                "aweme_list": [
                    {
                        "aweme_id": "7658893225607908651",
                        "author": {"sec_uid": "profile", "nickname": "Miya"},
                        "images": [{"url_list": [image_url]}],
                    }
                ],
            },
            sec_uid="profile",
            posts_by_id=posts,
            logs=[],
        )
        self.assertEqual(username, "Miya")
        self.assertFalse(has_more)
        self.assertEqual(added, 1)
        candidates, images = dd.profile_post_media_candidates(posts["7658893225607908651"])
        self.assertEqual(candidates, [])
        self.assertEqual([candidate.url for candidate in images], [image_url])

    def test_profile_payload_accepts_direct_douyin_cdn_video(self) -> None:
        video_url = (
            "https://v26-web.douyinvod.com/video/tos/cn/item/"
            "?bt=1318&mime_type=video_mp4"
        )
        payload = {
            "aweme_id": "7658893225607908651",
            "author": {"sec_uid": "profile", "nickname": "Miya"},
            "video": {"play_addr": {"url_list": [video_url]}},
        }
        posts: dict[str, dd.DouyinProfilePost] = {}
        _username, _has_more, added = dd.add_douyin_profile_payload(
            {"has_more": 0, "aweme_list": [payload]},
            sec_uid="profile",
            posts_by_id=posts,
            logs=[],
        )
        self.assertEqual(added, 1)
        candidates, images = dd.profile_post_media_candidates(posts["7658893225607908651"])
        self.assertEqual(candidates[0].url, video_url)
        self.assertEqual(images, [])

    def test_douyin_static_image_post_ignores_unmarked_nested_and_music_video(self) -> None:
        image_url = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/image-target"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images&x-signature=signed"
        )
        second_image_url = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/image-target-2"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images&x-signature=signed"
        )
        video_url = (
            "https://v26-web.douyinvod.com/video/tos/cn/image-music/"
            "?bt=1318&mime_type=video_mp4"
        )
        payload = {
            "aweme_id": "7664807527763307958",
            "aweme_type": 68,
            "media_type": 2,
            "video": {"play_addr": {"url_list": [video_url]}},
            "images": [
                {
                    "url_list": [image_url],
                    "video": {"play_addr": {"url_list": [video_url]}},
                },
                {"url_list": [second_image_url]},
            ],
        }

        candidates, images = dd.extract_douyin_item_media_candidates(
            payload,
            source="test",
        )

        self.assertEqual(candidates, [])
        self.assertEqual(
            [candidate.url for candidate in images],
            [image_url, second_image_url],
        )

    def test_douyin_live_photo_prefers_embedded_video(self) -> None:
        image_url = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/live-photo-cover"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images&x-signature=signed"
        )
        live_photo_video_url = (
            "https://www.douyin.com/aweme/v1/play/"
            "?video_id=v0200fg10000d9fdo2vog65j74kr1q20"
        )
        soundtrack_url = (
            "https://sf11-cdn-tos.douyinstatic.com/obj/ies-music/"
            "7625615681576323850.mp3"
        )
        music_container_url = (
            "https://v26-web.douyinvod.com/video/tos/cn/image-music/"
            "?bt=1318&mime_type=video_mp4"
        )
        payload = {
            "aweme_id": "7664807527763307958",
            "aweme_type": 68,
            "media_type": 2,
            "is_live_photo": 1,
            "image_album_music_info": {"begin_time": 0, "end_time": 335000},
            "music": {
                "duration": 335,
                "play_url": {"url_list": [soundtrack_url]},
            },
            "video": {"play_addr": {"url_list": [music_container_url]}},
            "images": [
                {
                    "url_list": [image_url],
                    "live_photo_type": 1,
                    "video": {
                        "duration": 1967,
                        "width": 720,
                        "height": 1422,
                        "play_addr": {"url_list": [live_photo_video_url]},
                    },
                }
            ],
        }

        candidates, images = dd.extract_douyin_item_media_candidates(
            payload,
            source="test",
        )

        self.assertEqual(images, [])
        self.assertEqual([candidate.url for candidate in candidates], [live_photo_video_url])
        self.assertIn("live-photo[0]", candidates[0].source)
        self.assertEqual(candidates[0].live_photo_audio_url, soundtrack_url)
        self.assertEqual(candidates[0].live_photo_duration, 335.0)

    def test_compose_live_photo_loops_clip_to_complete_soundtrack_duration(self) -> None:
        candidate = dd.Candidate(
            "https://example.com/live-photo.mp4",
            "douyin.browser-item.live-photo[0].play_addr",
            1,
            live_photo_audio_url="https://example.com/soundtrack.mp3",
            live_photo_duration=335.0,
        )
        captured_command: list[str] = []
        temporary_audio_paths: list[Path] = []

        def fake_download_audio(_url, output_path, **_kwargs):
            temporary_audio_paths.append(output_path)
            output_path.write_bytes(b"audio")
            return output_path

        def fake_run(command, **_kwargs):
            captured_command.extend(command)
            Path(command[-1]).write_bytes(b"complete-video")
            return dd.subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmpdir:
            clip_path = Path(tmpdir) / "live-photo.mp4"
            clip_path.write_bytes(b"short-clip")
            with mock.patch(
                "media_downloader.download_live_photo_audio",
                side_effect=fake_download_audio,
            ), mock.patch(
                "media_downloader.run_task_subprocess",
                side_effect=fake_run,
            ), mock.patch(
                "media_downloader.shutil.which",
                return_value="/usr/bin/ffmpeg",
            ), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                result = dd.compose_live_photo_video(
                    clip_path,
                    candidate,
                    cookie=None,
                    timeout=30,
                    referer="https://www.douyin.com/",
                    verbose=False,
                )

            self.assertEqual(result.read_bytes(), b"complete-video")
            self.assertTrue(temporary_audio_paths)
            self.assertTrue(all(not path.exists() for path in temporary_audio_paths))

        self.assertIn("-stream_loop", captured_command)
        self.assertIn("335.000", captured_command)
        self.assertIn("1:a:0", captured_command)

    def test_find_douyin_aweme_payload_selects_requested_item_only(self) -> None:
        requested = {
            "aweme_id": "7664807527763307958",
            "images": [{"uri": "target"}],
            "author": {"nickname": "Louie"},
        }
        related = {
            "aweme_id": "7664907477746862948",
            "images": [{"uri": "related-1"}, {"uri": "related-2"}],
        }
        payload = {"aweme_list": [related, requested]}

        self.assertIs(dd.find_douyin_aweme_payload(payload, requested["aweme_id"]), requested)

    def test_exact_item_browser_collector_uses_requested_aweme_payload(self) -> None:
        item_id = "7664807527763307958"
        image_url = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/image-target"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images&x-signature=signed"
        )
        related_image_url = (
            "https://p3-pc-sign.douyinpic.com/tos-cn-i-0813/image-related"
            "~tplv-dy-aweme-images:q75.webp?biz_tag=aweme_images&x-signature=signed"
        )
        response_payload = {
            "status_code": 0,
            "aweme_list": [
                {"aweme_id": "7664907477746862948", "images": [{"url_list": [related_image_url]}]},
                {
                    "aweme_id": item_id,
                    "aweme_type": 68,
                    "media_type": 2,
                    "images": [{"url_list": [image_url]}],
                    "video": {
                        "play_addr": {
                            "url_list": [
                                "https://v26-web.douyinvod.com/video/tos/cn/music/"
                                "?bt=1318&mime_type=video_mp4"
                            ]
                        }
                    },
                },
            ],
        }

        class FakeProcess:
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

        class FakeDevTools:
            def __init__(self):
                self.next_id = 0
                self.sent: list[tuple[int, str]] = []
                self.stage = 0

            def send(self, method, params=None):
                self.next_id += 1
                self.sent.append((self.next_id, method))
                return self.next_id

            def recv(self, *, timeout):
                self.stage += 1
                if self.stage == 1:
                    return {
                        "method": "Network.responseReceived",
                        "params": {
                            "requestId": "item-request",
                            "response": {
                                "url": "https://www.douyin.com/aweme/v1/web/aweme/post/?max_cursor=0"
                            },
                        },
                    }
                if self.stage == 2:
                    return {
                        "method": "Network.loadingFinished",
                        "params": {"requestId": "item-request"},
                    }
                body_id = next(
                    command_id
                    for command_id, method in self.sent
                    if method == "Network.getResponseBody"
                )
                return {"id": body_id, "result": {"body": dd.json.dumps(response_payload)}}

            def close(self):
                return None

        fake_process = FakeProcess()
        with mock.patch("media_downloader.subprocess.Popen", return_value=fake_process), mock.patch(
            "media_downloader.wait_for_devtools_page_url",
            return_value="ws://local/page",
        ), mock.patch(
            "media_downloader.DevToolsConnection",
            return_value=FakeDevTools(),
        ), mock.patch(
            "media_downloader.terminate_process",
        ):
            candidates, images, logs = dd.gather_douyin_browser_item_candidates(
                [f"https://www.douyin.com/note/{item_id}"],
                item_id=item_id,
                cookie=None,
                timeout=5,
                chrome_path="/chrome",
                use_system_browser_cookies=False,
            )

        self.assertEqual(candidates, [])
        self.assertEqual([candidate.url for candidate in images], [image_url])
        self.assertTrue(any(f"aweme_id={item_id}" in line for line in logs))

    def test_profile_scroll_script_targets_internal_scroll_containers(self) -> None:
        script = dd.DOUYIN_PROFILE_STATE_SCRIPT
        self.assertIn("style.overflowY === 'auto'", script)
        self.assertIn("style.overflowY === 'scroll'", script)
        self.assertIn("node.scrollTop = node.scrollHeight", script)
        self.assertIn("node.dispatchEvent(new Event('scroll'", script)

    def test_profile_output_name_uses_username_and_local_publish_time(self) -> None:
        args = dd.parse_args([])
        published = time.struct_time((2026, 7, 21, 14, 32, 10, 1, 202, -1))
        with mock.patch("media_downloader.time.localtime", return_value=published):
            output_name = dd.profile_item_output_name(
                args,
                "Miya/测试",
                1784615530,
                "7658893225607908651",
            )
        self.assertEqual(output_name, "Miya_测试_2026-07-21_14-32-10.mp4")
        self.assertEqual(
            dd.profile_item_output_name(args, "Miya/测试", 0, "7658893225607908651"),
            "Miya_测试_unknown-date_7658893225607908651.mp4",
        )

    def test_profile_video_candidates_prefer_highest_muxed_quality(self) -> None:
        low = (
            "https://v26-web.douyinvod.com/video/tos/cn/item/"
            "?bt=576&mime_type=video_mp4"
        )
        high = (
            "https://v26-web.douyinvod.com/video/tos/cn/item/"
            "?bt=1318&mime_type=video_mp4"
        )
        silent = (
            "https://v26-web.douyinvod.com/video/tos/cn/item/media-video-avc1/"
            "?bt=5000&mime_type=video_mp4"
        )

        candidates = dd.extract_douyin_profile_video_candidates(
            {"play_addr": {"url_list": [low, silent, high]}}
        )

        self.assertEqual([candidate.url for candidate in candidates], [high, low, silent])

    def test_douyin_browser_target_uses_jingxuan_modal_route_as_fallback(self) -> None:
        original = "https://www.douyin.com/video/7441234567890123456"
        self.assertEqual(
            dd.prioritize_browser_target_urls("douyin", "7441234567890123456", [original]),
            [
                original,
                "https://www.douyin.com/jingxuan?modal_id=7441234567890123456",
            ],
        )

    def test_unverified_direct_douyin_media_is_replaced_by_exact_browser_item(self) -> None:
        item_id = "7658893225607908651"
        unrelated = dd.Candidate(
            "https://www.douyin.com/aweme/v1/play/?video_id=unrelated",
            "html-url",
            1,
        )
        requested = dd.Candidate(
            "https://www.douyin.com/aweme/v1/play/?video_id=requested",
            "douyin.browser-item.play_addr",
            1,
        )
        with mock.patch(
            "media_downloader.gather_candidates",
            return_value=(item_id, [unrelated], [], ["Final URL: https://www.douyin.com/video/"]),
        ), mock.patch(
            "media_downloader.gather_browser_candidates",
            return_value=(item_id, [requested], [], ["matched exact item"]),
        ) as gather_browser:
            _platform, parsed_id, candidates, images, logs = dd.gather_candidates_for_request(
                f"https://www.douyin.com/video/{item_id}",
                platform="douyin",
            )

        self.assertEqual(parsed_id, item_id)
        self.assertEqual(candidates, [requested])
        self.assertEqual(images, [])
        self.assertTrue(any("not verified against the requested item ID" in line for line in logs))
        self.assertTrue(gather_browser.call_args.kwargs["use_system_browser_cookies"])

    def test_douyin_browser_target_normalizes_direct_jingxuan_modal_link(self) -> None:
        modal_url = "https://www.douyin.com/jingxuan?modal_id=7658893225607908651"
        self.assertEqual(
            dd.prioritize_browser_target_urls("douyin", "7658893225607908651", [modal_url]),
            [
                "https://www.douyin.com/video/7658893225607908651",
                modal_url,
            ],
        )

    def test_douyin_browser_target_prefers_short_link_over_homepage(self) -> None:
        short_url = "https://v.douyin.com/abc123/"
        homepage = "https://www.douyin.com/"
        self.assertEqual(
            dd.prioritize_browser_target_urls(
                "douyin",
                "7441234567890123456",
                [homepage, short_url],
            ),
            [
                short_url,
                homepage,
                "https://www.douyin.com/jingxuan?modal_id=7441234567890123456",
            ],
        )

    def test_browser_target_routes_do_not_change_other_platforms(self) -> None:
        original = "https://www.xiaohongshu.com/discovery/item/abc"
        self.assertEqual(dd.prioritize_browser_target_urls("xiaohongshu", "abc", [original]), [original])

    def test_browser_candidates_continue_when_audio_is_required_but_stream_is_video_only(self) -> None:
        video_only = dd.Candidate(
            "https://v11-web.douyinvod.com/video/tos/cn/item/media-video-avc1/"
            "?bt=282&mime_type=video_mp4",
            "douyin.browser-netlog",
            1,
        )
        muxed = dd.Candidate(
            "https://v11-web.douyinvod.com/video/tos/cn/item/?bt=718&mime_type=video_mp4",
            "douyin.browser-netlog",
            2,
        )

        self.assertFalse(dd.browser_candidates_are_sufficient([video_only], [], require_audio=True))
        self.assertTrue(dd.browser_candidates_are_sufficient([video_only], [], require_audio=False))
        self.assertTrue(dd.browser_candidates_are_sufficient([video_only, muxed], [], require_audio=True))

    def test_detect_platform(self) -> None:
        self.assertEqual(dd.detect_platform("https://v.douyin.com/abc123/"), "douyin")
        self.assertEqual(dd.detect_platform("https://v.kuaishou.com/abc123"), "kuaishou")
        self.assertEqual(dd.detect_platform("https://xhslink.com/a/abc123"), "xiaohongshu")
        self.assertEqual(
            dd.detect_platform("https://www.tiktok.com/@li_viaris/video/7654516637915188498"),
            "tiktok",
        )
        self.assertEqual(dd.detect_platform("https://youtu.be/dQw4w9WgXcQ"), "youtube")

    def test_extract_tiktok_id(self) -> None:
        self.assertEqual(
            dd.extract_tiktok_id(
                "https://www.tiktok.com/@li_viaris/video/7654516637915188498?is_from_webapp=1"
            ),
            "7654516637915188498",
        )

    def test_extract_youtube_id(self) -> None:
        self.assertEqual(dd.extract_youtube_id("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(dd.extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(dd.extract_youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")

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

    def test_x_folder_prevents_implicit_interactive_mode(self) -> None:
        args = dd.parse_args(["--x-folder", "downloads/videos"])
        self.assertEqual(args.x_folder, "downloads/videos")
        with mock.patch.object(sys.stdin, "isatty", return_value=True):
            self.assertFalse(dd.should_start_interactive(args))

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
        self.assertTrue(dd.parse_args([]).simplify_chinese)
        self.assertFalse(dd.parse_args(["--no-simplify-chinese"]).simplify_chinese)
        self.assertTrue(dd.parse_args(["--simplify-chinese"]).simplify_chinese)

    def test_image_ocr_is_enabled_by_default(self) -> None:
        self.assertTrue(dd.parse_args([]).ocr_images)
        self.assertFalse(dd.parse_args(["--no-ocr-images"]).ocr_images)
        self.assertTrue(dd.parse_args(["--ocr-images"]).ocr_images)
        self.assertEqual(dd.parse_args([]).ocr_language, dd.image_ocr.DEFAULT_LANGUAGE)
        self.assertEqual(dd.parse_args(["--ocr-language", "eng"]).ocr_language, "eng")
        self.assertEqual(dd.parse_args([]).ocr_psm, dd.image_ocr.DEFAULT_PSM)
        self.assertEqual(
            dd.parse_args([]).ocr_min_line_confidence,
            dd.image_ocr.DEFAULT_MIN_LINE_CONFIDENCE,
        )
        self.assertEqual(dd.parse_args(["--ocr-min-line-confidence", "-1"]).ocr_min_line_confidence, -1)
        self.assertTrue(dd.parse_args([]).ocr_preprocess)
        self.assertFalse(dd.parse_args(["--no-ocr-preprocess"]).ocr_preprocess)
        self.assertTrue(dd.parse_args(["--ocr-preprocess"]).ocr_preprocess)

    def test_youtube_options(self) -> None:
        args = dd.parse_args(
            [
                "--platform",
                "yt",
                "--yt-dlp-bin",
                "/bin/yt-dlp",
                "--youtube-format",
                "best",
                "https://youtu.be/dQw4w9WgXcQ",
            ]
        )
        self.assertEqual(dd.normalize_platform(args.platform), "youtube")
        self.assertEqual(args.yt_dlp_bin, "/bin/yt-dlp")
        self.assertEqual(args.youtube_format, "best")

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

            keep_running, cookie = dd.handle_interactive_command(args, ":platform yt", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.platform, "youtube")

            keep_running, cookie = dd.handle_interactive_command(args, ":youtube-format best", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.youtube_format, "best")

            keep_running, cookie = dd.handle_interactive_command(args, ":yt-dlp-bin /bin/yt-dlp", cookie)
            self.assertTrue(keep_running)
            self.assertEqual(args.yt_dlp_bin, "/bin/yt-dlp")

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

            keep_running, cookie = dd.handle_interactive_command(args, ":simplify-chinese off", cookie)
            self.assertTrue(keep_running)
            self.assertFalse(args.simplify_chinese)

            keep_running, cookie = dd.handle_interactive_command(args, ":clear simplify-chinese", cookie)
            self.assertTrue(keep_running)
            self.assertTrue(args.simplify_chinese)

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

    def test_interactive_queue_command_prints_jobs(self) -> None:
        args = dd.parse_args(["--interactive"])
        task_queue = mock.Mock()

        keep_running, cookie = dd.handle_interactive_command(args, ":queue", None, task_queue)

        self.assertTrue(keep_running)
        self.assertIsNone(cookie)
        task_queue.print_snapshot.assert_called_once_with()

    def test_interactive_x_folder_command_queues_directory(self) -> None:
        args = dd.parse_args(["--interactive"])
        task_queue = mock.Mock()

        keep_running, cookie = dd.handle_interactive_command(
            args,
            ':x-folder "/tmp/videos with spaces"',
            None,
            task_queue,
        )

        self.assertTrue(keep_running)
        self.assertIsNone(cookie)
        task_queue.enqueue_x_folder.assert_called_once_with(args, "/tmp/videos with spaces")

    def test_interactive_x_file_command_queues_one_video(self) -> None:
        args = dd.parse_args(["--interactive"])
        task_queue = mock.Mock()

        keep_running, cookie = dd.handle_interactive_command(
            args,
            ':x-file "/tmp/videos with spaces/input video.mp4"',
            None,
            task_queue,
        )

        self.assertTrue(keep_running)
        self.assertIsNone(cookie)
        task_queue.enqueue_x_file.assert_called_once_with(
            args,
            "/tmp/videos with spaces/input video.mp4",
        )

    def test_interactive_cancel_command_cancels_running_and_queued_jobs(self) -> None:
        args = dd.parse_args(["--interactive"])
        task_queue = mock.Mock()
        task_queue.cancel_all.return_value = (2, [3, 4])

        with mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            keep_running, cookie = dd.handle_interactive_command(
                args,
                ":cancel",
                None,
                task_queue,
            )

        self.assertTrue(keep_running)
        self.assertIsNone(cookie)
        task_queue.cancel_all.assert_called_once_with()
        task_queue.print_snapshot.assert_called_once_with()
        self.assertIn("task_cancel: running=#2 queued=#3,#4", stdout.getvalue())

    def test_interactive_prompt_console_keeps_input_below_background_output(self) -> None:
        fake_readline = FakeReadline()
        fake_readline.line_buffer = "typing"
        stdout = FakeTTY()
        stderr = FakeTTY()

        with mock.patch.object(dd, "readline", fake_readline), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            console = dd.InteractivePromptConsole()
            console.install()
            console.input_started()
            print("media> ", end="", flush=True)

            def background_output() -> None:
                print("workflow line", file=sys.stderr, flush=True)
                print("\rprogress 50%", end="", file=sys.stderr, flush=True)

            worker = threading.Thread(target=background_output)
            worker.start()
            worker.join()
            console.input_finished()
            console.restore()

            self.assertIs(sys.stdout, stdout)
            self.assertIs(sys.stderr, stderr)

        self.assertIn("media> ", stdout.getvalue())
        self.assertGreaterEqual(stdout.getvalue().count("\033[2K"), 2)
        self.assertIn("workflow line\n", stderr.getvalue())
        self.assertIn("progress 50%\n", stderr.getvalue())
        self.assertTrue(stdout.getvalue().endswith("media> typing"))

    def test_interactive_prompt_console_overwrites_worker_progress_above_prompt(self) -> None:
        fake_readline = FakeReadline()
        fake_readline.line_buffer = "typing"
        stdout = FakeTTY()
        stderr = FakeTTY()

        with mock.patch.object(dd, "readline", fake_readline), mock.patch.object(
            sys.stdin,
            "isatty",
            return_value=True,
        ), mock.patch.object(sys, "stdout", stdout), mock.patch.object(sys, "stderr", stderr):
            console = dd.InteractivePromptConsole()
            console.install()
            console.input_started()
            print("media> ", end="", flush=True)

            def background_progress() -> None:
                sys.stderr.write_progress("transcribe_progress: 7%")
                sys.stderr.write_progress("transcribe_progress: 15%")
                sys.stderr.finish_progress()

            worker = threading.Thread(target=background_progress)
            worker.start()
            worker.join()
            console.input_finished()
            console.restore()

        self.assertIn("transcribe_progress: 7%\n", stderr.getvalue())
        self.assertIn("\033[1A\r\033[2Ktranscribe_progress: 15%\n", stderr.getvalue())
        self.assertTrue(stdout.getvalue().endswith("media> typing"))

    def test_interactive_task_queue_runs_in_order_and_snapshots_settings(self) -> None:
        args = dd.parse_args(["--interactive"])
        calls: list[tuple[str, bool, str | None]] = []

        def handler(current_args: argparse.Namespace, share_text: str, cookie: str | None) -> int:
            calls.append((share_text, current_args.transcribe, cookie))
            return 0

        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            task_queue = dd.InteractiveTaskQueue(handler=handler)
            task_queue.enqueue(args, "https://v.douyin.com/first/", "session=one")
            args.transcribe = True
            task_queue.enqueue(args, "https://v.douyin.com/second/", "session=two")
            task_queue.shutdown(wait=True)

        self.assertEqual(
            calls,
            [
                ("https://v.douyin.com/first/", False, "session=one"),
                ("https://v.douyin.com/second/", True, "session=two"),
            ],
        )
        self.assertEqual([task.status for task in task_queue.snapshot()], ["completed", "completed"])

    def test_interactive_task_queue_runs_x_folder_with_snapshotted_settings(self) -> None:
        args = dd.parse_args(["--interactive", "--x-force", "--x-crf", "21"])
        calls: list[tuple[str, int, bool]] = []

        def x_folder_handler(current_args: argparse.Namespace) -> int:
            calls.append((current_args.x_folder, current_args.x_crf, current_args.x_force))
            return 0

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            task_queue = dd.InteractiveTaskQueue(x_folder_handler=x_folder_handler)
            task_queue.enqueue_x_folder(args, tmpdir)
            args.x_crf = 18
            args.x_force = False
            task_queue.shutdown(wait=True)

        self.assertEqual(calls, [(tmpdir, 21, True)])
        task = task_queue.snapshot()[0]
        self.assertEqual(task.kind, "x_folder")
        self.assertEqual(task.platform, "x")
        self.assertEqual(task.status, "completed")

    def test_interactive_task_queue_runs_x_file_with_snapshotted_settings(self) -> None:
        args = dd.parse_args(["--interactive", "--x-force", "--x-crf", "21"])
        calls: list[tuple[str, int, bool]] = []

        def x_file_handler(current_args: argparse.Namespace) -> int:
            calls.append((current_args.x_file, current_args.x_crf, current_args.x_force))
            return 0

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ), mock.patch("sys.stderr", new_callable=io.StringIO):
            video_path = Path(tmpdir) / "input video.mp4"
            video_path.write_bytes(b"video")
            task_queue = dd.InteractiveTaskQueue(x_file_handler=x_file_handler)
            task_queue.enqueue_x_file(args, str(video_path))
            args.x_crf = 18
            task_queue.shutdown(wait=True)

        self.assertEqual(calls, [(str(video_path), 21, False)])
        task = task_queue.snapshot()[0]
        self.assertEqual(task.kind, "x_file")
        self.assertEqual(task.platform, "x")
        self.assertEqual(task.status, "completed")

    def test_process_x_file_skips_an_already_compatible_video(self) -> None:
        args = dd.parse_args(["--interactive", "--x-force"])
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "already-compatible.mp4"
            video_path.write_bytes(b"video")
            args.x_file = video_path.name
            with mock.patch.object(
                dd,
                "SCRIPT_DIRECTORY",
                Path(tmpdir),
            ), mock.patch(
                "media_downloader.make_x_compatible_if_needed",
                side_effect=lambda path, _args: path,
            ) as make_compatible, mock.patch(
                "sys.stdout",
                new_callable=io.StringIO,
            ) as stdout:
                self.assertEqual(dd.process_x_file(args), 0)

        called_args = make_compatible.call_args.args[1]
        self.assertEqual(make_compatible.call_args.args[0], video_path)
        self.assertFalse(called_args.x_force)
        self.assertIn("x_file_skipped: already_compatible", stdout.getvalue())

    def test_process_x_file_finds_bare_filename_in_output_directory(self) -> None:
        args = dd.parse_args(["--interactive"])
        with tempfile.TemporaryDirectory() as tmpdir:
            script_directory = Path(tmpdir)
            video_path = script_directory / "downloads" / "downloaded.mp4"
            video_path.parent.mkdir()
            video_path.write_bytes(b"video")
            args.x_file = video_path.name
            with mock.patch.object(
                dd,
                "SCRIPT_DIRECTORY",
                script_directory,
            ), mock.patch(
                "media_downloader.make_x_compatible_if_needed",
                side_effect=lambda path, _args: path,
            ) as make_compatible, mock.patch(
                "sys.stdout",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.process_x_file(args), 0)

        self.assertEqual(make_compatible.call_args.args[0], video_path)

    def test_interactive_profile_all_modifier_applies_only_to_that_task(self) -> None:
        args = dd.parse_args(["--interactive"])
        profile_url = "https://www.douyin.com/user/profile-sec-uid"
        calls: list[tuple[str, int | str]] = []

        def handler(current_args: argparse.Namespace, share_text: str, _cookie: str | None) -> int:
            calls.append((share_text, current_args.profile_limit))
            return 0

        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            task_queue = dd.InteractiveTaskQueue(handler=handler)
            task_queue.enqueue(args, f"{profile_url} all", None)
            task_queue.enqueue(args, profile_url, None)
            task_queue.shutdown(wait=True)

        self.assertEqual(calls, [(profile_url, "all"), (profile_url, 100)])
        self.assertEqual(args.profile_limit, 100)

    def test_interactive_xiaohongshu_profile_all_modifier(self) -> None:
        args = dd.parse_args(["--interactive"])
        profile_url = "https://www.xiaohongshu.com/user/profile/5e1d98150000000001007051"
        calls: list[tuple[str, int | str]] = []

        def handler(current_args: argparse.Namespace, share_text: str, _cookie: str | None) -> int:
            calls.append((share_text, current_args.profile_limit))
            return 0

        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            task_queue = dd.InteractiveTaskQueue(handler=handler)
            task_queue.enqueue(args, f"{profile_url} all", None)
            task_queue.shutdown(wait=True)

        self.assertEqual(calls, [(profile_url, "all")])
        self.assertEqual(args.profile_limit, 100)

    def test_interactive_task_queue_continues_after_failure(self) -> None:
        args = dd.parse_args(["--interactive"])
        calls: list[str] = []

        def handler(_args: argparse.Namespace, share_text: str, _cookie: str | None) -> int:
            calls.append(share_text)
            if share_text == "first":
                raise dd.DouyinDownloadError("broken task")
            return 0

        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            task_queue = dd.InteractiveTaskQueue(handler=handler)
            task_queue.enqueue(args, "first", None)
            task_queue.enqueue(args, "second", None)
            task_queue.shutdown(wait=True)

        self.assertEqual(calls, ["first", "second"])
        tasks = task_queue.snapshot()
        self.assertEqual([task.status for task in tasks], ["failed", "completed"])
        self.assertEqual(tasks[0].error, "broken task")

    def test_interactive_task_queue_cancels_current_and_waiting_then_accepts_new_task(self) -> None:
        args = dd.parse_args(["--interactive"])
        started = threading.Event()

        def handler(_args: argparse.Namespace, share_text: str, _cookie: str | None) -> int:
            if share_text != "first":
                return 0
            token = dd.current_cancellation_token()
            self.assertIsNotNone(token)
            started.set()
            assert token is not None
            token.wait(1)
            token.raise_if_cancelled()
            return 0

        with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            task_queue = dd.InteractiveTaskQueue(handler=handler)
            task_queue.enqueue(args, "first", None)
            task_queue.enqueue(args, "second", None)
            self.assertTrue(started.wait(1))
            running_id, queued_ids = task_queue.cancel_all()
            task_queue.enqueue(args, "third", None)
            task_queue.shutdown(wait=True)

        self.assertEqual(running_id, 1)
        self.assertEqual(queued_ids, [2])
        self.assertEqual(
            [task.status for task in task_queue.snapshot()],
            ["cancelled", "cancelled", "completed"],
        )

    def test_cancelled_video_download_removes_partial_file(self) -> None:
        token = dd.CancellationToken()

        class CancelAfterFirstChunk:
            headers = {"content-type": "video/mp4"}

            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _size: int) -> bytes:
                token.cancel()
                return b"partial video data"

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch(
            "media_downloader.urllib.request.urlopen",
            return_value=CancelAfterFirstChunk(),
        ):
            output_path = Path(tmpdir) / "video.mp4"
            dd._TASK_CONTEXT.cancel_token = token
            try:
                with self.assertRaises(dd.OperationCancelled):
                    dd.download_candidate(
                        dd.Candidate("https://example.com/video.mp4", "test", 1),
                        output_path,
                    )
            finally:
                del dd._TASK_CONTEXT.cancel_token

            self.assertFalse(output_path.with_suffix(".mp4.part").exists())
            self.assertFalse(output_path.exists())

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

    def test_interactive_loop_accepts_another_task_while_worker_is_busy(self) -> None:
        args = dd.parse_args(["--interactive"])
        first_started = threading.Event()
        first_finished = threading.Event()
        release_first = threading.Event()
        responses = iter(["first task", "second task", ":quit"])
        accepted_while_busy: list[bool] = []
        calls: list[str] = []

        def fake_input(_prompt: str) -> str:
            response = next(responses)
            if response == "second task":
                first_started.wait(timeout=1)
                accepted_while_busy.append(not first_finished.is_set())
            elif response == ":quit":
                release_first.set()
            return response

        def fake_handle_share_text(
            _args: argparse.Namespace,
            share_text: str,
            _cookie: str | None,
        ) -> int:
            calls.append(share_text)
            if share_text == "first task":
                first_started.set()
                release_first.wait(timeout=2)
                first_finished.set()
            return 0

        with mock.patch("builtins.input", side_effect=fake_input), mock.patch(
            "media_downloader.handle_share_text",
            side_effect=fake_handle_share_text,
        ), mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            self.assertEqual(dd.interactive_loop(args, None), 0)

        self.assertEqual(accepted_while_busy, [True])
        self.assertEqual(calls, ["first task", "second task"])

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
        self.assertIn(":queue ", dd.interactive_completion_candidates(":qu", 1, 3))
        self.assertIn(":x-file ", dd.interactive_completion_candidates(":x-f", 1, 4))
        self.assertIn("whisper-model ", dd.interactive_completion_candidates(":set whi", 5, 8))
        self.assertIn("funasr-model ", dd.interactive_completion_candidates(":set fun", 5, 8))
        self.assertIn("funasr-rich-text ", dd.interactive_completion_candidates(":set fun", 5, 8))
        self.assertIn("ocr-images ", dd.interactive_completion_candidates(":set ocr", 5, 8))
        self.assertIn("ocr-preprocess ", dd.interactive_completion_candidates(":set ocr", 5, 8))
        self.assertIn("douyin ", dd.interactive_completion_candidates(":set platform d", 14, 15))
        self.assertIn("youtube ", dd.interactive_completion_candidates(":set platform y", 14, 15))
        self.assertIn("youtube-format ", dd.interactive_completion_candidates(":set you", 5, 8))
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
        self.assertTrue(transcribe_audio.call_args.kwargs["simplify_chinese"])
        output = stdout.getvalue()
        self.assertIn(f"audio: {audio_path}", output)
        self.assertIn(f"transcript: {transcript_path}", output)

    def test_handle_share_text_retries_browser_candidate_when_download_has_no_audio(self) -> None:
        args = dd.parse_args(["--extract-audio", "https://v.douyin.com/abc123/"])
        video_only = dd.Candidate("https://example.com/video-only.mp4", "direct", 1)
        muxed = dd.Candidate("https://example.com/muxed.mp4", "douyin.browser-netlog", 2)
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            with mock.patch(
                "media_downloader.gather_candidates_for_request",
                return_value=("douyin", "7441234567890123456", [video_only], [], []),
            ), mock.patch(
                "media_downloader.gather_browser_candidates",
                return_value=("7441234567890123456", [muxed], [], ["browser retry"]),
            ) as gather_browser, mock.patch(
                "media_downloader.download_candidate",
                return_value=saved_path,
            ) as download, mock.patch(
                "media_downloader.video_transcriber.probe_audio_stream",
                side_effect=[False, True, True],
            ), mock.patch(
                "media_downloader.handle_downloaded_video",
            ) as handle_video, mock.patch(
                "sys.stdout",
                new_callable=io.StringIO,
            ), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertEqual(
            [call.args[0] for call in download.call_args_list],
            [video_only, muxed],
        )
        gather_browser.assert_called_once()
        handle_video.assert_called_once_with(saved_path, args)
        self.assertIn("audio_candidate_retry", stderr.getvalue())

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
        self.assertTrue(transcribe.call_args.kwargs["simplify_chinese"])

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
        self.assertTrue(ocr_images.call_args.kwargs["print_progress"])
        self.assertEqual(
            ocr_images.call_args.kwargs["min_line_confidence"],
            dd.image_ocr.DEFAULT_MIN_LINE_CONFIDENCE,
        )
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

    def test_gather_youtube_candidates(self) -> None:
        item_id, candidates, image_candidates, logs = dd.gather_youtube_candidates("https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(item_id, "dQw4w9WgXcQ")
        self.assertEqual(candidates[0].url, "https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(candidates[0].source, "youtube.yt-dlp")
        self.assertEqual(image_candidates, [])
        self.assertIn("youtube: using yt-dlp", logs[0])

    def test_build_youtube_download_command(self) -> None:
        command = dd.build_youtube_command(
            "/bin/yt-dlp",
            "https://youtu.be/dQw4w9WgXcQ",
            output_template=Path("downloads/video.%(ext)s"),
            format_selector="best",
            cookie="SID=abc",
            timeout=12,
            overwrite=True,
        )
        self.assertIn("--no-playlist", command)
        self.assertIn("--merge-output-format", command)
        self.assertIn("after_move:filepath", command)
        self.assertIn("--force-overwrites", command)
        self.assertIn("Cookie: SID=abc", command)

    def test_build_youtube_print_url_command(self) -> None:
        command = dd.build_youtube_command(
            "/bin/yt-dlp",
            "https://youtu.be/dQw4w9WgXcQ",
            format_selector="best",
            print_url=True,
        )
        self.assertIn("--get-url", command)
        self.assertNotIn("-o", command)

    def test_youtube_output_template_avoids_existing_stem_with_any_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "clip.webm").write_text("existing", encoding="utf-8")

            self.assertEqual(
                dd.youtube_output_template(output_dir, "clip.mp4"),
                output_dir / "clip.1.%(ext)s",
            )

    def test_download_youtube_video_uses_ytdlp(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "clip.mp4"
            saved_path.write_bytes(b"video")
            completed = dd.subprocess.CompletedProcess(
                ["/bin/yt-dlp"],
                0,
                f"{saved_path}\n",
                "",
            )
            candidate = dd.Candidate("https://youtu.be/dQw4w9WgXcQ", "youtube.yt-dlp", 1)
            with mock.patch("media_downloader.find_yt_dlp_binary", return_value="/bin/yt-dlp"), mock.patch(
                "media_downloader.subprocess.run",
                return_value=completed,
            ) as run:
                result = dd.download_youtube_video(
                    candidate,
                    Path(tmpdir),
                    output_name="clip.mp4",
                    format_selector="best",
                    cookie="SID=abc",
                    timeout=9,
                    overwrite=True,
                )

        self.assertEqual(result, saved_path)
        command = run.call_args.args[0]
        self.assertIn("/bin/yt-dlp", command[0])
        self.assertIn("best", command)
        self.assertIn("Cookie: SID=abc", command)

    def test_print_youtube_media_urls_uses_ytdlp(self) -> None:
        completed = dd.subprocess.CompletedProcess(
            ["/bin/yt-dlp"],
            0,
            "https://video.example/stream\nhttps://audio.example/stream\n",
            "",
        )
        candidate = dd.Candidate("https://youtu.be/dQw4w9WgXcQ", "youtube.yt-dlp", 1)
        with mock.patch("media_downloader.find_yt_dlp_binary", return_value="/bin/yt-dlp"), mock.patch(
            "media_downloader.subprocess.run",
            return_value=completed,
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            dd.print_youtube_media_urls(candidate, format_selector="best")

        self.assertIn("https://video.example/stream", stdout.getvalue())
        self.assertIn("https://audio.example/stream", stdout.getvalue())

    def test_handle_share_text_downloads_youtube_with_ytdlp(self) -> None:
        args = dd.parse_args(["--platform", "youtube", "https://youtu.be/dQw4w9WgXcQ"])
        with tempfile.TemporaryDirectory() as tmpdir:
            saved_path = Path(tmpdir) / "video.mp4"
            with mock.patch(
                "media_downloader.download_youtube_video",
                return_value=saved_path,
            ) as download_youtube, mock.patch(
                "media_downloader.handle_downloaded_video",
            ) as handle_video:
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr",
                    new_callable=io.StringIO,
                ) as stderr:
                    self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        self.assertEqual(download_youtube.call_args.args[0].url, "https://youtu.be/dQw4w9WgXcQ")
        handle_video.assert_called_once_with(saved_path, args)
        self.assertIn("platform=youtube", stderr.getvalue())

    def test_handle_share_text_prints_youtube_media_urls(self) -> None:
        args = dd.parse_args(["--print-url", "https://youtu.be/dQw4w9WgXcQ"])
        with mock.patch("media_downloader.print_youtube_media_urls") as print_urls:
            with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ):
                self.assertEqual(dd.handle_share_text(args, args.share, None), 0)

        print_urls.assert_called_once()

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
        self.assertFalse(
            dd.looks_like_douyin_browser_video_url(
                "https://v11-web.douyinvod.com/video/tos/cn/item/media-audio-und-mp4a/"
                "?bt=44&mime_type=video_mp4"
            )
        )
        self.assertTrue(
            dd.looks_like_video_only_stream_url(
                "https://v11-web.douyinvod.com/video/tos/cn/item/media-video-avc1/"
                "?bt=282&mime_type=video_mp4"
            )
        )
        self.assertFalse(
            dd.looks_like_video_only_stream_url(
                "https://v11-web.douyinvod.com/video/tos/cn/item/?bt=718&mime_type=video_mp4"
            )
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

    def test_douyin_feed_netlog_only_keeps_requested_item(self) -> None:
        item_id = "7664255574183430521"
        unrelated = (
            "https://v11-web.douyinvod.com/video/tos/cn/unrelated/media-video-avc1/"
            "?bt=1696&mime_type=video_mp4"
        )
        requested = (
            "https://v11-web.douyinvod.com/video/tos/cn/requested/"
            f"?bt=338&mime_type=video_mp4&__vid={item_id}"
        )
        payload = {"events": [{"params": {"url": unrelated}}, {"params": {"url": requested}}]}

        candidates = dd.extract_browser_candidates_from_netlog_payload(
            payload,
            "douyin",
            item_id=item_id,
            require_item_match=True,
        )

        self.assertEqual([candidate.url for candidate in candidates], [requested])

    def test_douyin_item_matched_netlog_still_prefers_higher_bitrate(self) -> None:
        item_id = "7658893225607908651"
        low = (
            "https://v26-web.douyinvod.com/video/tos/cn/requested/"
            f"?bt=576&mime_type=video_mp4&__vid={item_id}"
        )
        high = (
            "https://v26-web.douyinvod.com/video/tos/cn/requested/"
            f"?bt=1318&mime_type=video_mp4&__vid={item_id}"
        )
        payload = {"events": [{"params": {"url": low}}, {"params": {"url": high}}]}

        candidates = dd.extract_browser_candidates_from_netlog_payload(
            payload,
            "douyin",
            item_id=item_id,
            require_item_match=True,
        )

        self.assertEqual([candidate.url for candidate in candidates], [high, low])

    def test_douyin_browser_uses_incomplete_netlog_after_chrome_timeout(self) -> None:
        item_id = "7658893225607908651"
        page_url = f"https://www.douyin.com/video/{item_id}"
        video_url = (
            "https://v26-web.douyinvod.com/video/tos/cn/requested/"
            "?bt=1318&mime_type=video_mp4"
        )

        def fake_browser_run(command, **_kwargs):
            netlog_arg = next(arg for arg in command if arg.startswith("--log-net-log="))
            netlog_path = Path(netlog_arg.split("=", 1)[1])
            netlog_path.write_text(
                f'{{"events":[{{"params":{{"url":"{video_url}"}}}},\n',
                encoding="utf-8",
            )
            raise dd.subprocess.TimeoutExpired(command, 1, output="", stderr="")

        resolved = dd.FetchResult(page_url, 200, b"<html></html>", {"content-type": "text/html"})
        with mock.patch("media_downloader.http_get", return_value=resolved):
            with mock.patch("media_downloader.find_chrome_executable", return_value="/chrome"):
                with mock.patch("media_downloader.run_task_subprocess", side_effect=fake_browser_run):
                    parsed_item_id, candidates, images, logs = dd.gather_browser_candidates(
                        page_url,
                        platform="douyin",
                        timeout=1,
                    )

        self.assertEqual(parsed_item_id, item_id)
        self.assertEqual([candidate.url for candidate in candidates], [video_url])
        self.assertEqual(images, [])
        self.assertTrue(any("network log was incomplete" in line for line in logs))

    def test_gather_douyin_profile_posts_reads_paginated_api_payload(self) -> None:
        sec_uid = "profile-sec-uid"
        profile_url = f"https://www.douyin.com/user/{sec_uid}"
        payload = {
            "status_code": 0,
            "has_more": 0,
            "aweme_list": [
                {
                    "aweme_id": "7658893225607908651",
                    "create_time": 1784616000,
                    "author": {"sec_uid": sec_uid, "nickname": "Miya🦄️"},
                    "video": {
                        "play_addr": {
                            "url_list": [
                                "https://www.douyin.com/aweme/v1/play/?video_id=target"
                            ]
                        }
                    },
                }
            ],
        }

        class FakeProcess:
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

        class FakeDevTools:
            def __init__(self):
                self.next_id = 0
                self.sent: list[tuple[int, str]] = []
                self.stage = 0

            def send(self, method, params=None):
                self.next_id += 1
                self.sent.append((self.next_id, method))
                return self.next_id

            def recv(self, *, timeout):
                self.stage += 1
                if self.stage == 1:
                    return {
                        "method": "Network.responseReceived",
                        "params": {
                            "requestId": "request-1",
                            "response": {
                                "url": "https://www.douyin.com/aweme/v1/web/aweme/post/?max_cursor=0"
                            },
                        },
                    }
                if self.stage == 2:
                    return {
                        "method": "Network.loadingFinished",
                        "params": {"requestId": "request-1"},
                    }
                if self.stage == 3:
                    body_id = next(command_id for command_id, method in self.sent if method == "Network.getResponseBody")
                    return {"id": body_id, "result": {"body": dd.json.dumps(payload)}}
                state_id = [command_id for command_id, method in self.sent if method == "Runtime.evaluate"][-1]
                return {
                    "id": state_id,
                    "result": {"result": {"value": {"title": "Miya🦄️的抖音 - 抖音"}}},
                }

            def close(self):
                return None

        fake_process = FakeProcess()
        fake_devtools = FakeDevTools()
        progress_messages: list[str] = []
        with mock.patch("media_downloader.find_chrome_executable", return_value="/chrome"):
            with mock.patch("media_downloader.subprocess.Popen", return_value=fake_process):
                with mock.patch("media_downloader.wait_for_devtools_page_url", return_value="ws://local/page"):
                    with mock.patch("media_downloader.DevToolsConnection", return_value=fake_devtools):
                        with mock.patch("media_downloader.terminate_process"):
                            result = dd.gather_douyin_profile_posts(
                                profile_url,
                                sec_uid,
                                limit="all",
                                interval=0,
                                timeout=5,
                                progress=progress_messages.append,
                                use_system_browser_cookies=False,
                            )

        self.assertEqual(result.username, "Miya🦄️")
        self.assertEqual([post.item_id for post in result.posts], ["7658893225607908651"])
        self.assertEqual(result.posts[0].create_time, 1784616000)
        self.assertTrue(any("opening" in message for message in progress_messages))
        self.assertTrue(any("processing post response 1" in message for message in progress_messages))
        self.assertTrue(any("collected 1 post(s)" in message for message in progress_messages))
        self.assertTrue(any("collection finished" in message for message in progress_messages))

    def test_profile_download_uses_username_folder_and_sequential_names(self) -> None:
        profile_url = "https://www.douyin.com/user/profile-sec-uid"
        posts = [
            dd.DouyinProfilePost("7658893225607908651", 20, {}),
            dd.DouyinProfilePost("7658893225607908650", 10, {}),
        ]
        result = dd.DouyinProfileResult("profile-sec-uid", "Miya/测试", posts, [])
        candidate = dd.Candidate(
            "https://www.douyin.com/aweme/v1/play/?video_id=target",
            "douyin.profile.play_addr",
            1,
        )
        image_candidate = dd.ImageCandidate(
            "https://p3-pc-sign.douyinpic.com/profile-image.webp",
            "douyin.profile-image",
            1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            args = dd.parse_args(
                [
                    "--output-dir",
                    tmpdir,
                    "--profile-limit",
                    "2",
                    "--profile-interval",
                    "1.25",
                    profile_url,
                ]
            )
            calls: list[tuple[str, str, str]] = []

            def fake_handle_resolved(
                item_args,
                _share_text,
                _cookie,
                _platform,
                item_id,
                video_candidates,
                image_candidates,
                _logs,
            ):
                media_folder = "videos" if video_candidates else "images"
                calls.append((item_id, item_args.output_name, media_folder))
                output_dir = Path(item_args.output_dir)
                self.assertEqual(output_dir, Path(tmpdir) / "Miya_测试" / media_folder)
                output_dir.mkdir(parents=True, exist_ok=True)
                if image_candidates:
                    output_file = output_dir / f"{Path(item_args.output_name).stem}_01.webp"
                    (output_dir / f"{Path(item_args.output_name).stem}_ocr.txt").write_text(
                        "OCR text is not part of the download manifest.",
                        encoding="utf-8",
                    )
                else:
                    output_file = output_dir / item_args.output_name
                output_file.write_bytes(b"downloaded")
                return 0

            def fake_profile_candidates(post):
                if post.item_id == "7658893225607908651":
                    return [candidate], []
                return [], [image_candidate]

            with mock.patch("media_downloader.gather_douyin_profile_posts", return_value=result):
                with mock.patch("media_downloader.profile_post_media_candidates", side_effect=fake_profile_candidates):
                    with mock.patch("media_downloader.handle_resolved_media", side_effect=fake_handle_resolved):
                        with mock.patch("media_downloader.wait_for_profile_interval") as wait_mock:
                            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                                self.assertEqual(dd.handle_share_text(args, profile_url, None), 0)
                                self.assertEqual(dd.handle_share_text(args, profile_url, None), 0)

            profile_dir = Path(tmpdir) / "Miya_测试"
            self.assertTrue(profile_dir.is_dir())
            first_name = f"Miya_测试_{dd.profile_publish_time(20, posts[0].item_id)}.mp4"
            second_name = f"Miya_测试_{dd.profile_publish_time(10, posts[1].item_id)}.mp4"
            self.assertEqual(
                calls,
                [
                    ("7658893225607908651", first_name, "videos"),
                    ("7658893225607908650", second_name, "images"),
                ],
            )
            wait_mock.assert_called_once_with(1.25)
            manifest_path = profile_dir / "profile_downloads.json"
            self.assertTrue(manifest_path.is_file())
            manifest = dd.json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest["downloaded"]),
                {"7658893225607908651", "7658893225607908650"},
            )
            self.assertEqual(
                manifest["downloaded"]["7658893225607908651"]["files"],
                [f"videos/{first_name}"],
            )
            self.assertEqual(
                manifest["downloaded"]["7658893225607908650"]["files"],
                [f"images/{Path(second_name).stem}_01.webp"],
            )
            self.assertEqual(
                manifest["downloaded"]["7658893225607908651"]["published_at"],
                dd.profile_publish_time(20, posts[0].item_id),
            )
            progress_output = stderr.getvalue()
            self.assertIn("profile_manifest:", progress_output)
            self.assertIn("profile_item_media:", progress_output)
            self.assertIn("profile_item_completed:", progress_output)
            self.assertIn("profile_item_skipped:", progress_output)
            self.assertIn("profile_completed:", progress_output)

    def test_xiaohongshu_profile_download_classifies_media_and_updates_manifest(self) -> None:
        profile_url = "https://www.xiaohongshu.com/user/profile/5e1d98150000000001007051"
        posts = [
            dd.XiaohongshuProfilePost("6a2ead47000000001c025f7d", 20, "token-a", "video"),
            dd.XiaohongshuProfilePost("68e45f4b000000000300f33d", 10, "token-b", "normal"),
        ]
        result = dd.XiaohongshuProfileResult(
            "5e1d98150000000001007051",
            "Miya/测试",
            posts,
            [],
        )
        video_candidate = dd.Candidate(
            "https://sns-video-hw.xhscdn.com/stream/video.mp4",
            "xiaohongshu.test-video",
            1,
        )
        image_candidate = dd.ImageCandidate(
            "https://sns-webpic-qc.xhscdn.com/default-image",
            "xiaohongshu.test-image",
            1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            args = dd.parse_args(
                [
                    "--output-dir",
                    tmpdir,
                    "--profile-limit",
                    "2",
                    "--profile-interval",
                    "1.25",
                    profile_url,
                ]
            )
            calls: list[tuple[str, str, str]] = []

            def fake_gather(_item_args, item_url, _cookie):
                if posts[0].item_id in item_url:
                    return "xiaohongshu", posts[0].item_id, [video_candidate], [], []
                return "xiaohongshu", posts[1].item_id, [], [image_candidate], []

            def fake_handle_resolved(
                item_args,
                _share_text,
                _cookie,
                platform,
                item_id,
                video_candidates,
                image_candidates,
                _logs,
            ):
                self.assertEqual(platform, "xiaohongshu")
                media_folder = "videos" if video_candidates else "images"
                calls.append((item_id, item_args.output_name, media_folder))
                output_dir = Path(item_args.output_dir)
                self.assertEqual(output_dir, Path(tmpdir) / "Miya_测试" / media_folder)
                output_dir.mkdir(parents=True, exist_ok=True)
                if image_candidates:
                    output_file = output_dir / f"{Path(item_args.output_name).stem}_01.webp"
                    (output_dir / f"{Path(item_args.output_name).stem}_ocr.txt").write_text(
                        "excluded from manifest",
                        encoding="utf-8",
                    )
                else:
                    output_file = output_dir / item_args.output_name
                output_file.write_bytes(b"downloaded")
                return 0

            with mock.patch(
                "media_downloader.gather_xiaohongshu_profile_posts",
                return_value=result,
            ), mock.patch(
                "media_downloader.gather_candidates_for_request_with_retries",
                side_effect=fake_gather,
            ) as gather, mock.patch(
                "media_downloader.handle_resolved_media",
                side_effect=fake_handle_resolved,
            ), mock.patch(
                "media_downloader.wait_for_profile_interval"
            ) as wait_mock, mock.patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ) as stderr:
                self.assertEqual(dd.handle_share_text(args, profile_url, None), 0)
                self.assertEqual(dd.handle_share_text(args, profile_url, None), 0)

            self.assertEqual(gather.call_count, 2)
            wait_mock.assert_called_once_with(1.25)
            manifest_path = Path(tmpdir) / "Miya_测试" / dd.PROFILE_MANIFEST_FILENAME
            manifest = dd.json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["platform"], "xiaohongshu")
            self.assertEqual(manifest["user_id"], "5e1d98150000000001007051")
            self.assertEqual(set(manifest["downloaded"]), {post.item_id for post in posts})
            self.assertEqual(manifest["downloaded"][posts[0].item_id]["media_type"], "video")
            self.assertEqual(manifest["downloaded"][posts[1].item_id]["media_type"], "images")
            self.assertEqual(
                manifest["downloaded"][posts[1].item_id]["files"],
                [f"images/{Path(calls[1][1]).stem}_01.webp"],
            )
            self.assertIn("profile_detected: platform=xiaohongshu", stderr.getvalue())
            self.assertIn("profile_item_skipped:", stderr.getvalue())

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
