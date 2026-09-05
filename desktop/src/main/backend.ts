import { ChildProcess, spawn } from 'child_process';
import { execFile } from 'child_process';
import { app } from 'electron';
import * as path from 'path';
import * as crypto from 'crypto';
import * as net from 'net';
import { log } from './logger';

const BACKEND_PORT = 8756;
const MAX_RESTARTS_PER_HOUR = 8;
const HEALTH_POLL_MS = 2000;   // 周期探活间隔（V1.0.10：界面版本号实时刷新，旧进程残留自动纠正）
const PORT_WAIT_MS = 15000;    // 杀进程后等待端口释放的最长时间

export interface BackendStatus {
  running: boolean;
  version: string | null;
  url: string;
  restartCount: number;
  error: string | null;  // 最近一次启动失败/连接失败原因
}

/** 探测 127.0.0.1:PORT 是否已有服务在监听（不关心是否为本后端） */
function portHasListener(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const done = (v: boolean) => { socket.destroy(); resolve(v); };
    socket.setTimeout(800);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
    socket.connect(port, '127.0.0.1');
  });
}

/** 找出占用指定端口的进程 PID 列表（netstat -ano） */
function findPidByPort(port: number): Promise<number[]> {
  return new Promise((resolve) => {
    execFile('netstat', ['-ano', '-p', 'tcp'], { windowsHide: true }, (_err, stdout) => {
      const pids = new Set<number>();
      const re = new RegExp(`127.0.0.1:${port}\\s+.*?LISTENING\\s+(\\d+)`, 'g');
      let m: RegExpExecArray | null;
      while ((m = re.exec(stdout))) {
        const pid = Number(m[1]);
        if (pid > 0) pids.add(pid);
      }
      resolve([...pids]);
    });
  });
}

/** 强制结束进程树（Windows taskkill /T /F；其它平台直接 kill） */
function killProcessTree(pid: number): void {
  try {
    if (process.platform === 'win32') {
      execFile('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () => { /* 忽略结果 */ });
    } else {
      try { process.kill(pid, 'SIGKILL'); } catch { /* ignore */ }
    }
  } catch { /* ignore */ }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

class BackendManager {
  private proc: ChildProcess | null = null;
  private readonly token = crypto.randomBytes(16).toString('hex');
  private stopping = false;
  private restartTimer: NodeJS.Timeout | null = null;
  private restartCount = 0;
  private restartWindowStart = Date.now();
  private lastError: string | null = null;
  private healthTimer: NodeJS.Timeout | null = null;
  private stoppingPromise: Promise<void> | null = null;
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

  /**
   * V1.0.10：启动前清理 8756 端口上的残留进程（如升级后未被杀干净的旧版后端），
   * 避免新版本后端 bind 失败 / 探测到旧版本。
   */
  private async ensurePortFree(): Promise<boolean> {
    const deadline = Date.now() + PORT_WAIT_MS;
    while (Date.now() < deadline) {
      if (!(await portHasListener(BACKEND_PORT))) return true;
      const pids = await findPidByPort(BACKEND_PORT);
      if (pids.length === 0) return true;
      for (const pid of pids) {
        killProcessTree(pid);
        log('WARN', `[backend] 端口 ${BACKEND_PORT} 被残留进程占用（PID ${pid}），已强制结束（V1.0.10 防旧进程残留）`);
      }
      await sleep(500);
    }
    this.lastError = `端口 ${BACKEND_PORT} 清理超时（15 秒内无法释放）`;
    log('ERROR', `[backend] ${this.lastError}`);
    return false;
  }

  /** 周期探活（V1.0.10）：每 2 秒刷新状态/版本；发现失联或版本与主程序不一致 → 自动重启后端 */
  private startHealthTimer(): void {
    this.stopHealthTimer();
    this.healthTimer = setInterval(() => { void this.healthCheck(); }, HEALTH_POLL_MS);
  }

  private stopHealthTimer(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  private async healthCheck(): Promise<void> {
    if (this.stopping) return;
    try {
      const res = await fetch(this.backendUrl() + '/api/health', {
        headers: { 'X-Backend-Token': this.token },
        signal: AbortSignal.timeout(4000),
      });
      if (res.ok) {
        const data = (await res.json()) as { version?: string };
        const version = data.version || null;
        if (this.status.version !== version) {
          log('INFO', `[backend] 版本刷新: ${this.status.version} → ${version}`);
        }
        this.status = { running: true, version, url: this.backendUrl(), restartCount: this.restartCount, error: null };
        // 后端版本与主程序不一致（如升级后仍跑旧包）→ 强制重启后端加载新版本
        if (version && app.isPackaged && version !== app.getVersion()) {
          log('WARN', `[backend] 后端版本 ${version} 与主程序 ${app.getVersion()} 不一致，重启后端以加载新版本`);
          await this.restartBackend('版本不一致，自动重启');
        }
        return;
      }
      if (res.status === 401) {
        // 端口上有一个「不认识我们 token」的服务 = 残留的旧版后端进程（旧 token）
        log('WARN', '[backend] 探测到旧版残留后端（token 不匹配），清理并重启');
        await this.restartBackend('旧版后端残留，清理重启');
        return;
      }
      // 其它 HTTP 错误：短暂视为异常但由下一轮探活处理
      this.status = { ...this.status, running: false, error: `后端异常响应 HTTP ${res.status}` };
    } catch {
      // 连接失败：后端不在线。若进程已退出，exit 回调会安排重启；这里只刷新状态
      if (this.status.running) {
        this.status = { ...this.status, running: false, error: '后端连接中断（等待自动恢复）' };
      }
      if (!this.proc) {
        log('WARN', '[backend] 探活失败且无运行进程，自动重启');
        await this.scheduleRestart();
      }
    }
  }

  private async restartBackend(reason: string): Promise<void> {
    if (this.stopping) return;
    log('INFO', `[backend] 重启（${reason}）`);
    this.stopHealthTimer();
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const p = this.proc;
    this.proc = null;
    if (p && p.pid) {
      try { p.kill(); } catch { /* ignore */ }
      const pid = p.pid;
      if (pid) killProcessTree(pid);
    }
    await sleep(1200);
    await this.start();
  }

  async start(): Promise<void> {
    this.stopping = false;
    this.lastError = null;
    // 1) 清理端口残留（防止旧版进程占用）
    const ok = await this.ensurePortFree();
    if (!ok) {
      this.status = { ...this.status, running: false, error: this.lastError };
      return;
    }
    // 2) spawn 后端
    const { cmd, args, cwd } = this.backendCommand();
    log('INFO', `[backend] 启动: ${cmd} ${args.join(' ')}`);
    try {
      this.proc = spawn(cmd, args, {
        env: { ...process.env, BACKEND_TOKEN: this.token },
        cwd,
        stdio: 'ignore',
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      this.lastError = `后端启动失败: ${msg}`;
      log('ERROR', `[backend] spawn 失败: ${msg}`);
      this.status = { ...this.status, running: false, error: this.lastError };
      return;
    }
    this.proc.on('error', (err) => {
      this.lastError = `后端进程错误: ${err.message}`;
      log('ERROR', `[backend] 进程错误: ${err.message}`);
      this.status = { ...this.status, running: false, error: this.lastError };
    });
    this.proc.on('exit', (code) => {
      log('WARN', `[backend] 进程退出 code=${code}`);
      this.proc = null;
      if (!this.stopping) {
        this.status = { ...this.status, running: false };
        if (code !== null && code !== 0) {
          this.lastError = `后端进程异常退出（code=${code}）`;
          this.status = { ...this.status, error: this.lastError };
        }
        void this.scheduleRestart();
      }
    });
    // 3) 等待健康 + 开启周期探活
    this.startHealthTimer();
    await this.waitForHealth();
  }

  private scheduleRestart(): void {
    if (this.restartTimer) return; // 已安排重启，避免重复
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
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      void this.start();
    }, 2000);
  }

  private async waitForHealth(): Promise<void> {
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (this.stopping) return;
      try {
        const res = await fetch(`${this.backendUrl()}/api/health`, {
          headers: { 'X-Backend-Token': this.token },
          signal: AbortSignal.timeout(4000),
        });
        if (res.ok) {
          const data = (await res.json()) as { version: string };
          this.status = { running: true, version: data.version, url: this.backendUrl(), restartCount: this.restartCount, error: null };
          log('INFO', `[backend] 就绪 version=${data.version}`);
          return;
        }
        if (res.status === 401) {
          // 残留旧进程占端口（旧 token）→ 清掉后重试（本函数外层由 start 保证端口已清理；
          // 走到这里说明刚被再次占用，交由 healthCheck 周期逻辑处理）
          log('WARN', '[backend] 健康检查遇 401（疑似端口被旧进程抢占）');
        }
      } catch {
        // 未就绪，继续轮询
      }
      await sleep(500);
    }
    const msg = '后端健康检查超时（30 秒未就绪），请查看 data/logs/desktop.log 与后端日志';
    this.lastError = msg;
    log('ERROR', `[backend] ${msg}`);
    this.status = { ...this.status, running: false, error: msg };
  }

  async stop(): Promise<void> {
    if (this.stoppingPromise) return this.stoppingPromise;
    this.stopping = true;
    this.stoppingPromise = (async () => {
      this.stopHealthTimer();
      const p = this.proc;
      this.proc = null;
      if (p && p.pid) {
        try { p.kill(); } catch { /* ignore */ }
        killProcessTree(p.pid);
      }
      // 兜底清理端口残留（升级/退出时把旧版后端一并清掉）
      try {
        const pids = await findPidByPort(BACKEND_PORT);
        for (const pid of pids) killProcessTree(pid);
      } catch { /* ignore */ }
      this.status = { ...this.status, running: false };
    })();
    return this.stoppingPromise;
  }

  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60_000);
    let res: Response;
    try {
      res = await fetch(this.backendUrl() + path, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-Backend-Token': this.token,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (e) {
      clearTimeout(timer);
      const msg = e instanceof Error && e.name === 'AbortError'
        ? '请求超时（后端处理超过 60 秒）'
        : '无法连接后端: ' + (e instanceof Error ? e.message : String(e));
      return { ok: false, status: 0, error: msg };
    }
    clearTimeout(timer);
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
