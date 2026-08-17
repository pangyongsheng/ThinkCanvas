"use client";

interface Props {
  code: string | null;
  sceneName: string | null;
  isCoding: boolean;
}

/** 左侧 · 代码 tab：展示生成的 Manim 代码（只读）。 */
export function CodeView({ code, sceneName, isCoding }: Props) {
  if (isCoding) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-gray-700">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-gray-300 border-t-emerald-400" />
        <p className="text-sm">生成 Manim 代码中…</p>
      </div>
    );
  }

  if (!code) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        代码将在脚本确认后生成。
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-2 p-4">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>Manim 代码</span>
        {sceneName && <span className="rounded bg-gray-100 px-2 py-0.5">{sceneName}</span>}
      </div>
      <pre className="flex-1 overflow-auto rounded bg-gray-50 p-3 text-xs leading-5 text-gray-800">
{code}
      </pre>
    </div>
  );
}
