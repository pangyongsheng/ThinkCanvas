// Anonymous-user identity helper.
//
// The backend identifies users by a client-side ULID it gets back via
// the X-User-Id header. We generate one on first visit, persist it in
// localStorage, and stitch it onto every fetch. No login, no auth, no
// PII — the value is essentially "browser UUID" and has zero privacy
// weight.
//
// Stays valid forever (until the user clears site data). Browsers that
// block localStorage fall back to in-memory only: a session refresh
// would mint a new ID and history would split, but the request still
// works for the current tab.

const STORAGE_KEY = "thinkcanvas.user_id";

// Crockford base32 alphabet used by ULIDs. Matches the server-side
// _ULID_RE.
const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
const ULID_LEN = 26;

function randomChar(): string {
  const buf = new Uint8Array(1);
  // crypto.getRandomValues is available in every modern browser,
  // including SSR-incompatible ones (we guard window access below).
  crypto.getRandomValues(buf);
  return CROCKFORD[buf[0] % CROCKFORD.length];
}

function randomUlid(): string {
  let out = "";
  for (let i = 0; i < ULID_LEN; i++) {
    out += randomChar();
  }
  return out;
}

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(value: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // ignore — caller will use in-memory copy for the rest of the session
  }
}

let memo: string | null = null;

export function getOrCreateUserId(): string {
  if (memo) return memo;
  if (typeof window === "undefined") {
    // SSR: shouldn't reach this path because api.ts is client-only, but
    // fall back to a stable placeholder so calls don't crash.
    return "01SSR00000000000000000000";
  }
  const stored = readStored();
  if (stored && stored.length === ULID_LEN) {
    memo = stored;
    return stored;
  }
  const fresh = randomUlid();
  writeStored(fresh);
  memo = fresh;
  return fresh;
}

export function resetUserIdForTests(): void {
  memo = null;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
