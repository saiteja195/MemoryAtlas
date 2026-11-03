import { useCallback, useEffect, useState } from "react";
import { api, ApiError, onUnauthorized } from "../api/client";
import type { Me } from "../api/types";

export type SessionStatus = "loading" | "signedOut" | "signedIn";

/** Who is using the app. With `auth: false` (single-user mode) the person counts as signed in. */
export function useSession() {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const m = await api.me();
      setMe(m);
      setError(null);
      setStatus("signedIn");
    } catch (e) {
      setMe(null);
      if (e instanceof ApiError && e.status === 401) {
        setError(null);
      } else {
        setError("MemoryAtlas could not be reached. Check your connection and try again.");
      }
      setStatus("signedOut");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Any request that finds the session gone sends the person back to the sign-in screen.
  useEffect(() => {
    onUnauthorized(() => { setMe(null); setStatus("signedOut"); });
    return () => onUnauthorized(null);
  }, []);

  const signOut = useCallback(async () => {
    try { await api.signout(); } catch { /* the cookie is gone or the server is; either way, leave */ }
    setMe(null);
    setStatus("signedOut");
  }, []);

  return { status, me, error, refresh, signOut };
}
