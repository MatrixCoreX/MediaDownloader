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

解析失败时会自动重试 3 次；每次解析都会向 `stderr` 打印 `parse_attempt: 当前次数/总次数`。交互模式和一次性模式一致。

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

启动后粘贴分享文案并回车，下载完成后会继续回到输入提示符。输入 `exit`、`quit` 或 `q` 退出。终端里可以用方向键上/下翻看历史输入，Tab 可以补齐交互命令和参数名；有多个匹配项时，终端会显示候选列表。历史默认保存到 `~/.media_downloader_history`；也可以用环境变量 `MEDIA_DOWNLOADER_HISTORY` 指定历史文件路径。

交互模式里可以用 `:` 或 `/` 开头的命令临时修改后续下载参数。常用命令：

```text
:help
:status
:history
:on transcribe
:off transcribe
:toggle verbose
:set platform douyin
:set output-dir downloads
:set audio-output downloads/input_audio.wav
:set text-output downloads/input_transcript.txt
:clear audio-output
:quit
```

布尔参数也支持快捷写法，例如 `:transcribe on`、`:extract-audio off`、`:x-compatible toggle`。路径、平台、超时、whisper 模型等参数支持 `:set 参数名 值`；输入 `:status` 可以查看当前配置。

`:extract-audio off` 只关闭“单独拆 WAV”功能，不会自动关闭转文字；如果 `:transcribe on` 仍然开启，下载后仍会生成或复用中间 WAV 并继续转文字。要停止转文字，需要执行 `:transcribe off`。`:clear audio-output` 只是清除自定义音频路径，恢复默认 `_audio.wav` 路径。

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

## 本机语音转文字

`video_transcriber.py` 会先用 `ffmpeg` 从视频里拆出单独的 16 kHz 单声道 WAV 音频，再调用本机 ASR 引擎生成文字稿。默认引擎是已有的 `whisper.cpp`；也可以切到 FunASR。

主下载器默认只下载视频。只有显式加参数时，才会在同一次运行里下载视频后继续拆音频或转文字。

如果解析到的是图文作品，`--extract-audio` 和 `--transcribe` 会被忽略，仍只保存图片。

下载视频后同时拆音频：

```bash
python3 media_downloader.py --extract-audio "https://v.douyin.com/xxxx/"
```

下载视频后同时拆音频并转文字：

```bash
python3 media_downloader.py --transcribe "https://v.douyin.com/xxxx/"
```

转文字时默认会打印 whisper.cpp 的进度。默认线程数会按本机 CPU 自动选择，并最多使用 8 个线程；也可以手动指定：

```bash
python3 media_downloader.py --transcribe --whisper-threads 8 "https://v.douyin.com/xxxx/"
```

如果不想打印转写进度：

```bash
python3 media_downloader.py --transcribe --whisper-no-progress "https://v.douyin.com/xxxx/"
```

如果更看重速度，可以开启快速解码模式。它会让 whisper.cpp 使用更轻的解码参数，可能略微降低识别稳健性：

```bash
python3 media_downloader.py --transcribe --whisper-fast "https://v.douyin.com/xxxx/"
```

如果要使用 FunASR，本机当前是 CPU 环境，默认配置为 `iic/SenseVoiceSmall`、`cpu`、`fsmn-vad`。系统 Python 是受管环境，建议先建虚拟环境安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install funasr modelscope torch torchaudio
```

安装后可以选择 FunASR 转写：

```bash
python media_downloader.py \
  --transcribe \
  --transcribe-engine funasr \
  --funasr-model iic/SenseVoiceSmall \
  --funasr-device cpu \
  "https://v.douyin.com/xxxx/"
```

FunASR 使用 SenseVoice 时默认输出纯文字，会过滤情绪和声音事件 emoji。如果想保留这些富文本标记，例如背景音乐、笑声、情绪判断，可以加：

```bash
python media_downloader.py --transcribe --transcribe-engine funasr --funasr-rich-text "https://v.douyin.com/xxxx/"
```

音频和文字输出路径使用独立参数：

```bash
python3 media_downloader.py \
  --transcribe \
  --audio-output downloads/input_audio.wav \
  --text-output downloads/input_transcript.txt \
  "https://v.douyin.com/xxxx/"
```

默认输出路径会基于下载后的视频文件名生成：

```text
downloads/20260624_153012.mp4
downloads/20260624_153012_audio.wav
downloads/20260624_153012_transcript.txt
```

交互模式同样需要显式加参数：

```bash
python3 media_downloader.py --interactive --transcribe
```

如果已经进入交互模式，也可以先输入 `:transcribe on` 再粘贴链接；只开 `:extract-audio` 会只生成 WAV，不会生成文字稿。反过来，关闭 `:extract-audio` 不会关闭转写；只要 `:transcribe on` 还开着，程序仍会为了转文字生成或复用中间 WAV。

交互模式中可以临时调节转写参数：

```text
:transcribe-engine funasr
:funasr-model iic/SenseVoiceSmall
:funasr-device cpu
:funasr-rich-text on
:whisper-progress off
:whisper-threads 8
:whisper-fast on
:whisper-no-gpu on
```

如果需要指定 whisper.cpp 路径或模型：

```bash
python3 media_downloader.py \
  --transcribe \
  --whisper-bin ~/rustclaw/data/vendor/whisper.cpp/build/bin/whisper-cli \
  --whisper-model ~/rustclaw/data/models/whisper.cpp/ggml-small.bin \
  "https://v.douyin.com/xxxx/"
```

也可以单独处理本地已有视频。

转写最新下载的视频：

```bash
python3 video_transcriber.py
```

转写指定视频：

```bash
python3 video_transcriber.py downloads/input.mp4
```

如果已经有 `downloads/input_audio.wav`，也可以直接转这个 WAV：

```bash
python3 video_transcriber.py downloads/input_audio.wav
```

单独转写本地文件时同样默认打印进度，并自动选择线程数。可以用 `--threads` 调速，用 `--no-progress` 关闭进度输出；需要进一步提速时可以加 `--fast`。

```bash
python3 video_transcriber.py --threads 8 downloads/input.mp4
python3 video_transcriber.py --fast downloads/input.mp4
python3 video_transcriber.py --no-progress downloads/input.mp4
```

单独处理本地文件时也可以选择 FunASR：

```bash
python video_transcriber.py --engine funasr downloads/input.mp4
```

默认会过滤 SenseVoice 富文本 emoji；需要保留时加 `--funasr-rich-text`。

默认会输出：

```text
downloads/input_audio.wav
downloads/input_transcript.txt
```

只拆音频、不转文字：

```bash
python3 video_transcriber.py --extract-only downloads/input.mp4
```

如果本机 `whisper.cpp` 不在 PATH，脚本会自动尝试使用 `~/rustclaw/data/vendor/whisper.cpp/build/bin/whisper-cli` 和 `~/rustclaw/data/models/whisper.cpp/ggml-small.bin`。也可以手动指定：

```bash
python3 video_transcriber.py \
  --whisper-bin ~/rustclaw/data/vendor/whisper.cpp/build/bin/whisper-cli \
  --model ~/rustclaw/data/models/whisper.cpp/ggml-small.bin \
  downloads/input.mp4
```

## 浏览器 fallback

默认启用本机 Chromium 系浏览器 fallback。支持 Chrome、Chromium、Microsoft Edge、Brave、Vivaldi 等 Chromium 系浏览器。

禁用浏览器 fallback，只使用纯 HTTP 直连解析：

```bash
python3 media_downloader.py --no-browser-fallback "https://v.douyin.com/xxxx/"
```

浏览器 fallback 默认最多等待 30 秒。页面较慢时，可以指定浏览器路径或继续调大浏览器加载时间：

```bash
python3 media_downloader.py --chrome-path /usr/bin/google-chrome --browser-timeout 45 "https://v.douyin.com/xxxx/"
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

`video_transcriber.py` 需要系统安装 `ffmpeg`。默认 `whisper` 引擎需要可用的本机 `whisper.cpp` 可执行文件和 ggml 模型；`funasr` 引擎需要在当前 Python 环境安装 `funasr`、`modelscope`、`torch`、`torchaudio`。

## 说明

这个工具不会破解 DRM、不会绕过私密作品权限、不会处理付费或未授权内容。解析依赖公开视频页面/API 或网页播放器已公开请求的媒体地址；遇到登录限制、风控、验证码、页面结构变化或服务维护时会直接报错，不会绕过限制。
