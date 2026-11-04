import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Grant, Receipt } from "../api/types";
import { personName, sessionLabel } from "./Badges";

const DEMO_PIN = "4242";

type Props = {
  grantId: string;
  /** Withdraw consent. Resolves with the receipt. */
  onRevoke: (grantId: string, token: string) => Promise<Receipt>;
  onDone?: (r: Receipt) => void;
};

/**
 * A stand-in for the other person's phone. In a real deployment the revocation token would live
 * only on their device; here the demo server hands it over so the demo can play both sides. The
 * PIN is theatre: it only shows where a real unlock step would be.
 */
export function ConsentDevice({ grantId, onRevoke, onDone }: Props) {
  const [grant, setGrant] = useState<Grant | null>(null);
  const [step, setStep] = useState<"ask" | "pin" | "working" | "done">("ask");
  const [pin, setPin] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);

  useEffect(() => {
    api.demoGrants().then((all) => setGrant(all.find((g) => g.grant_id === grantId) ?? null))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [grantId]);

  const confirm = async (given?: string) => {
    const token = grant?.demo_token ?? given;
    if (!grant || !token) return;
    setStep("working");
    setError(null);
    try {
      const r = await onRevoke(grant.grant_id, token);
      setReceipt(r);
      setStep("done");
      onDone?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep("pin");
    }
  };

  if (!grant) {
    return <div className="phone">{error ? <p className="notice error" role="alert">{error}</p> : <progress aria-label="Loading" />}</div>;
  }
  const who = personName(grant.grantor);
  // A consent given with an upload has no demo code: the person keeps the code shown when it was saved.
  const needsCode = !grant.demo_token;

  return (
    <div className="phone" aria-label={`${who}'s phone (simulated)`}>
      <p className="small muted">{who}'s phone · simulated</p>
      {grant.revoked_at && step !== "done" ? (
        <>
          <h2>Consent already withdrawn</h2>
          <p className="small">{who} withdrew permission for “{sessionLabel(grant.scope_ref)}”. Nothing more to do.</p>
        </>
      ) : step === "done" && receipt ? (
        <>
          <h2>Done. It&apos;s been forgotten.</h2>
          <p className="small">Everything that depended only on {who === "You" ? "your" : `${who}'s`} permission for “{sessionLabel(grant.scope_ref)}” has been removed.</p>
          <p className="chip ok">{receipt.summary.probes_passed} of {receipt.summary.probes_total} checks passed</p>
        </>
      ) : (
        <>
          <h2>MemoryAtlas is using “{sessionLabel(grant.scope_ref)}”</h2>
          <p className="small">
            You allowed this on {new Date(grant.granted_at).toLocaleDateString()}. If you withdraw, MemoryAtlas will remove every
            memory that depended only on your permission, and prove it.
          </p>
          {step === "ask" && (
            <button type="button" className="btn danger" onClick={() => setStep("pin")}>Withdraw my consent…</button>
          )}
          {(step === "pin" || step === "working") && (
            <form onSubmit={(e) => {
              e.preventDefault();
              if (needsCode) void confirm(code.trim());
              else if (pin === DEMO_PIN) void confirm();
              else setError("That PIN is not right.");
            }}>
              {needsCode
                ? <label htmlFor="code" className="small">Enter the withdrawal code that was shown when this was saved</label>
                : <label htmlFor="pin" className="small">Unlock to confirm <span className="muted">(demo PIN: {DEMO_PIN})</span></label>}
              <div className="pin">
                {needsCode
                  ? <input id="code" type="text" autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)}
                           data-autofocus disabled={step === "working"} />
                  : <input id="pin" type="text" inputMode="numeric" autoComplete="off" maxLength={4} value={pin}
                           onChange={(e) => setPin(e.target.value)} data-autofocus disabled={step === "working"} />}
                <button type="submit" className="btn danger" disabled={step === "working" || (needsCode ? code.trim().length < 6 : pin.length < 4)}>
                  {step === "working" ? "Forgetting…" : "Withdraw"}
                </button>
              </div>
            </form>
          )}
          {step === "working" && <progress aria-label="Forgetting and checking" />}
          {error && <p className="notice error" role="alert">{error}</p>}
        </>
      )}
    </div>
  );
}
