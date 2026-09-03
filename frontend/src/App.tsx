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

/** 引导完成标记：写在本机 localStorage，任何版本更新/重启都不会再要求填写（仅首次使用弹出） */
const ONBOARDED_LS_KEY = 'ai_invest_onboarded_v1';

export default function App() {
  const [onboarded, setOnboarded] = useState<boolean | null>(null);

  useEffect(() => {
    let alive = true;
    // ① 本地已标记完成 → 直接进入主界面（版本更新/再次打开均不弹）
    try {
      if (localStorage.getItem(ONBOARDED_LS_KEY) === '1') {
        setOnboarded(true);
        return;
      }
    } catch {
      /* localStorage 不可用时继续走后端判定 */
    }

    // ② 询问后端画像：只有「明确返回 onboarded=0」才弹首次引导；
    //    后端未就绪/请求失败时重试，超时后直接进入主界面（绝不误弹）
    let tries = 0;
    const check = async () => {
      try {
        const res = await getProfile();
        if (!alive) return;
        const data = res.data as { onboarded?: number } | undefined;
        if (res.ok && data && typeof data.onboarded === 'number') {
          if (data.onboarded === 1) {
            try { localStorage.setItem(ONBOARDED_LS_KEY, '1'); } catch { /* ignore */ }
            setOnboarded(true);
          } else {
            setOnboarded(false); // 首次使用：弹引导问卷
          }
          return;
        }
        throw new Error('no profile data');
      } catch {
        if (!alive) return;
        tries += 1;
        if (tries <= 10) {
          window.setTimeout(check, 1500); // 后端仍在启动：1.5s 后重试
        } else {
          setOnboarded(true); // 长时间不可用：先进入主界面（不弹引导）
        }
      }
    };
    void check();
    return () => {
      alive = false;
    };
  }, []);

  if (onboarded === null) {
    return (
      <div className="min-h-screen bg-primary-50 flex items-center justify-center">
        <Loading text="正在连接本地服务..." />
      </div>
    );
  }

  if (!onboarded) {
    return (
      <Onboarding
        onDone={() => {
          try { localStorage.setItem(ONBOARDED_LS_KEY, '1'); } catch { /* ignore */ }
          setOnboarded(true);
        }}
      />
    );
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