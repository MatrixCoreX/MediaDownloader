# Media Downloader

一个命令行工具：粘贴抖音、快手或小红书分享文案/链接，解析可访问的视频地址，并下载为 MP4。

默认输出文件名使用本地时间，例如 `20260624_153012.mp4`。如果需要自动转成 X 兼容格式，下载脚本会沿用同一个时间名并加 `_x`，例如 `20260624_153012_x.mp4`。单独运行转码工具时，默认也会生成当前时间命名的 `_x.mp4`。

主程序文件名是 `media_downloader.py`。

支持平台：

- `douyin`: 抖音公开视频。
- `kuaishou`: 快手公开视频。
- `xiaohongshu`: 小红书视频笔记。

默认平台模式是 `--platform auto`，会根据分享链接自动识别平台。所有平台都只使用直连解析，不调用第三方解析网站。

## 使用

```bash
python3 media_downloader.py "复制来的分享文案或链接"
```

交互输入模式：

```bash
python3 media_downloader.py
```

或显式指定：

```bash
python3 media_downloader.py --interactive
```

启动后粘贴分享文案并回车，下载完成后会继续回到输入提示符。输入 `exit`、`quit` 或 `q` 退出。

手动指定平台：

```bash
python3 media_downloader.py --platform kuaishou "快手分享文案或链接"
python3 media_downloader.py --platform xiaohongshu "小红书分享文案或链接"
python3 media_downloader.py --platform douyin "抖音分享文案或链接"
```

只打印解析出的下载地址：

```bash
python3 media_downloader.py --print-url "https://v.douyin.com/xxxx/"
```

从文件或管道读取：

```bash
python3 media_downloader.py -i share.txt
cat share.txt | python3 media_downloader.py
```

带 cookie 访问需要登录态才能看的公开视频：

```bash
python3 media_downloader.py --cookie cookies.txt "https://v.douyin.com/xxxx/"
```

指定保存目录和文件名：

```bash
python3 media_downloader.py -o videos --output-name my_video.mp4 "https://v.douyin.com/xxxx/"
```

下载后显示分辨率、时长、编码、码率和文件大小：

```bash
python3 media_downloader.py --show-info "https://v.douyin.com/xxxx/"
```

下载完成后会默认检查 X 上传兼容性；如果不是 X 稳定支持的 H.264/AAC MP4，会自动生成 `_x.mp4`：

```bash
python3 media_downloader.py "https://v.douyin.com/xxxx/"
```

交互模式同样会自动检查和转码：

```bash
python3 media_downloader.py --interactive
```

如果只想下载原文件，不做 X 兼容性检查和转码：

```bash
python3 media_downloader.py --no-x-compatible "https://v.douyin.com/xxxx/"
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

## 依赖

默认解析模式只需要 Python 3 标准库。

`--show-info` 需要系统安装 `ffprobe`。如果没有安装，工具仍会下载视频，但只能显示文件大小。

默认 X 兼容检查/转码和 `x_transcoder.py` 需要系统安装 `ffmpeg` 和 `ffprobe`。如果暂时不需要转码，可使用 `--no-x-compatible`。

## 说明

这个工具不会破解 DRM、不会绕过私密作品权限、不会处理付费或未授权内容。解析依赖公开视频页面/API 里已经公开返回的数据；遇到登录限制、风控、验证码、页面结构变化或服务维护时会直接报错，不会绕过限制。
