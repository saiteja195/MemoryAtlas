export type ThemePref = "system" | "light" | "dark";

/** The saved appearance. Light is the default; "system" (follow the device) is only used when chosen. */
export function parseTheme(raw: string | null): ThemePref {
  return raw === "dark" || raw === "system" ? raw : "light";
}
