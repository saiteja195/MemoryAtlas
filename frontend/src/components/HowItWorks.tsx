import { Dialog } from "./Dialog";

type Props = { open: boolean; onClose: () => void };

/** A plain-language guide, reachable at any time from the header. */
export function HowItWorks({ open, onClose }: Props) {
  return (
    <Dialog open={open} onClose={onClose} title="How MemoryAtlas works"
            footer={<button type="button" className="btn primary" onClick={onClose}>Got it</button>}>
      <section className="guide">
        <h3>What you are looking at</h3>
        <p>
          The map shows <strong>people, places and things</strong> from a staged day, joined by
          <strong> facts</strong> (the lines between them). Each fact remembers its evidence: a photo,
          a conversation or a calendar entry.
        </p>
      </section>
      <section className="guide">
        <h3>Ways to explore</h3>
        <ul className="guide-list">
          <li><strong>Hover</strong> a node to light up what it is connected to.</li>
          <li><strong>Click</strong> a node or line to see the fact, its source and a Why? trail.</li>
          <li><strong>Drag</strong> to pan, <strong>scroll or pinch</strong> to zoom, <strong>Fit</strong> to start over.</li>
          <li><strong>Episodes</strong> shows the day as moments in order. <strong>Details</strong> shows everything inside them.</li>
          <li><strong>Scrub the timeline</strong> to watch the map grow, or press Watch it build.</li>
        </ul>
      </section>
      <section className="guide">
        <h3>Three things worth trying</h3>
        <ol className="guide-list numbered">
          <li><strong>Ask</strong> which restaurant Alex recommended. The answer comes from linking a chat to a photo of a sign.</li>
          <li><strong>Correct:</strong> upload the later photo, then ask where your wallet is. The old answer stays as history.</li>
          <li><strong>Forget:</strong> in Consent, let Alex withdraw. You get a receipt with seven automated leak checks.</li>
        </ol>
      </section>
      <section className="guide">
        <h3>Privacy</h3>
        <p>
          Photos and audio are turned into text and discarded; the header shows the raw bytes kept.
          The model proposes facts, but plain code decides what is stored, shown and deleted.
        </p>
      </section>
    </Dialog>
  );
}
