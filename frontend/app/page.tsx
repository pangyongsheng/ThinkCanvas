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
  subscribeRefine,
} from "@/lib/api";

import { HistorySidebar } from "@/components/HistorySidebar";
import { CodeViewer } from "@/components/CodeViewer";
import { ConversationPanel } from "@/components/ConversationPanel";

type Status = "idle" | "creating" | "generating" | "rendering" | "done" | "failed";

// Tiny helper to mint stable-but-temp ids for optimistic messages.
function tempId(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

export default function Page() {
  // ----- top-level state -----
  const [activeConversation, setActiveConversation] = useState<ConversationDetail | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [statusLabel, setStatusLabel] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [style, setStyle] = useState<StyleId>("3b1b");

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

    try {
      const created = await createConversation(prompt, style);
      const fresh = await getConversation(created.conversation.id);
      setActiveConversation(fresh);
      setStatus("done");
      setStatusLabel("完成");
      setHistoryRefreshKey((k) => k + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("failed");
      setStatusLabel("失败");
      setActiveConversation(null);
      return;
    }

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

    abortRef.current = subscribeRefine(idAtSubscribe, instruction, {
      started: () => setStatusLabel("开始调整…"),
      generating: () => setStatusLabel("调用模型…"),
      code: () => setStatusLabel("渲染中…"),
      rendering: () => setStatus("rendering"),
      done: async () => {
        const fresh = await getConversation(idAtSubscribe);
        // Only apply if we're still on the same conversation (no race).
        setActiveConversation((cur) => (cur?.id === idAtSubscribe ? fresh : cur));
        setStatus("done");
        setStatusLabel("完成");
        setHistoryRefreshKey((k) => k + 1);
      },
      failed: (d) => {
        setStatus("failed");
        setStatusLabel("失败");
        setError(d.error ?? "未知错误");
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
        onSend={handleSend}
        onSaveAsFewShot={handleSaveAsFewShot}
        disabled={busy}
        // Empty conversation: show a welcoming placeholder.
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
