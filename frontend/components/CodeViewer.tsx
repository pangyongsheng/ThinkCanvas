"use client";

import { useState } from "react";

interface Props {
  videoUrl: string | null;
  code: string | null;
  sceneName: string | null;
  /** Render an empty-state when there's nothing to show yet. */
  emptyHint?: string;
}

/** Middle column: tabbed "视频 | 代码" viewer. Code is collapsed by default. */
export function CodeViewer({ videoUrl, code, sceneName, emptyHint }: Props) {
  const [tab, setTab] = useState<"video" | "code">("video");
  const [codeOpen, setCodeOpen] = useState(false);

  const hasContent = videoUrl || code;

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-gray-800 bg-gray-900">
      {!hasContent && (
        <div className="flex flex-1 items-center justify-center text-sm text-gray-500">
          {emptyHint ?? "生成结果会显示在这里"}
        </div>
      )}

      {hasContent && (
        <>
          <div className="flex items-center gap-1 border-b border-gray-800 p-2">
            <Tab active={tab === "video"} onClick={() => setTab("video")}>
              视频
            </Tab>
            <Tab active={tab === "code"} onClick={() => setTab("code")} disabled={!code}>
              代码
            </Tab>
            <span className="ml-2 text-xs text-gray-500">{sceneName ?? ""}</span>
            <span className="flex-1" />
            {tab === "code" && code && (
              <button
                onClick={() => setCodeOpen((v) => !v)}
                className="rounded bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700"
              >
                {codeOpen ? "▾ 折叠" : "▸ 展开"}
              </button>
            )}
          </div>

          <div className="flex-1 overflow-auto p-3">
            {tab === "video" && videoUrl && (
              <video
                key={videoUrl}
                src={videoUrl}
                controls
                className="w-full rounded bg-black"
              />
            )}
            {tab === "video" && !videoUrl && (
              <p className="text-sm text-gray-500">视频还没渲染好</p>
            )}

            {tab === "code" && code && (
              <>
                {codeOpen ? (
                  <pre className="overflow-auto rounded bg-gray-950 p-3 text-xs text-gray-200">
                    <code>{code}</code>
                  </pre>
                ) : (
                  <div className="rounded border border-gray-800 bg-gray-950 p-3 text-xs text-gray-500">
                    代码默认折叠（点上方"展开"查看）
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function Tab({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
        active
          ? "bg-blue-600 text-white"
          : "bg-gray-800 text-gray-300 hover:bg-gray-700"
      } disabled:cursor-not-allowed disabled:opacity-40`}
    >
      {children}
    </button>
  );
}
