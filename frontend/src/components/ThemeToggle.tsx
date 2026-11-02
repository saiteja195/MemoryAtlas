import type { ThemePref } from "../hooks/useTheme";

const OPTIONS: { id: ThemePref; label: string; icon: string }[] = [
  { id: "light", label: "Light", icon: "☀" },
  { id: "system", label: "Auto", icon: "◐" },
  { id: "dark", label: "Dark", icon: "☾" },
];

/** Three-way appearance switch: light, follow the system, dark. */
export function ThemeToggle({ pref, onChange }: { pref: ThemePref; onChange: (p: ThemePref) => void }) {
  return (
    <div className="seg theme-toggle" role="group" aria-label="Appearance">
      {OPTIONS.map((o) => (
        <button key={o.id} type="button" aria-pressed={pref === o.id} onClick={() => onChange(o.id)}
                title={o.id === "system" ? "Match this device" : `${o.label} appearance`}>
          <span aria-hidden="true">{o.icon}</span><span className="sr-only">{o.label}</span>
        </button>
      ))}
    </div>
  );
}
