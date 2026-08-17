"use client";

import { useEffect, useRef, useState } from "react";
import { V2StepEvent } from "@/lib/api-v2";

export interface ChatMsg {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
}

interface Props {
  messages: ChatMsg[];
  steps: V2StepEvent[];
  busy: boolean;
  /** 当前进度阶段（最新一条 step 的 label）。 */
  currentLabel: string | null;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** 右侧 · 对话框：消息流 + 当前步骤 + 输入区。 */
export function ChatBox({ messages, steps, busy, currentLabel, onSend, onStop }: Props) {
  const [draft, setDraft] = useState("");
  const tailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    tailRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, steps.length]);

  function submit() {
    const v = draft.trim();
    if (!v || busy) return;
    onSend(v);
    setDraft("");
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 消息流 */}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {messages.length === 0 && (
          <p className="text-xs text-gray-400">还没有对话，输入消息开始。</p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`max-w-[90%] rounded-lg px-3 py-2 text-sm leading-6 ${
              m.role === "user"
                ? "ml-auto bg-blue-600 text-white"
                : m.role === "system"
                ? "bg-red-50 text-red-700"
                : "bg-gray-100 text-gray-100"
            }`}
          >
            {m.content}
          </div>
        ))}

        {/* 当前进度提示（最新一条 SSE step） */}
        {currentLabel && (
          <div className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue-400" />
            <span>{currentLabel}</span>
          </div>
        )}

        <div ref={tailRef} />
      </div>

      {/* 操作按钮栏 */}
      {busy && (
        <div className="flex shrink-0 items-center gap-2 border-t border-gray-300 px-3 py-1.5 text-xs">
          <button
            onClick={onStop}
            className="rounded border border-red-300 px-2 py-1 text-red-700 hover:bg-red-100"
          >
            停止
          </button>
        </div>
      )}

      {/* 输入区 */}
      <div className="flex shrink-0 gap-2 border-t border-gray-300 p-3">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={busy ? "生成中…（按停止可中断）" : "输入消息，Enter 发送，Shift+Enter 换行"}
          rows={2}
          className="flex-1 resize-none rounded border border-gray-300 bg-gray-50 px-3 py-2 text-sm outline-none focus:border-gray-900"
        />
        <button
          onClick={submit}
          disabled={busy || !draft.trim()}
          className="self-end rounded bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-800 disabled:opacity-40"
        >
          发送
        </button>
      </div>
    </div>
  );
}
