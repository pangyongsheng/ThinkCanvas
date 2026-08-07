"""Manim CLI subprocess wrapper — renders validated code to MP4."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.config import get_settings, project_root
from app.tools.validator import extract_scene_name


@dataclass
class RenderResult:
    code_path: Path
    video_path: Path | None
    duration_sec: float
    error: str | None


def _safe_name(name: str) -> str:
    """Sanitize a string for use in a filename."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


async def render_code(code: str, scene_name: str | None = None) -> RenderResult:
    """Render `code` via the Manim CLI. Returns a RenderResult.

    Side effects:
        - Writes code to `./tmp/code/{timestamp}_{scene}.py`
        - Manim writes video to `./media/videos/<file-stem>/<quality>/<scene>.mp4`
        - Both paths are gitignored.
    """
    settings = get_settings()

    # Resolve scene name from code if not provided
    if not scene_name:
        scene_name = extract_scene_name(code)
    if not scene_name:
        return RenderResult(
            code_path=Path(),
            video_path=None,
            duration_sec=0.0,
            error="no Scene subclass found in code",
        )

    # Write code to tmp/code/<timestamp>_<scene>.py
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    code_dir = project_root / "tmp" / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    code_path = code_dir / f"{timestamp}_{_safe_name(scene_name)}.py"
    code_path.write_text(code, encoding="utf-8")

    # Manim CLI: manim -q<quality> <file> <scene>
    cmd = [
        "manim",
        f"-q{settings.manim_default_quality}",
        str(code_path),
        scene_name,
    ]

    media_dir = project_root / "media"
    start = time.time()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.manim_timeout,
        )
        duration = time.time() - start

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="ignore")
            tail = err_msg[-3000:] if len(err_msg) > 3000 else err_msg
            return RenderResult(
                code_path=code_path,
                video_path=None,
                duration_sec=duration,
                error=f"manim exit {proc.returncode}\nstderr (tail): {tail}",
            )

        # Manim outputs to ./media/videos/<file-stem>/<quality>/<scene>.mp4
        matches = list(media_dir.rglob(f"{scene_name}.mp4"))
        if matches:
            video_path = max(matches, key=lambda p: p.stat().st_mtime)
        else:
            video_path = None

        if video_path is None:
            return RenderResult(
                code_path=code_path,
                video_path=None,
                duration_sec=duration,
                error=f"manim exited 0 but no mp4 found under {media_dir}",
            )

        return RenderResult(
            code_path=code_path,
            video_path=video_path,
            duration_sec=duration,
            error=None,
        )

    except asyncio.TimeoutError:
        return RenderResult(
            code_path=code_path,
            video_path=None,
            duration_sec=time.time() - start,
            error=f"manim timed out after {settings.manim_timeout}s",
        )
    except Exception as e:  # pragma: no cover
        return RenderResult(
            code_path=code_path,
            video_path=None,
            duration_sec=time.time() - start,
            error=f"render exception: {e}",
        )
