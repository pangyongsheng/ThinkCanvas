"use client";

import { useEffect, useState } from "react";
import { V2Conversation, v2DeleteConversation, v2ListConversations } from "@/lib/api-v2";

interface Props {
  refreshKey: number;
  selectedId: string | null;
  onPick: (conv: V2Conversation) => void;
  onNew: () => void;
}

function fmtTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function HistoryList({ refreshKey, selectedId, onPick, onNew }: Props) {
  const [rows, setRows] = useState<V2Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const list = await v2ListConversations(50);
      setRows(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("删除这条对话？")) return;
    try {
      await v2DeleteConversation(id);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="flex h-full flex-col gap-2 border-b border-gray-300 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-gray-400">历史会话</span>
        <button
          onClick={onNew}
          className="rounded bg-gray-900 px-2 py-0.5 text-xs text-white hover:bg-gray-800"
        >
          + 新建
        </button>
      </div>
      {error && <p className="text-xs text-red-700">{error}</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && rows.length === 0 ? (
          <p className="text-xs text-gray-400">加载中…</p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-gray-400">暂无会话</p>
        ) : (
          <ul className="space-y-1">
            {rows.map((r) => (
              <li
                key={r.id}
                onClick={() => onPick(r)}
                className={`group flex cursor-pointer items-center justify-between rounded px-2 py-1.5 text-xs hover:bg-gray-100 ${
                  selectedId === r.id ? "bg-gray-100" : ""
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-gray-800">{r.title ?? "（无标题）"}</p>
                  <p className="truncate text-[10px] text-gray-400">
                    {fmtTime(r.updated_at)} · {r.phase}
                  </p>
                </div>
                <button
                  onClick={(e) => handleDelete(r.id, e)}
                  className="ml-1 rounded px-1 text-gray-400 opacity-0 hover:bg-red-100 hover:text-red-700 group-hover:opacity-100"
                  title="删除"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
