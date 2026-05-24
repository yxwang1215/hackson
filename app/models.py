from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class PhotoItem(BaseModel):
    time: str = Field(default="", description="图片对应时间，可选；为空时由模型按图片顺序概括")
    desc: str = Field(default="", description="图片对应的一句话描述，可选；为空时由 VLM 图像理解自动补足")
    image_analysis: str = Field(default="", description="图像内容分析")
    time_label: Optional[str] = Field(default=None, description="相对时间标签，可选")
    stage_label: Optional[str] = Field(default=None, description="阶段标签，可选")
    semantic_hint: Optional[str] = Field(default=None, description="弱语义提示，可选")
    analysis_priority: Optional[str] = Field(default=None, description="分析优先级，可选")
    image_url: Optional[str] = Field(default=None, description="图片地址，可选")
    image_filename: Optional[str] = Field(default=None, description="图片文件名，可选")
    image_mime_type: Optional[str] = Field(default=None, description="图片 MIME 类型，可选")


class GenerateNarrativeRequest(BaseModel):
    items: List[PhotoItem]
    language: str = "zh-CN"
    tone: str = "warm"
    max_lines_per_block: int = 3


class LineBlock(BaseModel):
    lines: List[str]


class TimelineNode(BaseModel):
    index: int
    time: str
    desc: str
    image_analysis: str
    headline: str
    paragraph: LineBlock
    transition_next: str = ""
    tags: List[str] = Field(default_factory=list)


class NarrativeStyle(BaseModel):
    tone: str = "warm"
    pace: str = "gentle"
    emotion_level: str = "moderate"


class GenerateNarrativeResponse(BaseModel):
    version: str = "1.0"
    language: str = "zh-CN"
    style: NarrativeStyle = Field(default_factory=NarrativeStyle)
    title: str
    intro: LineBlock
    timeline: List[TimelineNode]
    conclusion: LineBlock
    render_hints: dict = Field(default_factory=dict)
