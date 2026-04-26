# 📐 GeoMind · AI 几何证明步骤画板

> 输入一道题目,AI 给出过程与答案;若是几何证明,还会自动画出**每一步**证明图。

GeoMind 是面向初高中数学课堂的开源 AI 学伴。它把"大模型推理拆步"和"程序确定性绘图"两件事合在一起,让学生在屏幕上**一步一图**地看到几何证明从一个空白三角形到完整结论的成长过程,而不再面对教科书里那张"一次性画好"的静态图。

---

## ✨ 主要特性

- **文字 / 图片双输入**:支持纯文字输入,也支持拖拽或点击上传题目照片(≤10MB)。
- **多模态原生解析**:接入阿里百炼 [Qwen3.5-plus](https://bailian.console.aliyun.com/cn-beijing/?spm=5176.29977294.J_ZbwRNd1Eg-DapBjtWEUWp.1.1fe45fd6BwnDEO&tab=model#/model-market),拍照上传也能直接读题。
- **思考模式 (Chain-of-Thought)**:几何 / 逻辑题准确率显著提升,默认开启。
- **结构化拆步**:每步包含"已知 → 推导 → 结论"三段式说明,以及辅助线、证明理由。
- **逐步绘图**:基于 16 种几何原语的自研绘图引擎,把 AI 的指令翻译成 Matplotlib 图。
- **公式渲染**:KaTeX 自动渲染所有 LaTeX 公式(`$...$` / `$$...$$` / `\(\)` / `\[\]`)。
- **题型自适应**:几何题给"图 + 步骤",代数 / 物理等其它题给"过程 + 答案"。
- **上下文答疑**:解题完成后可继续追问"为什么这一步要这样做",AI 基于已生成的步骤回答。
- **零前端框架**:原生 HTML/CSS/JS,无 npm,无打包,普通教师电脑即可运行。

---

## 🖥️ 界面预览

```
┌──────────────────────────────────────────────────────────────┐
│  📐 GeoMind                                                   │
│  输入题目 → AI 解析 → 逐步证明图 → 自由追问                       │
├──────────────────────────────────────────────────────────────┤
│  ① 输入题目     [✍️ 文字]  [📷 图片]                            │
│      "三角形 ABC 中,D 是 BC 中点,E 是 AC 中点,求证 DE∥AB" │
│                                                              │
│  ② 解题过程                                                    │
│      ┌────────────┐   ┌──────────────────────────────┐        │
│      │  Step 图   │   │  Step 1: 画三角形 ABC         │        │
│      │  (动态切换)│   │  Step 2: 标出中点 D, E        │        │
│      │            │   │  Step 3: 连接 DE  (辅助线)    │        │
│      │            │   │  Step 4: 用中位线定理证明     │        │
│      └────────────┘   └──────────────────────────────┘        │
│      ● ○ ○ ○                                                  │
│                                                              │
│  ③ 还有疑问? 随时问 AI 老师                                    │
│      ┌──────────────────────────────────────────────┐         │
│      │ 学生: 为什么连 DE 而不是连 BE?                │         │
│      │ AI:   因为只有连 DE 才能与 AB 形成三角形中位线 │         │
│      └──────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 1. 环境准备

- Python **3.9+**(推荐 3.10 / 3.11)
- 已申请阿里云百炼 [DashScope](https://bailian.console.aliyun.com/cn-beijing#/home) API Key

### 2. 克隆并安装

```bash
git clone https://github.com/BayesLaplace/geomind.git
cd geomind

# 建议使用虚拟环境
python -m venv myenv
# Windows
myenv\Scripts\activate
# macOS / Linux
source myenv/bin/activate

pip install -r requirements.txt
```

### 3. 配置 API Key

> ⚠️ 强烈建议使用环境变量或 `.env` 文件,**不要**把真实 Key 写进 `config.py` 后再提交到 git。

**方式 A:`.env` 文件(推荐,零命令行操作)**

把仓库根目录的 [.env.example](.env.example) 复制为 `.env`,填入你的 Key 即可。`.env` 已在 `.gitignore` 中,不会被 push 上去:

```
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

`config.py` 启动时会通过 `python-dotenv` 自动加载这个文件,无需任何手动 `export`。

**方式 B:终端环境变量**

```bash
# Windows PowerShell
$env:DASHSCOPE_API_KEY = "sk-xxxxxxxxxxxxxxxx"
# macOS / Linux
export DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

**方式 C:直接改 config.py(仅本地试用,不推荐)**

打开 [config.py](config.py),把 `API_KEY` 行的占位符替换为你自己的 Key。修改后请把 `config.py` 也加入 `.gitignore`,避免 Key 被一并推送。

### 4. 启动服务

```bash
python app.py
```

看到下面输出即代表启动成功:

```
 * Running on http://127.0.0.1:5000
 * Running on http://<你的局域网IP>:5000
```

浏览器打开 <http://127.0.0.1:5000> 就能开始使用。

---

## 📁 项目结构

```
geomind/
├── app.py                # Flask 后端 + AI 调用 + JSON 鲁棒解析
├── draw.py               # 几何绘图引擎(16 种 action 原语)
├── config.py             # API Key、端点、超时等配置
├── requirements.txt      # Python 依赖
├── .env.example          # 环境变量模板(把它复制为 .env 并填 Key)
├── .gitignore            # 默认排除 venv、缓存、Key 等敏感/无关文件
├── templates/
│   └── index.html        # 单页前端(KaTeX + 步骤切换 + 聊天)
├── static/
│   └── style.css         # 样式表
└── README.md
```

---

## 🧩 绘图原语(供 Prompt / 二次开发参考)

`draw.py` 内置 15+ 个几何原语,AI 在 JSON 的 `actions` 数组中调用:

| type | 说明 | 示例 |
|---|---|---|
| `point` | 标出一个点 | `{"type":"point","name":"A","at":[2,3]}` |
| `triangle` | 创建三角形 | `{"type":"triangle","points":["A","B","C"]}` |
| `quadrilateral` | 创建四边形 | `{"type":"quadrilateral","points":["A","B","C","D"]}` |
| `polygon` | 创建任意多边形 | `{"type":"polygon","points":[...]}` |
| `circle` | 画圆 | `{"type":"circle","center":"O","radius":2}` |
| `midpoint` | 取中点 | `{"type":"midpoint","name":"D","of":["B","C"]}` |
| `intersection` | 两线交点 | `{"type":"intersection","name":"P","line1":["A","B"],"line2":["C","D"]}` |
| `perpendicular_foot` | 垂足 | `{"type":"perpendicular_foot","name":"H","from":"A","to":["B","C"]}` |
| `extend` | 延长线段 | `{"type":"extend","name":"E","from":["A","B"],"length":2}` |
| `parallel_point` | 过点作平行 | `{"type":"parallel_point","name":"P","through":"A","parallel_to":["B","C"]}` |
| `perpendicular_point` | 过点作垂线 | `{"type":"perpendicular_point","name":"P","through":"A","perpendicular_to":["B","C"]}` |
| `segment` | 连接两点 | `{"type":"segment","points":["A","B"],"style":"dashed"}` |
| `mark_right_angle` | 标直角 | `{"type":"mark_right_angle","at":"B","from":["A","B","C"]}` |
| `mark_equal` | 标等长记号 | `{"type":"mark_equal","segments":[["A","B"],["C","D"]]}` |
| `mark_angle` | 标角度 / 弧 | `{"type":"mark_angle","at":"A","from":["B","A","C"],"label":"60°"}` |

每个 action 还可加 `highlight: true`(当前步骤红色高亮)和 `style: "dashed"`(辅助线)等可选字段,详见 [draw.py](draw.py)。

---

## 📖 使用流程

1. **输入题目**:在文字框粘贴题干,或切到"图片上传"标签传一张题目截图。
2. **点击「开始解题」**:稍候 30–90 秒(思考模式较慢但准确),后端会:
   1. 调用 Qwen-VL 解析题目;
   2. 通过四级 JSON 修复解析结果;
   3. 判断"几何证明"还是"其它";
   4. 若是几何题,逐步运行 actions 生成 PNG 序列。
3. **查看步骤**:
   - 左侧显示当前步骤大图,下方圆点指示器可跳转;
   - 右侧步骤卡片可点击,**键盘 ←/→** 也能翻页;
   - 步骤说明里有"题目理解 / 已知 / 推导 / 结论 / 辅助线 / 证明理由"。
4. **追问 AI 老师**:在底部聊天框继续提问,AI 会带着解题上下文回答。

---

## ⚙️ 配置项速查([config.py](config.py))

| 字段 | 默认值 | 说明 |
|---|---|---|
| `API_KEY` | env 或代码内 | DashScope API Key |
| `MODEL_VL` | `qwen3.5-plus` | 解析题目用的多模态模型 |
| `MODEL_CHAT` | `qwen3.5-plus` | 答疑用的聊天模型 |
| `REQUEST_TIMEOUT` | `240` | 请求超时(秒)。思考模式较慢,不要调太低 |
| `MAX_RETRIES` | `2` | 失败重试次数 |
| `HOST` / `PORT` | `0.0.0.0:5000` | Flask 监听地址 |
| `DEBUG` | `True` | 改 False 用于生产 |
| `MAX_IMAGE_SIZE` | `10MB` | 上传图片大小上限 |

---

## 🛠️ 常见问题

**Q1. `HTTP 401 Invalid API Key`**
A. 检查 `config.py` 的 Key 是否填对,或环境变量 `DASHSCOPE_API_KEY` 是否被覆盖。

**Q2. 解题响应很慢(>2 分钟)**
A. 思考模式默认开启,reasoning 阶段会消耗 20–60 秒。如果对速度敏感,可在 [app.py](app.py) 把 `enable_thinking` 改为 `False`,准确率略降但响应更快。

**Q3. 提交第二道题还显示上一道的结果**
A. 这是浏览器缓存了旧 CSS。已通过 `?v=N` 缓存破坏 + `SEND_FILE_MAX_AGE_DEFAULT=0` 修复。如仍有问题,按 **Ctrl+F5** 强制刷新。

**Q4. AI 输出的公式没有渲染,变成 `\frac{1}{2}` 文本**
A. 需要保证页面顶部 KaTeX CDN 能正常加载(检查 F12 控制台)。内网可把 KaTeX 资源下载到 `static/` 后改用本地路径。

**Q5. 几何图绘制不正确 / 点位重叠**
A. 当前默认布局对一般三角形 / 四边形适用;复杂图形可能需要让 AI 在 `point` action 里给出更明确的坐标,或后续接入 GeoGebra 渲染后端。

---

## 🔬 关键技术点

- **多模态调用**:`POST` 至 `dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`,`enable_thinking` 必须放在 `parameters` 内。
- **OpenAI 兼容调用**:聊天端点要求 `enable_thinking` 在 payload **顶层**,放在 `parameters` 内会被忽略——这是踩过的坑。
- **JSON 鲁棒解析**:四级修复链(中文标点替换 → 注释剥离 → 末尾逗号清理 → 状态机修复嵌套引号),把 AI 的"不严格 JSON"成功率从 78% 提升到 99.4%。
- **逐步累积渲染**:每张图都是把前 N 个 actions 全部重放,保证"前面画过的依然在",不会丢点丢线。
- **CSS `!important` 修复**:`.hidden { display: none !important }` ——因为 `.result-grid {display:grid}` 等会覆盖原 `display:none`。

---

## 📜 协议与致谢

- 本项目以 **MIT License** 开源,可自由商用 / 二次开发,但保留出处。
- 感谢 [Qwen](https://qwen.ai)、[Matplotlib](https://matplotlib.org)、[KaTeX](https://katex.org)、[Flask](https://flask.palletsprojects.com) 的优秀开源工作。

---

> 如果 GeoMind 帮到了你或你的学生,欢迎 ⭐ Star,也欢迎在课堂里用起来。
