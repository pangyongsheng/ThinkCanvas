import { getOrCreateUserId } from "./user";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export interface GenerateResult {
  prompt: string;
  code: string;
  scene_name: string | null;
  model: string;
  attempts: number;
}

export interface RenderResult {
  code_path: string;
  video_url: string | null;
  duration_sec: number;
  error: string | null;
}

export interface TaskRecord {
  id: string;
  prompt: string;
  code: string | null;
  scene_name: string | null;
  video_url: string | null;
  status: "pending" | "succeeded" | "failed" | string;
  style: StyleId | string;
  duration_sec: number;
  error: string | null;
  tool_calls: number;
  created_at: string;
  updated_at: string;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
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
      // keep raw text
    }
    throw new ApiError(res.status, detail);
  }
  return text ? JSON.parse(text) : ({} as T);
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`HTTP ${status}`);
  }
}

export async function checkHealth() {
  return fetchJson<{ status: string; service: string }>("/api/v1/health");
}

export async function checkReadyz() {
  return fetchJson<{ status: string; db: number }>("/api/v1/readyz");
}

export async function generateCode(prompt: string): Promise<GenerateResult> {
  return fetchJson<GenerateResult>("/api/v1/generate", {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export async function renderManim(
  code: string,
  sceneName?: string,
): Promise<RenderResult> {
  return fetchJson<RenderResult>("/api/v1/render", {
    method: "POST",
    body: JSON.stringify({ code, scene_name: sceneName }),
  });
}

// ---------------------------------------------------------------------------
// Task history (Step 5)
// ---------------------------------------------------------------------------

export async function listTasks(limit = 50): Promise<TaskRecord[]> {
  return fetchJson<TaskRecord[]>(`/api/v1/tasks?limit=${limit}`);
}

export async function getTask(id: string): Promise<TaskRecord> {
  return fetchJson<TaskRecord>(`/api/v1/tasks/${id}`);
}

export async function deleteTask(id: string): Promise<{ deleted: string }> {
  return fetchJson<{ deleted: string }>(`/api/v1/tasks/${id}`, {
    method: "DELETE",
  });
}

export type StyleId = "3b1b" | "minimal" | "academic";

export interface StyleOption {
  id: StyleId;
  label: string;
}

export const STYLES: StyleOption[] = [
  { id: "3b1b", label: "3Blue1Brown（深色鲜艳）" },
  { id: "minimal", label: "Minimal（深色极简）" },
  { id: "academic", label: "Academic（明亮学术）" },
];

// ---------------------------------------------------------------------------
// SSE: subscribeGenerate
// ---------------------------------------------------------------------------

export type StreamEvent =
  | "started"
  | "llm_call"
  | "validating"
  | "code"
  | "rendering"
  | "retry"
  | "done"
  | "failed";

export interface StreamHandlers {
  started?: (data: { prompt: string; task_id?: string }) => void;
  llm_call?: (data: { step: string; attempt: number }) => void;
  validating?: (data: { attempt: number }) => void;
  code?: (data: {
    code: string;
    scene_name: string;
    attempts: number;
    task_id?: string;
  }) => void;
  rendering?: (data: { scene_name?: string }) => void;
  retry?: (data: { reason: string; attempt: number; error?: string }) => void;
  done?: (data: {
    code: string;
    scene_name: string;
    video_url: string;
    attempts: number;
    duration_sec: number;
    task_id?: string;
  }) => void;
  failed?: (data: {
    error: string;
    history?: unknown[];
    task_id?: string;
    tool_calls?: number;
    iterations?: number;
    last_message?: string;
  }) => void;
}

export function subscribeGenerate(
  prompt: string,
  handlers: StreamHandlers,
  style: StyleId = "3b1b",
): () => void {
  const url = new URL("/api/v1/generate/stream", BACKEND_URL);
  url.searchParams.set("prompt", prompt);
  url.searchParams.set("style", style);
  const es = new EventSource(url.toString());

  for (const [name, fn] of Object.entries(handlers)) {
    if (!fn) continue;
    es.addEventListener(name, (e) => {
      try {
        fn(JSON.parse((e as MessageEvent).data));
      } catch {
        // ignore parse errors
      }
    });
  }

  return () => es.close();
}

// ---------------------------------------------------------------------------
// Multi-turn conversations (v1.x)
// ---------------------------------------------------------------------------

export interface ConversationRecord {
  id: string;
  title: string;
  style: StyleId | string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface MessageRecord {
  id: string;
  role: "user" | "assistant";
  content: string;
  code: string | null;
  video_url: string | null;
  scene_name: string | null;
  duration_sec: number | null;
  status: string;
  error: string | null;
  created_at: string;
}

export interface ConversationDetail extends ConversationRecord {
  messages: MessageRecord[];
}

export interface SceneDraft {
  index: number;
  duration_sec: number;
  description: string;
  animation: string;
  text_overlays: string[];
  math_objects: string[];
}

export interface ScriptDraft {
  title: string;
  concept: string;
  total_duration_sec: number;
  style: string;
  scenes: SceneDraft[];
}

/** POST /conversations 的 done 事件 payload。
 *  - status="done"          — 正常出视频完成
 *  - status="script_ready"  — 脚本阶段等用户确认（assistant_message/code/video 都没）
 */
export interface CreateConversationResult {
  status?: "done" | "script_ready";
  conversation: ConversationRecord;
  message: MessageRecord;
  assistant_message: MessageRecord | null;
  code: string | null;
  video_url: string | null;
  duration_sec: number | null;
  scene_name: string | null;
  script?: ScriptDraft;
  need_script?: boolean;
}

export async function createConversation(
  prompt: string,
  style: StyleId = "3b1b",
): Promise<CreateConversationResult> {
  // SSE 流式：POST /conversations 现在返 event-stream。
  // 这里简化用法：不传 handlers，只等 done 事件拿结果。
  const sub = subscribeCreateConversation(prompt, style, {});
  return sub.result;
}

export async function listConversations(limit = 50): Promise<ConversationRecord[]> {
  return fetchJson<ConversationRecord[]>(`/api/v1/conversations?limit=${limit}`);
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return fetchJson<ConversationDetail>(`/api/v1/conversations/${id}`);
}

export async function deleteConversation(id: string): Promise<{ deleted: string }> {
  return fetchJson<{ deleted: string }>(`/api/v1/conversations/${id}`, {
    method: "DELETE",
  });
}

/** POST /conversations/{id}/confirm — 用户确认脚本后调，触发 Coder 续跑。 */
export interface ConfirmConversationResult {
  code: string;
  scene_name: string | null;
  conversation_id: string;
}

export async function confirmConversation(
  conversationId: string,
): Promise<ConfirmConversationResult> {
  return fetchJson<ConfirmConversationResult>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/confirm`,
    { method: "POST" },
  );
}

// ---------- Few-shot library ----------

export interface FewShotRecord {
  id: string;
  prompt: string;
  code: string;
  summary: string;
  style: string;
  source_conversation_id: string | null;
  source_message_id: string | null;
  created_at: string;
}

export interface SaveFewShotInput {
  prompt: string;
  code: string;
  style: string;
  source_conversation_id?: string;
  source_message_id?: string;
}

export async function saveAsFewShot(input: SaveFewShotInput): Promise<FewShotRecord> {
  return fetchJson<FewShotRecord>("/api/v1/few_shots", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listFewShots(
  style?: string,
  limit = 50,
): Promise<FewShotRecord[]> {
  const params = new URLSearchParams();
  if (style) params.set("style", style);
  params.set("limit", String(limit));
  return fetchJson<FewShotRecord[]>(`/api/v1/few_shots?${params}`);
}

export interface RefineStreamHandlers {
  started?: (data: { conversation_id: string; user_message_id: string }) => void;
  generating?: (data: { instruction: string }) => void;
  /** Agent 每次调 LLM 前发一条。 */
  thinking?: (data: { step: string; attempt: number }) => void;
  /** Agent 每次调工具（validate_manim_code / render_manim_dryrun）前发一条。 */
  toolCall?: (data: { tool: string }) => void;
  /** 工具返回后发一条，status 区分 ok / failed。 */
  toolResult?: (data: { tool: string; status: "ok" | "failed"; error?: string }) => void;
  /** invoke_with_recovery 触发 1-shot 重试时发一条（罕见）。 */
  retry?: (data: { reason: string; attempt: number; error?: string }) => void;
  code?: (data: { code: string; scene_name: string }) => void;
  rendering?: (data: { scene_name?: string }) => void;
  done?: (data: {
    code: string;
    video_url: string;
    scene_name: string;
    duration_sec: number;
  }) => void;
  failed?: (data: {
    error: string;
    tool_calls?: number;
    last_message?: string;
  }) => void;
}

/** POST /conversations 流式（SSE）handlers — 与 RefineStreamHandlers 共用同一组步骤事件。 */
export type CreateStreamHandlers = Omit<
  RefineStreamHandlers,
  "started" | "generating" | "done"
> & {
  started?: (data: { conversation_id: string }) => void;
  done?: (data: CreateConversationResult) => void;
};

/** 后端事件名 → 前端 handler 名（snake_case → camelCase） */
const EVENT_TO_HANDLER: Record<string, string> = {
  tool_call: "toolCall",
  tool_result: "toolResult",
};

function resolveHandlerName(eventName: string): string {
  return EVENT_TO_HANDLER[eventName] ?? eventName;
}

/**
 * POST /conversations 改 SSE 流式后用这个订阅。返回 unsubscribe + 一个 Promise：
 * Promise 在收到 ``done`` 事件时 resolve（payload 跟旧 ``createConversation`` 返回值一致），
 * 收到 ``failed`` 或网络错误时 reject。
 */
export function subscribeCreateConversation(
  prompt: string,
  style: StyleId,
  handlers: CreateStreamHandlers,
): { unsubscribe: () => void; result: Promise<CreateConversationResult> } {
  const controller = new AbortController();
  const url = `${BACKEND_URL}/api/v1/conversations`;

  const result = new Promise<CreateConversationResult>((resolve, reject) => {
    (async () => {
      let res: Response;
      try {
        res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-User-Id": getOrCreateUserId(),
          },
          body: JSON.stringify({ prompt, style }),
          signal: controller.signal,
        });
      } catch (err) {
        handlers.failed?.({ error: String(err) });
        reject(err);
        return;
      }
      if (!res.ok || !res.body) {
        const errMsg = `HTTP ${res.status}`;
        handlers.failed?.({ error: errMsg });
        reject(new Error(errMsg));
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          let frameEnd: number;
          while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, frameEnd);
            buffer = buffer.slice(frameEnd + 2);
            const lines = frame.split("\n");
            let eventName = "message";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event:")) eventName = line.slice(6).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (!data) continue;
            let parsed: unknown;
            try {
              parsed = JSON.parse(data);
            } catch {
              continue;
            }
            const fn = (handlers as Record<string, ((d: unknown) => void) | undefined>)[
              resolveHandlerName(eventName)
            ];
            if (fn) fn(parsed);
            if (eventName === "done") {
              resolve(parsed as CreateConversationResult);
              return;
            }
            if (eventName === "failed") {
              reject(new Error(((parsed as { error?: string })?.error) ?? "failed"));
              return;
            }
          }
        }
      } catch (err) {
        handlers.failed?.({ error: String(err) });
        reject(err);
      }
    })();
  });

  return {
    unsubscribe: () => controller.abort(),
    result,
  };
}

export function subscribeRefine(
  conversationId: string,
  instruction: string,
  handlers: RefineStreamHandlers,
): () => void {
  const controller = new AbortController();
  const url = `${BACKEND_URL}/api/v1/conversations/${encodeURIComponent(
    conversationId,
  )}/refine`;
  (async () => {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-User-Id": getOrCreateUserId(),
        },
        body: JSON.stringify({ instruction }),
        signal: controller.signal,
      });
    } catch (err) {
      handlers.failed?.({ error: String(err) });
      return;
    }
    if (!res.ok || !res.body) {
      handlers.failed?.({ error: `HTTP ${res.status}` });
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (err) {
        handlers.failed?.({ error: String(err) });
        return;
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      // SSE frames are separated by a blank line, each one starting with
      // "event: <name>\n" and "data: <json>\n".
      let frameEnd: number;
      while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, frameEnd);
        buffer = buffer.slice(frameEnd + 2);
        const lines = frame.split("\n");
        let eventName = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        const fn = (handlers as Record<string, ((d: unknown) => void) | undefined>)[
          resolveHandlerName(eventName)
        ];
        if (!fn) continue;
        try {
          fn(JSON.parse(data));
        } catch {
          // ignore parse errors
        }
      }
    }
  })();

  return () => controller.abort();
}
