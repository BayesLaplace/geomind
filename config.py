"""
GeoMind v2 - 配置文件

填入你在阿里云百炼平台申请的 API Key 即可使用。
推荐通过环境变量 DASHSCOPE_API_KEY 传入(优先级更高,不会把 Key 泄到 git 仓库)。

  Windows PowerShell:
    $env:DASHSCOPE_API_KEY = "sk-xxxxxxxx"
  macOS / Linux:
    export DASHSCOPE_API_KEY=sk-xxxxxxxx

如果选择直接改本文件,请务必把改后的 config.py 加入 .gitignore,避免误上传。
"""
import os

# === API 凭证 ===
# 优先从环境变量读取;否则使用代码内填写的默认值(仅供本地快速试用,请勿提交到公共仓库)
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "your-dashscope-api-key-here")

# === 模型与端点 ===
# Qwen 多模态接口（支持图片输入）
API_BASE_VL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
# Qwen 纯文本兼容 OpenAI 风格接口（聊天追问用）
API_BASE_CHAT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 模型名称
# qwen3.5-plus 是阿里原生的多模态 Plus 档,文本/图片统一支持,
# 比 multimodal-generation 端点上常被回退的 qwen-vl-plus 视觉能力更强。
# 由于本项目题目可能含图片,统一走多模态接口与 qwen3.5-plus 即可。
MODEL_VL = "qwen3.5-plus"        # 解析题目（含图片）
MODEL_CHAT = "qwen3.5-plus"      # 聊天追问（纯文本）

# === 调用参数 ===
# qwen3.5-plus 默认开启"思考模式"。本项目已在 app.py 显式打开 enable_thinking=True
# (几何/逻辑题先做 chain-of-thought 后再输出结构化 JSON,效果显著更稳),
# 但 reasoning 阶段会额外消耗 20-60 秒 + 数千 reasoning_tokens,
# 因此把请求超时从 120 放宽到 240,避免把模型刚算完答案就被网络层 cut 掉。
REQUEST_TIMEOUT = 240         # 请求超时(秒)
MAX_RETRIES = 2               # 失败重试次数

# === Flask 配置 ===
HOST = "0.0.0.0"
PORT = 5000
DEBUG = True

# 上传图片大小上限（字节），默认 10MB
MAX_IMAGE_SIZE = 10 * 1024 * 1024
