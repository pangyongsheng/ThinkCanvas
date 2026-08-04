#!/bin/bash
# ThinkCanvas 一键验证脚本
# 安装 manim + 运行最小测试 demo

set -e

ENV_NAME="my-manim-environment"
DEMO_FILE="demos/01_hello.py"
SCENE="HelloThinkCanvas"

echo "==> Sourcing conda..."
source /opt/miniconda3/etc/profile.d/conda.sh

echo "==> Activating env: $ENV_NAME"
conda activate "$ENV_NAME"

echo "==> Python: $(python --version)"
echo "==> Pip:    $(pip --version)"

# 检查 manim 是否已装
if ! python -c "import manim" 2>/dev/null; then
    echo "==> Installing manim..."
    pip install --upgrade pip
    pip install manim
else
    echo "==> manim already installed: $(python -c 'import manim; print(manim.__version__)')"
fi

# 确保在项目根目录
cd "$(dirname "$0")"
echo "==> Working dir: $(pwd)"

echo "==> Rendering demo..."
manim -ql "$DEMO_FILE" "$SCENE"

VIDEO="media/videos/01_hello/480p15/${SCENE}.mp4"
if [ -f "$VIDEO" ]; then
    echo ""
    echo "==> Success!"
    echo "==> Video: $VIDEO"
    ls -lh "$VIDEO"
    echo "==> Opening with default player..."
    open "$VIDEO" 2>/dev/null || true
else
    echo ""
    echo "==> Render failed - check the output above"
    exit 1
fi
