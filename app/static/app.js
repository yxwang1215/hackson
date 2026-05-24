const itemsList = document.querySelector("#itemsList");
const appShell = document.querySelector("#appShell");
const itemTemplate = document.querySelector("#itemTemplate");
const form = document.querySelector("#narrativeForm");
const addItemButton = document.querySelector("#addItemButton");
const sampleButton = document.querySelector("#sampleButton");
const resetButton = document.querySelector("#resetButton");
const historyButton = document.querySelector("#historyButton");
const clearHistoryButton = document.querySelector("#clearHistoryButton");
const submitButton = document.querySelector("#submitButton");
const storyOutput = document.querySelector("#storyOutput");
const previewEmpty = document.querySelector("#previewEmpty");
const historyPanel = document.querySelector("#historyPanel");
const historyList = document.querySelector("#historyList");
const previewTitle = document.querySelector("#previewTitle");
const enterPreviewButton = document.querySelector("#enterPreviewButton");
const messageBox = document.querySelector("#messageBox");
const serviceStatus = document.querySelector("#serviceStatus");
const toneSelect = document.querySelector("#toneSelect");
const languageSelect = document.querySelector("#languageSelect");
const lineCountInput = document.querySelector("#lineCountInput");
const folderButton = document.querySelector("#folderButton");
const folderInput = document.querySelector("#folderInput");
const folderSummary = document.querySelector("#folderSummary");
const folderPathInput = document.querySelector("#folderPathInput");
const folderPathButton = document.querySelector("#folderPathButton");
const timelinePager = document.querySelector("#timelinePager");
const timelineGroupSummary = document.querySelector("#timelineGroupSummary");
const timelineTotalSummary = document.querySelector("#timelineTotalSummary");
const timelineGroupButtons = document.querySelector("#timelineGroupButtons");

const sampleItems = [
  {
    time: "2026年4月",
    desc: "我的孩子会爬了",
  },
  {
    time: "2026年12月",
    desc: "我的孩子会走路了",
  },
];

const imageUrls = new WeakMap();
const rowFiles = new WeakMap();
const SLIDE_DURATION_STORAGE_KEY = "hackson-slide-duration-sec";
const DEFAULT_SLIDE_DURATION_SEC = 1.8;
const MIN_SLIDE_DURATION_SEC = 0.8;
const MAX_SLIDE_DURATION_SEC = 6;
const ITEMS_PER_GROUP = 5;
const HISTORY_STORAGE_KEY = "ai-time-narrative-history";
const MAX_HISTORY_ITEMS = 12;
const MAX_HISTORY_IMAGE_BYTES = 4 * 1024 * 1024;
let currentTimelineGroup = 0;
let historyRecords = loadHistoryRecords();
let musicTracks = [];
let previewAudio = null;
let ffmpegAvailable = false;
let xhsPublishStatus = { available: true, provider: "mock", formats: ["carousel", "video"] };
let reportState = {
  current: 0,
  total: 0,
  timer: null,
  pages: [],
  progressItems: [],
  counter: null,
  playButton: null,
  shell: null,
  previewTitle: "",
};

function enterPreviewMode() {
  document.body.classList.add("preview-mode");
  appShell?.classList.add("preview-mode");
  syncPreviewChrome();
}

function exitPreviewMode() {
  stopPreviewAudio();
  document.body.classList.remove("preview-mode");
  appShell?.classList.remove("preview-mode");
  syncPreviewChrome();
}

function hasGeneratedStory() {
  return reportState.total > 0 && storyOutput.children.length > 0;
}

function syncPreviewChrome() {
  const inPreviewMode = document.body.classList.contains("preview-mode");
  const hasStory = hasGeneratedStory();
  const showingHistory = !historyPanel.hidden;

  enterPreviewButton.hidden = !hasStory || inPreviewMode || showingHistory;
  storyOutput.hidden = !hasStory || showingHistory;
  previewEmpty.hidden = hasStory || showingHistory;
  previewTitle.textContent = showingHistory
    ? "历史记录"
    : hasStory
      ? inPreviewMode
        ? reportState.previewTitle || "已生成纪念册"
        : "已生成纪念册"
      : "等待生成";
}

function openPreviewMode() {
  if (!hasGeneratedStory()) {
    showMessage("请先生成纪念册。");
    return;
  }
  hideMessage();
  enterPreviewMode();
}

function createItemRow(data = {}) {
  const node = itemTemplate.content.firstElementChild.cloneNode(true);
  const timeInput = node.querySelector(".time-input");
  const descInput = node.querySelector(".desc-input");
  const imageInput = node.querySelector(".image-input");
  const imagePreview = node.querySelector(".image-preview");
  const uploadBox = node.querySelector(".upload-box");
  const removeButton = node.querySelector(".remove-button");

  timeInput.value = data.time || "";
  descInput.value = data.desc || "";

  imageInput.addEventListener("change", () => {
    setRowImage(node, imageInput.files?.[0] || null);
  });

  removeButton.addEventListener("click", () => {
    if (itemsList.children.length <= 1) {
      showMessage("至少保留一页照片。");
      return;
    }
    revokeRowImage(node);
    node.remove();
    updateIndexes();
  });

  itemsList.append(node);
  if (data.file) {
    setRowImage(node, data.file);
  }
  updateIndexes();
  showTimelineGroup(Math.floor((itemsList.children.length - 1) / ITEMS_PER_GROUP));
}

function setRowImage(row, file) {
  const imageInput = row.querySelector(".image-input");
  const imagePreview = row.querySelector(".image-preview");
  const uploadBox = row.querySelector(".upload-box");
  const placeholder = row.querySelector(".upload-placeholder span");

  revokeRowImage(row);

  if (!file) {
    rowFiles.delete(row);
    imagePreview.hidden = true;
    imagePreview.removeAttribute("src");
    uploadBox.classList.remove("has-image");
    placeholder.textContent = "选择照片";
    return;
  }

  const nextUrl = URL.createObjectURL(file);
  rowFiles.set(row, file);
  imageUrls.set(imageInput, nextUrl);
  imagePreview.src = nextUrl;
  imagePreview.hidden = false;
  uploadBox.classList.add("has-image");
  placeholder.textContent = file.name;
}

function updateIndexes() {
  [...itemsList.children].forEach((row, index) => {
    row.querySelector(".item-index").textContent = String(index + 1);
  });
  renderTimelinePager();
}

function renderTimelinePager() {
  const rows = [...itemsList.children];
  const groupCount = Math.max(1, Math.ceil(rows.length / ITEMS_PER_GROUP));
  currentTimelineGroup = Math.min(currentTimelineGroup, groupCount - 1);
  timelinePager.hidden = rows.length <= ITEMS_PER_GROUP;
  timelineGroupSummary.textContent = `第 ${currentTimelineGroup + 1} 组 / 共 ${groupCount} 组`;
  timelineTotalSummary.textContent = `${rows.length} 张照片，每组最多 ${ITEMS_PER_GROUP} 张`;

  timelineGroupButtons.replaceChildren();
  for (let index = 0; index < groupCount; index += 1) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-group-button";
    button.classList.toggle("active", index === currentTimelineGroup);
    button.textContent = String(index + 1);
    button.addEventListener("click", () => showTimelineGroup(index));
    timelineGroupButtons.append(button);
  }

  rows.forEach((row, index) => {
    const groupIndex = Math.floor(index / ITEMS_PER_GROUP);
    row.hidden = groupIndex !== currentTimelineGroup;
  });
}

function showTimelineGroup(groupIndex) {
  const groupCount = Math.max(1, Math.ceil(itemsList.children.length / ITEMS_PER_GROUP));
  currentTimelineGroup = Math.min(Math.max(groupIndex, 0), groupCount - 1);
  renderTimelinePager();
}

function revokeRowImage(row) {
  const imageInput = row.querySelector(".image-input");
  const oldUrl = imageUrls.get(imageInput);
  if (oldUrl) {
    URL.revokeObjectURL(oldUrl);
    imageUrls.delete(imageInput);
  }
  rowFiles.delete(row);
}

function collectPayload() {
  const rows = [...itemsList.children];
  const items = [];
  const images = [];

  rows.forEach((row, index) => {
    const time = row.querySelector(".time-input").value.trim();
    const desc = row.querySelector(".desc-input").value.trim();
    const imageFile = rowFiles.get(row) || row.querySelector(".image-input").files?.[0] || null;

    if (!imageFile) {
      throw new Error(`第 ${index + 1} 页需要选择照片。`);
    }

    items.push({
      time: time || `第 ${index + 1} 张`,
      desc,
      image_analysis: "",
      image_filename: imageFile.name,
      image_mime_type: imageFile.type || "image/jpeg",
    });
    images.push(imageFile);
  });

  return { items, images };
}

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  folderPathButton.disabled = isLoading;
  submitButton.textContent = isLoading ? "生成中..." : "生成纪念册";
  folderPathButton.textContent = isLoading ? "分析中..." : "分析文件夹";
}

function showMessage(message, type = "error") {
  messageBox.textContent = message;
  messageBox.classList.toggle("info", type === "info");
  messageBox.hidden = false;
}

function hideMessage() {
  messageBox.hidden = true;
  messageBox.textContent = "";
  messageBox.classList.remove("info");
}

function loadHistoryRecords() {
  try {
    const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
    const records = raw ? JSON.parse(raw) : [];
    return Array.isArray(records) ? records : [];
  } catch {
    return [];
  }
}

function persistHistoryRecords() {
  const recordsForStorage = historyRecords.map((record) => ({
    ...record,
    imageSources: (record.imageSources || []).filter((source) => !source.startsWith("blob:")),
  }));

  try {
    window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(recordsForStorage));
  } catch {
    showMessage("历史记录已保留在当前页面，但图片太大，无法全部写入浏览器存储。", "info");
  }
}

function addHistoryRecord(data, imageSources = []) {
  const snapshot = JSON.parse(JSON.stringify(data));
  const timeline = snapshot.timeline || [];
  const record = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    createdAt: new Date().toISOString(),
    title: snapshot.title || "未命名纪念册",
    count: timeline.length,
    imageSources,
    data: snapshot,
  };

  historyRecords = [record, ...historyRecords].slice(0, MAX_HISTORY_ITEMS);
  persistHistoryRecords();
  renderHistoryList();
}

function toggleHistoryPanel(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : historyPanel.hidden;
  stopAutoplay();
  exitPreviewMode();
  historyPanel.hidden = !shouldOpen;
  syncPreviewChrome();
  hideMessage();
  renderHistoryList();
}

function renderHistoryList() {
  if (!historyList) {
    return;
  }

  historyList.replaceChildren();
  if (!historyRecords.length) {
    const empty = document.createElement("p");
    empty.className = "history-empty";
    empty.textContent = "暂无历史生成记录。生成纪念册后会自动保存到这里。";
    historyList.append(empty);
    return;
  }

  historyRecords.forEach((record) => {
    const item = document.createElement("button");
    item.className = "history-item";
    item.type = "button";

    const title = document.createElement("strong");
    title.textContent = record.title;

    const meta = document.createElement("span");
    meta.textContent = `${formatHistoryTime(record.createdAt)} · ${record.count || 0} 张照片`;

    const action = document.createElement("em");
    action.textContent = "重新播放";

    item.append(title, meta, action);
    item.addEventListener("click", () => replayHistoryRecord(record.id));
    historyList.append(item);
  });
}

function replayHistoryRecord(recordId) {
  const record = historyRecords.find((item) => item.id === recordId);
  if (!record) {
    showMessage("这条历史记录不存在。");
    return;
  }
  historyPanel.hidden = true;
  syncPreviewChrome();
  renderStory(record.data, {
    imageSources: record.imageSources || [],
    saveHistory: false,
  });
}

function clearHistory() {
  historyRecords = [];
  window.localStorage.removeItem(HISTORY_STORAGE_KEY);
  renderHistoryList();
  historyPanel.hidden = false;
  syncPreviewChrome();
}

function formatHistoryTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "")));
    reader.addEventListener("error", () => reject(reader.error || new Error("图片读取失败")));
    reader.readAsDataURL(file);
  });
}

async function buildUploadHistoryImages(files) {
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  if (totalBytes > MAX_HISTORY_IMAGE_BYTES) {
    return [];
  }

  try {
    return await Promise.all(files.map(readFileAsDataUrl));
  } catch {
    return [];
  }
}

function lineBlock(lines = []) {
  const wrapper = document.createElement("div");
  wrapper.className = "line-block";
  lines.forEach((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    wrapper.append(p);
  });
  return wrapper;
}

function renderStory(data, options = {}) {
  const uploadedImages = [...itemsList.querySelectorAll(".image-input")].map((input) => imageUrls.get(input));
  const sourceImages = options.imageSources?.length ? options.imageSources : data.render_hints?.source_images || [];
  const localImages = sourceImages.length ? sourceImages : uploadedImages;
  stopAutoplay();
  storyOutput.replaceChildren();

  const shell = document.createElement("div");
  shell.className = "report-shell";

  const progress = document.createElement("div");
  progress.className = "report-progress";

  const stage = document.createElement("div");
  stage.className = "report-stage";

  const pages = buildReportPages(data, localImages);
  const progressItems = pages.map(() => {
    const item = document.createElement("span");
    item.className = "progress-segment";
    progress.append(item);
    return item;
  });
  pages.forEach((page) => stage.append(page));

  const controls = document.createElement("nav");
  controls.className = "report-controls";

  const prevButton = document.createElement("button");
  prevButton.className = "deck-button";
  prevButton.type = "button";
  prevButton.textContent = "上一页";

  const playButton = document.createElement("button");
  playButton.className = "deck-button primary-deck-button";
  playButton.type = "button";
  playButton.textContent = "自动播放";

  const nextButton = document.createElement("button");
  nextButton.className = "deck-button";
  nextButton.type = "button";
  nextButton.textContent = "下一页";

  const exitButton = document.createElement("button");
  exitButton.className = "deck-button";
  exitButton.type = "button";
  exitButton.textContent = "返回编辑";

  const counter = document.createElement("span");
  counter.className = "deck-counter";

  prevButton.addEventListener("click", () => showReportPage(reportState.current - 1, "prev"));
  nextButton.addEventListener("click", () => showReportPage(reportState.current + 1, "next"));
  playButton.addEventListener("click", toggleAutoplay);
  exitButton.addEventListener("click", () => {
    stopAutoplay();
    exitPreviewMode();
    showMessage("已退出全屏预览。", "info");
  });

  const speedControl = buildSpeedControl();
  const exportBar = buildExportControls();
  controls.append(exitButton, prevButton, playButton, nextButton, counter, speedControl.bar, exportBar);
  shell.append(progress, stage, controls);
  wireSwipeNavigation(shell);
  storyOutput.append(shell);
  applySlideDurationToShell(shell);

  const assetInfo = parseAssetInfo(data.render_hints || {});

  reportState = {
    current: 0,
    total: pages.length,
    timer: null,
    pages,
    progressItems,
    counter,
    playButton,
    shell,
    previewTitle: data.title || "年度汇报",
    storyData: data,
    assetToken: assetInfo.token,
    assetSource: assetInfo.source,
    musicSelect: exportBar.querySelector(".export-music-select"),
    exportButton: exportBar.querySelector(".export-mp4-button"),
    xhsButton: exportBar.querySelector(".xhs-publish-button"),
    xhsFormatSelect: exportBar.querySelector(".xhs-format-select"),
    speedInput: speedControl.input,
    speedValueLabel: speedControl.valueLabel,
  };
  showReportPage(0, "next");

  historyPanel.hidden = true;
  if (options.saveHistory !== false) {
    addHistoryRecord(data, localImages.filter(Boolean));
  }
  enterPreviewMode();
}

function handleFolderUpload() {
  const files = [...(folderInput.files || [])].filter(isImageFile);
  if (!files.length) {
    showMessage("这个文件夹里没有可识别的图片。");
    return;
  }

  files.sort((a, b) => {
    const pathA = a.webkitRelativePath || a.name;
    const pathB = b.webkitRelativePath || b.name;
    return pathA.localeCompare(pathB, "zh-Hans-CN");
  });

  stopAutoplay();
  clearRows();
  files.forEach((file, index) => {
    createItemRow({
      time: formatFileTime(file, index),
      desc: "",
      file,
    });
  });

  folderSummary.textContent = `已导入 ${files.length} 张图片，将按文件夹路径顺序分析。`;
  storyOutput.replaceChildren();
  reportState = {
    current: 0,
    total: 0,
    timer: null,
    pages: [],
    progressItems: [],
    counter: null,
    playButton: null,
    shell: null,
    previewTitle: "",
  };
  syncPreviewChrome();
  hideMessage();
  showMessage(`已导入 ${files.length} 张图片，点击“生成纪念册”开始 VLM 分析。`, "info");
}

function isImageFile(file) {
  if (file.type.startsWith("image/")) {
    return true;
  }
  return /\.(avif|bmp|gif|heic|heif|jpe?g|png|webp)$/i.test(file.name);
}

function formatFileTime(file, index) {
  if (!file.lastModified) {
    return `第 ${index + 1} 张`;
  }
  const date = new Date(file.lastModified);
  if (Number.isNaN(date.getTime())) {
    return `第 ${index + 1} 张`;
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

const MEMORY_LAYOUTS = [
  "layout-text-right",
  "layout-text-left",
  "layout-text-bottom",
  "layout-text-top",
];

function pickMemoryLayout(index) {
  return MEMORY_LAYOUTS[index % MEMORY_LAYOUTS.length];
}

function buildReportPages(data, localImages) {
  const timeline = data.timeline || [];
  const pages = [buildCoverPage(data, timeline)];

  timeline.forEach((node, index) => {
    pages.push(buildMemoryPage(node, localImages[index], index, timeline.length));
  });

  pages.push(buildConclusionPage(data));
  return pages;
}

function buildCoverPage(data, timeline) {
  const page = document.createElement("section");
  page.className = "report-page cover-page";

  const kinetic = document.createElement("div");
  kinetic.className = "kinetic-bg";
  page.append(kinetic);

  const content = document.createElement("div");
  content.className = "cover-content";

  const eyebrow = document.createElement("p");
  eyebrow.className = "report-eyebrow";
  eyebrow.textContent = "2026 MEMORY RECAP";

  const title = document.createElement("h2");
  title.className = "report-title";
  title.textContent = data.title || "成长纪念册";

  const intro = lineBlock(data.intro?.lines || []);
  intro.classList.add("report-intro");

  const metrics = document.createElement("div");
  metrics.className = "report-metrics";
  metrics.append(buildMetric("照片", timeline.length), buildMetric("标签", countLabels(timeline)), buildMetric("章节", timeline.length + 2));

  const labelCloud = buildLabelCloud(timeline);
  content.append(eyebrow, title, intro, metrics);
  if (labelCloud) {
    content.append(labelCloud);
  }

  page.append(content);
  return page;
}

function buildMemoryPage(node, imageUrl, index, total) {
  const page = document.createElement("section");
  page.className = `report-page memory-page ${pickMemoryLayout(index)}`;

  if (imageUrl) {
    const backdrop = document.createElement("img");
    backdrop.className = "memory-backdrop";
    backdrop.alt = "";
    backdrop.src = imageUrl;
    page.append(backdrop);
  }

  const photo = document.createElement("figure");
  photo.className = "memory-photo";
  if (imageUrl) {
    const image = document.createElement("img");
    image.alt = node.desc || node.headline || `第 ${index + 1} 页照片`;
    image.src = imageUrl;
    photo.append(image);
  }

  const copy = document.createElement("div");
  copy.className = "memory-copy";

  const meta = document.createElement("div");
  meta.className = "memory-meta";

  const step = document.createElement("span");
  step.className = "step-chip";
  step.textContent = `${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`;

  const time = document.createElement("span");
  time.className = "time-chip";
  time.textContent = node.time || `第 ${index + 1} 页`;
  meta.append(step, time);

  const headline = document.createElement("h3");
  headline.textContent = node.headline || node.desc || "这一页的记录";

  const tags = document.createElement("div");
  tags.className = "tag-rush";
  (node.tags || []).forEach((tag, tagIndex) => {
    const tagChip = document.createElement("span");
    tagChip.className = "tag-chip";
    tagChip.style.setProperty("--tag-delay", `${160 + tagIndex * 90}ms`);
    tagChip.textContent = tag;
    tags.append(tagChip);
  });

  copy.append(meta, headline, tags);

  if (node.image_analysis) {
    const analysis = document.createElement("p");
    analysis.className = "analysis-line";
    analysis.textContent = node.image_analysis;
    copy.append(analysis);
  }

  const paragraph = lineBlock(node.paragraph?.lines || []);
  paragraph.classList.add("memory-lines");
  copy.append(paragraph);

  if (node.transition_next) {
    const transition = document.createElement("p");
    transition.className = "transition";
    transition.textContent = node.transition_next;
    copy.append(transition);
  }

  page.append(photo, copy);
  return page;
}

function buildConclusionPage(data) {
  const page = document.createElement("section");
  page.className = "report-page conclusion-page";

  const ring = document.createElement("div");
  ring.className = "final-ring";

  const content = document.createElement("div");
  content.className = "conclusion-content";

  const eyebrow = document.createElement("p");
  eyebrow.className = "report-eyebrow";
  eyebrow.textContent = "FINAL";

  const title = document.createElement("h2");
  title.className = "report-title";
  title.textContent = "这一段，被好好保存";

  const conclusion = lineBlock(data.conclusion?.lines || []);
  conclusion.classList.add("report-intro");

  content.append(eyebrow, title, conclusion);
  page.append(ring, content);
  return page;
}

function buildLabelCloud(timeline) {
  const labels = [...new Set(timeline.flatMap((node) => node.tags || []).filter(Boolean))];
  if (!labels.length) {
    return null;
  }

  const cloud = document.createElement("div");
  cloud.className = "label-cloud";
  labels.forEach((label) => {
    const chip = document.createElement("span");
    chip.className = "label-chip";
    chip.textContent = label;
    cloud.append(chip);
  });
  return cloud;
}

function buildMetric(label, value) {
  const metric = document.createElement("div");
  metric.className = "metric-card";

  const valueNode = document.createElement("strong");
  valueNode.textContent = String(value);

  const labelNode = document.createElement("span");
  labelNode.textContent = label;

  metric.append(valueNode, labelNode);
  return metric;
}

function countLabels(timeline) {
  return new Set(timeline.flatMap((node) => node.tags || []).filter(Boolean)).size;
}

function getSlideDurationSec() {
  const stored = Number.parseFloat(localStorage.getItem(SLIDE_DURATION_STORAGE_KEY) || "");
  if (Number.isFinite(stored)) {
    return clampSlideDuration(stored);
  }
  return DEFAULT_SLIDE_DURATION_SEC;
}

function setSlideDurationSec(seconds) {
  const normalized = clampSlideDuration(seconds);
  localStorage.setItem(SLIDE_DURATION_STORAGE_KEY, String(normalized));
  return normalized;
}

function clampSlideDuration(seconds) {
  return Math.min(MAX_SLIDE_DURATION_SEC, Math.max(MIN_SLIDE_DURATION_SEC, Number(seconds) || DEFAULT_SLIDE_DURATION_SEC));
}

function getSlideDurationMs() {
  return Math.round(getSlideDurationSec() * 1000);
}

function formatSlideDurationLabel(seconds) {
  return `${Number(seconds).toFixed(1)}s`;
}

function applySlideDurationToShell(shell, seconds = getSlideDurationSec()) {
  if (!shell) {
    return;
  }
  const durationMs = Math.round(seconds * 1000);
  const transitionMs = Math.max(320, Math.round(durationMs * 0.42));
  shell.style.setProperty("--slide-duration", `${durationMs}ms`);
  shell.style.setProperty("--slide-transition", `${transitionMs}ms`);
}

function refreshProgressAnimation() {
  if (!reportState.shell?.classList.contains("playing")) {
    return;
  }
  const activeItem = reportState.progressItems[reportState.current];
  if (!activeItem) {
    return;
  }
  activeItem.classList.remove("active");
  void activeItem.offsetWidth;
  activeItem.classList.add("active");
}

function restartAutoplayIfPlaying() {
  if (!reportState.timer) {
    return;
  }
  window.clearInterval(reportState.timer);
  reportState.timer = window.setInterval(() => {
    showReportPage(reportState.current + 1, "next");
  }, getSlideDurationMs());
  refreshProgressAnimation();
}

function handleSlideDurationChange(nextValue) {
  const seconds = setSlideDurationSec(Number.parseFloat(nextValue));
  applySlideDurationToShell(reportState.shell, seconds);
  if (reportState.speedValueLabel) {
    reportState.speedValueLabel.textContent = formatSlideDurationLabel(seconds);
  }
  restartAutoplayIfPlaying();
}

function showReportPage(index, direction = "next") {
  if (!reportState.total) {
    return;
  }

  const nextIndex = (index + reportState.total) % reportState.total;
  reportState.current = nextIndex;
  reportState.shell.dataset.direction = direction;

  reportState.pages.forEach((page, pageIndex) => {
    page.classList.toggle("active", pageIndex === nextIndex);
    page.classList.toggle("before", pageIndex < nextIndex);
    page.classList.toggle("after", pageIndex > nextIndex);
  });

  reportState.progressItems.forEach((item, itemIndex) => {
    item.classList.toggle("active", itemIndex === nextIndex);
    item.classList.toggle("passed", itemIndex < nextIndex);
  });

  reportState.counter.textContent = `${String(nextIndex + 1).padStart(2, "0")} / ${String(reportState.total).padStart(2, "0")}`;
}

function getSelectedMusicTrack() {
  const musicId = reportState.musicSelect?.value || "";
  if (!musicId) {
    return null;
  }
  return musicTracks.find((track) => track.id === musicId) || null;
}

function ensurePreviewAudio() {
  if (previewAudio) {
    return previewAudio;
  }

  previewAudio = new Audio();
  previewAudio.loop = true;
  previewAudio.preload = "auto";
  previewAudio.volume = 0.85;
  return previewAudio;
}

function resolveMusicUrl(url) {
  return new URL(url, window.location.origin).href;
}

function startPreviewAudio() {
  const track = getSelectedMusicTrack();
  if (!track?.url) {
    return;
  }

  const audio = ensurePreviewAudio();
  const nextSrc = resolveMusicUrl(track.url);
  if (audio.src !== nextSrc) {
    audio.src = track.url;
  }

  const playPromise = audio.play();
  if (playPromise) {
    playPromise.catch(() => {
      showMessage("浏览器未能播放背景音乐，请再次点击「自动播放」。", "info");
    });
  }
}

function pausePreviewAudio() {
  previewAudio?.pause();
}

function stopPreviewAudio() {
  if (!previewAudio) {
    return;
  }
  previewAudio.pause();
  previewAudio.currentTime = 0;
}

function pauseAutoplay() {
  if (reportState.timer) {
    window.clearInterval(reportState.timer);
  }
  if (reportState.playButton) {
    reportState.playButton.textContent = "自动播放";
  }
  if (reportState.shell) {
    reportState.shell.classList.remove("playing");
  }
  reportState.timer = null;
  pausePreviewAudio();
}

function toggleAutoplay() {
  if (reportState.timer) {
    pauseAutoplay();
    return;
  }

  reportState.playButton.textContent = "暂停";
  reportState.shell.classList.add("playing");
  startPreviewAudio();
  reportState.timer = window.setInterval(() => {
    showReportPage(reportState.current + 1, "next");
  }, getSlideDurationMs());
}

function stopAutoplay() {
  pauseAutoplay();
  stopPreviewAudio();
}

function wireSwipeNavigation(shell) {
  let startX = 0;
  shell.addEventListener("pointerdown", (event) => {
    startX = event.clientX;
  });
  shell.addEventListener("pointerup", (event) => {
    const distance = event.clientX - startX;
    if (Math.abs(distance) < 48) {
      return;
    }
    showReportPage(reportState.current + (distance < 0 ? 1 : -1), distance < 0 ? "next" : "prev");
  });
}

function parseAssetInfo(renderHints = {}) {
  if (renderHints.asset_token) {
    return {
      token: renderHints.asset_token,
      source: renderHints.asset_source || "folder",
    };
  }

  const first = (renderHints.source_images || [])[0] || "";
  const folderMatch = String(first).match(/\/folder-assets\/([^/]+)\//);
  if (folderMatch) {
    return { token: folderMatch[1], source: "folder" };
  }
  const uploadMatch = String(first).match(/\/upload-assets\/([^/]+)\//);
  if (uploadMatch) {
    return { token: uploadMatch[1], source: "upload" };
  }
  return { token: "", source: "" };
}

function buildSpeedControl() {
  const bar = document.createElement("div");
  bar.className = "speed-control";

  const label = document.createElement("span");
  label.className = "export-label";
  label.textContent = "每页";

  const input = document.createElement("input");
  input.type = "range";
  input.className = "speed-slider";
  input.min = String(MIN_SLIDE_DURATION_SEC);
  input.max = String(MAX_SLIDE_DURATION_SEC);
  input.step = "0.2";
  input.value = String(getSlideDurationSec());
  input.title = "调整自动播放与 MP4 导出时每页停留时长";
  input.addEventListener("input", () => handleSlideDurationChange(input.value));

  const valueLabel = document.createElement("span");
  valueLabel.className = "speed-value";
  valueLabel.textContent = formatSlideDurationLabel(input.value);

  bar.append(label, input, valueLabel);
  return { bar, input, valueLabel };
}

function buildExportControls() {
  const exportBar = document.createElement("div");
  exportBar.className = "export-bar";

  const label = document.createElement("span");
  label.className = "export-label";
  label.textContent = "音乐";

  const musicSelect = document.createElement("select");
  musicSelect.className = "export-music-select";
  musicSelect.title = "预览播放与 MP4 导出使用的背景音乐";
  populateMusicSelect(musicSelect);
  musicSelect.addEventListener("change", () => {
    if (reportState.timer) {
      startPreviewAudio();
    }
  });

  const exportButton = document.createElement("button");
  exportButton.className = "deck-button export-mp4-button";
  exportButton.type = "button";
  exportButton.textContent = "导出 MP4";
  exportButton.disabled = !ffmpegAvailable || !musicTracks.length;
  exportButton.title = ffmpegAvailable
    ? "导出带背景音乐的纪念册视频"
    : "服务器未安装 ffmpeg，暂无法导出 MP4";
  exportButton.addEventListener("click", exportCurrentStoryMp4);

  const xhsFormatSelect = document.createElement("select");
  xhsFormatSelect.className = "export-music-select xhs-format-select";
  xhsFormatSelect.title = "选择小红书发布形式";
  [
    ["carousel", "图文"],
    ["video", "视频"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    xhsFormatSelect.append(option);
  });

  const xhsButton = document.createElement("button");
  xhsButton.className = "deck-button xhs-publish-button";
  xhsButton.type = "button";
  xhsButton.textContent = "发小红书";
  xhsButton.title = "打包图文/视频并发布到小红书";
  xhsButton.addEventListener("click", publishCurrentStoryToXhs);

  exportBar.append(label, musicSelect, exportButton, xhsFormatSelect, xhsButton);
  exportBar.dataset.xhsFormatSelect = "1";
  return exportBar;
}

function populateMusicSelect(selectNode) {
  selectNode.replaceChildren();
  if (!musicTracks.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "暂无音乐";
    selectNode.append(option);
    return;
  }

  musicTracks.forEach((track, index) => {
    const option = document.createElement("option");
    option.value = track.id;
    option.textContent = track.name;
    option.selected = index === 0;
    selectNode.append(option);
  });
}

async function loadMusicTracks() {
  try {
    const response = await fetch("/export/music-tracks");
    if (!response.ok) {
      throw new Error("music list unavailable");
    }
    const data = await response.json();
    musicTracks = data.tracks || [];
    ffmpegAvailable = Boolean(data.ffmpeg_available);
  } catch {
    musicTracks = [];
    ffmpegAvailable = false;
  }
}

async function loadXhsPublishStatus() {
  try {
    const response = await fetch("/publish/xiaohongshu/status");
    if (!response.ok) {
      throw new Error("xhs status unavailable");
    }
    xhsPublishStatus = await response.json();
  } catch {
    xhsPublishStatus = { available: true, provider: "mock", formats: ["carousel", "video"] };
  }
}

function ensureXhsModal() {
  let modal = document.querySelector("#xhsPublishModal");
  if (modal) {
    return modal;
  }

  modal = document.createElement("div");
  modal.id = "xhsPublishModal";
  modal.className = "xhs-modal";
  modal.hidden = true;
  modal.innerHTML = `
    <div class="xhs-modal-backdrop" data-xhs-close></div>
    <section class="xhs-modal-panel" role="dialog" aria-labelledby="xhsModalTitle" aria-modal="true">
      <header class="xhs-modal-header">
        <div>
          <p class="eyebrow">Xiaohongshu</p>
          <h3 id="xhsModalTitle">发布到小红书</h3>
        </div>
        <button class="icon-button xhs-modal-close" type="button" data-xhs-close aria-label="关闭">×</button>
      </header>
      <div class="xhs-modal-body">
        <p class="xhs-modal-status" id="xhsModalStatus"></p>
        <div class="xhs-qr-wrap" id="xhsQrWrap" hidden>
          <img id="xhsQrImage" alt="小红书发布二维码" />
          <p>用小红书 App 扫码完成发布</p>
        </div>
        <label class="xhs-field">
          <span>标题</span>
          <div class="xhs-copy-row">
            <textarea id="xhsTitleField" rows="2" readonly></textarea>
            <button class="secondary-button compact" type="button" data-xhs-copy="xhsTitleField">复制</button>
          </div>
        </label>
        <label class="xhs-field">
          <span>正文</span>
          <div class="xhs-copy-row">
            <textarea id="xhsContentField" rows="8" readonly></textarea>
            <button class="secondary-button compact" type="button" data-xhs-copy="xhsContentField">复制</button>
          </div>
        </label>
        <div class="xhs-media-list" id="xhsMediaList"></div>
      </div>
      <footer class="xhs-modal-footer">
        <a class="deck-button primary-deck-button" id="xhsCreatorLink" href="https://creator.xiaohongshu.com/publish/publish?source=official" target="_blank" rel="noopener noreferrer">打开创作中心</a>
        <button class="deck-button" type="button" data-xhs-close>关闭</button>
      </footer>
    </section>
  `;

  modal.querySelectorAll("[data-xhs-close]").forEach((node) => {
    node.addEventListener("click", closeXhsModal);
  });
  modal.querySelectorAll("[data-xhs-copy]").forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-xhs-copy");
      const field = targetId ? document.querySelector(`#${targetId}`) : null;
      if (!field) {
        return;
      }
      navigator.clipboard.writeText(field.value).then(
        () => showMessage("已复制到剪贴板。", "info"),
        () => showMessage("复制失败，请手动选择文本。"),
      );
    });
  });

  document.body.append(modal);
  return modal;
}

function openXhsModal(payload = {}) {
  const modal = ensureXhsModal();
  const statusNode = modal.querySelector("#xhsModalStatus");
  const titleField = modal.querySelector("#xhsTitleField");
  const contentField = modal.querySelector("#xhsContentField");
  const qrWrap = modal.querySelector("#xhsQrWrap");
  const qrImage = modal.querySelector("#xhsQrImage");
  const mediaList = modal.querySelector("#xhsMediaList");
  const creatorLink = modal.querySelector("#xhsCreatorLink");

  statusNode.textContent = payload.instructions || "素材已准备好。";
  titleField.value = payload.title || "";
  contentField.value = payload.content || "";
  creatorLink.href = payload.creator_url || "https://creator.xiaohongshu.com/publish/publish?source=official";

  if (payload.qrcode) {
    qrWrap.hidden = false;
    qrImage.src = payload.qrcode;
  } else {
    qrWrap.hidden = true;
    qrImage.removeAttribute("src");
  }

  mediaList.replaceChildren();
  (payload.media_urls || []).forEach((url, index) => {
    const item = document.createElement("a");
    item.className = "xhs-media-item";
    item.href = url;
    item.target = "_blank";
    item.rel = "noopener noreferrer";
    const label = url.endsWith(".mp4") ? `下载视频 ${index + 1}` : `下载图片 ${index + 1}`;
    item.textContent = label;
    mediaList.append(item);
  });

  if (payload.publish_url) {
    const link = document.createElement("a");
    link.className = "xhs-media-item";
    link.href = payload.publish_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "打开发布页";
    mediaList.prepend(link);
  }

  modal.hidden = false;
}

function closeXhsModal() {
  const modal = document.querySelector("#xhsPublishModal");
  if (modal) {
    modal.hidden = true;
  }
}

async function publishCurrentStoryToXhs() {
  if (!reportState.storyData) {
    showMessage("请先生成纪念册。");
    return;
  }
  if (!reportState.assetToken) {
    showMessage("当前会话图片已失效，请重新生成纪念册后再发布。");
    return;
  }

  const modal = ensureXhsModal();
  const publishFormat = reportState.xhsFormatSelect?.value || "carousel";
  const musicId = reportState.musicSelect?.value || "";

  if (publishFormat === "video" && !musicId) {
    showMessage("视频笔记请先选择背景音乐。");
    return;
  }
  if (publishFormat === "video" && !ffmpegAvailable) {
    showMessage("视频发布需要 ffmpeg，请先安装：brew install ffmpeg");
    return;
  }

  stopAutoplay();
  showMessage("正在准备小红书素材...", "info");
  if (reportState.xhsButton) {
    reportState.xhsButton.disabled = true;
    reportState.xhsButton.textContent = "准备中...";
  }

  const formData = new FormData();
  formData.append("story_json", JSON.stringify(reportState.storyData));
  formData.append("asset_token", reportState.assetToken);
  formData.append("asset_source", reportState.assetSource || "folder");
  formData.append("publish_format", publishFormat);
  formData.append("slide_duration", String(getSlideDurationSec()));
  if (musicId) {
    formData.append("music_id", musicId);
  }

  try {
    const response = await fetch("/publish/xiaohongshu", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      let detail = "发布准备失败";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        detail = await response.text();
      }
      throw new Error(detail || "发布准备失败");
    }

    const payload = await response.json();
    hideMessage();
    openXhsModal(payload);
    showMessage(
      payload.status === "qr" ? "已生成小红书发布二维码。" : "小红书素材已准备好，请按弹窗指引发布。",
      "info",
    );
  } catch (error) {
    showMessage(error.message || "发布准备失败，请稍后再试。");
  } finally {
    if (reportState.xhsButton) {
      reportState.xhsButton.disabled = false;
      reportState.xhsButton.textContent = "发小红书";
    }
  }
}

async function exportCurrentStoryMp4() {
  if (!reportState.storyData) {
    showMessage("请先生成纪念册。");
    return;
  }
  if (!ffmpegAvailable) {
    showMessage("服务器未安装 ffmpeg，请先执行：brew install ffmpeg");
    return;
  }

  const musicId = reportState.musicSelect?.value || "";
  if (!musicId) {
    showMessage("请选择背景音乐。");
    return;
  }
  if (!reportState.assetToken) {
    showMessage("当前会话图片已失效，请重新生成纪念册后再导出。");
    return;
  }

  stopAutoplay();
  showMessage("正在导出 MP4，请稍候...", "info");
  reportState.exportButton.disabled = true;
  reportState.exportButton.textContent = "导出中...";

  const formData = new FormData();
  formData.append("story_json", JSON.stringify(reportState.storyData));
  formData.append("music_id", musicId);
  formData.append("asset_token", reportState.assetToken);
  formData.append("asset_source", reportState.assetSource || "folder");
  formData.append("slide_duration", String(getSlideDurationSec()));

  try {
    const response = await fetch("/export/mp4", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      let detail = "导出失败";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        detail = await response.text();
      }
      throw new Error(detail || "导出失败");
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${reportState.previewTitle || "memory-recap"}.mp4`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    hideMessage();
    showMessage("MP4 已导出。", "info");
  } catch (error) {
    showMessage(error.message || "导出失败，请稍后再试。");
  } finally {
    if (reportState.exportButton) {
      reportState.exportButton.disabled = !ffmpegAvailable || !musicTracks.length;
      reportState.exportButton.textContent = "导出 MP4";
    }
  }
}

async function submitNarrative(event) {
  event.preventDefault();
  hideMessage();

  let payload;
  try {
    payload = collectPayload();
  } catch (error) {
    showMessage(error.message);
    return;
  }

  const formData = new FormData();
  formData.append("items_json", JSON.stringify(payload.items));
  formData.append("language", languageSelect.value);
  formData.append("tone", toneSelect.value);
  formData.append("max_lines_per_block", lineCountInput.value);
  payload.images.forEach((image) => formData.append("images", image));

  setLoading(true);
  showMessage("正在进行图片理解，并生成纪念册与 labels...", "info");

  try {
    const response = await fetch("/narrative/generate-upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "生成失败");
    }
    const historyImages = await buildUploadHistoryImages(payload.images);
    hideMessage();
    renderStory(data, { imageSources: historyImages });
  } catch (error) {
    showMessage(error.message || "生成失败，请稍后再试。");
  } finally {
    setLoading(false);
  }
}

async function analyzeFolderPath() {
  hideMessage();
  const folderPath = folderPathInput.value.trim();
  if (!folderPath) {
    showMessage("请先输入文件夹地址。");
    return;
  }

  const formData = new FormData();
  formData.append("folder_path", folderPath);
  formData.append("language", languageSelect.value);
  formData.append("tone", toneSelect.value);
  formData.append("max_lines_per_block", lineCountInput.value);

  setLoading(true);
  showMessage("后端正在读取文件夹，优先使用本地标签和文件名生成弱分析...", "info");

  try {
    const response = await fetch("/narrative/generate-folder", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "文件夹分析失败");
    }
    hideMessage();
    folderSummary.textContent = `已分析 ${data.timeline?.length || 0} 张图片：${data.render_hints?.source_folder || folderPath}`;
    renderStory(data);
  } catch (error) {
    showMessage(error.message || "文件夹分析失败，请检查路径和模型配置。");
  } finally {
    setLoading(false);
  }
}

function fillSample() {
  clearRows();
  sampleItems.forEach((item) => createItemRow(item));
  hideMessage();
  showMessage("示例结构已填入；也可以清空文字，只上传照片。", "info");
}

function clearRows() {
  [...itemsList.children].forEach(revokeRowImage);
  itemsList.replaceChildren();
  currentTimelineGroup = 0;
  renderTimelinePager();
}

function resetAll() {
  stopAutoplay();
  exitPreviewMode();
  folderInput.value = "";
  folderPathInput.value = "";
  folderSummary.textContent = "可以输入本机文件夹地址，或用浏览器选择文件夹。";
  clearRows();
  createItemRow();
  createItemRow();
  storyOutput.replaceChildren();
  historyPanel.hidden = true;
  reportState = {
    current: 0,
    total: 0,
    timer: null,
    pages: [],
    progressItems: [],
    counter: null,
    playButton: null,
    shell: null,
    previewTitle: "",
  };
  syncPreviewChrome();
  hideMessage();
}

async function checkService() {
  try {
    const response = await fetch("/health");
    if (!response.ok) {
      throw new Error("offline");
    }
    serviceStatus.textContent = "服务在线";
    serviceStatus.classList.add("online");
    serviceStatus.classList.remove("offline");
  } catch {
    serviceStatus.textContent = "服务离线";
    serviceStatus.classList.add("offline");
    serviceStatus.classList.remove("online");
  }
}

addItemButton.addEventListener("click", () => createItemRow());
sampleButton.addEventListener("click", fillSample);
resetButton.addEventListener("click", resetAll);
enterPreviewButton.addEventListener("click", openPreviewMode);
historyButton.addEventListener("click", () => toggleHistoryPanel());
clearHistoryButton.addEventListener("click", clearHistory);
form.addEventListener("submit", submitNarrative);
folderButton.addEventListener("click", () => folderInput.click());
folderInput.addEventListener("change", handleFolderUpload);
folderPathButton.addEventListener("click", analyzeFolderPath);
folderPathInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    analyzeFolderPath();
  }
});
document.addEventListener("keydown", (event) => {
  if (storyOutput.hidden || !reportState.total) {
    return;
  }
  if (event.key === "ArrowRight") {
    showReportPage(reportState.current + 1, "next");
  }
  if (event.key === "ArrowLeft") {
    showReportPage(reportState.current - 1, "prev");
  }
});

createItemRow();
renderHistoryList();
syncPreviewChrome();
loadMusicTracks();
loadXhsPublishStatus();
checkService();
