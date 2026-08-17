"use client";

import { useState } from "react";

interface Props {
  videoUrl: string | null;
  isRendering: boolean;
  error: string | null;
}

/** 左侧 · 视频 tab：渲染中显示进度，渲染完播放视频。 */
export function VideoView({ videoUrl, isRendering, error }: Props) {
  const [reloadKey, setReloadKey] = useState(0);

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-red-700">
        <p className="text-sm">渲染失败</p>
        <pre className="max-h-48 overflow-auto rounded bg-red-50 p-3 text-xs">
{error}
        </pre>
      </div>
    );
  }

  if (isRendering) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-gray-700">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-gray-300 border-t-blue-400" />
        <p className="text-sm">编译视频中…</p>
      </div>
    );
  }

  if (!videoUrl) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-gray-400">
        尚无视频。先在右侧发起对话。
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4">
      <div className="flex items-center justify-between text-xs text-gray-400">
        <span>视频预览</span>
        <button
          onClick={() => setReloadKey((k) => k + 1)}
          className="rounded border border-gray-300 px-2 py-1 hover:bg-gray-100"
        >
          重新加载
        </button>
      </div>
      <video
        key={reloadKey}
        src={videoUrl}
        controls
        className="max-h-full w-full rounded bg-black"
      />
    </div>
  );
}
