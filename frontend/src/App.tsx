import { useEffect, useState } from "react";

type Health = { status: string; llm_mode: string };

export function App() {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    fetch("/api/health").then((r) => r.json()).then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", padding: 24 }}>
      <h1>MemoryAtlas</h1>
      <p>
        Backend: {health ? health.status : "unreachable"}
        {health && ` · model mode: ${health.llm_mode}`}
      </p>
    </main>
  );
}
