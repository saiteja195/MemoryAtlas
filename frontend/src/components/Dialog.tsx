import { useEffect, useId, useRef, type ReactNode } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Modal blocks the page (receipts, consent). Non-modal leaves the page usable (the drawer). */
  modal?: boolean;
  className?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** A CSS selector inside the dialog to focus on open (the safe or primary control). */
  initialFocus?: string;
};

/**
 * A thin wrapper over the native <dialog>. The browser supplies the top layer, the inert page,
 * focus containment, Esc and focus return, so none of that is re-implemented here.
 */
export function Dialog({ open, onClose, title, modal = true, className, children, footer, initialFocus }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      if (modal) d.showModal(); else d.show();
      if (initialFocus) d.querySelector<HTMLElement>(initialFocus)?.focus();
    } else if (!open && d.open) {
      d.close();
    }
  }, [open, modal, initialFocus]);

  // Light dismiss. Native where `closedby` exists; elsewhere test the pointer position (not
  // event.target, which is also the dialog for its own padding) and require press and release
  // both outside, so a text-selection drag that ends on the backdrop does not close it.
  useEffect(() => {
    const d = ref.current;
    if (!d || !modal || "closedBy" in HTMLDialogElement.prototype) return;
    const outside = (e: PointerEvent) => {
      const r = d.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    const down = (e: PointerEvent) => { pressedOutside = outside(e); };
    const up = (e: PointerEvent) => { if (pressedOutside && outside(e)) d.close(); };
    d.addEventListener("pointerdown", down);
    d.addEventListener("pointerup", up);
    return () => { d.removeEventListener("pointerdown", down); d.removeEventListener("pointerup", up); };
  }, [modal]);

  const extra = modal ? ({ closedby: "any" } as Record<string, string>) : {};
  return (
    <dialog ref={ref} className={className} aria-labelledby={titleId} onClose={onClose} {...extra}>
      <div className="dlg-head">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="btn small" onClick={() => ref.current?.close()}>Close</button>
      </div>
      {/* Focusable so keyboard users can scroll long content (evidence trees, receipts). */}
      <div className="dlg-body" tabIndex={0} role="region" aria-labelledby={titleId}>{children}</div>
      {footer && <div className="dlg-foot">{footer}</div>}
    </dialog>
  );
}
