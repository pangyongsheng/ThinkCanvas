import { getOrCreateUserId } from "./user";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// 类型定义（按 v2 流程图：分类 → 脚本/动画/修改 → 渲染 → 回流）
// ---------------------------------------------------------------------------

export type V2Intent =
  | "generate_script"
  | "refine_script"
  | "generate_code"
  | "refine_code"
  | "render_video"
  | "auto";

export type V2Phase =
  | "idle"
  | "classifying"
  | "designing_script"
  | "script_pending"
  | "coding"
  | "rendering"
  | "completed"
  | "failed";

export interface V2Conversation {
  id: string;
  title: string | null;
  phase: V2Phase;
  intent: V2Intent | null;
  script: string | null;
  code: string | null;
  scene_name: string | null;
  video_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface V2StepEvent {
  node: string;
  label: string;
  status: "ok" | "failed" | "running";
  payload?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// 基础 fetch 封装
// ---------------------------------------------------------------------------

export class V2ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`HTTP ${status}`);
  }
}

async function v2Fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": getOrCreateUserId(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  const text = await res.text();
  if (!res.ok) {
    let detail: unknown = text;
    try {
      detail = JSON.parse(text);
    } catch {
      /* keep raw text */
    }
    throw new V2ApiError(res.status, detail);
  }
  return text ? JSON.parse(text) : ({} as T);
}

// ---------------------------------------------------------------------------
// 会话管理
// ---------------------------------------------------------------------------

export async function v2ListConversations(limit = 50): Promise<V2Conversation[]> {
  return v2Fetch<V2Conversation[]>(`/api/v2/conversations?limit=${limit}`);
}

export async function v2GetConversation(id: string): Promise<V2Conversation> {
  return v2Fetch<V2Conversation>(`/api/v2/conversations/${id}`);
}

export async function v2DeleteConversation(id: string): Promise<{ deleted: string }> {
  return v2Fetch<{ deleted: string }>(`/api/v2/conversations/${id}`, {
    method: "DELETE",
  });
}

// ---------------------------------------------------------------------------
// 核心交互
// ---------------------------------------------------------------------------

/** 新建会话，自动触发"分类 → 分支"流程。 */
export async function v2CreateConversation(
  input: string,
  intent?: V2Intent,
): Promise<V2Conversation> {
  return v2Fetch<V2Conversation>(`/api/v2/conversations`, {
    method: "POST",
    body: JSON.stringify({ input, intent: intent ?? "auto" }),
  });
}

/** 续轮：用户后续输入（修改脚本 / 调整动画 / 重生成 等）。 */
export async function v2ContinueConversation(
  id: string,
  input: string,
  intent?: V2Intent,
): Promise<V2Conversation> {
  return v2Fetch<V2Conversation>(`/api/v2/conversations/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ input, intent: intent ?? "auto" }),
  });
}

/** 用户编辑脚本后确认，触发"生成代码 → 渲染"。 */
export async function v2ConfirmScript(
  id: string,
  script: string,
): Promise<V2Conversation> {
  return v2Fetch<V2Conversation>(`/api/v2/conversations/${id}/confirm-script`, {
    method: "POST",
    body: JSON.stringify({ script }),
  });
}

/** 主动触发渲染（不修改脚本/代码）。 */
export async function v2TriggerRender(id: string): Promise<V2Conversation> {
  return v2Fetch<V2Conversation>(`/api/v2/conversations/${id}/render`, {
    method: "POST",
  });
}

/** 停止正在进行的流程。 */
export async function v2StopConversation(id: string): Promise<V2Conversation> {
  return v2Fetch<V2Conversation>(`/api/v2/conversations/${id}/stop`, {
    method: "POST",
  });
}

// ---------------------------------------------------------------------------
// SSE 订阅
// ---------------------------------------------------------------------------

export interface V2StreamHandlers {
  onStep?: (e: V2StepEvent) => void;
  onUpdate?: (conv: V2Conversation) => void;
  onError?: (e: Error) => void;
  onDone?: () => void;
}

/** 订阅会话 SSE 流，返回 dispose 函数。 */
export function v2SubscribeConversation(
  id: string,
  handlers: V2StreamHandlers,
): () => void {
  const userId = getOrCreateUserId();
  // EventSource 不支持自定义 header，user_id 走 query。
  const url = `${BACKEND_URL}/api/v2/conversations/${id}/events?user_id=${encodeURIComponent(userId)}`;
  const es = new EventSource(url);
  es.addEventListener("step", (ev) => {
    try {
      const data = JSON.parse((ev as MessageEvent).data) as V2StepEvent;
      handlers.onStep?.(data);
    } catch (e) {
      handlers.onError?.(e as Error);
    }
  });
  es.addEventListener("update", (ev) => {
    try {
      const data = JSON.parse((ev as MessageEvent).data) as V2Conversation;
      handlers.onUpdate?.(data);
    } catch (e) {
      handlers.onError?.(e as Error);
    }
  });
  es.addEventListener("error", () => {
    handlers.onError?.(new Error("SSE 连接断开"));
  });
  es.addEventListener("done", () => {
    handlers.onDone?.();
    es.close();
  });
  return () => es.close();
}
