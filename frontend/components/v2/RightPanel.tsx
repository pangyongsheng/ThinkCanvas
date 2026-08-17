"use client";

import { HistoryList } from "./HistoryList";
import { ChatBox, ChatMsg } from "./ChatBox";
import { V2Conversation, V2StepEvent } from "@/lib/api-v2";

interface Props {
  conversations: V2Conversation[];
  selectedId: string | null;
  refreshKey: number;
  messages: ChatMsg[];
  steps: V2StepEvent[];
  currentLabel: string | null;
  busy: boolean;
  onPick: (conv: V2Conversation) => void;
  onNew: () => void;
  onSend: (text: string) => void;
  onStop: () => void;
}

/** 右侧装配：顶部历史会话 + 下方对话框。 */
export function RightPanel(props: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col border-l border-gray-300">
      {/* 顶部：标题 + 新建按钮 */}
      <div className="flex shrink-0 items-center justify-between border-b border-gray-300 px-3 py-2">
        <h2 className="text-sm font-medium text-gray-800">ThinkCanvas v2</h2>
        <button
          onClick={props.onNew}
          className="rounded bg-gray-900 px-2 py-0.5 text-xs text-white hover:bg-gray-800"
        >
          新建会话
        </button>
      </div>

      {/* 历史会话：约 30% 高 */}
      <div className="h-[30%] min-h-0">
        <HistoryList
          refreshKey={props.refreshKey}
          selectedId={props.selectedId}
          onPick={props.onPick}
          onNew={props.onNew}
        />
      </div>

      {/* 对话框：占满剩余 */}
      <div className="min-h-0 flex-1">
        <ChatBox
          messages={props.messages}
          steps={props.steps}
          busy={props.busy}
          currentLabel={props.currentLabel}
          onSend={props.onSend}
          onStop={props.onStop}
        />
      </div>
    </div>
  );
}
