type Props = {
  disabled: boolean;
  offline: boolean;
  onPlayDay: () => void;
  onStep: () => void;
};

const STEPS = [
  { n: 1, title: "Play the day", text: "Photos, a calendar entry and a recorded chat become small, sourced facts." },
  { n: 2, title: "Ask a question", text: "Get answers no single source holds, each one linked to its evidence." },
  { n: 3, title: "Withdraw consent", text: "One person leaves. Everything only they supported is removed, with a receipt." },
];

/** First thing a new visitor sees on an empty graph: what this is, and one obvious next step. */
export function Welcome({ disabled, offline, onPlayDay, onStep }: Props) {
  return (
    <div className="welcome">
      <div className="welcome-card">
        <p className="eyebrow">Welcome</p>
        <h2>A memory you can question, correct and verifiably erase.</h2>
        <p className="lede">
          MemoryAtlas turns a staged day into a map of facts. Every fact shows where it came from, and
          disappears when the consent behind it is withdrawn.
        </p>
        <ol className="steps">
          {STEPS.map((s) => (
            <li key={s.n}>
              <span className="step-n" aria-hidden="true">{s.n}</span>
              <div>
                <strong>{s.title}</strong>
                <span>{s.text}</span>
              </div>
            </li>
          ))}
        </ol>
        {offline ? (
          <p className="notice error" role="alert">
            The backend is not reachable. Start it with <code>make api</code>, then reload.
          </p>
        ) : (
          <div className="welcome-actions">
            <button type="button" className="btn primary large" disabled={disabled} onClick={onPlayDay}>
              Play the whole day
            </button>
            <button type="button" className="btn large" disabled={disabled} onClick={onStep}>
              Step through one event
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
