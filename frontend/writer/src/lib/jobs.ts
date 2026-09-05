import { API } from '@/lib/api'

export interface JobState {
  status: "running" | "done" | "error";
  tokens: string;
  result: string | null;
  error: string | null;
  meta: Record<string, unknown>;
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** POST to fullUrl, expect {job_id} back. fullUrl = `${API}/books/...` */
export async function startJob(
  fullUrl: string,
  body: Record<string, unknown>,
): Promise<string> {
  const res = await fetch(fullUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text || `HTTP ${res.status}`);
  }
  const data = await res.json();
  if (!data.job_id) throw new Error("No job_id in response");
  return data.job_id as string;
}

export async function pollJob(jobId: string): Promise<JobState> {
  const res = await fetch(`${API}/jobs/${jobId}`);
  if (!res.ok) throw new Error(`Poll failed: HTTP ${res.status}`);
  return res.json();
}

/**
 * Run a job and stream tokens via a callback.
 * Resolves with the final JobState when status is done or error.
 */
export async function runJob(
  fullUrl: string,
  body: Record<string, unknown>,
  onToken?: (token: string, accumulated: string) => void,
): Promise<JobState> {
  const jobId = await startJob(fullUrl, body);
  let accumulated = "";
  while (true) {
    await sleep(1000);
    const state = await pollJob(jobId);
    if (state.tokens.length > accumulated.length) {
      const newTokens = state.tokens.slice(accumulated.length);
      accumulated = state.tokens;
      onToken?.(newTokens, accumulated);
    }
    if (state.status !== "running") return state;
  }
}
