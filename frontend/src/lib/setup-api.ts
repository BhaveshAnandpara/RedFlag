// Calls to the setup API. The owner password is held in memory by the page and passed in here;
// the endpoint key is only ever sent to the connection test and to the run, never to the chat.

export type ApiResult<T> = { ok: boolean; status: number; data: T };

export class SetupApi {
  constructor(
    private readonly apiUrl: string,
    private readonly token: string,
  ) {}

  async call<T = unknown>(method: string, path: string, body?: unknown): Promise<ApiResult<T>> {
    try {
      const response = await fetch(`${this.apiUrl}${path}`, {
        method,
        headers: {
          "X-Owner-Token": this.token,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const data = (await response.json().catch(() => ({}))) as T;
      return { ok: response.ok, status: response.status, data };
    } catch {
      return { ok: false, status: 0, data: {} as T };
    }
  }
}
