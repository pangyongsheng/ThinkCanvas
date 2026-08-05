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

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
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
// SSE: subscribeGenerate
// ---------------------------------------------------------------------------

export type StreamEvent =
  | "llm_call"
  | "validating"
  | "code"
  | "rendering"
  | "retry"
  | "done"
  | "failed";

export interface StreamHandlers {
  llm_call?: (data: { step: string; attempt: number }) => void;
  validating?: (data: { attempt: number }) => void;
  code?: (data: { code: string; scene_name: string; attempts: number }) => void;
  rendering?: (data: { scene_name?: string }) => void;
  retry?: (data: { reason: string; attempt: number; error?: string }) => void;
  done?: (data: {
    code: string;
    scene_name: string;
    video_url: string;
    attempts: number;
    duration_sec: number;
  }) => void;
  failed?: (data: { error: string; history?: unknown[] }) => void;
}

export function subscribeGenerate(
  prompt: string,
  handlers: StreamHandlers,
): () => void {
  const url = new URL("/api/v1/generate/stream", BACKEND_URL);
  url.searchParams.set("prompt", prompt);
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
