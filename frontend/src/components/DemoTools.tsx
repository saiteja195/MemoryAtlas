import type { DemoStatus } from "../api/types";

type Props = {
  status: DemoStatus | null;
  busy: string | null;
  offline: boolean;
  onNext: () => void;
  onAll: () => void;
  onLive: (id: string) => void;
  onReset: () => void;
  canReset: boolean;
};

export function DemoTools(p: Props) {
  const next = p.status?.events.find((e) => e.id === p.status?.next);
  const live = p.status?.events.filter((e) => e.live_upload && !e.played) ?? [];
  const disabled = p.busy !== null || p.offline;

  return (
    <details className="demo-tools">
      <summary>Demo tools</summary>
      <div className="demo-tools-body">
        <p className="muted small">These controls add scripted sample memories to this profile. The sample wallet sighting uses a predefined description; it does not upload a photo. To upload your own, use Add memory.</p>
        <div className="demo-tools-actions" role="group" aria-label="Scripted sample day">
          {p.busy && <progress aria-label={p.busy} />}
          <button type="button" className="btn" disabled={disabled || !next} onClick={p.onNext}>
            {next ? `Play next: ${next.at} ${kindWord(next.kind, next.label)}` : "Day played"}
          </button>
          <button type="button" className="btn" disabled={disabled || !next} onClick={p.onAll}>Play the day</button>
          {live.map((e) => (
            <button type="button" className="btn" key={e.id} disabled={disabled} onClick={() => p.onLive(e.id)}>
              Add sample wallet sighting · {e.at}
            </button>
          ))}
          {p.canReset && <button type="button" className="btn ghost" disabled={disabled} onClick={p.onReset}>Reset</button>}
        </div>
      </div>
    </details>
  );
}

export function kindWord(kind: string, label: string): string {
  if (kind === "calendar") return label;
  if (kind === "audio") return "conversation";
  return kind === "frame" ? "photo" : label;
}
