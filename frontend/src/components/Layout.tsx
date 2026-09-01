import {
  Activity, Beaker, BookOpenCheck, BriefcaseBusiness, CircleDollarSign,
  Gauge, Layers3, Menu, Settings, ShieldCheck, TrendingUp, X,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { demoMode, useDashboard } from "../hooks/useDashboard";
import { formatAge, formatDateTime } from "../utils/format";

const nav = [
  { label: "Today", path: "/", icon: Gauge, primary: true },
  { label: "Portfolio", path: "/portfolio", icon: BriefcaseBusiness, primary: true },
  { label: "Bets", path: "/bets", icon: CircleDollarSign, primary: true },
  { label: "Parlay", path: "/parlay", icon: Layers3, primary: true },
  { label: "Market Movement", path: "/market-movement", icon: TrendingUp },
  { label: "Models", path: "/models", icon: Activity },
  { label: "Research", path: "/research", icon: Beaker },
  { label: "History", path: "/history", icon: BookOpenCheck },
  { label: "Settings", path: "/settings", icon: Settings },
];

export function Layout() {
  const [moreOpen, setMoreOpen] = useState(false);
  const { data } = useDashboard();
  const riskState = data?.risk.portfolio_state ?? "—";
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark">D</span><div><strong>Dino Desk</strong><small>NCAAF portfolio</small></div></div>
        <nav>{nav.map((item) => <NavItem key={item.path} {...item} />)}</nav>
        <div className="sidebar-foot"><ShieldCheck size={16} /><span>Human approval required</span></div>
      </aside>
      <div className="main-frame">
        <header className="global-header">
          <div className="header-status">
            <span className="paper-badge">Paper trading</span>
            {demoMode && <span className="preview-badge">Preview data</span>}
            <span className={`status-dot ${data?.system.system_status === "OPERATIONAL" ? "ok" : "warn"}`} />
            <span>{data?.system.system_status ?? "Connecting"}</span>
          </div>
          <div className="header-meta">
            <span><small>Odds refresh</small>{data?.system.last_odds_refresh ? formatAge(data.system.last_odds_refresh) : "Unavailable"}</span>
            <span><small>Risk state</small><strong className={`risk-${riskState.toLowerCase().replace("_", "-")}`}>{riskState}</strong></span>
          </div>
        </header>
        <main className="page-content"><Outlet /></main>
      </div>
      <nav className="mobile-nav" aria-label="Mobile navigation">
        {nav.filter((item) => item.primary).map((item) => <NavItem key={item.path} {...item} compact />)}
        <button className="mobile-nav-link" onClick={() => setMoreOpen(true)} aria-label="More navigation"><Menu size={20} /><span>More</span></button>
      </nav>
      {moreOpen && <div className="mobile-drawer" role="dialog" aria-label="More navigation"><button className="icon-button close" onClick={() => setMoreOpen(false)}><X /></button>{nav.filter((item) => !item.primary).map((item) => <NavItem key={item.path} {...item} onClick={() => setMoreOpen(false)} />)}<div className="drawer-refresh">Last refresh<br />{data?.system.last_odds_refresh ? formatDateTime(data.system.last_odds_refresh) : "Unavailable"}</div></div>}
    </div>
  );
}

function NavItem({ label, path, icon: Icon, compact, onClick }: (typeof nav)[number] & { compact?: boolean; onClick?: () => void }) {
  return <NavLink to={path} end={path === "/"} onClick={onClick} className={({ isActive }) => `${compact ? "mobile-nav-link" : "nav-link"} ${isActive ? "active" : ""}`}><Icon size={compact ? 20 : 18} /><span>{label}</span></NavLink>;
}
