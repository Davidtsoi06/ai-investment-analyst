import { ChildProcess, spawn } from 'child_process';
import { app } from 'electron';
import * as path from 'path';
import * as crypto from 'crypto';
import { log } from './logger';

const BACKEND_PORT = 8756;
const MAX_RESTARTS_PER_HOUR = 5;

export interface BackendStatus {
  running: boolean;
  version: string | null;
  url: string;
  restartCount: number;
  error: string | null;  // 最近一次启动失败/连接失败原因（E: 传递给前端展示）
}

class BackendManager {
  private proc: ChildProcess | null = null;
  private readonly token = crypto.randomBytes(16).toString('hex');
  private stopping = false;
  private restartCount = 0;
  private restartWindowStart = Date.now();
  private lastError: string | null = null;
  private status: BackendStatus = { running: false, version: null, url: '', restartCount: 0, error: null };

  private backendUrl(): string {
    return `http://127.0.0.1:${BACKEND_PORT}`;
  }

  private backendCommand(): { cmd: string; args: string[]; cwd: string } {
    if (app.isPackaged) {
      // 生产（onedir 模式）：resources/backend-bin/ai-invest-backend/ai-invest-backend.exe
      const exe = path.join(process.resourcesPath, 'backend-bin', 'ai-invest-backend', 'ai-invest-backend.exe');
      return { cmd: exe, args: [], cwd: path.dirname(exe) };
    }
    // 开发：backend/.venv/Scripts/python.exe run.py
    const projectRoot = path.resolve(__dirname, '..', '..', '..');
    const cmd = path.join(projectRoot, 'backend', '.venv', 'Scripts', 'python.exe');
    return {
      cmd,
      args: [path.join(projectRoot, 'backend', 'run.py')],
      cwd: path.join(projectRoot, 'backend'),
    };
  }

  async start(): Promise<void> {
    if (this.proc) return;
    this.stopping = false;
    const { cmd, args, cwd } = this.backendCommand();
    log('INFO', `[backend] 启动: ${cmd} ${args.join(' ')}`);
    this.lastError = null;
    try {
      this.proc = spawn(cmd, args, {
        env: { ...process.env, BACKEND_TOKEN: this.token },
        cwd,
        stdio: 'ignore',
      });
    } catch (e) {
      // spawn 本身失败（如 exe 不存在/无权限）
      const msg = e instanceof Error ? e.message : String(e);
      this.lastError = `后端启动失败: ${msg}`;
      log('ERROR', `[backend] spawn 失败: ${msg}`);
      this.status = { ...this.status, running: false, error: this.lastError };
      return;
    }
    this.proc.on('error', (err) => {
      // 启动失败（exe 无法执行等）
      this.lastError = `后端进程错误: ${err.message}`;
      log('ERROR', `[backend] 进程错误: ${err.message}`);
      this.status = { ...this.status, running: false, error: this.lastError };
    });
    this.proc.on('exit', (code) => {
      log('WARN', `[backend] 进程退出 code=${code}`);
      this.proc = null;
      this.status = { ...this.status, running: false };
      if (!this.stopping) {
        if (code !== null && code !== 0) {
          this.lastError = `后端进程异常退出（code=${code}）`;
          this.status = { ...this.status, error: this.lastError };
        }
        this.scheduleRestart();
      }
    });
    await this.waitForHealth();
  }

  private scheduleRestart(): void {
    const now = Date.now();
    if (now - this.restartWindowStart > 3600_000) {
      this.restartWindowStart = now;
      this.restartCount = 0;
    }
    if (this.restartCount >= MAX_RESTARTS_PER_HOUR) {
      const msg = '后端重启次数超限，停止自动重启（请查看 data/logs/desktop.log）';
      this.lastError = msg;
      log('ERROR', `[backend] ${msg}`);
      this.status = { ...this.status, running: false, error: msg };
      return;
    }
    this.restartCount += 1;
    log('WARN', `[backend] 2 秒后自动重启（第 ${this.restartCount} 次）`);
    setTimeout(() => { void this.start(); }, 2000);
  }

  private async waitForHealth(): Promise<void> {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (this.stopping) return;
      try {
        const res = await fetch(`${this.backendUrl()}/api/health`, {
          headers: { 'X-Backend-Token': this.token },
        });
        if (res.ok) {
          const data = (await res.json()) as { version: string };
          this.status = { running: true, version: data.version, url: this.backendUrl(), restartCount: this.restartCount, error: null };
          log('INFO', `[backend] 就绪 version=${data.version}`);
          return;
        }
      } catch {
        // 未就绪，继续轮询
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    const msg = '后端健康检查超时（30 秒未就绪），请查看 data/logs/desktop.log 与后端日志';
    this.lastError = msg;
    log('ERROR', `[backend] ${msg}`);
    this.status = { ...this.status, running: false, error: msg };
  }

  async stop(): Promise<void> {
    this.stopping = true;
    if (this.proc) {
      this.proc.kill();
      this.proc = null;
    }
    this.status = { ...this.status, running: false };
  }

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const res = await fetch(`${this.backendUrl()}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Backend-Token': this.token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await res.text();
    let json: unknown = null;
    try { json = text ? JSON.parse(text) : null; } catch { json = text; }
    if (!res.ok) {
      return { ok: false, status: res.status, error: typeof json === 'string' ? json : JSON.stringify(json) };
    }
    return json;
  }

  getStatus(): BackendStatus {
    return this.status;
  }
}

export const backendManager = new BackendManager();
