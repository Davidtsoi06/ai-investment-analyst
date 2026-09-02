export {};

declare global {
  interface Window {
    appInfo?: {
      versions: {
        app: string;
        electron: string;
        chrome: string;
        node: string;
      };
    };
    backend?: {
      request: (method: string, path: string, body?: unknown) => Promise<unknown>;
      status: () => Promise<{ running: boolean; version: string | null; url: string; restartCount: number; error: string | null }>;
    };
    updater?: {
      getVersion: () => Promise<{ version: string; devMode: boolean }>;
      check: () => Promise<{ updateAvailable: boolean; currentVersion?: string; latestVersion?: string; message?: string; error?: string }>;
      download: () => Promise<{ success: boolean; error?: string }>;
      install: () => Promise<{ success: boolean }>;
      onStatus: (cb: (data: Record<string, unknown>) => void) => () => void;
    };
  }
}
