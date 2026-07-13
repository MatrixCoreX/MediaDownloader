# Media Downloader

命令行媒体下载工具：粘贴抖音、快手、小红书、TikTok 或 YouTube 分享文案/链接，自动识别平台和媒体类型，然后下载可访问的原始媒体。

主程序文件名是 `media_downloader.py`。

这个项目的目标是把“复制分享文案 -> 解析公开视频/图片地址 -> 保存文件 -> 可选后处理”做成一条本地命令。非 YouTube 的基础下载路径只依赖 Python 标准库；YouTube、OCR、转码、媒体信息和转文字需要额外安装本机工具、语言包或模型。

## 快速开始

进入项目目录后先确认 Python 版本。脚本使用了较新的 Python 语法，建议使用 Python 3.10 或更新版本：

```bash
python3 --version
python3 media_downloader.py --help
```

下载一条分享内容：

```bash
python3 media_downloader.py "复制来的分享文案或链接"
```

不带参数启动交互模式，适合连续粘贴多条分享：

```bash
python3 media_downloader.py
```

只解析媒体直链、不下载文件：

```bash
python3 media_downloader.py --print-url "https://v.douyin.com/xxxx/"
```

下载后顺便显示媒体信息：

```bash
python3 media_downloader.py --show-info "https://v.douyin.com/xxxx/"
```

下载后顺便转文字：

```bash
python3 media_downloader.py --transcribe "https://v.douyin.com/xxxx/"
```

下载 YouTube 视频需要本机安装 `yt-dlp`：

```bash
python3 media_downloader.py "https://youtu.be/dQw4w9WgXcQ"
```

图文作品下载后默认会识别图片里的文字：

```bash
python3 media_downloader.py "https://www.xiaohongshu.com/discovery/item/xxxx"
```

如果只想本地处理已有视频，可以直接使用 `video_transcriber.py` 或 `x_transcoder.py`，不需要经过下载器。

## 项目文件

| 文件 | 作用 |
| --- | --- |
| `media_downloader.py` | 主入口。负责读取分享内容、识别平台、解析候选媒体地址、下载文件，并可选调用转码或转写。 |
| `image_ocr.py` | 本地图片 OCR 工具。使用系统里的 `tesseract` 命令识别图片文字，可以被主下载器调用，也可以单独处理本地图片。 |
| `video_transcriber.py` | 本地音频拆分与语音转文字工具。可以被主下载器调用，也可以单独处理本地视频/音频文件。 |
| `x_transcoder.py` | X/Twitter 上传兼容性检查与转码工具。可以被主下载器调用，也可以单独处理本地视频。 |
| `install_funasr.sh` | 可选的 FunASR 环境安装脚本，会创建或复用本项目下的 `.venv`。 |
| `tests/` | 单元测试，覆盖链接提取、平台识别、输出路径、交互参数、转写/转码命令构造等行为。 |

## 支持能力

| 平台参数 | 支持媒体 | 常见链接域名 | 说明 |
| --- | --- | --- | --- |
| `douyin` | 抖音公开视频、公开图文作品图片 | `douyin.com`、`iesdouyin.com` | 支持从页面状态、接口数据和浏览器 fallback 中提取候选地址。 |
| `kuaishou` | 快手公开视频 | `kuaishou.com`、`v.kuaishou.com`、`ksurl.cn`、`gifshow.com`、`kwai.com` | 支持公开短视频分享链接。 |
| `xiaohongshu` | 小红书视频笔记、公开图文作品图片 | `xiaohongshu.com`、`xhslink.com`、`xhs.cn`、`xhscdn.com` | 图文笔记会保存为图片序列，视频笔记保存为视频。 |
| `tiktok` | TikTok 公开视频 | `tiktok.com`、`vm.tiktok.com`、`vt.tiktok.com`、`tiktokcdn.com` | 会延续页面响应下发的临时 cookie 到同次视频下载请求。 |
| `youtube` | YouTube 公开视频和 Shorts | `youtube.com`、`youtu.be`、`youtube-nocookie.com` | 使用本机 `yt-dlp` 下载，支持后续转写、转码和媒体信息。 |

默认平台模式是 `--platform auto`，会根据分享链接自动识别平台。除 YouTube 交给本机 `yt-dlp` 外，其它平台都使用本项目内置解析逻辑；不调用第三方解析网站。

抖音等页面如果不再把公开视频地址直接写在 HTML/API 里，脚本会默认启动本机 Chromium 系浏览器无头模式，读取本机网络日志中的公开视频请求地址作为 fallback。这仍然不调用第三方解析网站。

支持范围只包含当前用户可以正常访问的公开内容。脚本不会破解 DRM、不会绕过私密作品权限、不会移除已下载文件上的水印，也不会处理付费或未授权内容。

## 输出行为

每次解析成功后都会提示媒体类型，交互模式和一次性模式一致。这个提示输出到 `stderr`：

```text
detected_media: video (platform=douyin, candidates=5)
detected_media: video (platform=kuaishou, candidates=1)
detected_media: video (platform=tiktok, candidates=1)
detected_media: video (platform=youtube, candidates=1)
detected_media: images (platform=xiaohongshu, count=1)
```

URL、下载后的文件路径、`ocr:`、`audio:`、`transcript:`、`x_output:` 等结果输出到 `stdout`，方便配合管道或脚本处理。解析过程、候选日志、OCR/转写进度和错误信息输出到 `stderr`。YouTube 的 `--print-url` 会调用 `yt-dlp --get-url`，可能输出视频流和音频流两行。

解析失败时会自动重试 3 次，也就是最多尝试 4 次；每次解析都会向 `stderr` 打印 `parse_attempt: 当前次数/总次数`。交互模式和一次性模式一致。

默认输出文件名使用本地时间：

```text
downloads/20260624_153012.mp4
```

如果指定的输出文件名没有 `.mp4` 后缀，视频下载会自动补成 `.mp4`。如果目标文件已存在且没有开启 `--overwrite`，下载器会自动生成不冲突的文件名，例如：

```text
downloads/20260624_153012.1.mp4
downloads/20260624_153012.2.mp4
```

图文作品会保存为图片序列：

```text
downloads/20260624_153012_01.webp
downloads/20260624_153012_02.webp
downloads/20260624_153012_03.jpg
```

图片后缀会优先根据响应的 `Content-Type` 修正。只有 1 张图片时不会加 `_01`；多张图片才会使用 `_01`、`_02` 这样的序号。

图文作品下载完成后默认会生成 OCR 文本文件，并输出 `ocr: 路径`：

```text
downloads/20260624_153012_01.webp
downloads/20260624_153012_02.webp
downloads/20260624_153012_ocr.txt
```

如果有多张图片，OCR 文本会按图片路径分段写入同一个 TXT 文件。

加 `--save-meta` 会在输出旁边保存 JSON 元数据，内容包括平台、作品 ID、创建时间、候选媒体地址、图片候选地址和解析日志。视频元数据默认写到同名 `.json`，图文元数据使用图片序列前缀：

```bash
python3 media_downloader.py --save-meta "https://v.douyin.com/xxxx/"
```

```text
downloads/20260624_153012.mp4
downloads/20260624_153012.json
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

交互命令可以用 `:` 或 `/` 开头，下面这些写法等价：

```text
:set platform douyin
/set platform douyin
:platform douyin

:on transcribe
:transcribe on

:toggle verbose
:verbose toggle
```

交互模式支持的布尔选项：

```text
browser-fallback, extract-audio, print-url, save-meta, show-info,
ocr-images, ocr-preprocess, transcribe, verbose, funasr-rich-text, whisper-fast,
whisper-no-gpu, whisper-progress, whisper-timestamps, whisper-translate,
overwrite, x-compatible, x-force, x-overwrite
```

交互模式支持的取值选项：

```text
platform, output-dir, output-name, timeout, browser-timeout, chrome-path,
cookie, yt-dlp-bin, youtube-format, ocr-output, ocr-language, ocr-bin, ocr-psm,
ocr-min-line-confidence, audio-output,
text-output, audio-sample-rate, audio-channels, transcribe-engine,
funasr-model, funasr-device, funasr-vad-model, funasr-punc-model,
funasr-batch-size-s, whisper-bin, whisper-model, whisper-language,
whisper-threads, x-crf, x-output-dir
```

手动指定平台：

```bash
python3 media_downloader.py --platform douyin "抖音分享文案或链接"
python3 media_downloader.py --platform kuaishou "快手分享文案或链接"
python3 media_downloader.py --platform xiaohongshu "小红书分享文案或链接"
python3 media_downloader.py --platform tiktok "TikTok 分享文案或链接"
python3 media_downloader.py --platform youtube "YouTube 分享链接"
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

下载图文作品并识别图片文字：

```bash
python3 media_downloader.py "https://www.xiaohongshu.com/discovery/item/xxxx"
```

下载 YouTube 视频：

```bash
python3 media_downloader.py "https://youtu.be/dQw4w9WgXcQ"
```

指定 `yt-dlp` 路径或格式选择：

```bash
python3 media_downloader.py \
  --yt-dlp-bin /usr/local/bin/yt-dlp \
  --youtube-format "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]" \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

默认使用 Tesseract 的 `chi_sim` 语言包识别简体中文。中文图片里混用 `eng` 容易把大号中文误判成英文噪声；如果图片确实是中英文混排，可以按需指定语言、输出路径或页面分割模式：

```bash
python3 media_downloader.py \
  --ocr-language chi_sim+eng \
  --ocr-psm 6 \
  --ocr-output downloads/post_ocr.txt \
  "https://www.xiaohongshu.com/discovery/item/xxxx"
```

如果只想下载图片、不做 OCR：

```bash
python3 media_downloader.py --no-ocr-images "https://www.xiaohongshu.com/discovery/item/xxxx"
```

保存解析元数据：

```bash
python3 media_downloader.py --save-meta "https://v.douyin.com/xxxx/"
```

打开详细日志，排查解析失败或候选地址不可用：

```bash
python3 media_downloader.py -v "https://v.douyin.com/xxxx/"
```

覆盖指定输出文件：

```bash
python3 media_downloader.py --overwrite -o downloads --output-name clip.mp4 "https://v.douyin.com/xxxx/"
```

完整工作流示例：下载、保存元数据、显示媒体信息、转成 X 兼容 MP4、同时转文字：

```bash
python3 media_downloader.py \
  --save-meta \
  --show-info \
  --x-compatible \
  --transcribe \
  "https://v.douyin.com/xxxx/"
```

## 主程序参数速查

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `share` | 无 | 位置参数，复制来的分享文案或 URL。 |
| `-I`, `--interactive` | 自动判断 | 启动交互输入循环。不带参数且 stdin 是终端时也会自动进入交互模式。 |
| `-i`, `--input-file` | 无 | 从 UTF-8 文本文件读取分享内容。 |
| `-o`, `--output-dir` | `downloads` | 下载文件保存目录。 |
| `--output-name` | 本地时间 | 指定输出文件名；视频会补 `.mp4`，图文会取文件名主体作为序列前缀。 |
| `--platform` | `auto` | 手动指定平台：`douyin`、`kuaishou`、`xiaohongshu`、`tiktok`、`youtube`。 |
| `--cookie` | 无 | 原始 Cookie 字符串，或包含 Cookie 的文本文件路径。 |
| `--timeout` | `20` | HTTP 请求超时时间，单位秒。 |
| `--print-url` | 关闭 | 只打印解析出的媒体地址，不下载。不能和 `--extract-audio`、`--transcribe` 同用。 |
| `--save-meta` | 关闭 | 保存解析元数据 JSON。 |
| `--show-info` | 关闭 | 下载后显示媒体信息；视频信息依赖 `ffprobe`。 |
| `--ocr-images` | 开启 | 图文作品图片下载后，调用本机 Tesseract OCR 识别图片文字。视频作品会忽略此参数。 |
| `--no-ocr-images` | 关闭 | 禁用图文作品下载后的 OCR。 |
| `--ocr-preprocess` | 开启 | OCR 时同时尝试原图和 Pillow 预处理图，按 Tesseract 行级置信度自动选择更好的结果。 |
| `--no-ocr-preprocess` | 关闭 | 禁用 OCR 图片预处理，只把原图交给 Tesseract。 |
| `--ocr-output` | 自动 | 自定义 OCR TXT 输出路径；默认是图片序列前缀加 `_ocr.txt`。 |
| `--ocr-language` | `chi_sim` | Tesseract 语言列表，例如 `eng`、`chi_sim`、`chi_sim+eng`。 |
| `--ocr-bin` | 自动查找 | 指定 `tesseract` 可执行文件路径或命令名。 |
| `--ocr-psm` | `6` | Tesseract 页面分割模式；`6` 适合单个均匀文本块。需要自动分割时可改成 `3`。 |
| `--ocr-min-line-confidence` | `15` | 丢弃低于该行级置信度的 OCR 行，用来过滤插画、图标等误识别噪声；设为负数可关闭过滤。 |
| `--overwrite` | 关闭 | 允许覆盖下载、音频或文字输出。未开启时，下载文件会自动避让重名。 |
| `-v`, `--verbose` | 关闭 | 打印解析日志、候选 URL、ffmpeg/ASR 命令等调试信息。 |
| `--browser-fallback` | 开启 | 直连解析无候选时，启用本机 Chromium 系浏览器 fallback。 |
| `--no-browser-fallback` | 关闭 | 禁用浏览器 fallback，只走 HTTP 直连解析。 |
| `--browser-timeout` | `30` | 浏览器 fallback 页面加载等待时间，单位秒。 |
| `--chrome-path` | 自动查找 | 指定 Chrome/Chromium/Edge/Brave/Vivaldi 可执行文件路径或命令名。 |
| `--yt-dlp-bin` | 自动查找 | 指定 YouTube 下载使用的 `yt-dlp` 可执行文件路径或命令名。 |
| `--youtube-format` | MP4 优先 | 传给 `yt-dlp -f` 的格式选择器；默认优先下载 MP4 视频 + M4A 音频。 |
| `--extract-audio` | 关闭 | 下载视频后拆出 WAV 音频。图文作品会忽略此参数。 |
| `--transcribe` | 关闭 | 下载视频后拆音频并转文字。图文作品会忽略此参数。 |
| `--audio-output` | 自动 | 自定义 WAV 输出路径。 |
| `--text-output` | 自动 | 自定义文字稿输出路径。 |
| `--audio-sample-rate` | `16000` | 拆 WAV 时使用的采样率。 |
| `--audio-channels` | `1` | 拆 WAV 时使用的声道数。 |
| `--x-compatible` | 关闭 | 下载后检查并按需生成 X 兼容 MP4。 |
| `--x-force` | 关闭 | 和 `--x-compatible` 一起使用，即使原文件已兼容也强制转码。 |
| `--x-output-dir` | 原文件目录 | X 兼容文件输出目录。 |
| `--x-overwrite` | 关闭 | 允许覆盖 X 兼容输出文件。 |
| `--x-crf` | `23` | X 转码的 x264 CRF，数值越小质量越高、文件越大。 |

## 图片 OCR

图片 OCR 使用的是本机 `tesseract` 命令行引擎。主下载器默认会对图文作品下载后的图片做 OCR；视频作品不会触发 OCR。需要关闭时加 `--no-ocr-images`。

OCR 是默认开启的可选后处理：如果本机没有安装 `tesseract` 或语言包缺失，图片仍会正常保存，程序只会向 `stderr` 打印 `warning: Image OCR skipped: ...` 并跳过 OCR。

默认语言是 `chi_sim`，用于识别简体中文。默认会把原图和 Pillow 预处理图都交给 Tesseract `psm 6` + LSTM 引擎识别，然后按行级置信度自动选择更好的结果。预处理图会放大 2 倍、增强对比度并转成黑白图，适合大字文字卡片；原图通常更适合长段宋体/衬线字体。识别结果还会通过 Tesseract TSV 行级置信度过滤一次，默认丢弃低于 `15` 的行，减少插画、图标、表情被误识别成文字的情况。识别结果会保存到一个 TXT 文件，路径默认基于图片序列前缀生成：

```text
downloads/20260624_153012_01.jpg
downloads/20260624_153012_02.jpg
downloads/20260624_153012_ocr.txt
```

如果一条图文有多张图片，TXT 会按图片路径分段写入：

```text
## downloads/20260624_153012_01.jpg
第一张图片识别出的文字

## downloads/20260624_153012_02.jpg
第二张图片识别出的文字
```

下载图文并 OCR：

```bash
python3 media_downloader.py "https://www.xiaohongshu.com/discovery/item/xxxx"
```

指定语言和输出文件。中英文混排图片可以改成 `chi_sim+eng`，纯英文图片可以改成 `eng`：

```bash
python3 media_downloader.py \
  --ocr-language chi_sim+eng \
  --ocr-output downloads/post_ocr.txt \
  "https://www.xiaohongshu.com/discovery/item/xxxx"
```

指定 Tesseract 路径和页面分割模式：

```bash
python3 media_downloader.py \
  --ocr-bin /usr/bin/tesseract \
  --ocr-psm 6 \
  "https://www.xiaohongshu.com/discovery/item/xxxx"
```

调低或关闭低置信度行过滤：

```bash
python3 media_downloader.py \
  --ocr-min-line-confidence 5 \
  "https://www.xiaohongshu.com/discovery/item/xxxx"

python3 media_downloader.py \
  --ocr-min-line-confidence -1 \
  "https://www.xiaohongshu.com/discovery/item/xxxx"
```

关闭 OCR 预处理，只识别原图：

```bash
python3 media_downloader.py \
  --no-ocr-preprocess \
  "https://www.xiaohongshu.com/discovery/item/xxxx"
```

关闭主下载器默认 OCR：

```bash
python3 media_downloader.py --no-ocr-images "https://www.xiaohongshu.com/discovery/item/xxxx"
```

也可以单独识别本地图片：

```bash
python3 image_ocr.py downloads/input.jpg
python3 image_ocr.py downloads/input_01.jpg downloads/input_02.jpg -o downloads/input_ocr.txt
python3 image_ocr.py --language eng --psm 6 downloads/input.jpg
python3 image_ocr.py --min-line-confidence 5 downloads/input.jpg
python3 image_ocr.py --no-preprocess downloads/input.jpg
```

不传图片时，`image_ocr.py` 会默认处理 `downloads/` 里最新的图片文件。`--min-line-confidence` 和主下载器的 `--ocr-min-line-confidence` 含义相同。OCR 输出已存在时默认报错，加 `--overwrite` 才会覆盖。

## YouTube 下载

YouTube 下载使用本机 `yt-dlp`。脚本负责识别 YouTube 链接、组织输出路径、调用 `yt-dlp`，下载完成后继续复用本项目已有的媒体信息、音频提取、语音转文字和 X 兼容转码流程。

默认格式选择器是：

```text
bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b
```

也就是优先下载 MP4 视频流和 M4A 音频流，并让 `yt-dlp` 合并成 MP4；如果没有合适的 MP4 流，再退回到 `yt-dlp` 可用的最佳格式。

常用命令：

```bash
python3 media_downloader.py "https://youtu.be/dQw4w9WgXcQ"
python3 media_downloader.py --show-info "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
python3 media_downloader.py --transcribe "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
python3 media_downloader.py --print-url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

限制分辨率示例：

```bash
python3 media_downloader.py \
  --youtube-format "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]" \
  "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

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

主下载器里启用 `--x-compatible` 时，转码输出默认和原文件同目录，并在原文件名后加 `_x`：

```text
downloads/20260624_153012.mp4
downloads/20260624_153012_x.mp4
```

如果 `_x` 文件已存在且没有加 `--x-overwrite`，主下载器会自动避让重名，例如 `20260624_153012_x.1.mp4`。单独运行 `x_transcoder.py` 时，默认输出名是当前本地时间加 `_x`，例如 `20260624_153522_x.mp4`；如果显式指定的输出已存在，需要加 `--overwrite`。

兼容性检查当前关注这些条件：

- 文件扩展名和容器是 `.mp4` 或 `.mov`。
- 视频编码是 H.264，像素格式是 `yuv420p`。
- 如果有音频，音频编码需要是 AAC。
- 帧率不高于 40 fps。
- 文件大小不超过 512 MiB。
- 时长不超过 140 秒。
- 横屏分辨率不超过 1920x1080，竖屏分辨率不超过 1080x1920。

转码输出默认使用：

- MP4 容器。
- H.264 视频，`high` profile，level `4.1`。
- `yuv420p` 像素格式，30 fps。
- AAC 音频，128 kbps，44.1 kHz，双声道。
- `+faststart` 元数据，便于 Web 上传和处理。

单独检查文件时，兼容返回码有特殊含义：兼容返回 `0`，不兼容返回 `2`，工具错误返回 `1`。

`x_transcoder.py` 常用参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `input` | `downloads/` 下最新 MP4/MOV | 要检查或转码的视频。 |
| `-o`, `--output` | 本地时间加 `_x` | 输出文件路径；会补 `.mp4`。 |
| `--output-dir` | 输入文件目录 | 输出目录；指定 `--output` 时忽略。 |
| `--downloads-dir` | `downloads` | 未提供输入文件时，从这个目录找最新 MP4/MOV。 |
| `--suffix` | `_x` | 默认输出文件名后缀。 |
| `--check` | 关闭 | 只检查兼容性，不转码。 |
| `--force` | 关闭 | 即使输入已经兼容也继续转码。 |
| `--overwrite` | 关闭 | 允许覆盖输出文件。 |
| `--crf` | `23` | x264 质量参数，数值越小质量越高、文件越大。 |
| `--preset` | `medium` | x264 编码预设。 |
| `--fps` | `30` | 输出帧率。 |
| `--audio-bitrate` | `128k` | AAC 音频码率。 |
| `--h264-profile` | `high` | H.264 profile，可选 `baseline`、`main`、`high`。 |
| `--h264-level` | `4.1` | H.264 level。 |
| `--max-file-size-mb` | `512` | 兼容性检查的文件大小上限。 |
| `--max-duration` | `140` | 兼容性检查的时长上限，单位秒。 |
| `--max-fps` | `40` | 兼容性检查的帧率上限。 |
| `--max-landscape-width` / `--max-landscape-height` | `1920` / `1080` | 横屏最大分辨率。 |
| `--max-portrait-width` / `--max-portrait-height` | `1080` / `1920` | 竖屏最大分辨率。 |
| `-v`, `--verbose` | 关闭 | 打印 ffmpeg 命令。 |

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

如果要使用 FunASR，推荐运行一键安装脚本。脚本会创建或复用 `.venv`，自动检测 NVIDIA GPU；CPU 机器安装 CPU-only PyTorch，避免拉取 CUDA 大包，GPU 机器会安装默认 CUDA-capable PyTorch：

```bash
bash install_funasr.sh
```

可以先看安装计划，或手动指定模式：

```bash
bash install_funasr.sh --dry-run
bash install_funasr.sh --cpu
bash install_funasr.sh --cuda
bash install_funasr.sh --preload-models
```

安装后可以选择 FunASR 转写：

```bash
.venv/bin/python media_downloader.py \
  --transcribe \
  --transcribe-engine funasr \
  --funasr-model iic/SenseVoiceSmall \
  --funasr-device cpu \
  "https://v.douyin.com/xxxx/"
```

如果使用 `install_funasr.sh` 安装，推荐直接用 `.venv/bin/python` 启动，或者先激活虚拟环境：

```bash
. .venv/bin/activate
python media_downloader.py --transcribe --transcribe-engine funasr "https://v.douyin.com/xxxx/"
```

不强制必须是 `.venv`，但运行脚本的 Python 环境必须已经安装 `funasr`、`modelscope`、`torch`、`torchaudio`。如果这些包安装在 conda 环境里，就用 conda 环境里的 `python`；如果安装在项目 `.venv` 里，就用 `.venv/bin/python`。

如果脚本检测到 GPU 并安装了 CUDA 版 PyTorch，运行时可以把 `--funasr-device` 改成 `cuda:0`。

FunASR 使用 SenseVoice 时默认输出纯文字，会过滤情绪和声音事件 emoji。如果想保留这些富文本标记，例如背景音乐、笑声、情绪判断，可以加：

```bash
.venv/bin/python media_downloader.py --transcribe --transcribe-engine funasr --funasr-rich-text "https://v.douyin.com/xxxx/"
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
.venv/bin/python video_transcriber.py --engine funasr downloads/input.mp4
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

`video_transcriber.py` 的默认行为：

- 不传输入文件时，会在 `downloads/` 里找最新的媒体文件。
- 如果输入是视频，会先用 `ffmpeg` 拆出 WAV，再转文字。
- 如果输入已经是 WAV，且没有自定义 `--audio-output`，会直接把这个 WAV 当作转写输入。
- 默认 WAV 是 16 kHz、单声道、PCM s16le，更适合本地 ASR。
- 默认文字稿是 `.txt`，文件名后缀为 `_transcript`。
- 如果音频或文字输出已经存在，默认报错；加 `--overwrite` 才会覆盖。
- 主下载器执行 `--transcribe` 时，如果默认中间 WAV 已存在，会自动复用，避免重复拆音频。

`whisper.cpp` 自动查找顺序：

| 类型 | 查找方式 |
| --- | --- |
| 可执行文件 | `--whisper-bin` 指定路径，或环境变量 `WHISPER_BIN`、`WHISPER_CPP_BIN`、`WHISPER_CLI`，或 PATH 中的 `whisper-cli`、`whisper.cpp`。 |
| 模型文件 | `--whisper-model` / `--model` 指定路径，或环境变量 `WHISPER_MODEL`、`WHISPER_MODEL_PATH`、`WHISPER_CPP_MODEL`。 |
| rustclaw 默认路径 | `~/rustclaw/data/vendor/whisper.cpp/build/bin/whisper-cli` 和 `~/rustclaw/data/models/whisper.cpp/ggml-*.bin`。 |

可用环境变量：

```text
WHISPER_BIN
WHISPER_CPP_BIN
WHISPER_CLI
WHISPER_MODEL
WHISPER_MODEL_PATH
WHISPER_CPP_MODEL
RUSTCLAW_HOME
RUSTCLAW_ROOT
```

FunASR 安装脚本参数：

| 参数 | 说明 |
| --- | --- |
| `--venv PATH` | 指定虚拟环境路径，默认是项目目录下的 `.venv`。 |
| `--python COMMAND` | 指定创建虚拟环境用的 Python 命令，默认 `python3`。 |
| `--mode auto/cpu/cuda` | 指定安装模式，默认自动检测。 |
| `--cpu` | 强制安装 CPU-only PyTorch。 |
| `--cuda` | 强制安装 CUDA-capable PyTorch。 |
| `--preload-models` | 安装后预下载/缓存 SenseVoiceSmall 和 FSMN VAD。 |
| `--dry-run` | 只打印安装计划，不实际安装。 |

主下载器里的转写相关参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--transcribe` | 关闭 | 下载视频后拆音频并转文字。 |
| `--extract-audio` | 关闭 | 只拆出 WAV；如果同时启用 `--transcribe`，仍会继续转文字。 |
| `--audio-output` | 视频名加 `_audio.wav` | 自定义 WAV 输出路径。 |
| `--text-output` | 视频名加 `_transcript.txt` | 自定义文字稿路径。 |
| `--audio-sample-rate` | `16000` | WAV 采样率。 |
| `--audio-channels` | `1` | WAV 声道数。 |
| `--transcribe-engine` | `whisper` | 可选 `whisper` 或 `funasr`。 |
| `--whisper-bin` | 自动查找 | whisper.cpp 可执行文件路径或命令名。 |
| `--whisper-model` | 自动查找 | whisper.cpp ggml 模型路径。 |
| `--whisper-language` | `auto` | 语音语言；`auto` 表示自动识别。 |
| `--whisper-threads` | 自动，最多 8 | 传给 whisper.cpp 的线程数。 |
| `--whisper-translate` | 关闭 | 请求 whisper.cpp 翻译成英文。 |
| `--whisper-fast` | 关闭 | 使用更快的贪心解码参数，可能降低稳健性。 |
| `--whisper-no-gpu` | 关闭 | 向 whisper.cpp 传 `--no-gpu`。 |
| `--whisper-timestamps` | 关闭 | 保留 whisper.cpp 文本输出中的时间戳。 |
| `--whisper-no-progress` | 关闭 | 不显示 whisper.cpp 转写进度。 |
| `--funasr-model` | `iic/SenseVoiceSmall` | FunASR 模型 ID 或本地路径。 |
| `--funasr-device` | `cpu` | FunASR 运行设备，例如 `cpu` 或 `cuda:0`。 |
| `--funasr-vad-model` | `fsmn-vad` | FunASR VAD 模型；可用 `none` 或 `off` 关闭。 |
| `--funasr-punc-model` | `none` | 可选标点模型；可用 `none` 或 `off`。 |
| `--funasr-batch-size-s` | `60` | FunASR 批处理音频时长，单位秒。 |
| `--funasr-rich-text` | 关闭 | 保留 SenseVoice 的情绪和声音事件富文本标记。 |

`video_transcriber.py` 单独运行时的参数名略短：

| 主下载器参数 | 单独转写工具参数 |
| --- | --- |
| `--transcribe-engine` | `--engine` |
| `--whisper-model` | `--model` |
| `--whisper-language` | `--language` |
| `--whisper-threads` | `--threads` |
| `--whisper-translate` | `--translate` |
| `--whisper-fast` | `--fast` |
| `--whisper-no-gpu` | `--no-gpu` |
| `--whisper-timestamps` | `--timestamps` |
| `--whisper-no-progress` | `--no-progress` |
| `--audio-sample-rate` | `--sample-rate` |
| `--audio-channels` | `--channels` |

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

非 YouTube 的基础解析和下载只需要 Python 标准库，不需要安装第三方 Python 包。YouTube 下载依赖本机 `yt-dlp`。

| 功能 | 需要的额外依赖 |
| --- | --- |
| 普通解析和下载 | Python 3.10+。 |
| YouTube 下载 | `yt-dlp`。合并音视频或后续处理通常还需要 `ffmpeg`。 |
| 浏览器 fallback | Chrome、Chromium、Microsoft Edge、Brave、Vivaldi 等 Chromium 系浏览器之一。 |
| `--show-info` | `ffprobe`。通常随 `ffmpeg` 一起安装。 |
| `--ocr-images` / `image_ocr.py` | `tesseract` 命令行程序、需要的语言数据，例如 `chi_sim`、`eng`；图片预处理需要 Python Pillow，缺失时会自动回退到原图。 |
| `--x-compatible` / `x_transcoder.py` | `ffmpeg` 和 `ffprobe`。 |
| `--extract-audio` / `video_transcriber.py` | `ffmpeg`。 |
| `--transcribe` + `whisper` | `ffmpeg`、本机 `whisper.cpp` 可执行文件、ggml 模型文件。 |
| `--transcribe` + `funasr` | `ffmpeg`，以及运行脚本的 Python 环境里安装 `funasr`、`modelscope`、`torch`、`torchaudio`。 |

Debian/Ubuntu 示例：

```bash
sudo apt update
sudo apt install ffmpeg chromium yt-dlp tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng python3-pil
```

macOS 示例：

```bash
brew install ffmpeg yt-dlp tesseract tesseract-lang
python3 -m pip install Pillow
```

确认 OCR 语言包：

```bash
tesseract --list-langs
```

FunASR 推荐使用项目自带脚本安装到 `.venv`：

```bash
bash install_funasr.sh
.venv/bin/python media_downloader.py --transcribe --transcribe-engine funasr "https://v.douyin.com/xxxx/"
```

也可以安装到你自己的 conda 或系统 Python 环境。无论使用哪种方式，都要保证运行 `media_downloader.py` 或 `video_transcriber.py` 的那个 `python` 能导入 FunASR：

```bash
python -c "import funasr, modelscope, torch, torchaudio; print('ok')"
```

## 测试

运行单元测试：

```bash
python3 -m unittest
```

只跑某个测试文件：

```bash
python3 -m unittest tests.test_media_downloader
python3 -m unittest tests.test_image_ocr
python3 -m unittest tests.test_video_transcriber
python3 -m unittest tests.test_x_transcoder
```

这些测试不会真实访问平台下载媒体，主要验证解析函数、参数默认值、路径生成、转码命令和转写流程。

## 常见问题

`ModuleNotFoundError: No module named 'funasr'`

运行脚本的 Python 环境没有安装 FunASR。用 `install_funasr.sh` 安装后，请使用 `.venv/bin/python ...`，或先执行 `. .venv/bin/activate`。如果你装在 conda 里，就先激活对应 conda 环境。

`whisper.cpp binary was not found`

默认 `whisper` 引擎找不到 `whisper-cli`。可以把 `whisper-cli` 放进 PATH，或者传 `--whisper-bin /path/to/whisper-cli`，也可以设置 `WHISPER_BIN`。

`whisper.cpp model was not found`

找不到 ggml 模型文件。传 `--whisper-model /path/to/ggml-small.bin`，或设置 `WHISPER_MODEL`。单独运行 `video_transcriber.py` 时参数名是 `--model`。

`ffmpeg is required but was not found in PATH`

需要安装 `ffmpeg`，并确认 `ffmpeg` 和 `ffprobe` 在 PATH 中：

```bash
ffmpeg -version
ffprobe -version
```

`yt-dlp is required for YouTube downloads but was not found in PATH.`

YouTube 下载需要安装 `yt-dlp`，并确认命令可用：

```bash
yt-dlp --version
```

如果安装在非 PATH 目录，可以指定路径：

```bash
python3 media_downloader.py --yt-dlp-bin /path/to/yt-dlp "https://youtu.be/dQw4w9WgXcQ"
```

`warning: Image OCR skipped: tesseract is required but was not found in PATH.`

图片已经下载成功，但 OCR 被跳过。需要安装 Tesseract OCR，并确认命令可用：

```bash
tesseract --version
```

如果安装在非 PATH 目录，可以指定路径：

```bash
python3 media_downloader.py --ocr-bin /path/to/tesseract "分享链接"
```

`Error opening data file ... chi_sim.traineddata`

Tesseract 缺少对应语言数据。默认 OCR 语言是 `chi_sim`，需要简体中文语言包。可以安装语言包，或改成已有语言：

```bash
tesseract --list-langs
python3 media_downloader.py --ocr-language eng "分享链接"
```

`No downloadable video URL was found`

常见原因是作品不是公开可访问、链接过期、需要登录态、页面出现验证码/风控、平台页面结构变化，或者本机没有可用浏览器导致 fallback 无法执行。可以先加 `-v` 看解析日志：

```bash
python3 media_downloader.py -v "分享链接"
```

如果确认需要登录态，可以尝试传 Cookie：

```bash
python3 media_downloader.py --cookie cookies.txt "分享链接"
```

如果只想验证直连解析，不想启动浏览器 fallback：

```bash
python3 media_downloader.py --no-browser-fallback -v "分享链接"
```

`--print-url cannot be used with --extract-audio or --transcribe`

`--print-url` 不会下载文件，而拆音频和转文字都需要本地媒体文件。先去掉 `--print-url` 下载，再做音频处理。

输出文件已经存在

下载器本身会自动避让视频/图片重名。转写输出和单独转码输出默认不覆盖已有文件，需要加对应的 `--overwrite`；主下载器里的 X 兼容输出要加 `--x-overwrite`。

## 说明

这个工具不会破解 DRM、不会绕过私密作品权限、不会处理付费或未授权内容。解析依赖公开视频页面/API 或网页播放器已公开请求的媒体地址；遇到登录限制、风控、验证码、页面结构变化或服务维护时会直接报错，不会绕过限制。
