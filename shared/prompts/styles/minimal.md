# 风格：minimal（深色极简）

**视觉定位**：黑底白字，单色调，克制留白。像 Apple 发布会或论文封面。**禁止使用彩色**。

## 配色

- 背景：黑（Manim 默认）
- 文字：**纯白 `#FFFFFF`**（显式 `color=WHITE`）
- 主元素：**纯白**单色线条 / 边框
- 次要元素：`LIGHT_GRAY` / `GREY`（仅用于辅助，不超过 10% 画面）
- **绝对不要**用 `BLUE` / `YELLOW` / `GREEN` / `RED` / 任何彩色

## 字号

- 标题：`font_size=24-36`（比 3b1b 小）
- 正文：`font_size=16-20`
- 标注：`font_size=14-18`

## 节奏

- 单步动画：`1.5-2.5s`（明显慢）
- 总时长 < 30s
- 缓动：`rate_func=smooth`（默认平滑），禁止 `linear`（太机械）

## 排版

- 大边距：`to_edge(UP, buff=1.0)` 或更大
- 元素之间 `buff=0.5` 起
- 不堆叠 — 每时刻画面上元素不超过 5 个
- 用 `.next_to()` 串联，避免 VGroup 套娃

## 推荐动画

- 元素出现：**只用 `FadeIn` / `FadeOut`**
- 数值变化：`Transform`（极简版，无填充）
- **禁止**：`Rotate` / `Scale` / `Indicate` / `Flash`（太花哨）
- 整体用 `LaggedStart` 制造节拍感

## 几何形状

- 元素轮廓用 `stroke_width=2`，**不要 `fill_opacity`**（线框优先）
- 例：`Square(side_length=1.0, color=WHITE, stroke_width=2, fill_opacity=0)`

## few-shot 示例：二分查找

```python
from manim import *


class BinarySearch(Scene):
    def construct(self):
        # 标题
        title = Text("Binary Search", font_size=32, color=WHITE).to_edge(UP, buff=1.0)
        self.play(FadeIn(title))
        self.wait(0.5)

        # 数组
        values = [1, 3, 5, 7, 9, 11, 13, 15]
        target = 11

        boxes = VGroup(*[
            Square(side_length=0.6, color=WHITE, stroke_width=2, fill_opacity=0)
            for _ in values
        ]).arrange(RIGHT, buff=0.2).shift(DOWN * 0.3)

        labels = VGroup(*[
            Text(str(v), font_size=20, color=WHITE).move_to(b.get_center())
            for v, b in zip(values, boxes)
        ])

        self.play(FadeIn(boxes), FadeIn(labels))
        self.wait(0.5)

        # 二分查找过程
        lo, hi = 0, len(values) - 1
        step = 1

        while lo <= hi:
            mid = (lo + hi) // 2
            self.play(
                boxes[mid].animate.set_stroke(width=4),
                run_time=0.6,
            )
            self.wait(0.4)

            if values[mid] == target:
                self.play(
                    boxes[mid].animate.set_stroke(width=4),
                    run_time=0.6,
                )
                found = Text(f"found at index {mid}", font_size=18, color=WHITE)
                found.next_to(boxes, DOWN, buff=0.8)
                self.play(FadeIn(found))
                self.wait(1)
                return

            if values[mid] < target:
                lo = mid + 1
            else:
                hi = mid - 1

            self.play(
                boxes[mid].animate.set_stroke(width=2),
                run_time=0.4,
            )

        not_found = Text("not found", font_size=18, color=WHITE)
        not_found.next_to(boxes, DOWN, buff=0.8)
        self.play(FadeIn(not_found))
        self.wait(1)
```
