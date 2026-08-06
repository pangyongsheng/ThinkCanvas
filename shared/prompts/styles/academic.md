# 风格：academic（明亮学术）

**视觉定位**：白底 + 学术蓝，像 arXiv 论文 Figure 1 或 Khan Academy 板书。**严格、有标注、可用 LaTeX 公式**。

## 配色

- 背景：**白**（`#FFFFFF`）。代码开头必须写：
  在 ``Scene.camera.background_color`` 上设，**不要**用 ``config.background_color``
  （后者在 ``construct()`` 里赋值已经太晚，cairo 已绘黑底）。
  推荐：
  ```python
  class MyScene(Scene):
      def construct(self):
          self.camera.background_color = "#FFFFFF"
  ```
  如果非要改全局，再用 ``config.background_color = "#FFFFFF"`` 并放在
  ``construct()`` **第一行** — 但仍可能不生效，优先 camera 写法。
- 主色：**学术蓝** `#1E3A8A`（用 `BLUE_E` 或 `"#1E3A8A"`）
- 强调色：暗红 `RED_E` 或 `"#7F1D1D"`、橄榄绿 `GREEN_E` 或 `"#365314"`
- 文字：纯黑 `#000000`
- 次要标注：`GREY`（轴线 / 网格）

## 字号

- 标题：`font_size=28-40`
- 正文：`font_size=18-24`
- 公式：用 `MathTex(font_size=36-48)`
- 标注：`font_size=14-18`

## 节奏

- 单步动画：`1.0-1.5s`
- 总时长 < 30s
- 缓动：`rate_func=linear`（保持几何准确，不要 smooth）

## 必备元素

- **坐标轴**：用 `Axes(x_range=[...], y_range=[...], axis_config={...})`
- **标签**：元素旁边必须有 `Text` / `MathTex` 标注
- **箭头**：用 `Arrow` 指向关键节点
- **虚线框**：用 `DashedVMobject` 圈出重点
- 公式优先用 `MathTex`（mactex 已装）

## 推荐动画

- 元素出现：`Create`（坐标系）/ `Write`（文字、公式）
- 数值变化：`Transform`
- 强调：箭头 + 标注组合，不要 `Indicate`
- 过程：`Succession` 串步骤

## few-shot 示例：二叉树 BFS 遍历

```python
from manim import *


class BinaryTreeBFS(Scene):
    def construct(self):
        # 明亮背景（必须 camera.background_color，不能用 config）
        self.camera.background_color = "#FFFFFF"

        # 标题
        title = Text("Binary Tree BFS", font_size=32, color="#000000").to_edge(UP)
        self.play(Write(title))
        self.wait(0.3)

        # 节点位置（二叉树层级）
        positions = {
            1: (0, 2, 0),
            2: (-2, 1, 0),
            3: (2, 1, 0),
            4: (-3, 0, 0),
            5: (-1, 0, 0),
            6: (1, 0, 0),
            7: (3, 0, 0),
        }

        nodes = {}
        labels = {}
        for i, pos in positions.items():
            circle = Circle(radius=0.3, color="#1E3A8A", stroke_width=3, fill_opacity=0)
            circle.move_to(pos)
            label = Text(str(i), font_size=24, color="#000000").move_to(pos)
            nodes[i] = circle
            labels[i] = label

        # 边（父子关系）
        edges = [
            (1, 2), (1, 3),
            (2, 4), (2, 5),
            (3, 6), (3, 7),
        ]
        edge_mobs = VGroup(*[
            Line(nodes[a].get_center(), nodes[b].get_center(),
                 color=GREY, stroke_width=2)
            for a, b in edges
        ])

        # 一次性画出树结构
        self.play(Create(edge_mobs), run_time=1.5)
        self.play(*[Create(nodes[i]) for i in nodes])
        self.play(*[Write(labels[i]) for i in labels])
        self.wait(0.5)

        # BFS 遍历标注
        bfs_order = [1, 2, 3, 4, 5, 6, 7]
        step_label = Text("", font_size=20, color="#000000").to_edge(DOWN)
        self.add(step_label)

        for step, node_id in enumerate(bfs_order, start=1):
            text = MathTex(f"\\text{{step }} {step}: \\text{{visit }} {node_id}",
                           font_size=28, color="#1E3A8A")
            text.to_edge(DOWN)
            self.play(
                nodes[node_id].animate.set_fill("#1E3A8A", opacity=0.3),
                Transform(step_label, text),
                run_time=0.8,
            )
            self.wait(0.3)

        # 公式总结
        formula = MathTex(r"\text{Time Complexity: } O(n)",
                          font_size=32, color="#1E3A8A")
        formula.next_to(title, DOWN, buff=0.5)
        self.play(Write(formula))
        self.wait(1)
```
