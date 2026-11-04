import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Todo, TodoState } from "../api/types";

/**
 * The to-do list. A tick or a dismissal shows at once and is undone, with a message, if the server refuses it.
 * It is fetched again when `dataKey` changes (the memories changed), so a forgotten memory's to-dos disappear.
 */
export function useTodos(dataKey: number) {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.todos("all")
      .then((t) => { if (live) { setTodos(t); setError(null); } })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [dataKey]);

  const setState = useCallback(async (claimId: string, state: TodoState) => {
    let before: Todo[] = [];
    setTodos((t) => { before = t; return t.map((x) => (x.claim_id === claimId ? { ...x, state } : x)); });
    try {
      const updated = await api.setTodo(claimId, state);
      setTodos((t) => t.map((x) => (x.claim_id === claimId ? updated : x)));
      setError(null);
    } catch (e) {
      setTodos(before);
      setError(e instanceof Error ? e.message : "That change could not be saved.");
    }
  }, []);

  return { todos, loading, error, setState };
}
