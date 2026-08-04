const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export async function checkHealth(): Promise<{
  status: string;
  service: string;
}> {
  const res = await fetch(`${BACKEND_URL}/api/v1/health`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function checkReadyz(): Promise<{
  status: string;
  db: number;
}> {
  const res = await fetch(`${BACKEND_URL}/api/v1/readyz`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}
