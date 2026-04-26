"""
GeoMind v2 - 几何绘图引擎

设计要点:
1. AI 返回的每个证明步骤携带一个 `actions` 数组(结构化绘图指令),
   GeometryEngine 顺序执行指令,在累积的几何状态上叠加新元素。
2. 当前步骤新增的元素会被高亮(红色/加粗),已有元素呈灰色基线。
3. 渲染采用 grid 布局: N 个步骤 -> N 个子图,每图标题为该步骤说明。
4. 支持的绘图原语足以覆盖高中几何 90% 以上场景:三角形/四边形/圆/
   中点/垂足/平行线/垂线/延长线/角平分线/直角与等长标记。
5. 在 actions 解析失败或缺失时也能输出有意义的占位图,绝不崩溃。
"""

from __future__ import annotations

import base64
import io
import math
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Arc  # noqa: E402

# === 中文字体设置 ===
# Windows 下优先使用 SimHei / 微软雅黑;mac/Linux 下退到 DejaVu Sans
matplotlib.rcParams["font.sans-serif"] = [
    "SimHei",
    "Microsoft YaHei",
    "Heiti TC",
    "PingFang SC",
    "WenQuanYi Zen Hei",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def _np(point) -> np.ndarray:
    """把任意点表示统一成 np.array([x, y], dtype=float)."""
    return np.asarray(point, dtype=float)


def _unit(vec: np.ndarray) -> np.ndarray:
    """单位向量;若长度为 0 返回零向量。"""
    n = np.linalg.norm(vec)
    if n < 1e-9:
        return np.zeros_like(vec)
    return vec / n


def _line_intersection(
    p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, p4: np.ndarray
) -> Optional[np.ndarray]:
    """两直线 p1p2 与 p3p4 的交点(若平行返回 None)."""
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return np.array([x1 + t * (x2 - x1), y1 + t * (y2 - y1)])


def _perpendicular_foot(
    point: np.ndarray, line_a: np.ndarray, line_b: np.ndarray
) -> np.ndarray:
    """点 point 到直线 AB 的垂足。"""
    ab = line_b - line_a
    t = np.dot(point - line_a, ab) / max(np.dot(ab, ab), 1e-9)
    return line_a + t * ab


# ----------------------------------------------------------------------
# 默认布局 - 给定 N 个顶点的多边形,返回美观的初始坐标
# ----------------------------------------------------------------------

def _default_triangle_layout(shape: str = "acute") -> List[np.ndarray]:
    """三角形默认坐标。"""
    if shape == "right":         # 直角三角形(C 处直角)
        return [_np([1, 4]), _np([1, 1]), _np([5, 1])]
    if shape == "isosceles":     # 等腰
        return [_np([4, 5]), _np([1, 1]), _np([7, 1])]
    if shape == "obtuse":        # 钝角
        return [_np([2.5, 4.5]), _np([1, 1]), _np([7, 1])]
    return [_np([4, 5]), _np([1, 1]), _np([7, 1])]


def _default_quadrilateral_layout(shape: str = "parallelogram") -> List[np.ndarray]:
    if shape == "square":
        return [_np([1, 1]), _np([5, 1]), _np([5, 5]), _np([1, 5])]
    if shape == "rectangle":
        return [_np([1, 1]), _np([6, 1]), _np([6, 4.5]), _np([1, 4.5])]
    if shape == "rhombus":
        return [_np([4, 5]), _np([7, 3]), _np([4, 1]), _np([1, 3])]
    if shape == "trapezoid":
        return [_np([2, 1]), _np([6, 1]), _np([5, 4.5]), _np([3, 4.5])]
    # 默认平行四边形
    return [_np([1, 1]), _np([5, 1]), _np([6, 4]), _np([2, 4])]


def _regular_polygon_layout(n: int, center=(4, 3), radius: float = 2.5) -> List[np.ndarray]:
    cx, cy = center
    return [
        _np([cx + radius * math.cos(math.pi / 2 + 2 * math.pi * i / n),
             cy + radius * math.sin(math.pi / 2 + 2 * math.pi * i / n)])
        for i in range(n)
    ]


# ----------------------------------------------------------------------
# 几何引擎主体
# ----------------------------------------------------------------------

class GeometryEngine:
    """累积式几何状态 + 渲染器。"""

    def __init__(self) -> None:
        # 命名点 -> 坐标
        self.points: Dict[str, np.ndarray] = {}
        # 已绘制的元素列表;每个元素有 step_index 标识来自哪一步
        # type: 'segment' | 'circle' | 'arc' | 'right_angle' | 'equal_mark' | 'angle_mark'
        self.elements: List[Dict[str, Any]] = []
        # 当前正在执行的步骤序号(用于标记新增元素以便高亮)
        self.current_step: int = 0
        # 已知的多边形闭合体(便于 segment 自动添加)
        self._known_polygons: List[List[str]] = []

    # ------------------------------------------------------------------
    # 步骤执行
    # ------------------------------------------------------------------
    def apply_step(self, step_index: int, actions: List[Dict[str, Any]]) -> None:
        """对一组 actions 顺序执行,所有产生的元素打上 step_index 标记。"""
        self.current_step = step_index
        for action in actions or []:
            try:
                self._apply_one(action)
            except Exception as exc:
                # 单个指令失败不影响后续;打印诊断,继续
                print(f"[draw] action failed: {action} -> {exc}")

    def _apply_one(self, action: Dict[str, Any]) -> None:
        a_type = (action.get("type") or "").strip().lower()
        if not a_type:
            return

        handler = getattr(self, f"_act_{a_type}", None)
        if handler is None:
            print(f"[draw] unknown action type: {a_type}")
            return
        handler(action)

    # ------------------------------------------------------------------
    # 各类 action handler
    # ------------------------------------------------------------------
    def _act_point(self, a: Dict[str, Any]) -> None:
        """{type: 'point', name: 'A', at: [x, y]}"""
        name = a["name"]
        at = a.get("at", [0, 0])
        self.points[name] = _np(at)

    def _act_triangle(self, a: Dict[str, Any]) -> None:
        """{type: 'triangle', points: ['A','B','C'], shape: 'acute'}"""
        names = a.get("points") or a.get("vertices") or []
        if len(names) != 3:
            return
        coords = _default_triangle_layout(a.get("shape", "acute"))
        for n, c in zip(names, coords):
            if n not in self.points:        # 不覆盖已有坐标
                self.points[n] = c
        # 三条边
        self._add_segment(names[0], names[1])
        self._add_segment(names[1], names[2])
        self._add_segment(names[2], names[0])
        self._known_polygons.append(names)

    def _act_quadrilateral(self, a: Dict[str, Any]) -> None:
        names = a.get("points") or a.get("vertices") or []
        if len(names) != 4:
            return
        coords = _default_quadrilateral_layout(a.get("shape", "parallelogram"))
        for n, c in zip(names, coords):
            if n not in self.points:
                self.points[n] = c
        for i in range(4):
            self._add_segment(names[i], names[(i + 1) % 4])
        self._known_polygons.append(names)

    def _act_polygon(self, a: Dict[str, Any]) -> None:
        names = a.get("points") or a.get("vertices") or []
        if len(names) < 3:
            return
        coords = _regular_polygon_layout(len(names))
        for n, c in zip(names, coords):
            if n not in self.points:
                self.points[n] = c
        for i in range(len(names)):
            self._add_segment(names[i], names[(i + 1) % len(names)])
        self._known_polygons.append(names)

    def _act_circle(self, a: Dict[str, Any]) -> None:
        """{type: 'circle', center: 'O', radius: 2}  或 {center: 'O', through: 'A'}"""
        center_name = a.get("center")
        if center_name is None:
            return
        if center_name not in self.points:
            self.points[center_name] = _np(a.get("center_at", [4, 3]))
        center = self.points[center_name]
        through = a.get("through")
        if through is not None:
            if through not in self.points:
                # 把 through 放到圆心右边
                self.points[through] = center + _np([float(a.get("radius", 2.0)), 0])
            radius = float(np.linalg.norm(self.points[through] - center))
        else:
            radius = float(a.get("radius", 2.0))
        self.elements.append({
            "type": "circle",
            "center": center_name,
            "radius": radius,
            "step": self.current_step,
            "highlight": bool(a.get("highlight", False)),
            "style": a.get("style", "solid"),
        })

    def _act_midpoint(self, a: Dict[str, Any]) -> None:
        """{type: 'midpoint', name: 'D', of: ['B','C']}"""
        name = a["name"]
        of = a.get("of") or []
        if len(of) != 2:
            return
        p1 = self._require(of[0])
        p2 = self._require(of[1])
        if p1 is None or p2 is None:
            return
        self.points[name] = (p1 + p2) / 2.0

    def _act_intersection(self, a: Dict[str, Any]) -> None:
        """{type: 'intersection', name: 'P', line1: ['A','B'], line2: ['C','D']}"""
        name = a["name"]
        l1 = a.get("line1") or []
        l2 = a.get("line2") or []
        if len(l1) != 2 or len(l2) != 2:
            return
        p1 = self._require(l1[0])
        p2 = self._require(l1[1])
        p3 = self._require(l2[0])
        p4 = self._require(l2[1])
        if any(p is None for p in (p1, p2, p3, p4)):
            return
        pt = _line_intersection(p1, p2, p3, p4)
        if pt is not None:
            self.points[name] = pt

    def _act_perpendicular_foot(self, a: Dict[str, Any]) -> None:
        """{type: 'perpendicular_foot', name: 'H', from: 'A', to: ['B','C']}"""
        name = a["name"]
        src = a.get("from")
        line = a.get("to") or a.get("on") or []
        if not src or len(line) != 2:
            return
        p = self._require(src)
        a1 = self._require(line[0])
        a2 = self._require(line[1])
        if any(x is None for x in (p, a1, a2)):
            return
        self.points[name] = _perpendicular_foot(p, a1, a2)

    def _act_extend(self, a: Dict[str, Any]) -> None:
        """{type: 'extend', name:'F', from:'D', through:'E', ratio:1.5}
        在 DE 方向上,从 D 出发,长度为 |DE|*ratio 处放置新点。
        """
        name = a["name"]
        d = self._require(a.get("from"))
        e = self._require(a.get("through"))
        ratio = float(a.get("ratio", 1.5))
        if d is None or e is None:
            return
        self.points[name] = d + (e - d) * ratio

    def _act_parallel_point(self, a: Dict[str, Any]) -> None:
        """{type:'parallel_point', name:'F', through:'A', parallel_to:['B','C'], distance:2}
        通过 A 点,沿着 BC 方向延伸 distance 距离的新点。
        用于构造平行线的另一端点。
        """
        name = a["name"]
        thru = self._require(a.get("through"))
        ref = a.get("parallel_to") or []
        if len(ref) != 2 or thru is None:
            return
        b = self._require(ref[0])
        c = self._require(ref[1])
        if b is None or c is None:
            return
        d = float(a.get("distance", 2.0))
        direction = _unit(c - b)
        self.points[name] = thru + direction * d

    def _act_perpendicular_point(self, a: Dict[str, Any]) -> None:
        """{type:'perpendicular_point', name:'F', through:'A', perpendicular_to:['B','C'], distance:2}"""
        name = a["name"]
        thru = self._require(a.get("through"))
        ref = a.get("perpendicular_to") or []
        if len(ref) != 2 or thru is None:
            return
        b = self._require(ref[0])
        c = self._require(ref[1])
        if b is None or c is None:
            return
        d = float(a.get("distance", 2.0))
        bc = c - b
        normal = _np([-bc[1], bc[0]])
        normal = _unit(normal) * d
        self.points[name] = thru + normal

    def _act_segment(self, a: Dict[str, Any]) -> None:
        """{type: 'segment', from: 'D', to: 'E', style: 'dashed', highlight: true}"""
        p1 = a.get("from")
        p2 = a.get("to")
        if not p1 or not p2:
            return
        if p1 not in self.points or p2 not in self.points:
            return
        self._add_segment(
            p1, p2,
            style=a.get("style", "solid"),
            highlight=bool(a.get("highlight", True)),  # 默认新增的边高亮
            label=a.get("label"),
        )

    def _act_mark_right_angle(self, a: Dict[str, Any]) -> None:
        """{type:'mark_right_angle', at:'B', rays:['A','C']}"""
        at = a.get("at")
        rays = a.get("rays") or []
        if not at or len(rays) != 2:
            return
        if at not in self.points or rays[0] not in self.points or rays[1] not in self.points:
            return
        self.elements.append({
            "type": "right_angle",
            "at": at,
            "rays": rays,
            "step": self.current_step,
        })

    def _act_mark_equal(self, a: Dict[str, Any]) -> None:
        """{type:'mark_equal', segments:[['A','D'],['D','B']], ticks:1}"""
        segs = a.get("segments") or []
        if not segs:
            return
        ticks = int(a.get("ticks", 1))
        for seg in segs:
            if len(seg) != 2:
                continue
            if seg[0] in self.points and seg[1] in self.points:
                self.elements.append({
                    "type": "equal_mark",
                    "p1": seg[0], "p2": seg[1],
                    "ticks": ticks,
                    "step": self.current_step,
                })

    def _act_mark_angle(self, a: Dict[str, Any]) -> None:
        """{type:'mark_angle', at:'B', rays:['A','C'], label:'α'}"""
        at = a.get("at")
        rays = a.get("rays") or []
        if not at or len(rays) != 2:
            return
        if at not in self.points or rays[0] not in self.points or rays[1] not in self.points:
            return
        self.elements.append({
            "type": "angle_mark",
            "at": at,
            "rays": rays,
            "label": a.get("label", ""),
            "step": self.current_step,
        })

    # ------------------------------------------------------------------
    # 内部小工具
    # ------------------------------------------------------------------
    def _require(self, name: Optional[str]) -> Optional[np.ndarray]:
        if name is None:
            return None
        return self.points.get(name)

    def _add_segment(
        self, p1: str, p2: str, style: str = "solid",
        highlight: bool = False, label: Optional[str] = None,
    ) -> None:
        # 去重:若同一对端点已有一条同样 style 的,不再添加
        for el in self.elements:
            if el.get("type") == "segment" and {el["p1"], el["p2"]} == {p1, p2} and el.get("style", "solid") == style:
                return
        self.elements.append({
            "type": "segment",
            "p1": p1, "p2": p2,
            "style": style,
            "highlight": highlight,
            "label": label,
            "step": self.current_step,
        })

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def render(self, ax: plt.Axes, step_index: int, title: str = "") -> None:
        """在 ax 上绘制截至当前步骤(含)的所有元素;高亮当前新增的部分。"""
        if not self.points:
            ax.text(0.5, 0.5, "(无可用几何元素)", ha="center", va="center",
                    transform=ax.transAxes, fontsize=12, color="gray")
            ax.set_title(title, fontsize=11)
            ax.axis("off")
            return

        # 先绘元素(线、圆),再绘点和标签,这样点不被线覆盖
        for el in self.elements:
            if el.get("step", 0) > step_index:
                continue
            self._draw_element(ax, el, step_index)

        # 点
        for name, pos in self.points.items():
            ax.scatter(pos[0], pos[1], s=35, color="#222", zorder=5)
            offset = self._label_offset(name)
            ax.text(pos[0] + offset[0], pos[1] + offset[1], name,
                    fontsize=13, ha="center", va="center", zorder=6,
                    fontweight="bold")

        # 自适应坐标轴
        xs = [p[0] for p in self.points.values()]
        ys = [p[1] for p in self.points.values()]
        # 也把圆考虑进去
        for el in self.elements:
            if el.get("type") == "circle" and el.get("step", 0) <= step_index:
                c = self.points.get(el["center"])
                if c is not None:
                    r = el["radius"]
                    xs.extend([c[0] - r, c[0] + r])
                    ys.extend([c[1] - r, c[1] + r])
        if xs and ys:
            pad = max(0.8, 0.15 * (max(max(xs) - min(xs), max(ys) - min(ys))))
            ax.set_xlim(min(xs) - pad, max(xs) + pad)
            ax.set_ylim(min(ys) - pad, max(ys) + pad)

        ax.set_aspect("equal")
        ax.set_title(title, fontsize=11)
        ax.axis("off")

    def _draw_element(self, ax: plt.Axes, el: Dict[str, Any], step_index: int) -> None:
        is_current = (el.get("step") == step_index)
        highlight = el.get("highlight", False) or is_current

        kind = el.get("type")
        if kind == "segment":
            p1 = self.points.get(el["p1"])
            p2 = self.points.get(el["p2"])
            if p1 is None or p2 is None:
                return
            style = el.get("style", "solid")
            ls = {"solid": "-", "dashed": "--", "dotted": ":"}.get(style, "-")
            color = "#d62728" if highlight else "#444"   # 当前步红色,旧的灰
            lw = 2.4 if highlight else 1.6
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], linestyle=ls,
                    color=color, linewidth=lw, zorder=3)
            if el.get("label"):
                mx, my = (p1 + p2) / 2
                ax.text(mx, my + 0.15, el["label"], fontsize=10,
                        color=color, ha="center")

        elif kind == "circle":
            c = self.points.get(el["center"])
            if c is None:
                return
            color = "#d62728" if highlight else "#444"
            lw = 2.0 if highlight else 1.4
            circ = mpatches.Circle((c[0], c[1]), el["radius"], fill=False,
                                   edgecolor=color, linewidth=lw, zorder=2)
            ax.add_patch(circ)

        elif kind == "right_angle":
            at = self.points.get(el["at"])
            r1 = self.points.get(el["rays"][0])
            r2 = self.points.get(el["rays"][1])
            if at is None or r1 is None or r2 is None:
                return
            d1 = _unit(r1 - at) * 0.35
            d2 = _unit(r2 - at) * 0.35
            corner = at + d1 + d2
            color = "#d62728" if highlight else "#666"
            ax.plot([at[0] + d1[0], corner[0]], [at[1] + d1[1], corner[1]],
                    color=color, linewidth=1.2, zorder=4)
            ax.plot([at[0] + d2[0], corner[0]], [at[1] + d2[1], corner[1]],
                    color=color, linewidth=1.2, zorder=4)

        elif kind == "equal_mark":
            p1 = self.points.get(el["p1"])
            p2 = self.points.get(el["p2"])
            if p1 is None or p2 is None:
                return
            mid = (p1 + p2) / 2
            direction = _unit(p2 - p1)
            normal = _np([-direction[1], direction[0]]) * 0.18
            ticks = int(el.get("ticks", 1))
            color = "#d62728" if highlight else "#555"
            for i in range(ticks):
                offset = (i - (ticks - 1) / 2) * 0.12
                center = mid + direction * offset
                ax.plot([center[0] - normal[0], center[0] + normal[0]],
                        [center[1] - normal[1], center[1] + normal[1]],
                        color=color, linewidth=1.4, zorder=4)

        elif kind == "angle_mark":
            at = self.points.get(el["at"])
            r1 = self.points.get(el["rays"][0])
            r2 = self.points.get(el["rays"][1])
            if at is None or r1 is None or r2 is None:
                return
            v1 = r1 - at
            v2 = r2 - at
            ang1 = math.degrees(math.atan2(v1[1], v1[0]))
            ang2 = math.degrees(math.atan2(v2[1], v2[0]))
            # 使弧从 ang1 到 ang2 走小的方向
            if (ang2 - ang1) % 360 > 180:
                ang1, ang2 = ang2, ang1
            color = "#d62728" if highlight else "#666"
            radius = 0.5
            arc = Arc((at[0], at[1]), radius * 2, radius * 2,
                      angle=0, theta1=ang1, theta2=ang2,
                      edgecolor=color, linewidth=1.4, zorder=4)
            ax.add_patch(arc)
            if el.get("label"):
                bisector = _unit(_unit(v1) + _unit(v2)) * (radius + 0.25)
                ax.text(at[0] + bisector[0], at[1] + bisector[1],
                        el["label"], fontsize=11, color=color, ha="center", va="center")

    def _label_offset(self, name: str) -> Tuple[float, float]:
        """根据点相对于"图形重心"的方向给标签留出偏移,避免压字。"""
        if not self.points:
            return (0.2, 0.2)
        cx = float(np.mean([p[0] for p in self.points.values()]))
        cy = float(np.mean([p[1] for p in self.points.values()]))
        p = self.points[name]
        dx, dy = p[0] - cx, p[1] - cy
        norm = math.hypot(dx, dy)
        if norm < 1e-6:
            return (0.0, 0.3)
        return (0.32 * dx / norm, 0.32 * dy / norm)


# ----------------------------------------------------------------------
# 高层入口
# ----------------------------------------------------------------------

def draw_proof_steps(steps_data: Dict[str, Any], original_image_base64: Optional[str] = None) -> List[str]:
    """根据 AI 解析得到的步骤数据,**每步生成一张独立大图**,返回 base64 列表。

    Args:
        steps_data: 形如 {"题目理解": ..., "关键元素": {...}, "步骤": [...]}.
                    每个步骤可附带 "actions" 字段以驱动结构化绘图。
        original_image_base64: 用户上传的原题图片(预留参数,目前未在图中显示)。

    Returns:
        Base64 编码的 PNG 字符串列表,长度等于步骤数。每张图大尺寸独立呈现。
    """
    steps: List[Dict[str, Any]] = steps_data.get("步骤") or steps_data.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return [_empty_figure_to_base64("AI 未返回有效步骤,请重试或换一道题。")]

    images: List[str] = []
    engine = GeometryEngine()
    for idx, step in enumerate(steps):
        actions = step.get("actions") or step.get("绘图操作") or []
        engine.apply_step(idx, actions)

        # 单独一张大图(更宽敞、坐标轴自适应);标题已由前端步骤卡片提供,图内不再写
        fig, ax = plt.subplots(figsize=(8.5, 6.0))
        engine.render(ax, idx, title="")
        fig.tight_layout()
        images.append(fig_to_base64(fig))

    return images


def _format_step_title(no: int, step: Dict[str, Any]) -> str:
    """生成图标题,独立大图允许更长一点(40 字符内不截断)。"""
    desc = step.get("说明") or step.get("图形描述") or step.get("description") or ""
    desc = str(desc).strip().replace("\n", " ")
    if len(desc) > 40:
        desc = desc[:39] + "…"
    return f"步骤 {no}: {desc}" if desc else f"步骤 {no}"


def _empty_figure_to_base64(msg: str) -> str:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=14, color="#666")
    ax.axis("off")
    return fig_to_base64(fig)


def fig_to_base64(fig: plt.Figure) -> str:
    """matplotlib Figure -> Base64 PNG 字符串。"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=140, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    buf.close()
    return encoded
