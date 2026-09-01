import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description: string; actions?: ReactNode }) {
  return <div className="page-header"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1><p>{description}</p></div>{actions && <div className="page-actions">{actions}</div>}</div>;
}

export function Panel({ title, eyebrow, action, children, className = "" }: { title?: string; eyebrow?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{(title || action) && <header className="panel-header"><div>{eyebrow && <span className="eyebrow">{eyebrow}</span>}{title && <h2>{title}</h2>}</div>{action}</header>}{children}</section>;
}

export function Metric({ label, value, detail, icon: Icon, tone = "default" }: { label: string; value: string; detail?: string; icon?: LucideIcon; tone?: "default" | "positive" | "warning" | "negative" }) {
  return <div className={`metric-card tone-${tone}`}><div className="metric-label">{Icon && <Icon size={15} />}{label}</div><strong>{value}</strong>{detail && <small>{detail}</small>}</div>;
}

export function EmptyState({ icon: Icon, title, body }: { icon: LucideIcon; title: string; body: string }) {
  return <div className="empty-state"><Icon /><h3>{title}</h3><p>{body}</p></div>;
}

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "positive" | "warning" | "negative" | "info" }) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}

export function LoadingPage() {
  return <div className="loading-page" aria-label="Loading dashboard"><div className="skeleton wide" /><div className="metric-grid">{Array.from({ length: 5 }, (_, i) => <div className="skeleton card" key={i} />)}</div><div className="skeleton table" /></div>;
}

export function ErrorPage({ message, retry }: { message: string; retry: () => void }) {
  return <div className="error-page"><h2>Dashboard data unavailable</h2><p>{message}</p><button className="button primary" onClick={retry}>Try again</button></div>;
}
