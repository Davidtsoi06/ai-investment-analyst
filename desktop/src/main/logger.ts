import * as fs from 'fs';
import * as path from 'path';
import { app } from 'electron';

// 主进程文件日志（data/logs/desktop.log），便于用户环境问题定位
export function log(level: 'INFO' | 'WARN' | 'ERROR', msg: string): void {
  try {
    const dir = path.join(app.getPath('userData'), 'data', 'logs');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(
      path.join(dir, 'desktop.log'),
      `${new Date().toISOString()} [${level}] ${msg}\n`,
      'utf-8',
    );
  } catch {
    /* 日志失败不影响运行 */
  }
}
