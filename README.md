# AI Time Narrative App

这是一个用于生成“AI 时间叙事”文案的 FastAPI 应用，包含后端接口和可直接使用的前端页面。

## 前端页面

启动服务后打开：

```text
http://127.0.0.1:8000/
```

页面支持按时间线上传多张照片、填写时间和一句话描述、选择语气与语言，并调用 `/narrative/generate-upload` 生成纪念册预览。

也可以直接输入本机文件夹地址，前端会调用 `/narrative/generate-folder`，由后端递归读取该目录下所有图片并逐张完成 VLM 分析。

如果文件夹里放了 `labels.json`，后端会优先读取其中的时间标签和弱语义标签，用来降低逐张 VLM 负担。推荐按类别组织图片，每个类别目录下各放一份 `labels.json`。

## 接口

### `GET /health`
健康检查。

### `POST /narrative/generate`
输入图片时间、描述和图像分析，返回结构化纪念册文案 JSON。

### `POST /narrative/generate-upload`
以 multipart/form-data 上传图片和元数据，后端会自动调用国产视觉模型补充图片分析，再生成时间叙事文案。

## 请求示例

```json
{
  "items": [
    {
      "time": "2026年4月",
      "desc": "我的孩子会爬了",
      "image_analysis": "一个婴儿趴在地板上努力向前爬，脸上带着开心的笑容"
    },
    {
      "time": "2026年12月",
      "desc": "我的孩子会走路了",
      "image_analysis": "孩子扶着沙发慢慢向前走，神情兴奋"
    }
  ],
  "language": "zh-CN",
  "tone": "warm",
  "max_lines_per_block": 3
}
```

## 环境变量

复制 `.env.example` 并填写：
- `LLM_PROVIDER`
- `LLM_API_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `VISION_MODEL`

## 终端交互

如果你想在终端里逐条输入信息并自动分析图片，可以直接运行：

```bash
python -m app.cli
```

## 类别预处理

指定 `image/` 下的子文件夹，预先扫描图片、提取时间标签和文件名语义，并写入该类别的 `labels.json`：

```bash
# 预处理单个类别
python3 scripts/preprocess_category.py life

# 预处理所有类别
python3 scripts/preprocess_category.py --all

# 指定输出路径
python3 scripts/preprocess_category.py season --out image/season/labels.json
```

生成的 `labels.json` 会包含：

- `time_label` / `stage_label`：时间顺序与阶段
- `semantic_hint`：从文件名提取的弱语义
- `analysis_priority`：是否需要 VLM（如 `1.jpg` 会标记为 `vlm`）
- `preprocessed_analysis`：可直接用于本地弱分析的占位描述
- `metadata`：图片尺寸、文件大小（若安装了 Pillow）

## 图片目录结构

`image/` 按类别分子目录，每个类别下有自己的图片和 `labels.json`：

```text
image/
├── life/          # 生活记录（出行、美食、娱乐等）
│   ├── labels.json
│   └── *.jpg
└── season/        # 季节/成长节点
    ├── labels.json
    └── *.jpg
```

分析某一类相册时，在前端输入对应类别路径，例如：

```text
/Users/wyx/Code/hackson/image/life
/Users/wyx/Code/hackson/image/season
```

## 图片时间标签

为所有类别批量生成标签：

```bash
python3 scripts/preprocess_category.py --all
```

兼容旧命令（内部同样走预处理逻辑）：

```bash
python3 scripts/generate_image_labels.py --image-dir image --per-category
```

只为单个类别生成：

```bash
python3 scripts/preprocess_category.py life
```

每个 `labels.json` 中，每张图片都会包含：

- `id`：稳定的时间节点编号，例如 `T01`
- `time_label`：用于前端和模型理解的时间顺序标签
- `stage_label`：粗粒度阶段，例如 `早期`、`中期`、`后期`
- `time_source`：时间依据，优先使用 EXIF 拍摄时间；如果图片没有 EXIF，则使用文件修改时间和路径名做相对排序
- `sort_confidence`：排序置信度

注意：当前 `image/` 下图片没有 EXIF 拍摄时间，所以生成的是相对时序标签，不代表真实拍摄日期。它适合用来分析“先后关系”和组织叙事，不适合作为事实日期展示。

## 推荐 pipeline

对于图片较多的情况，建议用三段式流程：

1. 先生成轻量标签：`scripts/generate_image_labels.py`
2. 再做粗筛排序：优先使用 `time_label`、`stage_label`、`semantic_hint`
3. 最后只让少量关键帧进入 VLM 补充理解

这样可以把“全量图片理解”变成“少量疑难样本精判”，速度和成本都会更稳。

后端默认使用 `VISION_ANALYSIS_MODE=auto`：

- 已有 `image_analysis`：直接使用
- 有描述、文件名语义或 `semantic_hint`：本地合成弱图像分析，不调用 VLM
- `analysis_priority` 标记为 `high`、`vlm`、`vision`、`required` 或 `force_vlm`：调用 VLM 精判
- 没有任何可用线索：回退到 VLM

如果想完全跳过视觉模型，可以在 `.env` 中设置：

```text
VISION_ANALYSIS_MODE=local
```

这样即使没有语义线索，也会生成通用占位分析，适合黑客松演示或快速预览。

## 为什么这样设计

- 本地先做标签，减少每张图都跑 VLM 的成本
- 相册场景下，用户往往只需要少量关键照片被精细理解
- 时间顺序和阶段标签通常比完整 caption 更重要
- VLM 只负责补充语义，不负责吞掉全部图片

## 启动

完整步骤见 **[START.md](./START.md)**。

快速启动：

```bash
cd /Users/wyx/Code/hackson
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001
```

浏览器打开 http://127.0.0.1:8001/

## 说明

- `LLM_PROVIDER=mock` 时会返回稳定的本地模拟结果，方便前端联调。
- 切到 `domestic_openai_compatible` 后，请填写 `LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`VISION_MODEL`。
- `VISION_ANALYSIS_MODE=auto` 会优先本地弱分析，必要时才调用 VLM；`local` 会完全跳过 VLM。

## 导出 MP4

纪念册预览底部支持 **导出 MP4**，并可选择背景音乐：

1. 生成纪念册后，在预览控制栏选择音乐
2. 点击 **导出 MP4**
3. 浏览器会自动下载带配乐的视频

可选音乐位于 `app/static/music/`，默认提供 3 段 Mixkit 免费轻音乐。如需重新下载：

```bash
python3 scripts/download_music.py
```

你也可以把 `.mp3` / `.wav` 放进该目录，并更新 `tracks.json`。

导出依赖系统里的 **ffmpeg**：

```bash
brew install ffmpeg
```

若未安装 ffmpeg，页面上的导出按钮会处于不可用状态。

## 发布到小红书

小红书没有对个人开发者开放的「直接发帖」官方 API。项目提供 **发布准备接口**，自动打包标题、正文、话题标签和素材，并支持两种模式：

- `mock`（默认）：生成素材包 + 复制文案，手动到 [创作中心](https://creator.xiaohongshu.com/publish/publish) 上传
- `webhook`：把素材 POST 到第三方发布服务（通常返回扫码二维码）

### 接口

`GET /publish/xiaohongshu/status` — 查询发布能力与配置

`POST /publish/xiaohongshu` — multipart 表单字段：

- `story_json`：纪念册 JSON
- `asset_token` / `asset_source`：图片会话 token
- `publish_format`：`carousel`（图文）或 `video`（视频笔记）
- `music_id`：视频笔记必填
- `slide_duration`：视频每页时长（秒）

前端预览区点击 **发小红书** 即可调用。

### 环境变量（可选）

```text
XHS_PUBLISH_PROVIDER=mock
XHS_PUBLISH_API_URL=
XHS_PUBLISH_API_KEY=
PUBLIC_BASE_URL=http://127.0.0.1:8001
```

对接第三方 webhook 时，`PUBLIC_BASE_URL` 必须是公网可访问地址（如 ngrok），对方才能拉取图片/视频。
# hackson
