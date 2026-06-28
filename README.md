# Media Downloader

命令行媒体下载工具：粘贴抖音、快手、小红书或 TikTok 分享文案/链接，自动识别平台和媒体类型，然后下载可访问的原始媒体。

主程序文件名是 `media_downloader.py`。

## 支持能力

- `douyin`: 抖音公开视频、公开图文作品图片。
- `kuaishou`: 快手公开视频。
- `xiaohongshu`: 小红书视频笔记、公开图文作品图片。
- `tiktok`: TikTok 公开视频。

默认平台模式是 `--platform auto`，会根据分享链接自动识别平台。所有平台都只使用直连解析，不调用第三方解析网站。

抖音等页面如果不再把公开视频地址直接写在 HTML/API 里，脚本会默认启动本机 Chromium 系浏览器无头模式，读取本机网络日志中的公开视频请求地址作为 fallback。这仍然不调用第三方解析网站。

## 输出行为

每次解析成功后都会提示媒体类型，交互模式和一次性模式一致：

```text
detected_media: video (platform=douyin, candidates=5)
detected_media: video (platform=kuaishou, candidates=1)
detected_media: video (platform=tiktok, candidates=1)
detected_media: images (platform=xiaohongshu, count=1)
```

媒体类型提示输出到 `stderr`。URL、下载后的文件路径输出到 `stdout`，方便配合管道或脚本处理。

默认输出文件名使用本地时间：

```text
downloads/20260624_153012.mp4
```

图文作品会保存为图片序列：

```text
downloads/20260624_153012_01.webp
downloads/20260624_153012_02.webp
downloads/20260624_153012_03.jpg
```

## 使用

下载一条分享内容：

```bash
python3 media_downloader.py "复制来的分享文案或链接"
```

不带参数在终端里运行，会自动进入交互输入模式：

```bash
python3 media_downloader.py
```

也可以显式进入交互输入模式：

```bash
python3 media_downloader.py --interactive
```

启动后粘贴分享文案并回车，下载完成后会继续回到输入提示符。输入 `exit`、`quit` 或 `q` 退出。

手动指定平台：

```bash
python3 media_downloader.py --platform douyin "抖音分享文案或链接"
python3 media_downloader.py --platform kuaishou "快手分享文案或链接"
python3 media_downloader.py --platform xiaohongshu "小红书分享文案或链接"
python3 media_downloader.py --platform tiktok "TikTok 分享文案或链接"
```

只打印解析出的媒体地址，不下载：

```bash
python3 media_downloader.py --print-url "https://v.douyin.com/xxxx/"
```

如果是图文作品，`--print-url` 会按行打印图片地址。

从文件或管道读取：

```bash
python3 media_downloader.py -i share.txt
cat share.txt | python3 media_downloader.py
```

指定保存目录和文件名：

```bash
python3 media_downloader.py -o videos --output-name my_video.mp4 "https://v.douyin.com/xxxx/"
```

图文作品使用 `--output-name` 时，会取文件名主体作为图片序列前缀。

下载后显示媒体信息：

```bash
python3 media_downloader.py --show-info "https://v.douyin.com/xxxx/"
```

视频会显示分辨率、时长、编码、码率和文件大小。图片会显示文件路径和大小。

## X 兼容转码

默认只下载原文件，不检查、不转码。

需要检查 X 上传兼容性，并在格式不符合时自动生成 H.264/AAC MP4，加 `--x-compatible`：

```bash
python3 media_downloader.py --x-compatible "https://v.douyin.com/xxxx/"
```

交互模式同样需要显式加参数才会转码：

```bash
python3 media_downloader.py --interactive --x-compatible
```

如果视频已经兼容但仍想强制转码：

```bash
python3 media_downloader.py --x-compatible --x-force "https://v.douyin.com/xxxx/"
```

单独转码最新下载的视频：

```bash
python3 x_transcoder.py
```

单独检查或转码指定文件：

```bash
python3 x_transcoder.py --check downloads/input.mp4
python3 x_transcoder.py downloads/input.mp4
```

## 浏览器 fallback

默认启用本机 Chromium 系浏览器 fallback。支持 Chrome、Chromium、Microsoft Edge、Brave、Vivaldi 等 Chromium 系浏览器。

禁用浏览器 fallback，只使用纯 HTTP 直连解析：

```bash
python3 media_downloader.py --no-browser-fallback "https://v.douyin.com/xxxx/"
```

指定浏览器路径或调大浏览器加载时间：

```bash
python3 media_downloader.py --chrome-path /usr/bin/google-chrome --browser-timeout 25 "https://v.douyin.com/xxxx/"
```

如果系统没有可用浏览器，脚本仍会尝试直连解析；需要浏览器 fallback 的页面可能会解析失败，并给出缺少浏览器的提示。

## Cookie

带 cookie 访问需要登录态才能看的公开视频：

```bash
python3 media_downloader.py --cookie cookies.txt "https://v.douyin.com/xxxx/"
```

`--cookie` 可以传原始 Cookie 字符串，也可以传保存 Cookie 的文本文件路径。

浏览器 fallback 当前使用临时浏览器配置，不会自动读取你日常 Chrome 的登录状态。

解析 TikTok 公开页时，脚本会自动把页面响应下发的临时 cookie 延续到同次视频下载请求；这些临时 cookie 不会写入 metadata。

## 依赖

默认解析和下载只需要 Python 3 标准库。

浏览器 fallback 需要系统安装 Chrome、Chromium、Microsoft Edge、Brave、Vivaldi 等 Chromium 系浏览器之一。

`--show-info` 需要系统安装 `ffprobe`。如果没有安装，工具仍会下载，但只能显示基础文件大小。

`--x-compatible` 和 `x_transcoder.py` 需要系统安装 `ffmpeg` 和 `ffprobe`。不加 `--x-compatible` 时，主下载脚本不会执行 X 兼容检查或转码。

## 说明

这个工具不会破解 DRM、不会绕过私密作品权限、不会处理付费或未授权内容。解析依赖公开视频页面/API 或网页播放器已公开请求的媒体地址；遇到登录限制、风控、验证码、页面结构变化或服务维护时会直接报错，不会绕过限制。
