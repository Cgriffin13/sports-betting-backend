import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { LoadingPage } from "./components/Primitives";
import { TodayPage } from "./pages/TodayPage";

const PortfolioPage = lazy(() => import("./pages/PortfolioPage").then((module) => ({ default: module.PortfolioPage })));
const WatchlistPage = lazy(() => import("./pages/WatchlistPage").then((module) => ({ default: module.WatchlistPage })));
const BetsPage = lazy(() => import("./pages/BetsPage").then((module) => ({ default: module.BetsPage })));
const ParlayPage = lazy(() => import("./pages/ParlayPage").then((module) => ({ default: module.ParlayPage })));
const HistoryPage = lazy(() => import("./pages/HistoryPage").then((module) => ({ default: module.HistoryPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));

export default function App() {
  return <Suspense fallback={<LoadingPage />}><Routes><Route element={<Layout />}><Route index element={<TodayPage />} /><Route path="watchlist" element={<WatchlistPage />} /><Route path="portfolio" element={<PortfolioPage />} /><Route path="bets" element={<BetsPage />} /><Route path="parlay" element={<ParlayPage />} /><Route path="history" element={<HistoryPage />} /><Route path="settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes></Suspense>;
}
