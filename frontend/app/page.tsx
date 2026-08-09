"use client";

import { useRef, useState } from "react";
import {
  ConversationDetail,
  ConversationRecord,
  MessageRecord,
  STYLES,
  StyleId,
  createConversation,
  getConversation,
  saveAsFewShot,
  subscribeCreateConversation,
  subscribeRefine,
} from "@/lib/api";

import { HistorySidebar } from "@/components/HistorySidebar";
import { CodeViewer } from "@/components/CodeViewer";
import { ConversationPanel } from "@/components/ConversationPanel";

type Status = "idle" | "creating" | "generating" | "rendering" | "done" | "failed";

/** 单条步骤日志条目，对应后端一次 SSE 事件。 */
type Step = {
  id: string;
  kind: "thinking" | "pending" | "tool_call" | "tool_result" | "retry" | "code" | "rendering" | "rendered" | "failed";
  label: string;
  status?: "ok" | "failed";
  error?: string;
};

/** 工具名 → 友好中文。 */
function prettyTool(name: string): string {
  if (name === "validate_manim_code") return "校验代码";
  if (name === "render_manim_dryrun") return "试渲染";
  return name;
}

// Tiny helper to mint stable-but-temp ids for optimistic messages.
function tempId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

/** 把后端步骤事件转成 Step[] 更新器，给 handleCreateFirst 和 handleRefine 共用。 */
function buildStepHandlers(
  setSteps: (updater: (prev: Step[]) => Step[]) => void,
  setStatusLabel: (s: string) => void,
) {
  const push = (s: Step) => setSteps((prev) => [...prev, s]);
  const dropFirstByKind = (kind: Step["kind"]) => setSteps((prev) =>
    prev.find((s) => s.kind === kind) ? prev.filter((s) => s.kind !== kind) : prev,
  );
  const updateLastByKinds = (
    kinds: Step["kind"][],
    patch: Partial<Step>,
  ) => setSteps((prev) => {
    for (let i = prev.length - 1; i >= 0; i--) {
      if (kinds.includes(prev[i].kind)) {
        const copy = prev.slice();
        copy[i] = { ...copy[i], ...patch };
        return copy;
      }
    }
    return prev;
  });
  const updateLast = (
    predicate: (s: Step) => boolean,
    patch: Partial<Step>,
  ) => setSteps((prev) => {
    for (let i = prev.length - 1; i >= 0; i--) {
      if (predicate(prev[i])) {
        const copy = prev.slice();
        copy[i] = { ...copy[i], ...patch };
        return copy;
      }
    }
    return prev;
  });
  return {
    thinking: (d: { step: string; attempt: number }) => {
      push({ id: tempId("step"), kind: "thinking", label: `调用模型（第 ${d.attempt} 次）` });
      setStatusLabel("思考中…");
    },
    toolCall: (d: { tool: string }) => {
      dropFirstByKind("pending");
      push({ id: tempId("step"), kind: "tool_call", label: `调用 ${prettyTool(d.tool)}` });
      setStatusLabel("校验中…");
    },
    toolResult: (d: { tool: string; status: "ok" | "failed"; error?: string }) => {
      updateLast(
        (s) => s.kind === "tool_call" && !s.status,
        { status: d.status, error: d.error },
      );
      if (d.status === "failed") {
        setStatusLabel("校验未通过，正在重写…");
      }
    },
    retry: (d: { reason: string; attempt: number }) => {
      push({ id: tempId("step"), kind: "retry", label: `重试（第 ${d.attempt} 次：${d.reason}）` });
    },
    code: () => {
      dropFirstByKind("pending");
      push({ id: tempId("step"), kind: "code", label: "代码生成完成" });
      setStatusLabel("正在编译视频…");
    },
    rendering: () => {
      dropFirstByKind("pending");
      push({ id: tempId("step"), kind: "rendering", label: "正在编译视频…" });
    },
    failed: (d: { error: string }) => {
      push({ id: tempId("step"), kind: "failed", label: `❌ ${d.error}` });
    },
    /** Push an immediate "正在思考…" step so the panel isn't empty. */
    pending: (label = "正在思考…") => {
      push({ id: tempId("step"), kind: "pending", label });
    },
    /** On ``done``: replace the trailing rendering/pending step with success. */
    finalizeRendering: (durationSec?: number) => {
      const finalLabel =
        typeof durationSec === "number" && durationSec > 0
          ? `渲染完成 · ${durationSec.toFixed(1)}s`
          : "渲染完成";
      updateLastByKinds(
        ["rendering", "pending"],
        { kind: "rendered", label: finalLabel, status: "ok" },
      );
    },
  };
}

export default function Page() {
  // ----- top-level state -----
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [statusLabel, setStatusLabel] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [style, setStyle] = useState<StyleId>("3b1b");
  /** 步骤日志：每次新请求（创建 / refine）开始前清空。 */
  const [steps, setSteps] = useState<Step[]>([]);

  // sidebar refresh trigger — bumped after any successful op
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  // abort handle for refine SSE stream
  const abortRef = useRef<(() => void) | null>(null);

  // ----- derived -----
  const latestAssistant = activeConversation
    ? [...activeConversation.messages].reverse().find((m) => m.role === "assistant") ?? null
    : null;
  const currentCode = latestAssistant?.code ?? null;
  const currentVideo = latestAssistant?.video_url ?? null;
  const currentScene = latestAssistant?.scene_name ?? null;
  const busy = status === "creating" || status === "generating" || status === "rendering";

  function clearError() {
    setError(null);
  }

  function reset() {
    abortRef.current?.();
    abortRef.current = null;
    setActiveConversation(null);
    setError(null);
    setStatus("idle");
    setStatusLabel("");
    setSteps([]);
  }

  function handleNew() {
    reset();
  }

  async function handlePick(c: ConversationRecord) {
    try {
      const detail = await getConversation(c.id);
      setActiveConversation(detail);
      setError(null);
      setStatus("done");
      setStatusLabel(`已加载 v${detail.version}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  // ----- main entry: any text input goes through handleSend -----
  async function handleSend(instruction: string) {
    const text = instruction.trim();
    if (!text) return;
    clearError();

    // No active conversation yet -> this is the first turn.
    if (!activeConversation) {
      await handleCreateFirst(text);
      return;
    }

    // Subsequent turns run through refine.
    await handleRefine(text);
  }

  async function handleSaveAsFewShot(message: MessageRecord) {
    if (!message.code || !activeConversation) return;
    try {
      await saveAsFewShot({
        prompt: activeConversation.title,
        code: message.code,
        style: activeConversation.style,
        source_conversation_id: activeConversation.id,
        source_message_id: message.id,
      });
      setStatusLabel("✅ 已收藏为范例");
      setTimeout(() => setStatusLabel(""), 1500);
    } catch (e) {
      setStatusLabel(`收藏失败：${(e as Error).message}`);
      setTimeout(() => setStatusLabel(""), 2500);
    }
  }



  /** Push a synthetic assistant bubble explaining the failure + a retry button. */
  function appendFailedAssistant(errorText: string, retryInstruction: string | null) {
    const failedMsg: MessageRecord & { retryInstruction?: string | null } = {
      id: tempId("msg"),
      role: "assistant",
      content: "❌ 生成失败",
      code: null,
      video_url: null,
      scene_name: null,
      duration_sec: null,
      status: "failed",
      error: errorText,
      created_at: new Date().toISOString(),
      retryInstruction,
    };
    setActiveConversation((prev) =>
      prev
        ? { ...prev, messages: [...prev.messages, failedMsg] }
        : prev,
    );
  }

  async function handleCreateFirst(prompt: string) {
    setStatus("creating");
    setStatusLabel("创建对话 + 首次生成");

    // Optimistic local conversation so the user sees their prompt bubble
    // immediately instead of after the backend round-trip.
    const optimistic: ConversationDetail = {
      id: tempId("conv"),
      title: prompt.slice(0, 20),
      style,
      version: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      messages: [
        {
          id: tempId("msg"),
          role: "user",
          content: prompt,
          code: null,
          video_url: null,
          scene_name: null,
          duration_sec: null,
          status: "ok",
          error: null,
          created_at: new Date().toISOString(),
        },
      ],
    };
    setActiveConversation(optimistic);

    setSteps([]);
    const stepHandlers = buildStepHandlers(setSteps, setStatusLabel);
    stepHandlers.pending?.();

    const sub = subscribeCreateConversation(
      prompt,
      style,
      {
        ...stepHandlers,
        started: () => setStatusLabel("开始生成…"),
        done: async (created) => {
          const durationSec = created?.duration_sec ?? undefined;
          stepHandlers.finalizeRendering?.(durationSec);
          const fresh = await getConversation(created.conversation.id);
          setActiveConversation(fresh);
          setStatus("done");
          setStatusLabel("完成");
          setHistoryRefreshKey((k) => k + 1);
        },
        failed: (d) => {
          stepHandlers.failed?.(d);
          setStatus("failed");
          setStatusLabel("失败");
          setError(d.error ?? "未知错误");
          appendFailedAssistant(d.error ?? "未知错误", prompt);
        },
      },
    );
    abortRef.current = sub.unsubscribe;
    return sub.result;
  }

  async function handleRefine(instruction: string) {
    if (!activeConversation) return;
    setStatus("generating");
    setStatusLabel("正在调整…");
    abortRef.current?.();

    // Optimistic append: show user bubble immediately.
    const optimisticUserMsg: MessageRecord = {
      id: tempId("msg"),
      role: "user",
      content: instruction,
      code: null,
      video_url: null,
      scene_name: null,
      duration_sec: null,
      status: "ok",
      error: null,
      created_at: new Date().toISOString(),
    };
    setActiveConversation((prev) =>
      prev
        ? { ...prev, messages: [...prev.messages, optimisticUserMsg] }
        : prev,
    );

    const idAtSubscribe = activeConversation.id;
    setSteps([]);
    const stepHandlers = buildStepHandlers(setSteps, setStatusLabel);
    stepHandlers.pending?.("正在分析调整要求…");

    abortRef.current = subscribeRefine(idAtSubscribe, instruction, {
      ...stepHandlers,
      started: () => setStatusLabel("开始调整…"),
      generating: () => setStatusLabel("调用模型…"),
      rendering: () => setStatus("rendering"),
      done: async (payload) => {
        const durationSec = payload?.duration_sec ?? undefined;
        stepHandlers.finalizeRendering?.(durationSec);
        const fresh = await getConversation(idAtSubscribe);
        // Only apply if we're still on the same conversation (no race).
        setActiveConversation((cur) => (cur?.id === idAtSubscribe ? fresh : cur));
        setStatus("done");
        setStatusLabel("完成");
        setHistoryRefreshKey((k) => k + 1);
      },
      failed: (d) => {
        stepHandlers.failed?.(d);
        setStatus("failed");
        setStatusLabel("失败");
        setError(d.error ?? "未知错误");
        appendFailedAssistant(d.error ?? "未知错误", instruction);
      },
    });
  }

  return (
    <main className="flex h-screen gap-3 bg-gray-950 p-3 text-gray-100">
      <HistorySidebar
        refreshKey={historyRefreshKey}
        selectedId={activeConversation?.id ?? null}
        onPick={handlePick}
        onNew={handleNew}
      />

      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <Header style={style} setStyle={setStyle} />

        {activeConversation ? (
          <CodeViewer
            videoUrl={currentVideo}
            code={currentCode}
            sceneName={currentScene}
          />
        ) : (
          <EmptyState />
        )}

        {error && (
          <div className="rounded border border-red-700 bg-red-950/40 p-3 text-sm text-red-200">
            {error}
          </div>
        )}
      </div>

      <ConversationPanel
        messages={activeConversation?.messages ?? []}
        busy={busy}
        status={statusLabel}
        steps={steps}
        onSend={handleSend}
        onRetry={(instr) => {
          // Retry replays the same instruction through the normal send path,
          // which already short-circuits to handleCreateFirst / handleRefine
          // depending on whether an active conversation is present.
          if (!instr) return;
          void handleSend(instr);
        }}
        onSaveAsFewShot={handleSaveAsFewShot}
        disabled={busy}
        placeholder={
          activeConversation
            ? "还想调整什么？例如：把背景换成白色"
            : "描述一下你想看的动画，从这里开始"
        }
      />
    </main>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center rounded-lg border border-gray-800 bg-gray-900 p-8 text-center">
      <p className="text-sm text-gray-400">
        还没有对话，在右侧输入想看的动画开始吧
      </p>
      <p className="mt-2 text-xs text-gray-600">
        例如：冒泡排序、二分查找、梯形面积、勾股定理…
      </p>
    </div>
  );
}

function Header({
  style,
  setStyle,
}: {
  style: StyleId;
  setStyle: (s: StyleId) => void;
}) {
  return (
    <header className="flex items-center justify-between rounded-lg border border-gray-800 bg-gray-900 px-4 py-3">
      <div>
        <h1 className="text-xl font-bold text-blue-400">ThinkCanvas</h1>
        <p className="text-xs text-gray-500">文字 → Manim 视频 · 多轮对话</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-500">风格</span>
        <select
          value={style}
          onChange={(e) => setStyle(e.target.value as StyleId)}
          disabled={false}
          className="rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100"
        >
          {STYLES.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
    </header>
  );
}
