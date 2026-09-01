export const currency = (value: number, digits = 2) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
export const percent = (value: number | null | undefined, digits = 1) => value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
export const signedPercent = (value: number | null | undefined, digits = 1) => value == null ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`;
export const american = (value: number | null | undefined) => value == null ? "—" : value > 0 ? `+${value}` : `${value}`;
export const line = (value: number | null | undefined) => value == null ? "ML" : value > 0 ? `+${value}` : `${value}`;
export const titleCase = (value: string | null | undefined) => value ? value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase()) : "—";
export const formatDateTime = (value: string) => new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(value));
export const formatAge = (value: string) => {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
};
