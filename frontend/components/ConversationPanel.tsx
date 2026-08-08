"use client";

import { useState } from "react";
import { MessageRecord } from "@/lib/api";

/** 单条步骤日志，对应后端一次 SSE 事件。 */
type StepKind =
  | "thinking"
  | "pending"
  | "tool_call"
  | "tool_result"
  | "retry"
  | "code"
  | "rendering"
  | "rendered"
  | "failed";

export type Step = {
  id: string;
  kind: StepKind;
  label: string;
  status?: "ok" | "failed";
  error?: string;
};

interface Props {
  messages: MessageRecord[];
  busy: boolean;
  /** Latest status pill text shown at the top of the panel. */
  status?: string;
  /** 实时步骤流（SSE 事件拼成的日志）。busy=false 后保留显示直到下次新请求。 */
  steps?: Step[];
  /** Called when the user submits the bottom input box. */
  onSend: (instruction: string) => void;
  /** Called when the user clicks "👍 收藏为范例" on an assistant bubble. */
  onSaveAsFewShot?: (message: MessageRecord) => void;
  /** Disable input (used during refine generation). */
  disabled?: boolean;
  /** Default: "还想调整什么？例如：把背景换成白色" */
  placeholder?: string;
}

function fmtTime(iso: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ConversationPanel({
  messages,
  busy,
  status,
  steps,
  onSend,
  onSaveAsFewShot,
  disabled,
  placeholder,
}: Props) {
  const [draft, setDraft] = useState("");

  function submit() {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setDraft("");
  }

  return (
    <aside className="flex w-full max-w-md shrink-0 flex-col rounded-lg border border-gray-800 bg-gray-900">
      {/* header */}
      <div className="flex items-center justify-between border-b border-gray-800 p-3">
        <h2 className="text-sm font-semibold text-gray-300">对话</h2>
        {status && (
          <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-300">
            {status}
          </span>
        )}
      </div>

      {/* messages, newest at the bottom */}
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <p className="text-center text-xs text-gray-500">对话还没开始</p>
        )}
        {messages.map((m) => (
          <Bubble
            key={m.id}
            m={m}
            onSaveAsFewShot={m.role === "assistant" ? onSaveAsFewShot : undefined}
          />
        ))}
        {steps && steps.length > 0 && (
          <div className="rounded-lg border border-gray-800 bg-gray-950/60 p-2 text-xs text-gray-400">
            <div className="mb-1 flex items-center justify-between">
              <span className="font-medium text-gray-300">
                {busy ? "正在生成…" : "上次步骤"}
              </span>
            </div>
            <ul className="space-y-0.5">
              {steps.map((s) => (
                <li key={s.id} className="flex items-start gap-1.5">
                  <span className="shrink-0">{stepIcon(s)}</span>
                  <span className={stepLabelClass(s)}>{s.label}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* input */}
      <div className="border-t border-gray-800 p-3">
        <div className="flex gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={placeholder ?? "还想调整什么？例如：把背景换成白色"}
            rows={2}
            disabled={disabled}
            className="flex-1 resize-none rounded border border-gray-700 bg-gray-950 p-2 text-sm text-gray-100 placeholder-gray-600 focus:border-blue-500 focus:outline-none disabled:opacity-50"
          />
          <button
            onClick={submit}
            disabled={disabled || !draft.trim()}
            className="self-end rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
          >
            发送
          </button>
        </div>
        <p className="mt-1 text-[10px] text-gray-500">⌘/Ctrl + Enter 发送</p>
      </div>
    </aside>
  );
}

function stepIcon(s: Step): string {
  if (s.kind === "tool_call") {
    if (s.status === "failed") return "✗";
    if (s.status === "ok") return "✓";
    return "…";
  }
  if (s.kind === "retry") return "⟳";
  if (s.kind === "code") return "✓";
  if (s.kind === "rendering") return "…";
  if (s.kind === "failed") return "✗";
  return "•";
}

function stepLabelClass(s: Step): string {
  if (s.status === "failed" || s.kind === "failed") return "text-red-300";
  if (s.kind === "code") return "text-green-300";
  return "text-gray-400";
}

function Bubble({
  m,
  onSaveAsFewShot,
}: {
  m: MessageRecord;
  onSaveAsFewShot?: (m: MessageRecord) => void;
}) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">
          {m.content}
          <div className="mt-1 text-[10px] opacity-70">{fmtTime(m.created_at)}</div>
        </div>
      </div>
    );
  }
  // assistant
  const colour =
    m.status === "ok"
      ? "border-green-700 bg-green-950/40 text-green-100"
      : "border-red-700 bg-red-950/40 text-red-100";
  return (
    <div className="flex justify-start">
      <div className={`max-w-[80%] rounded-lg border px-3 py-2 text-sm ${colour}`}>
        <div className="flex items-center gap-2">
          <span>{m.status === "ok" ? "✅" : "❌"}</span>
          <span className="font-medium">
            {m.status === "ok" ? "完成" : "失败"}
            {m.duration_sec != null && ` · ${m.duration_sec.toFixed(1)}s`}
          </span>
        </div>
        {m.error && (
          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all text-xs opacity-80">
            {m.error}
          </pre>
        )}
        {m.status === "ok" && m.code && onSaveAsFewShot && (
          <button
            onClick={() => onSaveAsFewShot(m)}
            className="mt-2 rounded border border-green-700 bg-green-900/40 px-2 py-0.5 text-[11px] text-green-200 hover:bg-green-800/60"
          >
            👍 收藏为范例
          </button>
        )}
        <div className="mt-1 text-[10px] opacity-60">{fmtTime(m.created_at)}</div>
      </div>
    </div>
  );
}
