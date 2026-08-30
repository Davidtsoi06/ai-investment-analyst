// 构建时把 frontend/dist 复制到 desktop/app-renderer（Electron 加载目录）
import { rmSync, cpSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const here = dirname(fileURLToPath(import.meta.url));
const desktopRoot = join(here, '..');
const projectRoot = join(here, '..', '..');
const src = join(projectRoot, 'frontend', 'dist');
const dst = join(desktopRoot, 'app-renderer');

if (!existsSync(join(src, 'index.html'))) {
  console.error('错误：frontend/dist/index.html 不存在。请先构建前端：cd frontend && npm run build');
  process.exit(1);
}
rmSync(dst, { recursive: true, force: true });
cpSync(src, dst, { recursive: true });
console.log('frontend/dist 已复制到 desktop/app-renderer');
