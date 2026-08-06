"use client";

import { useEffect, useState } from "react";
import {
  ConversationRecord,
  deleteConversation,
  listConversations,
} from "@/lib/api";

interface Props {
  /** Bumped by parent after a successful generation to trigger a refresh. */
  refreshKey: number;
  /** Click a conversation -> load it into the main view. */
  onPick: (conv: ConversationRecord) => void;
  /** Currently selected conversation id (highlight). */
  selectedId?: string | null;
  /** Create a brand-new conversation in the input area. */
  onNew: () => void;
}

function fmtTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

const STYLE_LABEL: Record<string, string> = {
  "3b1b": "3B1B",
  minimal: "MIN",
  academic: "ACA",
};

export function HistorySidebar({ refreshKey, onPick, selectedId, onNew }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [conversations, setConversations] = useState<ConversationRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const rows = await listConversations(50);
      setConversations(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [refreshKey]);

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("删除这条对话？")) return;
    try {
      await deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
    } catch (err) {
      alert(`删除失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  // Collapsed rail: 48 px wide. Expanded drawer: 280 px.
  const widthClass = expanded ? "w-72" : "w-12";

  return (
    <aside
      className={`flex shrink-0 flex-col rounded-lg border border-gray-800 bg-gray-900 transition-[width] duration-150 ${widthClass}`}
    >
      <div className="flex flex-col gap-1 p-2">
        {/* New conversation button */}
        <button
          onClick={onNew}
          title="新对话"
          className="flex h-9 w-full items-center justify-center gap-1 rounded bg-blue-600 text-xs font-semibold text-white hover:bg-blue-500"
        >
          {expanded ? <span>＋ 新对话</span> : <span>＋</span>}
        </button>

        {/* Toggle expand */}
        <button
          onClick={() => setExpanded((v) => !v)}
          title={expanded ? "折叠" : "展开"}
          className="flex h-9 w-full items-center justify-center rounded bg-gray-800 text-xs text-gray-300 hover:bg-gray-700"
        >
          {expanded ? "▸" : "▾"}
        </button>

        {/* Refresh — only visible when expanded */}
        {expanded && (
          <button
            onClick={refresh}
            disabled={loading}
            className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50"
          >
            {loading ? "刷新中…" : "刷新"}
          </button>
        )}
      </div>

      {expanded && (
        <>
          {error && (
            <pre className="mb-2 max-h-32 overflow-auto rounded bg-red-950 p-2 text-xs text-red-200">
              {error}
            </pre>
          )}

          {conversations.length === 0 && !loading && (
            <p className="mt-4 text-center text-xs text-gray-500">还没有对话</p>
          )}

          <ul className="flex flex-col gap-1 overflow-y-auto p-2">
            {conversations.map((c) => {
              const active = c.id === selectedId;
              return (
                <li
                  key={c.id}
                  onClick={() => onPick(c)}
                  className={`group cursor-pointer rounded border p-2 transition-colors ${
                    active
                      ? "border-blue-500 bg-blue-950/40"
                      : "border-gray-800 bg-gray-950 hover:border-gray-600"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="line-clamp-2 flex-1 text-xs text-gray-200">
                      {c.title || <span className="italic text-gray-500">(空)</span>}
                    </p>
                    <button
                      onClick={(e) => handleDelete(c.id, e)}
                      className="invisible rounded px-1 text-xs text-gray-500 hover:bg-red-900 hover:text-red-200 group-hover:visible"
                      title="删除"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-gray-500">
                    <span className="font-mono">
                      v{c.version}
                    </span>
                    <span className="flex items-center gap-2">
                      <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-[9px] text-gray-400">
                        {STYLE_LABEL[c.style] ?? c.style}
                      </span>
                      <span>{fmtTime(c.updated_at)}</span>
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {/* Collapsed: minimal hint of current selection */}
      {!expanded && selectedId && (
        <div className="mt-2 flex flex-col items-center gap-1 px-1">
          {conversations
            .filter((c) => c.id === selectedId)
            .slice(0, 1)
            .map((c) => (
              <div
                key={c.id}
                className="flex h-9 w-9 items-center justify-center rounded bg-blue-700 text-xs font-bold text-white"
                title={c.title}
              >
                {(STYLE_LABEL[c.style] ?? c.style).slice(0, 3)}
              </div>
            ))}
        </div>
      )}
    </aside>
  );
}
