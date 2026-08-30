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
      status: () => Promise<{ running: boolean; version: string | null; url: string; restartCount: number }>;
    };
  }
}
