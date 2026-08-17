"use client";

import { useState } from "react";
import { VideoView } from "./VideoView";
import { ScriptView } from "./ScriptView";
import { CodeView } from "./CodeView";

type Tab = "video" | "script" | "code";

interface Props {
  script: string | null;
  code: string | null;
  sceneName: string | null;
  videoUrl: string | null;
  phase: string;
  error: string | null;
  /** 脚本编辑态：编辑区可写且未确认前为 true。 */
  scriptEditing: boolean;
  scriptDirty: boolean;
  onScriptChange: (v: string) => void;
  onScriptConfirm: () => void;
  onScriptCancel: () => void;
  busy: boolean;
}

/** 左侧内容区：视频 / 脚本 / 代码 三个 tab。 */
export function LeftPanel(props: Props) {
  const [tab, setTab] = useState<Tab>("video");
  const isRendering = props.phase === "rendering";
  const isCoding = props.phase === "coding";
  const isFailed = props.phase === "failed";

  return (
    <div className="flex h-full flex-col">
      {/* 顶部 tab 栏 */}
      <div className="flex shrink-0 border-b border-gray-300 bg-gray-200">
        {([
          ["video", "视频"],
          ["script", "脚本"],
          ["code", "代码"],
        ] as [Tab, string][]).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm transition ${
              tab === k
                ? "border-b-2 border-gray-900 text-gray-900"
                : "text-gray-400 hover:text-gray-800"
            }`}
          >
            {label}
          </button>
        ))}
        <div className="ml-auto flex items-center px-3 text-xs text-gray-400">
          阶段：{props.phase}
        </div>
      </div>

      {/* tab 内容 */}
      <div className="min-h-0 flex-1">
        {tab === "video" && (
          <VideoView
            videoUrl={props.videoUrl}
            isRendering={isRendering}
            error={isFailed ? props.error : null}
          />
        )}
        {tab === "script" && (
          <ScriptView
            script={props.script}
            isEditing={props.scriptEditing}
            isDirty={props.scriptDirty}
            onChange={props.onScriptChange}
            onConfirm={props.onScriptConfirm}
            onCancel={props.onScriptCancel}
            disabled={props.busy}
          />
        )}
        {tab === "code" && (
          <CodeView
            code={props.code}
            sceneName={props.sceneName}
            isCoding={isCoding}
          />
        )}
      </div>
    </div>
  );
}
