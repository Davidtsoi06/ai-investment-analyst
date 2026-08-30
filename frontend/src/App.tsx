import { HashRouter, Routes, Route } from 'react-router-dom';
import AppLayout from './layouts/AppLayout';
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

export default function App() {
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
