# Media Downloader Web

React + Vite 版本的浏览器应用，用 JavaScript 在网页里实现下载任务管理、直链下载、命令生成和本地图片 OCR。

## 启动

```bash
npm install
npm run dev
```

默认地址：

```text
http://127.0.0.1:5173
```

生产构建：

```bash
npm run build
```

## 当前能力

- 识别分享文本里的 URL、平台和作品 ID。
- 管理多条下载任务。
- 对直连图片、直连视频 URL 触发浏览器下载。
- 对平台分享页做 best-effort `fetch` 和 HTML 媒体 URL 提取。
- 对本地图片做浏览器内 OCR，多张图片合并成一个 TXT，并按行级置信度过滤明显噪声。
- 生成对应的 `media_downloader.py` 命令，包括默认启用的 OpenCC 转写简体转换；浏览器受限时可复制到本地执行。
- 抖音 `/user/` 与小红书 `/user/profile/` 主页命令默认自动复用系统浏览器对应站点的登录态，抓取最近 100 条视频或图文作品，按 5 秒间隔顺序保存到用户名目录下的 `videos/` 和 `images/` 子目录；文件按“用户名 + 本地发布时间”命名，多图追加编号，并通过可见的 `profile_downloads.json` 跳过已下载作品。上限可填数字或 `all`，自动登录态、数量和间隔可在下载设置中调整。

## 浏览器限制

React 测试模式本质上还是浏览器前端，不能自动绕过 CORS。只要请求目标平台页面或媒体资源没有允许当前网页源读取，`fetch` 就会失败。

Vite dev server 可以配置 proxy 来绕过开发环境 CORS，但那等于让请求经过本机 Node 服务转发，不再是完全纯浏览器运行。当前版本保持纯前端实现，所以 YouTube 的签名解析、音视频流选择、`yt-dlp`、`ffmpeg`、Tesseract CLI、FunASR/Whisper 等本地能力仍通过生成命令交给 Python 脚本处理。

浏览器 OCR 使用 `tesseract.js`，语言默认 `chi_sim`，PSM 默认 `6`，最低行置信度默认 `15`。首次运行时会下载浏览器版 OCR 运行文件和语言数据。
