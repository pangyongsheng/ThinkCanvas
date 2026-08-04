"""
ThinkCanvas 最小测试 Demo
=======================

验证 Manim 渲染管线正常工作:
  - 文字渲染 (Text)
  - 几何图形 (Circle, Square, Triangle)
  - 组合与变换 (VGroup, Transform)
  - 多种动画 (Write, FadeIn, FadeOut, LaggedStart)

运行命令:
  conda activate my-manim-environment
  manim -ql demos/01_hello.py HelloThinkCanvas

输出:
  media/videos/01_hello/480p15/HelloThinkCanvas.mp4
"""
from manim import *


class HelloThinkCanvas(Scene):
    def construct(self):
        # ---------- 1. 标题 ----------
        title = Text(
            "ThinkCanvas",
            font_size=80,
            color=BLUE,
            weight=BOLD,
        )
        self.play(Write(title), run_time=1.2)
        self.wait(0.4)

        # ---------- 2. 副标题:流程 ----------
        subtitle = Text(
            "Prompt  ->  Manim  ->  Video",
            font_size=36,
            color=GREY,
        )
        subtitle.next_to(title, DOWN, buff=0.7)
        self.play(FadeIn(subtitle, shift=UP * 0.3), run_time=0.8)
        self.wait(0.5)

        # ---------- 3. 三个图形 ----------
        circle = Circle(radius=0.55, color=YELLOW, fill_opacity=0.5)
        square = Square(side_length=1.1, color=RED, fill_opacity=0.5)
        triangle = Triangle(color=GREEN, fill_opacity=0.5).scale(1.2)

        shapes = VGroup(circle, square, triangle).arrange(RIGHT, buff=0.7)
        shapes.shift(DOWN * 1.6)

        self.play(
            LaggedStart(
                Create(circle),
                Create(square),
                Create(triangle),
                lag_ratio=0.25,
            ),
            run_time=1.8,
        )
        self.wait(0.4)

        # ---------- 4. 圆 -> 方 (Transform 测试) ----------
        target_square = square.copy().move_to(circle.get_center())
        self.play(Transform(circle, target_square), run_time=0.8)
        self.wait(0.3)

        # ---------- 5. 全部退出 ----------
        self.play(
            FadeOut(title),
            FadeOut(subtitle),
            FadeOut(shapes),
            run_time=0.6,
        )
        self.wait(0.3)
