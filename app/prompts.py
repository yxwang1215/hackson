from __future__ import annotations

import json
from typing import Dict, List

from app.models import PhotoItem


SYSTEM_PROMPT = """你是一个纪念册文案生成器。
你的任务是根据用户提供的时间、描述和图像分析，生成温暖、克制、真实的时间叙事文案。
如果用户没有提供时间或描述，要优先根据 image_analysis 自动理解画面，并补出自然、具体的节点描述。
必须强调成长、回忆、变化和时间流动感。
不要夸张，不要煽情过度，不要写成鸡汤。
输出必须是结构化 JSON，不能输出任何额外解释、标题说明或 markdown。
每个时间节点都要尽量结合时间、描述、图像分析中的至少两个信息点。
每个节点文案要短，适合前端按时间轴渲染。
避免重复句式、空话和套话。
语言要自然，像真实纪念册里的文案。
tags 字段就是前端展示的自动 label，每个节点生成 2 到 4 个短标签，必须来自画面主体、动作、场景或成长阶段。"""

STYLE_GUIDE = """风格要求：
- 温暖但克制
- 句子短，画面感强
- 多用具体动作、状态、变化
- 少用抽象抒情词
- 不夸大，不煽情，不空泛
- 每段 1 到 3 句
- 适合前端直接换行渲染"""

OUTPUT_SCHEMA_HINT = """请严格输出以下 JSON 结构：
{
  "version": "1.0",
  "language": "zh-CN",
  "style": {"tone": "warm", "pace": "gentle", "emotion_level": "moderate"},
  "title": "string",
  "intro": {"lines": ["string", "string"]},
  "timeline": [
    {
      "index": 1,
      "time": "string",
      "desc": "string",
      "image_analysis": "string",
      "headline": "string",
      "paragraph": {"lines": ["string", "string"]},
      "transition_next": "string",
      "tags": ["string"]
    }
  ],
  "conclusion": {"lines": ["string", "string"]},
  "render_hints": {"newline_mode": "line_array", "max_lines_per_block": 3, "allow_truncation": false}
}

硬性规则：
- 只输出 JSON
- 不要输出 markdown 代码块
- 不要输出解释
- 不要输出多余字段
- 不要生成超长段落
- 不要重复同义表达
- 不要写空话
- 如果 time 为空，输出“第 N 张”或能从素材中推断出的自然时间表达
- 如果 desc 为空，用 image_analysis 自动生成一句简短 desc
- tags 必须是可直接作为前端 label 展示的短词，不要超过 4 个字或一个短语"""

IMAGE_ANALYSIS_SYSTEM_PROMPT = """你是一个图片内容分析器。
请根据用户上传的图片，输出简洁、客观、具体的中文画面描述。
不要总结情绪，不要写空话，不要夸张，不要加入看不见的信息。
只输出一句话，控制在 20 到 40 字。"""


def build_image_analysis_prompt(time: str = "", desc: str = "") -> str:
  return f"""请基于图片内容做画面分析，只输出一句中文，20 到 40 字。
如果补充信息存在，只作为上下文参考，不要复述。

补充信息：
时间：{time or '无'}
一句话描述：{desc or '无'}

要求：
1. 只描述看得见的画面和动作。
2. 不要抒情，不要夸大，不要空话。
3. 尽量具体，像相册注释或纪念册说明。"""


def build_user_prompt(items: List[PhotoItem], language: str, tone: str, max_lines_per_block: int) -> str:
    payload: Dict[str, object] = {
        "language": language,
        "tone": tone,
        "max_lines_per_block": max_lines_per_block,
        "items": [item.model_dump() for item in items],
    }
    return f"""请根据以下输入生成结构化纪念册文案 JSON：
{json.dumps(payload, ensure_ascii=False, indent=2)}

要求：
1. 开头要有情感引导，但不要夸张。
2. 每个时间节点要写出独立叙事段落。
3. 节点之间要有轻微过渡句，体现时间流转。
4. 结尾要做总结，但不要空泛。
5. 每个段落都要适合前端按 lines 渲染。
6. 如果素材很少，也不要强行扩写。
7. 如果时间跨度明显，要体现前后变化。
8. 节点 headline 要简洁自然，像纪念册小标题。
9. 如果 desc 为空，必须根据 image_analysis 自动生成 desc。
10. 每个节点 tags 必须自动生成，适合作为前端 label。"""
