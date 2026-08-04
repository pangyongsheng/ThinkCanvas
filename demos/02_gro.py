"""
Gradio + Manim 集成最小 Demo
=============================

演示三件事:
  - Gradio 基础 UI 组件 (Textbox / Button / Video)
  - Python 进程内调用 manim CLI (subprocess)
  - 把渲染好的 mp4 直接喂回 Gradio Video 组件

运行命令:
  conda activate my-manim-environment
  python demos/02_gro.py

浏览器自动打开 http://127.0.0.1:7860
"""
import os
import subprocess

import gradio as gr


# ========== 1. 简单回显 ==========
def echo(text: str) -> str:
    """验证 Gradio 输入输出链路."""
    return f"你说: {text or '(空)'}"


# ========== 2. 调用 manim 渲染 01_hello.py ==========
def render_hello(_prompt: str) -> tuple[str | None, str]:
    """
    接受用户的提示词, 调用 manim CLI 渲染 demo 视频.
    返回 (mp4 路径, 状态文本) 给 Gradio.
    """
    # 相对于项目根目录的相对路径
    script = "demos/01_hello.py"
    scene = "HelloThinkCanvas"
    expected_mp4 = f"media/videos/01_hello/480p15/{scene}.mp4"

    # manim 会按 <media_root>/videos/<script_basename>/<quality>/<Scene>.mp4 组织输出
    # 默认 media_root 是当前工作目录
    cmd = ["manim", "-ql", script, scene]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode != 0:
            return None, f"❌ 渲染失败:\n{result.stderr or result.stdout}"

        if not os.path.exists(expected_mp4):
            return None, f"❌ 未找到预期文件: {expected_mp4}\n请确认你在项目根目录运行此脚本"

        return expected_mp4, f"✅ 渲染成功! 提示词: {_prompt or '(空)'}"

    except subprocess.TimeoutExpired:
        return None, "❌ 渲染超时 (>180s)"
    except FileNotFoundError:
        return None, "❌ 未找到 manim 命令, 请确认 conda 环境激活"


# ========== 3. Gradio 界面 ==========
with gr.Blocks(title="ThinkCanvas Demo", theme=gr.themes.Soft()) as demo:  # type: ignore[attr-defined]  # Gradio themes 是懒加载属性
    gr.Markdown(
        "# 🎬 ThinkCanvas Demo\n"
        "**最小链路**: Gradio 输入 → subprocess 调 manim → 视频回显"
    )

    # ----- Tab 1: 纯文本回显 -----
    with gr.Tab("① Echo (验证 Gradio 链路)"):
        gr.Markdown("输入任意文本,点按钮看回显")
        with gr.Row():
            inp_echo = gr.Textbox(label="输入", placeholder="Hello, ThinkCanvas!")
            out_echo = gr.Textbox(label="回显", interactive=False)
        btn_echo = gr.Button("回显", variant="primary")
        btn_echo.click(echo, inputs=inp_echo, outputs=out_echo)  # type: ignore[attr-defined]  # Gradio 事件方法运行时注入

    # ----- Tab 2: 跑 Manim 渲染 -----
    with gr.Tab("② Render (调用 manim)"):
        gr.Markdown("输入提示词(目前只用来在状态区展示),点按钮触发 `manim -ql`")
        prompt_in = gr.Textbox(
            label="提示词",
            placeholder="描述你想生成的算法/数学动画, e.g. '演示快速排序'",
            value="Demo 渲染 HelloThinkCanvas",
        )
        with gr.Row():
            video_out = gr.Video(label="生成的视频", interactive=False)
            status_out = gr.Textbox(label="状态", interactive=False, lines=5)
        btn_render = gr.Button("🎬 渲染", variant="primary")
        btn_render.click(  # type: ignore[attr-defined]  # Gradio 事件方法运行时注入
            render_hello,
            inputs=prompt_in,
            outputs=[video_out, status_out],
        )


if __name__ == "__main__":
    # share=False 仅本地;share=True 会生成一个临时公网链接(72h 有效)
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False)
