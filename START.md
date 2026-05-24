# Hackson 启动指南

AI 时间叙事应用（FastAPI + 前端页面）。按下面步骤在本机启动。

## 1. 进入项目目录

```bash
cd /Users/wyx/Code/hackson
```

## 2. 首次启动（只需做一次）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

复制环境变量（可选，mock 模式可不填 API Key）：

```bash
cp .env.example .env
```

导出 MP4 需要 ffmpeg（可选）：

```bash
brew install ffmpeg
```

## 3. 启动服务

```bash
cd /Users/wyx/Code/hackson
source .venv/bin/activate
uvicorn app.main:app --reload --port 8003
```

不激活虚拟环境时也可以：

```bash
cd /Users/wyx/Code/hackson
.venv/bin/uvicorn app.main:app --reload --port 8001
```

## 4. 打开页面

浏览器访问：

```text
http://127.0.0.1:8001/
```

健康检查：

```bash
curl http://127.0.0.1:8001/health
```

## 5. 常用命令

预处理某个图片类别（生成 `labels.json`）：

```bash
python3 scripts/preprocess_category.py life
python3 scripts/preprocess_category.py --all
```

终端交互模式：

```bash
python -m app.cli
```

## 6. 常见问题

### 端口被占用（Address already in use）

8001 已被占用时，可以换端口：

```bash
uvicorn app.main:app --reload --port 8002
```

或关闭旧进程后再启动：

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
kill <PID>
```

### 虚拟环境报错 bad interpreter

说明 `.venv` 是从别的目录搬过来的，需要重建：

```bash
cd /Users/wyx/Code/hackson
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 导出 MP4 按钮不可用

先安装 ffmpeg，然后重启服务：

```bash
brew install ffmpeg
```

## 7. 示例：分析本地相册

1. 启动服务后打开 http://127.0.0.1:8001/
2. 在「本机文件夹地址」输入：
   - `/Users/wyx/Code/hackson/image/life`
   - 或 `/Users/wyx/Code/hackson/image/season`
3. 点击「分析文件夹」生成纪念册
