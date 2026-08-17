"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LeftPanel } from "@/components/v2/LeftPanel";
import { RightPanel } from "@/components/v2/RightPanel";
import { ChatMsg } from "@/components/v2/ChatBox";
import {
  V2Conversation,
  V2StepEvent,
  v2ConfirmScript,
  v2ContinueConversation,
  v2CreateConversation,
  v2GetConversation,
  v2StopConversation,
  v2SubscribeConversation,
} from "@/lib/api-v2";

function tempId(p: string): string {
  return `${p}_${Math.random().toString(36).slice(2, 10)}`;
}

const BUSY_PHASES = new Set(["classifying", "designing_script", "coding", "rendering"]);

export default function V2HomePage() {
  const [conv, setConv] = useState<V2Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [steps, setSteps] = useState<V2StepEvent[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [scriptDraft, setScriptDraft] = useState<string>("");
  const [scriptDirty, setScriptDirty] = useState(false);
  const unsubRef = useRef<(() => void) | null>(null);

  const busy = useMemo(() => conv != null && BUSY_PHASES.has(conv.phase), [conv]);
  const currentLabel = useMemo(() => {
    const last = steps[steps.length - 1];
    return last?.status === "running" ? last.label : null;
  }, [steps]);

  useEffect(() => () => unsubRef.current?.(), []);

  useEffect(() => {
    if (!conv) return;
    unsubRef.current?.();
    setSteps([]);
    const unsub = v2SubscribeConversation(conv.id, {
      onStep: (e) => setSteps((prev) => [...prev, e]),
      onUpdate: (u) => {
        setConv(u);
        if (u.script != null && !scriptDirty) setScriptDraft(u.script);
      },
      onError: (e) => {
        setMessages((m) => [...m, { id: tempId("err"), role: "system", content: `SSE 错误：${e.message}` }]);
      },
      onDone: () => {/* 流结束 */},
    });
    unsubRef.current = unsub;
    return () => unsub();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conv?.id]);

  useEffect(() => {
    if (!conv) return;
    v2GetConversation(conv.id).then((c) => {
      setConv(c);
      if (c.script != null) {
        setScriptDraft(c.script);
        setScriptDirty(false);
      }
    }).catch((e) => {
      setMessages((m) => [...m, { id: tempId("err"), role: "system", content: `加载失败：${e.message}` }]);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conv?.id]);

  const handleNew = useCallback(() => {
    unsubRef.current?.();
    setConv(null);
    setMessages([]);
    setSteps([]);
    setScriptDraft("");
    setScriptDirty(false);
  }, []);

  const handlePick = useCallback((c: V2Conversation) => {
    unsubRef.current?.();
    setConv(c);
    setScriptDraft(c.script ?? "");
    setScriptDirty(false);
    setMessages([{ id: tempId("sys"), role: "system", content: `已切到会话 ${c.id.slice(-6)}` }]);
  }, []);

  const handleSend = useCallback(async (text: string) => {
    const userMsg: ChatMsg = { id: tempId("u"), role: "user", content: text };
    setMessages((m) => [...m, userMsg]);
    try {
      if (!conv) {
        const created = await v2CreateConversation(text);
        setConv(created);
        setMessages((m) => [...m, { id: tempId("a"), role: "assistant", content: `已创建会话，进入"${created.phase}"阶段。` }]);
        setRefreshKey((k) => k + 1);
      } else {
        await v2ContinueConversation(conv.id, text);
      }
    } catch (e) {
      setMessages((m) => [...m, { id: tempId("err"), role: "system", content: `请求失败：${(e as Error).message}` }]);
    }
  }, [conv]);

  const handleStop = useCallback(async () => {
    if (!conv) return;
    try {
      await v2StopConversation(conv.id);
    } catch (e) {
      setMessages((m) => [...m, { id: tempId("err"), role: "system", content: `停止失败：${(e as Error).message}` }]);
    }
  }, [conv]);

  const handleScriptConfirm = useCallback(async () => {
    if (!conv) return;
    try {
      await v2ConfirmScript(conv.id, scriptDraft);
      setScriptDirty(false);
    } catch (e) {
      setMessages((m) => [...m, { id: tempId("err"), role: "system", content: `确认失败：${(e as Error).message}` }]);
    }
  }, [conv, scriptDraft]);

  const handleScriptCancel = useCallback(() => {
    if (!conv) return;
    setScriptDraft(conv.script ?? "");
    setScriptDirty(false);
  }, [conv]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-gray-200 text-gray-900">
      <div className="min-w-0 flex-1">
        <LeftPanel
          script={conv?.script ?? null}
          code={conv?.code ?? null}
          sceneName={conv?.scene_name ?? null}
          videoUrl={conv?.video_url ?? null}
          phase={conv?.phase ?? "idle"}
          error={conv?.error ?? null}
          scriptEditing={conv?.phase === "script_pending"}
          scriptDirty={scriptDirty}
          onScriptChange={(v) => {
            setScriptDraft(v);
            setScriptDirty(v !== (conv?.script ?? ""));
          }}
          onScriptConfirm={handleScriptConfirm}
          onScriptCancel={handleScriptCancel}
          busy={busy}
        />
      </div>

      <div className="flex h-full w-[420px] shrink-0 flex-col">
        <RightPanel
          conversations={[]}
          selectedId={conv?.id ?? null}
          refreshKey={refreshKey}
          messages={messages}
          steps={steps}
          currentLabel={currentLabel}
          busy={busy}
          onPick={handlePick}
          onNew={handleNew}
          onSend={handleSend}
          onStop={handleStop}
        />
      </div>
    </div>
  );
}
