"use client";

import { useEffect, useState } from "react";

interface Props {
  script: string | null;
  isEditing: boolean;
  isDirty: boolean;
  onChange: (v: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
  disabled: boolean;
}

/** 左侧 · 脚本 tab：可编辑的脚本文案。脚本待确认时高亮编辑区。 */
export function ScriptView({ script, isEditing, isDirty, onChange, onConfirm, onCancel, disabled }: Props) {
  const [local, setLocal] = useState(script ?? "");
  useEffect(() => setLocal(script ?? ""), [script]);

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-center justify-between text-xs">
        <span className="text-gray-400">
          脚本 {isDirty && <span className="text-amber-400">（未保存）</span>}
        </span>
        <span className="text-gray-400">{local.length} 字</span>
      </div>
      <textarea
        value={local}
        onChange={(e) => {
          setLocal(e.target.value);
          onChange(e.target.value);
        }}
        placeholder={isEditing ? "脚本生成中…" : "脚本文案将出现在这里"}
        className={`flex-1 resize-none rounded border bg-white p-3 text-sm leading-6 outline-none ${
          isEditing ? "border-gray-900" : "border-gray-300 focus:border-gray-900"
        }`}
      />
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={onCancel}
          disabled={disabled || !isDirty}
          className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-100 disabled:opacity-40"
        >
          撤销
        </button>
        <button
          onClick={onConfirm}
          disabled={disabled || !local.trim()}
          className="rounded bg-gray-900 px-3 py-1 text-sm text-white hover:bg-gray-800 disabled:opacity-40"
        >
          确认脚本
        </button>
      </div>
    </div>
  );
}
