import { useEffect, useState } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import AppLayout from './layouts/AppLayout';
import Loading from './components/ui/Loading';
import Onboarding from './pages/Onboarding';
import Dashboard from './pages/Dashboard';
import News from './pages/News';
import Portfolio from './pages/Portfolio';
import Recommendation from './pages/Recommendation';
import Tracking from './pages/Tracking';
import Watchlist from './pages/Watchlist';
import Reports from './pages/Reports';
import Risk from './pages/Risk';
import Review from './pages/Review';
import Chat from './pages/Chat';
import Settings from './pages/Settings';
import { getProfile } from './services/api';

export default function App() {
  const [onboarded, setOnboarded] = useState<boolean | null>(null);

  useEffect(() => {
    getProfile().then((res) => {
      const data = res.data as { onboarded?: number } | undefined;
      setOnboarded(!!data && data.onboarded === 1);
    }).catch(() => setOnboarded(true)); // 后端不可用时直接进入主界面
  }, []);

  if (onboarded === null) {
    return (
      <div className="min-h-screen bg-primary-50 flex items-center justify-center">
        <Loading text="正在连接本地服务..." />
      </div>
    );
  }

  if (!onboarded) {
    return <Onboarding onDone={() => setOnboarded(true)} />;
  }

  return (
    <HashRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/news" element={<News />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/recommendation" element={<Recommendation />} />
          <Route path="/tracking" element={<Tracking />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/review" element={<Review />} />
          <Route path="/chat" element={<Chat />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}