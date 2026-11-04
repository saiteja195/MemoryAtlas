import { GLYPHS, glyphFor } from "../utils/icons";

/** The line icon for a kind of thing (person, place, thing...), drawn in the surrounding text colour. */
export function TypeIcon({ type }: { type: string }) {
  return (
    <svg className="type-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true" dangerouslySetInnerHTML={{ __html: GLYPHS[glyphFor(type)] }} />
  );
}
