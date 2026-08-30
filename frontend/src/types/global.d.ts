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
  }
}
