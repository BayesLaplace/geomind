"""
GeoMind v2 - Flask 主程序

路由:
  GET  /        : 主页面
  POST /solve   : 解析题目并生成证明步骤图
  POST /chat    : 聊天追问

注意:
  - 题目解析依赖 Qwen 多模态模型;聊天追问使用 Qwen 文本模型(兼容 OpenAI 风格端点)。
  - 所有 AI 输出在后端做 JSON 兜底解析,前端只接收稳定结构。
"""
from __future__ import annotations

import base64
import json
import re
import traceback
from typing import Any, Dict, List, Optional

import requests
from flask import Flask, jsonify, render_template, request

import config
from draw import draw_proof_steps

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_IMAGE_SIZE + 1 * 1024 * 1024  # 留 1MB 给表单其它字段
# 禁用 Flask 对 static/ 的浏览器缓存,防止改了 style.css/index.html 后用户看到旧版页面
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True


# ----------------------------------------------------------------------
# 路由
# ----------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/solve", methods=["POST"])
def solve():
    """解析题目 -> 调 AI -> 渲染步骤图。"""
    problem_text = (request.form.get("problem_text") or "").strip()
    problem_image = (request.form.get("problem_image") or "").strip()

    if not problem_text and not problem_image:
        return jsonify({"error": "请输入文字题目或上传图片"}), 400

    # 检查 API Key
    if not config.API_KEY or config.API_KEY == "your-dashscope-api-key-here":
        return jsonify({
            "error": "尚未配置 API Key,请编辑 config.py 或设置 DASHSCOPE_API_KEY 环境变量。"
        }), 500

    # 构造 prompt 并调用 Qwen
    prompt = build_solve_prompt(problem_text)
    try:
        raw_text = call_qwen_vl(prompt, problem_image or None)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"调用 AI 失败: {e}"}), 502

    # 尝试解析 JSON
    steps_data = parse_json_loose(raw_text)
    if steps_data is None:
        # 打到控制台,便于在 Flask 终端看到 AI 究竟返回了什么
        print("\n========= [solve] JSON 解析失败,AI 原始返回如下 =========")
        print(raw_text)
        print("=========================================================\n")
        return jsonify({
            "error": "AI 返回了非 JSON 内容,无法解析。可以重试或换种描述方式。",
            "raw": raw_text[:1500],
        }), 500

    # 渲染图片(仅几何证明分支需要)
    problem_type = (steps_data or {}).get("类型", "几何证明")
    imgs: List[str] = []
    if problem_type == "几何证明":
        try:
            imgs = draw_proof_steps(steps_data, problem_image or None)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"绘图失败: {e}", "steps": steps_data}), 500

    return jsonify({
        "steps": steps_data,
        "images": imgs,   # 每步一张独立大图(base64 列表),前端按步骤切换;非几何题为空
    })


@app.route("/chat", methods=["POST"])
def chat():
    """学生针对当前题目追问。

    请求体:
      {
        "question": "用户的问题",
        "context": {题目+步骤数据,可选,前端透传}
      }
    """
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    context = payload.get("context") or {}

    if not question:
        return jsonify({"error": "问题不能为空"}), 400

    if not config.API_KEY or config.API_KEY == "your-dashscope-api-key-here":
        return jsonify({"error": "尚未配置 API Key"}), 500

    messages = build_chat_messages(question, context)
    try:
        answer = call_qwen_chat(messages)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"调用 AI 失败: {e}"}), 502

    return jsonify({"answer": answer})


# ----------------------------------------------------------------------
# Prompt 构造
# ----------------------------------------------------------------------

SOLVE_PROMPT_TEMPLATE = """你是一个学习辅导专家。请仔细阅读用户给出的题目,先判断题目类型,再按对应规则输出 JSON。

==============================================================
判断规则:
- 如果题目要求**证明几何结论**(出现"求证"、"证明"、几何元素+结论形式),走"几何证明"分支。
- 否则(代数计算、应用题、物理化学、阅读理解等)走"其他题目"分支。

==============================================================
【分支 A:几何证明题】 输出 JSON 结构:

{{
  "题目理解": "用一句话概括题目要求",
  "类型": "几何证明",
  "关键元素": {{
    "点": ["A","B","C"],
    "线": ["AB","BC","AC"],
    "已知": ["D是BC中点","E是AC中点"],
    "结论": "DE∥AB"
  }},
  "步骤": [
    {{
      "step_id": 1,
      "图形描述": "(本步骤要做什么的简短小标题,5-15 字)",
      "辅助线": "无 / 简述本步引入的辅助线",
      "证明理由": "(本步引用的定理或定义,例如'三角形中位线定理'/'SAS 全等')",
      "说明": "(详细推理:用 2-4 句话讲清楚本步骤的'已知 → 推导 → 结论',要让学生明白每一步'为什么这样做'、'用了什么条件'。可以使用 LaTeX 公式)",
      "actions": [...]
    }}
  ]
}}

把证明过程拆成 5-10 个步骤(简单题至少 5 步,复杂题可到 10 步),不要把多步合成一句话。每个步骤都同时给出:
1. 自然语言的"说明"(详细推理,2-4 句),
2. 结构化绘图指令(actions),以便系统自动作图。

"说明"字段是给学生看的核心内容,要求:
- 每一步都要明确写出"用到的已知条件"+ "推导过程" + "得到的结论",像老师板书那样。
- 例如不要只写"DE 是中位线",要写成:"由第 2 步知 D、E 分别是 BC、AC 的中点,根据三角形中位线的定义,连接两边中点得到的线段 DE 就是△ABC 的中位线。"
- 涉及计算或公式时用 LaTeX,例如 $\\angle ADE = \\angle B$、$DE = \\frac{{1}}{{2}}AB$。

actions 是一个数组,数组中每个元素是一个 JSON 对象,代表一条绘图指令。可用指令类型如下:

- 创建基本图形(只在第一步使用一次):
  * {{"type":"triangle","points":["A","B","C"],"shape":"acute|right|isosceles|obtuse"}}
  * {{"type":"quadrilateral","points":["A","B","C","D"],"shape":"square|rectangle|rhombus|parallelogram|trapezoid"}}
  * {{"type":"polygon","points":["A","B","C","D","E"]}}
  * {{"type":"circle","center":"O","through":"A"}}

- 添加新点(派生于已有点):
  * {{"type":"midpoint","name":"D","of":["B","C"]}}
  * {{"type":"intersection","name":"P","line1":["A","B"],"line2":["C","D"]}}
  * {{"type":"perpendicular_foot","name":"H","from":"A","to":["B","C"]}}
  * {{"type":"extend","name":"F","from":"D","through":"E","ratio":1.6}}
  * {{"type":"parallel_point","name":"F","through":"A","parallel_to":["B","C"],"distance":2}}
  * {{"type":"perpendicular_point","name":"F","through":"A","perpendicular_to":["B","C"],"distance":2}}

- 连接线段(支持虚线表示辅助线):
  * {{"type":"segment","from":"D","to":"E","style":"solid|dashed","highlight":true}}

- 标记类:
  * {{"type":"mark_right_angle","at":"B","rays":["A","C"]}}
  * {{"type":"mark_equal","segments":[["A","D"],["D","B"]],"ticks":1}}
  * {{"type":"mark_angle","at":"B","rays":["A","C"],"label":"α"}}

注意:
- 步骤数量控制在 5-10 步,务必把推理拆细。
- 第一步必须建立基本图形(用 triangle/quadrilateral/polygon/circle),后续步骤只在已有点的基础上派生。
- 同一名称的点,后续步骤无需重复创建。
- 辅助线用 "style":"dashed" 表示。

下面给出一个"详细说明"风格的样例(只演示风格,不是答案):
{{
  "step_id": 3,
  "图形描述": "标记中点条件",
  "辅助线": "无",
  "证明理由": "题目已知条件",
  "说明": "由题目第 2 个已知条件,D 是 BC 的中点,E 是 AC 的中点。这意味着 $BD = DC$、$AE = EC$,这两组线段相等是后面证明中位线性质的基础。",
  "actions": [
    {{"type":"midpoint","name":"D","of":["B","C"]}},
    {{"type":"midpoint","name":"E","of":["A","C"]}}
  ]
}}

==============================================================
【分支 B:其他题目】 输出 JSON 结构:

{{
  "题目理解": "用一句话概括题目要求",
  "类型": "其他",
  "解题过程": "用清晰的多行文字写出解题步骤,每步换行。可以使用数学公式或符号。例如:\\n第一步: ...\\n第二步: ...\\n第三步: ...",
  "答案": "最终结果(简明,不要重复过程)"
}}

==============================================================
通用要求:
- 仅输出 JSON,不要前后缀,不要 ```json 代码块。
- JSON 的字符串内的换行用 \\n 表示。
- **字符串内部禁止使用英文双引号 `"` 来强调或引述**,因为这会把 JSON 字符串戳断。
  如果需要引述某个条件,请使用中文引号 `「」` 或不加任何引号,例如 `由已知条件 D 是 BC 的中点`,
  或者 `由已知条件「D 是 BC 的中点」`。
- **所有数学公式、分式、上下标、希腊字母都必须用 LaTeX 写,并用美元符包裹**:
  * 行内公式用单美元符,例如 `$\\frac{{5\\pi}}{{12}}$`、`$x^2 - 5x + 6 = 0$`、`$\\alpha + \\beta$`
  * 独立成行的大公式用双美元符,例如 `$$\\int_0^1 x^2\\,dx = \\frac{{1}}{{3}}$$`
  * 反斜杠在 JSON 字符串里要再转义一次,所以 LaTeX 的 `\\frac` 在你输出的 JSON 里要写成 `\\\\frac`(JSON 解析后会还原成 `\\frac`,前端再交给 KaTeX 渲染)
- 不要把公式写成纯文本,例如不要写 `5π/12`,要写 `$\\frac{{5\\pi}}{{12}}$`。

下面是题目:
{problem}
"""


def build_solve_prompt(problem_text: str) -> str:
    problem = problem_text.strip() if problem_text else "(题目以图片形式给出,请识别图中文字与图形)"
    return SOLVE_PROMPT_TEMPLATE.format(problem=problem)


CHAT_SYSTEM_PROMPT = (
    "你是一位耐心的高中辅导老师。学生正在学习一道题目和它的解题过程,题目可能是几何证明,"
    "也可能是代数、物理、化学等其它类型。请基于提供的题目和已有解题思路回答学生的问题,"
    "语言友好、简明,尽量用初中、高中阶段的知识解释,不要引入超纲内容。\n"
    "重要:所有数学公式、分式、上下标、希腊字母都要用 LaTeX 并用美元符包裹,"
    "行内用 $...$,独立成行用 $$...$$。例如要写 $\\frac{5\\pi}{12}$,而不是 5π/12。"
)


def build_chat_messages(question: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """构造聊天上下文(题目+步骤/解答)。"""
    sys_msg = {"role": "system", "content": CHAT_SYSTEM_PROMPT}

    # 把题目+步骤拼成简短上下文,避免一次塞太多
    context_text = ""
    if context:
        if context.get("题目理解") or context.get("understanding"):
            context_text += f"[题目理解] {context.get('题目理解') or context.get('understanding')}\n"

        ptype = context.get("类型") or ""
        if ptype:
            context_text += f"[题目类型] {ptype}\n"

        # 几何证明分支
        ke = context.get("关键元素") or context.get("elements") or {}
        if ke:
            try:
                context_text += f"[关键元素] {json.dumps(ke, ensure_ascii=False)}\n"
            except Exception:
                pass
        steps = context.get("步骤") or context.get("steps") or []
        if isinstance(steps, list) and steps:
            for s in steps[:8]:
                step_id = s.get("step_id", "?")
                desc = s.get("说明") or s.get("description") or ""
                context_text += f"  步骤{step_id}: {desc}\n"

        # 其它题目分支
        if context.get("解题过程"):
            context_text += f"[解题过程]\n{context['解题过程']}\n"
        if context.get("答案"):
            context_text += f"[答案] {context['答案']}\n"

    user_content = (
        f"以下是当前题目的上下文:\n{context_text}\n学生问题: {question}"
        if context_text
        else f"学生问题: {question}"
    )
    return [sys_msg, {"role": "user", "content": user_content}]


# ----------------------------------------------------------------------
# Qwen API 调用
# ----------------------------------------------------------------------

def call_qwen_vl(prompt: str, image_base64: Optional[str] = None) -> str:
    """调用 Qwen-VL 多模态接口,返回 AI 文本输出。"""
    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
    }
    content: List[Dict[str, Any]] = [{"text": prompt}]
    if image_base64:
        # 兼容用户传入纯 base64 或 dataURL 两种形式
        if image_base64.startswith("data:"):
            url = image_base64
        else:
            url = f"data:image/jpeg;base64,{image_base64}"
        # Qwen-VL 要求图片项以 "image" 字段表示;放到第一个位置以便先看图后看文
        content.insert(0, {"image": url})

    payload = {
        "model": config.MODEL_VL,
        "input": {
            "messages": [
                {"role": "user", "content": content}
            ]
        },
        "parameters": {
            "result_format": "message",
            # 思考模式打开后,reasoning 也会占 token,JSON 又长,放宽到 8000 给 AI 充足余量
            "max_tokens": 8000,
            "temperature": 0.3,
            # 开启思考模式:让 qwen 在输出前先做一段 chain-of-thought,
            # 对几何/逻辑题理解和拆步明显更准,代价是响应变慢且消耗 reasoning_tokens。
            "enable_thinking": True,
        },
    }

    last_exc = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = requests.post(
                config.API_BASE_VL, headers=headers, json=payload,
                timeout=config.REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            return _extract_qwen_vl_text(data)
        except Exception as e:
            last_exc = e
            if attempt >= config.MAX_RETRIES:
                break
    raise RuntimeError(f"Qwen-VL 调用失败: {last_exc}")


def _extract_qwen_vl_text(data: Dict[str, Any]) -> str:
    """从 Qwen-VL 返回中提取文本(适配多种返回结构)。"""
    output = data.get("output") or {}
    # message 格式
    choices = output.get("choices")
    if choices:
        msg = choices[0].get("message", {})
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for c in content:
                if isinstance(c, dict) and "text" in c:
                    texts.append(c["text"])
                elif isinstance(c, str):
                    texts.append(c)
            return "".join(texts)
    # 兼容旧版 text 输出
    if "text" in output:
        return output["text"]
    raise RuntimeError(f"无法解析 Qwen-VL 返回: {json.dumps(data)[:400]}")


def call_qwen_chat(messages: List[Dict[str, Any]]) -> str:
    """调用 Qwen 兼容 OpenAI 风格端点 -> 返回助手回答字符串。"""
    headers = {
        "Authorization": f"Bearer {config.API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.MODEL_CHAT,
        "messages": messages,
        "temperature": 0.6,
        # 思考模式打开后,reasoning 也吃 token,放宽到 2048 给推理 + 回答都留足空间。
        "max_tokens": 2048,
        # 开启思考模式:答疑常涉及多步推理(为什么这一步要这么做),
        # 让模型先 chain-of-thought 再回答,质量更高。代价是响应慢、token 增多。
        # 注意:OpenAI 兼容接口必须把该字段放在顶层,放在 parameters/其它位置会被忽略。
        "enable_thinking": True,
    }
    last_exc = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = requests.post(
                config.API_BASE_CHAT, headers=headers, json=payload,
                timeout=config.REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError("Qwen 聊天接口未返回 choices")
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            return str(content).strip()
        except Exception as e:
            last_exc = e
            if attempt >= config.MAX_RETRIES:
                break
    raise RuntimeError(f"Qwen 聊天调用失败: {last_exc}")


# ----------------------------------------------------------------------
# JSON 兜底解析
# ----------------------------------------------------------------------

def parse_json_loose(text: str) -> Optional[Dict[str, Any]]:
    """尽力解析 AI 输出的 JSON,处理常见污染:
    - markdown ```json``` 代码块
    - 前后多余的解释文字
    - 中文全角标点(逗号/引号/冒号/括号)
    - 行注释 //... 与块注释 /* ... */
    - 尾随逗号 `, }` / `, ]`
    - 单引号字符串
    """
    if not text:
        return None
    text = text.strip()

    # 1. 直接尝试
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. 抽取代码块或第一个 {...} 段
    candidates: List[str] = []
    fenced = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text)  # 兜底:整段都试一次

    for cand in candidates:
        result = _try_parse(cand)
        if result is not None:
            return result
    return None


def _try_parse(s: str) -> Optional[Dict[str, Any]]:
    """对单个候选片段做多轮清理后尝试解析。"""
    if not s:
        return None
    # 第一轮:原样
    try:
        return json.loads(s)
    except Exception:
        pass

    cleaned = _clean_json_text(s)
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 修复 AI 在字符串内乱写未转义双引号(例如 "由已知"D 是中点"，..." 这种)
    fixed = _fix_inner_quotes(cleaned)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    # 最后一招:把单引号当双引号
    try:
        return json.loads(fixed.replace("'", '"'))
    except Exception:
        return None


def _fix_inner_quotes(s: str) -> str:
    """启发式修复 JSON 字符串值内未转义的双引号。

    AI 经常会在字符串里写 `由已知"D 是中点"，...` 这种内嵌引述,
    把 JSON 戳穿。这个函数做一次状态机扫描:
    - 遇到字符串外的 `"` 视为字符串开始;
    - 在字符串内,如果遇到 `"`,看其后第一个非空白字符:
      * 是 `,`、`:`、`]`、`}` 或字符串末尾  -> 真的字符串结束;
      * 否则                             -> 视为内嵌引号,改成中文引号「」(交替开闭)。
    """
    out: List[str] = []
    in_str = False
    i = 0
    n = len(s)
    next_inner_open = True  # 内嵌引号交替使用 「」
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
                next_inner_open = True
            i += 1
            continue

        # in_str
        if ch == "\\":
            # JSON 转义,原样拷两个字符
            out.append(ch)
            if i + 1 < n:
                out.append(s[i + 1])
                i += 2
            else:
                i += 1
            continue

        if ch == '"':
            # 探测后面第一个非空白
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            terminator = j >= n or s[j] in ",:]}"
            if terminator:
                out.append('"')
                in_str = False
            else:
                # 内嵌引号,替换成中文引号
                out.append("「" if next_inner_open else "」")
                next_inner_open = not next_inner_open
            i += 1
            continue

        out.append(ch)
        i += 1
    return "".join(out)


# 全角 -> 半角 标点映射(只在 JSON 结构层做替换,字符串内部不影响解析正确性)
# 用 \uXXXX 转义,避免编辑器把字符存成多码点组合
_PUNCT_MAP = str.maketrans({
    "“": '"',  "”": '"',   # “ ”
    "‘": "'",  "’": "'",   # ‘ ’
    "，": ",",                   # ,
    "：": ":",                   # :
    "；": ";",                   # ;
    "（": "(",  "）": ")",   # ( )
    "【": "[",  "】": "]",   # 【 】
    "《": "<",  "》": ">",   # 《 》
    "　": " ",                   # 全角空格
})


def _clean_json_text(s: str) -> str:
    # 去 BOM、零宽字符
    s = s.replace("﻿", "").replace("​", "")
    # 去 // 行注释
    s = re.sub(r"(?m)//[^\n]*$", "", s)
    # 去 /* ... */ 块注释
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    # 全角标点 -> 半角
    s = s.translate(_PUNCT_MAP)
    # 去尾随逗号: `, }` / `, ]`
    s = re.sub(r",\s*([}\]])", r"\1", s)
    return s.strip()


# ----------------------------------------------------------------------
# 错误处理
# ----------------------------------------------------------------------

@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "上传内容过大,请压缩图片后重试。"}), 413


@app.errorhandler(404)
def not_found(_e):
    return jsonify({"error": "接口不存在"}), 404


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
