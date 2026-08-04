import { checkHealth, checkReadyz } from "@/lib/api";

export default async function Home() {
  const results = await Promise.allSettled([checkHealth(), checkReadyz()]);
  const backend = results[0];
  const db = results[1];

  const backendLabel = backend.status === "fulfilled" ? backend.value.status : "error";
  const dbLabel = db.status === "fulfilled" ? db.value.status : "error";
  const dbValue = db.status === "fulfilled" ? db.value.db : null;

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6">
      <h1 className="text-5xl font-bold text-blue-400">ThinkCanvas</h1>
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-6 text-center">
        <p className="text-lg">
          Backend:&nbsp;
          <span className="font-mono text-green-400">{backendLabel}</span>
        </p>
        <p className="mt-2 text-lg">
          Postgres:&nbsp;
          <span className="font-mono text-green-400">{dbLabel}</span>
          {dbValue !== null && (
            <span className="ml-2 text-sm text-gray-400">
              (SELECT 1 → {dbValue})
            </span>
          )}
        </p>
      </div>
    </main>
  );
}
