import React, { useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Copy, Download, FileText, ImagePlus, Play, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { createWorker } from "tesseract.js";
import "./styles.css";

const DEFAULTS = {
  platform: "auto",
  outputDir: "downloads",
  outputName: "",
  cookie: "",
  timeout: 20,
  browserFallback: true,
  browserTimeout: 30,
  chromePath: "",
  ytDlpBin: "",
  youtubeFormat: "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
  printUrl: false,
  saveMeta: false,
  showInfo: false,
  overwrite: false,
  ocrImages: true,
  ocrPreprocess: true,
  ocrOutput: "",
  ocrLanguage: "chi_sim",
  ocrPsm: 6,
  ocrMinLineConfidence: 15,
  ocrBin: "",
  extractAudio: false,
  transcribe: false,
  audioSampleRate: 16000,
  audioChannels: 1,
  audioOutput: "",
  textOutput: "",
  transcribeEngine: "whisper",
  whisperModel: "",
  funasrModel: "iic/SenseVoiceSmall",
  funasrDevice: "cpu",
  xCompatible: false,
  xForce: false,
  xCrf: 23
};

const SHARE_URL_RE = /https?:\/\/[^\s"'<>，。；：！？）】》、]+/g;
const TRAILING_URL_PUNCTUATION_RE = new RegExp("[.,;:!?)\\]}>\"'，。；：！？）】》、]+$", "u");
const MEDIA_URL_RE = /https?:\\?\/\\?\/[^"'<>\\\s]+|https?:\/\/[^"'<>\\\s]+|\/\/[^"'<>\\\s]+/g;
const VIDEO_EXTENSIONS = [".mp4", ".webm", ".mov", ".m4v", ".m3u8"];
const IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".bmp"];

const DOMAINS = {
  youtube: ["youtube.com", "youtu.be", "youtube-nocookie.com"],
  kuaishou: ["kuaishou.com", "gifshow.com", "ksurl.cn", "kwai.com", "v.kuaishou.com"],
  xiaohongshu: ["xiaohongshu.com", "xhslink.com", "xhscdn.com", "xhs.cn"],
  tiktok: ["tiktok.com", "tiktokv.com", "tiktokcdn.com", "vm.tiktok.com", "vt.tiktok.com"],
  douyin: ["douyin.com", "iesdouyin.com"]
};

const ID_PATTERNS = {
  youtube: [
    /youtu\.be\/([0-9A-Za-z_-]{11})/,
    /\/(?:shorts|embed|live)\/([0-9A-Za-z_-]{11})/,
    /[?&]v=([0-9A-Za-z_-]{11})/
  ],
  tiktok: [/\/@[^/?#]+\/video\/(\d{10,})/, /\/video\/(\d{10,})/, /[?&](?:item_id|itemId|video_id|videoId)=(\d{10,})/],
  xiaohongshu: [/\/(?:explore|discovery\/item)\/([0-9a-zA-Z]+)/, /[?&](?:note_id|noteId|item_id)=([^&#]+)/],
  kuaishou: [/\/short-video\/([^/?#]+)/, /[?&](?:photoId|photo_id)=([^&#]+)/],
  douyin: [/\/(?:video|note)\/(\d{10,})/, /[?&](?:aweme_id|modal_id|item_ids|item_id)=(\d{10,})/]
};

function App() {
  const [shareInput, setShareInput] = useState("");
  const [queue, setQueue] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [settings, setSettings] = useState(DEFAULTS);
  const [activeTab, setActiveTab] = useState("download");
  const [log, setLog] = useState([]);
  const [status, setStatus] = useState({ text: "浏览器模式", type: "warn" });
  const [images, setImages] = useState([]);
  const [ocrText, setOcrText] = useState("");
  const [ocrProgress, setOcrProgress] = useState(0);
  const fileInputRef = useRef(null);

  const detected = useMemo(() => {
    const urls = extractUrls(shareInput);
    return {
      urls,
      platform: shareInput.trim() ? detectPlatform(shareInput) : "-"
    };
  }, [shareInput]);

  const selectedTask = queue.find((task) => task.id === selectedId) || queue[0] || null;
  const selectedCommand = selectedTask ? buildCommand(selectedTask, settings) : "";

  function appendLog(message) {
    const time = new Date().toLocaleTimeString();
    setLog((items) => [...items, `[${time}] ${message}`]);
  }

  function updateTask(id, patch) {
    setQueue((items) => items.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  function addInputToQueue(replace = false) {
    const tasks = parseInputItems(shareInput).map((item) => {
      const url = item.urls[0] || item.raw;
      const platform = detectPlatform(item.raw);
      const normalizedPlatform = platform === "unknown" ? "auto" : platform;
      return {
        id: cryptoId(),
        raw: item.raw,
        url,
        platform: normalizedPlatform,
        itemId: extractItemId(normalizedPlatform, item.raw),
        status: "pending",
        message: ""
      };
    });
    setQueue((items) => {
      const next = replace ? tasks : [...items, ...tasks];
      if (!selectedId && next[0]) setSelectedId(next[0].id);
      if (replace && next[0]) setSelectedId(next[0].id);
      return next;
    });
  }

  async function runTask(task) {
    setSelectedId(task.id);
    updateTask(task.id, { status: "running", message: "浏览器执行中" });
    appendLog(`开始: ${task.raw}`);
    try {
      const message = await executeTaskInBrowser(task, settings, appendLog);
      updateTask(task.id, { status: "done", message });
      setStatus({ text: "执行完成", type: "" });
      appendLog(`完成: ${message}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      updateTask(task.id, { status: "failed", message });
      setStatus({ text: "执行失败", type: "error" });
      appendLog(`失败: ${message}`);
    }
  }

  async function runAllTasks() {
    if (!queue.length) {
      setStatus({ text: "没有任务", type: "error" });
      return;
    }
    for (const task of queue) {
      await runTask(task);
    }
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      setShareInput(text);
      setStatus({ text: "已粘贴", type: "" });
    } catch {
      setStatus({ text: "剪贴板不可用", type: "error" });
    }
  }

  async function copyText(text) {
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      setStatus({ text: "已复制", type: "" });
    } catch {
      fallbackCopy(text);
      setStatus({ text: "已复制", type: "" });
    }
  }

  function addImageFiles(files) {
    const imageFiles = files.filter((file) => file.type.startsWith("image/"));
    setImages((items) => [
      ...items,
      ...imageFiles.map((file) => ({ id: cryptoId(), file, url: URL.createObjectURL(file), text: "" }))
    ]);
  }

  async function runLocalOcr() {
    if (!images.length) {
      setStatus({ text: "没有图片", type: "error" });
      return;
    }
    setStatus({ text: "OCR 运行中", type: "warn" });
    setOcrText("");
    setOcrProgress(0);

    const worker = await createWorker(settings.ocrLanguage, 1, {
      logger: (message) => {
        if (message.status === "recognizing text" && typeof message.progress === "number") {
          setOcrProgress(message.progress);
        }
      }
    });
    await worker.setParameters({
      tessedit_pageseg_mode: String(settings.ocrPsm),
      preserve_interword_spaces: "1"
    });

    try {
      const chunks = [];
      for (let index = 0; index < images.length; index += 1) {
        const image = images[index];
        const source = settings.ocrPreprocess ? await preprocessImage(image.file) : image.file;
        const result = await worker.recognize(source);
        const text = normalizeOcrText(
          textFromRecognitionResult(result.data, settings.ocrMinLineConfidence)
        );
        chunks.push(`## ${image.file.name}`);
        if (text) chunks.push(text);
        chunks.push("");
        setOcrText(chunks.join("\n").trim() + "\n");
        setOcrProgress((index + 1) / images.length);
      }
      setStatus({ text: "OCR 完成", type: "" });
    } finally {
      await worker.terminate();
    }
  }

  function downloadOcrText() {
    if (!ocrText.trim()) {
      setStatus({ text: "没有 OCR 文本", type: "error" });
      return;
    }
    triggerBlobDownload(new Blob([ocrText], { type: "text/plain;charset=utf-8" }), "images_ocr.txt");
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>Media Downloader Web</h1>
          <p className="muted">React + 浏览器 JavaScript</p>
        </div>
        <div className="status-strip" aria-live="polite">
          <span className={`status-pill ${status.type}`}>{status.text}</span>
          <span className="status-pill">{queue.length} 个任务</span>
        </div>
      </header>

      <main className="workspace">
        <section className="pane input-pane">
          <div className="pane-head">
            <h2>输入</h2>
            <div className="button-row">
              <IconButton title="从剪贴板粘贴" onClick={pasteFromClipboard}><FileText size={17} /></IconButton>
              <IconButton title="清空输入" onClick={() => setShareInput("")}><X size={17} /></IconButton>
            </div>
          </div>
          <textarea
            value={shareInput}
            spellCheck="false"
            placeholder="粘贴分享文案或链接，每行一个任务"
            onChange={(event) => setShareInput(event.target.value)}
          />
          <div className="action-grid">
            <button className="primary" type="button" onClick={() => addInputToQueue(false)}>
              <Plus size={16} /> 加入队列
            </button>
            <button type="button" onClick={() => addInputToQueue(true)}>
              <RotateCcw size={16} /> 替换队列
            </button>
          </div>
          <div className="quick-summary">
            <div><span className="label">识别平台</span><strong>{detected.platform}</strong></div>
            <div><span className="label">URL 数</span><strong>{detected.urls.length}</strong></div>
          </div>
        </section>

        <section className="pane queue-pane">
          <div className="pane-head">
            <h2>任务</h2>
            <div className="button-row">
              <button type="button" onClick={() => selectedTask && runTask(selectedTask)}><Play size={16} />执行</button>
              <button type="button" onClick={runAllTasks}><Play size={16} />全部执行</button>
              <IconButton title="复制全部命令" onClick={() => copyText(queue.map((task) => buildCommand(task, settings)).join("\n"))}><Copy size={17} /></IconButton>
              <IconButton title="清空队列" onClick={() => { setQueue([]); setSelectedId(null); }}><Trash2 size={17} /></IconButton>
            </div>
          </div>

          <div className={queue.length ? "queue-list" : "queue-list empty"}>
            {queue.length ? queue.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                active={task.id === selectedId}
                onSelect={() => setSelectedId(task.id)}
                onRun={() => runTask(task)}
                onCopy={() => copyText(buildCommand(task, settings))}
                onRemove={() => {
                  setQueue((items) => {
                    const next = items.filter((item) => item.id !== task.id);
                    if (selectedId === task.id) setSelectedId(next[0]?.id || null);
                    return next;
                  });
                }}
              />
            )) : <p>暂无任务</p>}
          </div>

          <OutputPanel title="命令" value={selectedCommand} onCopy={() => copyText(selectedCommand)} />
          <OutputPanel title="浏览器执行日志" value={log.join("\n")} onClear={() => setLog([])} />
        </section>

        <SettingsPane
          settings={settings}
          activeTab={activeTab}
          onTab={setActiveTab}
          onChange={setSettings}
          onReset={() => setSettings(DEFAULTS)}
        />

        <section className="pane ocr-pane">
          <div className="pane-head">
            <h2>本地图片 OCR</h2>
            <div className="button-row">
              <IconButton title="识别图片" onClick={runLocalOcr}><ImagePlus size={17} /></IconButton>
              <IconButton title="下载文本" onClick={downloadOcrText}><Download size={17} /></IconButton>
            </div>
          </div>
          <label
            className="drop-zone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              addImageFiles(Array.from(event.dataTransfer.files || []));
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={(event) => {
                addImageFiles(Array.from(event.target.files || []));
                event.target.value = "";
              }}
            />
            <span>选择或拖入图片</span>
          </label>
          <div className="image-list">
            {images.map((image) => (
              <div className="image-item" key={image.id}>
                <img alt="" src={image.url} />
                <div>
                  <div>{image.file.name}</div>
                  <small>{formatBytes(image.file.size)}</small>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    URL.revokeObjectURL(image.url);
                    setImages((items) => items.filter((item) => item.id !== image.id));
                  }}
                >
                  删除
                </button>
              </div>
            ))}
          </div>
          <progress value={ocrProgress} max="1" />
          <textarea value={ocrText} spellCheck="false" readOnly />
        </section>
      </main>
    </>
  );
}

function IconButton({ title, onClick, children }) {
  return <button className="icon-button" type="button" title={title} onClick={onClick}>{children}</button>;
}

function TaskCard({ task, active, onSelect, onRun, onCopy, onRemove }) {
  return (
    <article className={`task ${active ? "active" : ""}`} onClick={onSelect}>
      <div className="task-top">
        <div className="task-meta">
          <span className="badge platform">{task.platform}</span>
          <span className="badge">{task.itemId || "no-id"}</span>
          <span className={`badge ${statusClass(task.status)}`}>{statusLabel(task.status)}</span>
        </div>
        <div className="task-actions">
          <button type="button" onClick={(event) => { event.stopPropagation(); onRun(); }}>执行</button>
          <button type="button" onClick={(event) => { event.stopPropagation(); onCopy(); }}>复制</button>
          <button type="button" onClick={(event) => { event.stopPropagation(); onRemove(); }}>删除</button>
        </div>
      </div>
      <div className="task-url">{task.raw}</div>
      {task.message ? <div className="task-url muted">{task.message}</div> : null}
    </article>
  );
}

function OutputPanel({ title, value, onCopy, onClear }) {
  return (
    <div className="output-panel">
      <div className="pane-head compact">
        <h2>{title}</h2>
        {onCopy ? <IconButton title={`复制${title}`} onClick={onCopy}><Copy size={17} /></IconButton> : null}
        {onClear ? <IconButton title={`清空${title}`} onClick={onClear}><X size={17} /></IconButton> : null}
      </div>
      <textarea className="code-output" value={value} spellCheck="false" readOnly />
    </div>
  );
}

function SettingsPane({ settings, activeTab, onTab, onChange, onReset }) {
  function update(name, value) {
    onChange({ ...settings, [name]: value });
  }
  return (
    <aside className="pane settings-pane">
      <div className="pane-head">
        <h2>配置</h2>
        <IconButton title="恢复默认配置" onClick={onReset}><RotateCcw size={17} /></IconButton>
      </div>
      <div className="tabs" role="tablist" aria-label="设置分类">
        {["download", "ocr", "post"].map((tab) => (
          <button key={tab} className={`tab ${activeTab === tab ? "active" : ""}`} type="button" onClick={() => onTab(tab)}>
            {tab === "download" ? "下载" : tab === "ocr" ? "OCR" : "后处理"}
          </button>
        ))}
      </div>
      {activeTab === "download" ? <DownloadSettings settings={settings} update={update} /> : null}
      {activeTab === "ocr" ? <OcrSettings settings={settings} update={update} /> : null}
      {activeTab === "post" ? <PostSettings settings={settings} update={update} /> : null}
    </aside>
  );
}

function DownloadSettings({ settings, update }) {
  return (
    <div className="tab-panel active">
      <Field label="平台">
        <select value={settings.platform} onChange={(event) => update("platform", event.target.value)}>
          {["auto", "douyin", "kuaishou", "xiaohongshu", "tiktok", "youtube"].map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </Field>
      <TextField label="输出目录" value={settings.outputDir} onChange={(value) => update("outputDir", value)} />
      <TextField label="输出文件名" value={settings.outputName} placeholder="自动" onChange={(value) => update("outputName", value)} />
      <TextField label="Cookie" value={settings.cookie} placeholder="原始 Cookie 或文件路径" onChange={(value) => update("cookie", value)} />
      <div className="field-grid two">
        <NumberField label="超时秒数" value={settings.timeout} onChange={(value) => update("timeout", value)} />
        <NumberField label="浏览器秒数" value={settings.browserTimeout} onChange={(value) => update("browserTimeout", value)} />
      </div>
      <TextField label="Chrome 路径" value={settings.chromePath} placeholder="自动查找" onChange={(value) => update("chromePath", value)} />
      <TextField label="yt-dlp 路径" value={settings.ytDlpBin} placeholder="自动查找" onChange={(value) => update("ytDlpBin", value)} />
      <TextField label="YouTube 格式" value={settings.youtubeFormat} onChange={(value) => update("youtubeFormat", value)} />
      <div className="toggle-list">
        <Checkbox label="只打印地址" checked={settings.printUrl} onChange={(value) => update("printUrl", value)} />
        <Checkbox label="保存元数据" checked={settings.saveMeta} onChange={(value) => update("saveMeta", value)} />
        <Checkbox label="显示媒体信息" checked={settings.showInfo} onChange={(value) => update("showInfo", value)} />
        <Checkbox label="覆盖输出" checked={settings.overwrite} onChange={(value) => update("overwrite", value)} />
        <Checkbox label="浏览器 fallback" checked={settings.browserFallback} onChange={(value) => update("browserFallback", value)} />
      </div>
    </div>
  );
}

function OcrSettings({ settings, update }) {
  return (
    <div className="tab-panel active">
      <div className="toggle-list">
        <Checkbox label="图文下载后 OCR" checked={settings.ocrImages} onChange={(value) => update("ocrImages", value)} />
        <Checkbox label="OCR 预处理" checked={settings.ocrPreprocess} onChange={(value) => update("ocrPreprocess", value)} />
      </div>
      <TextField label="OCR 输出" value={settings.ocrOutput} placeholder="自动" onChange={(value) => update("ocrOutput", value)} />
      <div className="field-grid two">
        <TextField label="语言" value={settings.ocrLanguage} onChange={(value) => update("ocrLanguage", value)} />
        <NumberField label="PSM" value={settings.ocrPsm} onChange={(value) => update("ocrPsm", value)} />
      </div>
      <NumberField
        label="最低行置信度"
        value={settings.ocrMinLineConfidence}
        onChange={(value) => update("ocrMinLineConfidence", value)}
      />
      <TextField label="Tesseract 路径" value={settings.ocrBin} placeholder="自动查找" onChange={(value) => update("ocrBin", value)} />
    </div>
  );
}

function PostSettings({ settings, update }) {
  return (
    <div className="tab-panel active">
      <div className="toggle-list">
        <Checkbox label="拆 WAV" checked={settings.extractAudio} onChange={(value) => update("extractAudio", value)} />
        <Checkbox label="转文字" checked={settings.transcribe} onChange={(value) => update("transcribe", value)} />
        <Checkbox label="X 兼容转码" checked={settings.xCompatible} onChange={(value) => update("xCompatible", value)} />
        <Checkbox label="强制 X 转码" checked={settings.xForce} onChange={(value) => update("xForce", value)} />
      </div>
      <Field label="转写引擎">
        <select value={settings.transcribeEngine} onChange={(event) => update("transcribeEngine", event.target.value)}>
          <option value="whisper">whisper</option>
          <option value="funasr">funasr</option>
        </select>
      </Field>
      <div className="field-grid two">
        <NumberField label="采样率" value={settings.audioSampleRate} onChange={(value) => update("audioSampleRate", value)} />
        <NumberField label="声道" value={settings.audioChannels} onChange={(value) => update("audioChannels", value)} />
      </div>
      <TextField label="音频输出" value={settings.audioOutput} placeholder="自动" onChange={(value) => update("audioOutput", value)} />
      <TextField label="文字输出" value={settings.textOutput} placeholder="自动" onChange={(value) => update("textOutput", value)} />
      <TextField label="Whisper 模型" value={settings.whisperModel} placeholder="ggml 模型路径" onChange={(value) => update("whisperModel", value)} />
      <TextField label="FunASR 模型" value={settings.funasrModel} onChange={(value) => update("funasrModel", value)} />
      <div className="field-grid two">
        <TextField label="FunASR 设备" value={settings.funasrDevice} onChange={(value) => update("funasrDevice", value)} />
        <NumberField label="X CRF" value={settings.xCrf} onChange={(value) => update("xCrf", value)} />
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return <label><span>{label}</span>{children}</label>;
}

function TextField({ label, value, placeholder = "", onChange }) {
  return <Field label={label}><input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></Field>;
}

function NumberField({ label, value, onChange }) {
  return <Field label={label}><input type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} /></Field>;
}

function Checkbox({ label, checked, onChange }) {
  return <label><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /> {label}</label>;
}

function extractUrls(text) {
  const urls = [];
  for (const match of text.matchAll(SHARE_URL_RE)) {
    const url = match[0].replace(TRAILING_URL_PUNCTUATION_RE, "");
    if (url && !urls.includes(url)) urls.push(url);
  }
  return urls;
}

function normalizePlatform(platform) {
  if (platform === "yt") return "youtube";
  if (platform === "titok") return "tiktok";
  return platform;
}

function detectPlatform(text) {
  const lowered = text.toLowerCase();
  for (const platform of ["youtube", "kuaishou", "xiaohongshu", "tiktok", "douyin"]) {
    if (DOMAINS[platform].some((domain) => lowered.includes(domain))) return platform;
  }
  return "unknown";
}

function extractItemId(platform, text) {
  const patterns = ID_PATTERNS[platform] || [];
  const decoded = decodeLoose(text);
  for (const pattern of patterns) {
    const match = pattern.exec(decoded);
    if (match) return match[1];
  }
  return "";
}

function decodeLoose(text) {
  try {
    return decodeURIComponent(text);
  } catch {
    return text;
  }
}

function parseInputItems(text) {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length > 1) {
    return lines.map((line) => ({ raw: line, urls: extractUrls(line) })).filter((item) => item.urls.length);
  }
  const urls = extractUrls(text);
  if (urls.length > 1) return urls.map((url) => ({ raw: url, urls: [url] }));
  return text.trim() ? [{ raw: text.trim(), urls }] : [];
}

function buildCommand(task, opts) {
  const args = ["python3", "media_downloader.py"];
  const platform = normalizePlatform(opts.platform);
  addOpt(args, "--platform", platform !== "auto" ? platform : task.platform !== "auto" ? task.platform : "");
  addOpt(args, "--output-dir", opts.outputDir !== DEFAULTS.outputDir ? opts.outputDir : "");
  addOpt(args, "--output-name", opts.outputName);
  addOpt(args, "--cookie", opts.cookie);
  addOpt(args, "--timeout", opts.timeout !== DEFAULTS.timeout ? String(opts.timeout) : "");
  if (!opts.browserFallback) args.push("--no-browser-fallback");
  addOpt(args, "--browser-timeout", opts.browserTimeout !== DEFAULTS.browserTimeout ? String(opts.browserTimeout) : "");
  addOpt(args, "--chrome-path", opts.chromePath);
  addOpt(args, "--yt-dlp-bin", opts.ytDlpBin);
  addOpt(args, "--youtube-format", opts.youtubeFormat !== DEFAULTS.youtubeFormat ? opts.youtubeFormat : "");
  if (opts.printUrl) args.push("--print-url");
  if (opts.saveMeta) args.push("--save-meta");
  if (opts.showInfo) args.push("--show-info");
  if (opts.overwrite) args.push("--overwrite");
  if (!opts.ocrImages) args.push("--no-ocr-images");
  if (!opts.ocrPreprocess) args.push("--no-ocr-preprocess");
  addOpt(args, "--ocr-output", opts.ocrOutput);
  addOpt(args, "--ocr-language", opts.ocrLanguage !== DEFAULTS.ocrLanguage ? opts.ocrLanguage : "");
  addOpt(args, "--ocr-bin", opts.ocrBin);
  addOpt(args, "--ocr-psm", opts.ocrPsm !== DEFAULTS.ocrPsm ? String(opts.ocrPsm) : "");
  addOpt(
    args,
    "--ocr-min-line-confidence",
    opts.ocrMinLineConfidence !== DEFAULTS.ocrMinLineConfidence ? String(opts.ocrMinLineConfidence) : ""
  );
  if (opts.extractAudio) args.push("--extract-audio");
  if (opts.transcribe) args.push("--transcribe");
  addOpt(args, "--audio-output", opts.audioOutput);
  addOpt(args, "--text-output", opts.textOutput);
  addOpt(args, "--audio-sample-rate", opts.audioSampleRate !== DEFAULTS.audioSampleRate ? String(opts.audioSampleRate) : "");
  addOpt(args, "--audio-channels", opts.audioChannels !== DEFAULTS.audioChannels ? String(opts.audioChannels) : "");
  addOpt(args, "--transcribe-engine", opts.transcribeEngine !== DEFAULTS.transcribeEngine ? opts.transcribeEngine : "");
  addOpt(args, "--whisper-model", opts.whisperModel);
  addOpt(args, "--funasr-model", opts.funasrModel !== DEFAULTS.funasrModel ? opts.funasrModel : "");
  addOpt(args, "--funasr-device", opts.funasrDevice !== DEFAULTS.funasrDevice ? opts.funasrDevice : "");
  if (opts.xCompatible) args.push("--x-compatible");
  if (opts.xForce) args.push("--x-force");
  addOpt(args, "--x-crf", opts.xCrf !== DEFAULTS.xCrf ? String(opts.xCrf) : "");
  args.push(task.raw);
  return args.map(shellQuote).join(" ");
}

function addOpt(args, flag, value) {
  if (value) args.push(flag, value);
}

function shellQuote(value) {
  const text = String(value);
  if (/^[A-Za-z0-9_./:=+,%@-]+$/.test(text)) return text;
  return `'${text.replace(/'/g, "'\"'\"'")}'`;
}

async function executeTaskInBrowser(task, opts, logLine) {
  const url = task.url || extractUrls(task.raw)[0];
  if (!url) throw new Error("没有可执行 URL");
  warnUnsupportedPostProcessing(opts, logLine);
  const directKind = mediaKindFromUrl(url);
  if (directKind) {
    if (opts.printUrl) {
      logLine(url);
      return "已输出直链";
    }
    return downloadDirectUrl(url, suggestedFileName(task, opts, directKind, 1));
  }
  if (task.platform === "youtube") {
    throw new Error("YouTube 的媒体签名和分流需要 yt-dlp；纯浏览器 JS 不能可靠解析并下载。");
  }
  const htmlText = await fetchPageText(url, opts);
  const candidates = extractMediaCandidates(htmlText, task.platform);
  if (!candidates.length) {
    throw new Error("页面可读取，但没有找到可下载媒体直链。平台页面结构或加密签名可能不支持纯前端解析。");
  }
  if (opts.printUrl) {
    for (const candidate of candidates) logLine(`${candidate.kind}: ${candidate.url}`);
    return `已输出 ${candidates.length} 个候选地址`;
  }
  const videos = candidates.filter((candidate) => candidate.kind === "video");
  const images = candidates.filter((candidate) => candidate.kind === "image");
  if (videos.length) return downloadDirectUrl(videos[0].url, suggestedFileName(task, opts, "video", 1));
  let count = 0;
  for (const image of images) {
    count += 1;
    await downloadDirectUrl(image.url, suggestedFileName(task, opts, "image", count));
  }
  return `已触发 ${images.length} 张图片下载`;
}

function warnUnsupportedPostProcessing(opts, logLine) {
  const unsupported = [];
  if (opts.showInfo) unsupported.push("媒体信息");
  if (opts.extractAudio) unsupported.push("拆音频");
  if (opts.transcribe) unsupported.push("转文字");
  if (opts.xCompatible) unsupported.push("X 转码");
  if (unsupported.length) logLine(`浏览器 JS 不能执行 ${unsupported.join("、")}；这些能力需要本地 ffmpeg/ASR。`);
  if (opts.cookie) logLine("浏览器网页不能手动设置 Cookie 请求头；只能使用浏览器当前允许发送的站点 Cookie。");
  if (opts.outputDir && opts.outputDir !== DEFAULTS.outputDir) logLine("浏览器网页不能指定保存目录；文件会进入浏览器默认下载目录。");
}

async function fetchPageText(url, opts) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), Math.max(1000, opts.timeout * 1000));
  try {
    const response = await fetch(url, { method: "GET", mode: "cors", credentials: "include", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("浏览器请求超时。");
    throw new Error("浏览器无法读取该页面，通常是平台未开放 CORS。纯前端 JS 不能绕过这个限制。");
  } finally {
    window.clearTimeout(timeout);
  }
}

function extractMediaCandidates(pageText, platform) {
  const text = normalizeEmbeddedUrlText(pageText);
  const seen = new Set();
  const candidates = [];
  for (const match of text.matchAll(MEDIA_URL_RE)) {
    const normalized = normalizeMediaUrl(match[0]);
    if (!normalized || seen.has(normalized)) continue;
    const kind = mediaKindFromUrl(normalized, platform);
    if (!kind) continue;
    seen.add(normalized);
    candidates.push({ url: normalized, kind });
  }
  return candidates;
}

function normalizeEmbeddedUrlText(text) {
  return text
    .replace(/\\u002[Ff]/g, "/")
    .replace(/\\u0026/g, "&")
    .replace(/\\u003[Dd]/g, "=")
    .replace(/\\u003[Ff]/g, "?")
    .replace(/\\\//g, "/")
    .replace(/&amp;/g, "&");
}

function normalizeMediaUrl(url) {
  let value = url.replace(/\\\//g, "/").replace(TRAILING_URL_PUNCTUATION_RE, "");
  if (value.startsWith("//")) value = `https:${value}`;
  if (value.startsWith("http:\\/\\/") || value.startsWith("https:\\/\\/")) value = value.replace(/\\\//g, "/");
  try {
    return new URL(value).href;
  } catch {
    return "";
  }
}

function mediaKindFromUrl(url, platform = "") {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return "";
  }
  const lowered = `${parsed.hostname}${parsed.pathname}${parsed.search}`.toLowerCase();
  const path = parsed.pathname.toLowerCase();
  if (IMAGE_EXTENSIONS.some((ext) => path.includes(ext))) {
    if (platform === "xiaohongshu" && /avatar|icon|emoji|sprite/.test(lowered)) return "";
    return "image";
  }
  if (VIDEO_EXTENSIONS.some((ext) => path.includes(ext))) return "video";
  if (/mime_type=video|\/video\/tos\/|douyinvod|sns-video|googlevideo|videoplayback/.test(lowered)) return "video";
  if (/sns-webpic|sns-img|douyinpic|byteimg/.test(lowered)) return "image";
  return "";
}

async function downloadDirectUrl(url, filename) {
  try {
    const response = await fetch(url, { mode: "cors", credentials: "include" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    triggerBlobDownload(blob, filename);
    return `已保存 ${filename}`;
  } catch {
    triggerAnchorDownload(url, filename);
    return "已打开下载链接；如果浏览器没有保存文件，说明该跨域地址禁止网页读取。";
  }
}

function triggerBlobDownload(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

function triggerAnchorDownload(url, filename) {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.target = "_blank";
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function suggestedFileName(task, opts, kind, index) {
  const base = safeFileStem(opts.outputName || task.itemId || task.platform || "media");
  const suffix = kind === "image" ? ".jpg" : ".mp4";
  const numbered = index > 1 ? `${base}_${String(index).padStart(2, "0")}` : base;
  if (/\.[a-z0-9]{2,5}$/i.test(numbered)) return numbered;
  return `${numbered}${suffix}`;
}

function safeFileStem(value) {
  return String(value).replace(/\.[a-z0-9]{2,5}$/i, "").replace(/[\\/:*?"<>|]+/g, "_").trim() || "media";
}

function statusLabel(status) {
  return { pending: "待执行", running: "执行中", done: "完成", failed: "失败" }[status] || "待执行";
}

function statusClass(status) {
  return { running: "running", done: "done", failed: "failed" }[status] || "";
}

function cryptoId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function fallbackCopy(text) {
  const area = document.createElement("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

function preprocessImage(file) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      const canvas = document.createElement("canvas");
      const scale = 2;
      canvas.width = image.naturalWidth * scale;
      canvas.height = image.naturalHeight * scale;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.imageSmoothingEnabled = true;
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
      const data = pixels.data;
      for (let index = 0; index < data.length; index += 4) {
        const gray = 0.299 * data[index] + 0.587 * data[index + 1] + 0.114 * data[index + 2];
        const contrast = (gray - 128) * 2 + 128;
        const value = contrast < 180 ? 0 : 255;
        data[index] = value;
        data[index + 1] = value;
        data[index + 2] = value;
      }
      context.putImageData(pixels, 0, 0);
      canvas.toBlob((blob) => {
        URL.revokeObjectURL(url);
        if (blob) resolve(blob);
        else reject(new Error("preprocess failed"));
      }, "image/png");
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("image load failed"));
    };
    image.src = url;
  });
}

function normalizeOcrText(text) {
  const lines = text.replace(/\f/g, "").split(/\r?\n/).map((line) => line.trimEnd());
  while (lines.length && !lines[0].trim()) lines.shift();
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  return lines.join("\n");
}

function textFromRecognitionResult(data, minLineConfidence) {
  const lines = Array.isArray(data?.lines) ? data.lines : [];
  if (!lines.length) return data?.text || "";
  const threshold = Number(minLineConfidence);
  return lines
    .filter((line) => threshold < 0 || Number(line.confidence ?? 0) >= threshold)
    .map((line) => line.text || "")
    .join("\n");
}

function formatBytes(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / 1024 / 1024).toFixed(1)} MiB`;
}

createRoot(document.getElementById("root")).render(<App />);
