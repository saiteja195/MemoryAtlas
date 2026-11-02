import type { ClaimStatus, Support } from "../api/types";
import { clock, evidenceLabel, sourceLabel } from "../utils/graph";

export function EvidenceChip({ evidence }: { evidence: string }) {
  const cls = evidence === "inference" ? "warn" : evidence === "user_confirmation" ? "ok" : "";
  return <span className={`chip ${cls}`}>{evidenceLabel(evidence)}</span>;
}

export function StatusChip({ status }: { status: ClaimStatus | string }) {
  if (status === "superseded") return <span className="chip">⏱ Replaced by newer evidence</span>;
  if (status === "disputed") return <span className="chip warn">⚠ Disputed</span>;
  return <span className="chip ok">Current</span>;
}

export function SourceChips({ supports }: { supports: Support[] }) {
  return (
    <span className="sources">
      {supports.map((s, i) => (
        <span className="chip" key={i} title={s.kind === "derivation" ? "Worked out from other facts" : undefined}>
          {sourceLabel(s.kind)}{s.at ? ` · ${clock(s.at)}` : ""}
        </span>
      ))}
    </span>
  );
}

export const personName = (id: string) => (id === "me" ? "You" : id.charAt(0).toUpperCase() + id.slice(1));

const SESSIONS: Record<string, string> = {
  "day-1": "Your day: photos and calendar",
  "sync-alex": "The recorded conversation",
};
export const sessionLabel = (scopeRef: string) => SESSIONS[scopeRef] ?? scopeRef.replace(/-/g, " ");
