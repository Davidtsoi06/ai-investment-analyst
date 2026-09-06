import { createRoot } from 'react-dom/client';
import App from './App';
import './index.css';

// V1.1.2：全局错误捕获——任何渲染异常都会显示红条（含错误信息），
// 避免"界面空白却不知道原因"；错误同时打印到控制台便于排查。
function showFatal(message: string) {
  try {
    let el = document.getElementById('fatal-error');
    if (!el) {
      el = document.createElement('div');
      el.id = 'fatal-error';
      el.style.cssText =
        'position:fixed;left:0;right:0;bottom:0;z-index:99999;background:#FFF1F0;color:#CF1322;' +
        'border-top:1px solid #FFA39E;padding:10px 16px;font:12px/1.6 Consolas,monospace;' +
        'white-space:pre-wrap;max-height:40vh;overflow:auto;';
      document.body.appendChild(el);
    }
    el.textContent = '⚠️ 界面渲染出错：' + message;
  } catch { /* ignore */ }
  console.error('[render-error]', message);
}

window.addEventListener('error', (e) => showFatal(e.message || '未知错误（' + (e.filename || '') + ':' + (e.lineno || '') + '）'));
window.addEventListener('unhandledrejection', (e) => {
  const reason = e.reason instanceof Error ? e.reason.message : String(e.reason);
  showFatal('异步错误：' + reason);
});

try {
  createRoot(document.getElementById('root')!).render(<App />);
} catch (err) {
  showFatal(err instanceof Error ? err.message : String(err));
}
