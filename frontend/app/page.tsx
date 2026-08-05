"use client";

import { useRef, useState } from "react";
import {
  ApiError,
  renderManim,
  subscribeGenerate,
} from "@/lib/api";

type Status = "idle" | "generating" | "rendering" | "done" | "failed";

const STATUS_LABEL: Record<Status, string> = {
  idle: "就绪",
  generating: "正在生成代码…",
  rendering: "正在渲染视频…",
  done: "完成",
  failed: "失败",
};

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastStep, setLastStep] = useState<string>("");
  const [code, setCode] = useState<string | null>(null);
  const [sceneName, setSceneName] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<number | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [renderDuration, setRenderDuration] = useState<number | null>(null);

  // Keep cancellation handle so a new run can close the old EventSource.
  const closeRef = useRef<(() => void) | null>(null);

  function runPipeline(reRenderOnly = false) {
    setError(null);
    if (!reRenderOnly) setVideoUrl(null);

    if (closeRef.current) {
      closeRef.current();
      closeRef.current = null;
    }

    if (reRenderOnly) {
      // Just hit POST /render — no SSE needed for a single subprocess call.
      void runReRender();
      return;
    }

    if (!prompt.trim()) {
      setError("prompt is empty");
      setStatus("failed");
      return;
    }

    setStatus("generating");
    setCode(null);
    setAttempts(null);

    const close = subscribeGenerate(prompt.trim(), {
      llm_call: (d) => {
        setStatus("generating");
        setLastStep(`调用 LLM（第 ${d.attempt} 次）`);
      },
      validating: (d) => {
        setLastStep(`校验代码（第 ${d.attempt} 次）`);
      },
      code: (d) => {
        setCode(d.code);
        setSceneName(d.scene_name);
        setAttempts(d.attempts);
        setLastStep(`代码 OK，准备渲染`);
      },
      rendering: (d) => {
        setStatus("rendering");
        setLastStep(`渲染 ${d.scene_name ?? ""}`);
      },
      retry: (d) => {
        setLastStep(
          `第 ${d.attempt} 次失败（${d.reason}）${d.error ? "，自动重试" : ""}`,
        );
      },
      done: (d) => {
        setCode(d.code);
        setSceneName(d.scene_name);
        setAttempts(d.attempts);
        setVideoUrl(d.video_url);
        setRenderDuration(d.duration_sec);
        setStatus("done");
        setLastStep("完成");
        if (closeRef.current) {
          closeRef.current();
          closeRef.current = null;
        }
      },
      failed: (d) => {
        setError(d.error);
        setStatus("failed");
        setLastStep("失败");
        if (closeRef.current) {
          closeRef.current();
          closeRef.current = null;
        }
      },
    });
    closeRef.current = close;
  }

  async function runReRender() {
    if (!code) return;
    setStatus("rendering");
    setError(null);
    try {
      const ren = await renderManim(code, sceneName ?? undefined);
      if (ren.error || !ren.video_url) {
        setError(ren.error ?? "render failed");
        setStatus("failed");
        return;
      }
      setVideoUrl(ren.video_url);
      setRenderDuration(ren.duration_sec);
      setStatus("done");
    } catch (e) {
      const msg = e instanceof ApiError ? describeApiError(e) : String(e);
      setError(`渲染失败：${msg}`);
      setStatus("failed");
    }
  }

  const busy = status === "generating" || status === "rendering";

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-6 px-6 py-10">
      <header>
        <h1 className="text-4xl font-bold text-blue-400">ThinkCanvas</h1>
        <p className="mt-1 text-sm text-gray-500">Prompt → Manim 视频（SSE 实时进度）</p>
      </header>

      <section className="rounded-lg border border-gray-800 bg-gray-900 p-4">
        <label htmlFor="prompt" className="block text-sm text-gray-400">
          算法描述（中文 / 英文）
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="例：冒泡排序 / binary search / 二叉树 BFS 遍历"
          rows={3}
          className="mt-2 w-full rounded bg-gray-950 p-2 font-mono text-sm text-white outline-none ring-1 ring-gray-800 focus:ring-blue-500"
          disabled={busy}
        />
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={() => runPipeline(false)}
            disabled={busy}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:bg-gray-700"
          >
            {busy ? STATUS_LABEL[status] : "Generate"}
          </button>
          <span className="text-sm text-gray-400">{STATUS_LABEL[status]}</span>
          {lastStep && (
            <span className="text-xs text-gray-500">— {lastStep}</span>
          )}
          {attempts !== null && status === "done" && (
            <span className="text-xs text-gray-500">（retry {attempts} 次）</span>
          )}
          {renderDuration !== null && status === "done" && (
            <span className="text-xs text-gray-500">渲染 {renderDuration.toFixed(1)}s</span>
          )}
        </div>
        {error && (
          <pre className="mt-3 max-h-60 overflow-auto rounded bg-red-950 p-3 text-xs text-red-200">
            {error}
          </pre>
        )}

        <ProgressBar status={status} />
      </section>

      {code && (
        <section className="rounded-lg border border-gray-800 bg-gray-900 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-300">
              生成的代码 {sceneName && <span className="ml-2 text-xs text-gray-500">({sceneName})</span>}
            </h2>
            <button
              onClick={() => runPipeline(true)}
              disabled={busy}
              className="rounded bg-gray-800 px-3 py-1 text-xs hover:bg-gray-700 disabled:bg-gray-700"
            >
              重新渲染
            </button>
          </div>
          <pre className="max-h-96 overflow-auto rounded bg-gray-950 p-3 text-xs text-gray-200">
            <code>{code}</code>
          </pre>
        </section>
      )}

      {videoUrl && (
        <section className="rounded-lg border border-gray-800 bg-gray-900 p-4">
          <h2 className="mb-2 text-sm font-semibold text-gray-300">视频</h2>
          <video
            src={videoUrl}
            controls
            className="w-full rounded bg-black"
          />
          <a
            href={videoUrl}
            download
            className="mt-2 inline-block text-xs text-blue-400 hover:underline"
          >
            下载 .mp4
          </a>
        </section>
      )}
    </main>
  );
}

function describeApiError(e: ApiError): string {
  let d: unknown = e.detail;
  if (d && typeof d === "object" && "detail" in (d as Record<string, unknown>)) {
    d = (d as Record<string, unknown>).detail;
  }
  if (d && typeof d === "object" && "error" in (d as Record<string, unknown>)) {
    return String((d as Record<string, unknown>).error);
  }
  if (typeof d === "string") return d;
  return e.message;
}

const PIPELINE_STEPS = ["提交请求", "生成代码", "校验代码", "渲染视频"];

function ProgressBar({ status }: { status: Status }) {
  const STEP_INDEX: Record<Status, number> = {
    idle: 0,
    generating: 1,
    rendering: 3,
    done: PIPELINE_STEPS.length,
    failed: 1,
  };
  const idx = STEP_INDEX[status];
  const total = PIPELINE_STEPS.length;
  const pct = Math.min(100, Math.round(((idx + 0.5) / total) * 100));

  return (
    <div className="mt-3" data-testid="progress-bar">
      <div className="h-2 w-full overflow-hidden rounded bg-gray-800">
        <div
          className={`h-full transition-all duration-300 ${
            status === "failed" ? "bg-red-500" : "bg-blue-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-xs text-gray-500">
        {PIPELINE_STEPS.map((s, i) => (
          <span key={s} className={i <= idx ? "text-blue-400" : "text-gray-600"}>
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}
