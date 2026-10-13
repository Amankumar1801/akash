import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { ApiError, explain, HttpApi } from "../api/client";
import { follow } from "../lib/follow";

let srv: Server, base = "";
const seenAuth: (string | undefined)[] = [];

beforeAll(async () => {
  srv = createServer((req, res) => {
    seenAuth.push(req.headers.authorization);
    const url = new URL(req.url ?? "/", "http://x");
    if (req.headers.authorization !== "Bearer akash_k_secret") {
      res.writeHead(401, { "content-type": "application/json" });
      return void res.end(JSON.stringify({ error: { code: "unauthenticated", message: "bad key", request_id: "r1" } }));
    }
    if (url.pathname === "/v1/me") { res.writeHead(200, { "content-type": "application/json" }); return void res.end('{"name":"t","role":"researcher","key_id":"k"}'); }
    if (url.pathname === "/v1/objects/search") { res.writeHead(429, { "content-type": "application/json", "retry-after": "7" }); return void res.end('{"error":{"code":"rate_limited","message":"slow down"}}'); }
    if (url.pathname.endsWith("/events")) {
      const after = Number(url.searchParams.get("after") ?? 0);
      res.writeHead(200, { "content-type": "text/event-stream" });
      res.write(": keepalive\n\n");
      const frame = (n: number, kind: string, d: object) => `id: ${n}\nevent: ${kind}\ndata: ${JSON.stringify({ ...d, ts: 1 })}\n\n`;
      if (after < 1) res.write(frame(1, "job_started", {}));
      if (after < 2) { // split one frame across two network chunks
        const f = frame(2, "phase", { phase: "fetch_data", status: "started" });
        res.write(f.slice(0, 25));
        return void setTimeout(() => { res.write(f.slice(25)); res.end(frame(3, "job_succeeded", { outcome: "assessed" })); }, 30);
      }
      return void res.end(frame(3, "job_succeeded", { outcome: "assessed" }));
    }
    res.writeHead(404); res.end();
  });
  await new Promise<void>((r) => srv.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${(srv.address() as AddressInfo).port}`;
});
afterAll(() => srv.close());

describe("HttpApi against a real server", () => {
  it("sends the key as a bearer token and parses the error envelope", async () => {
    const bad = new HttpApi(base, "wrong");
    await expect(bad.me()).rejects.toMatchObject({ status: 401, code: "unauthenticated", requestId: "r1" });
    const ok = await new HttpApi(base, "akash_k_secret").me();
    expect(ok.role).toBe("researcher");
    expect(seenAuth.at(-1)).toBe("Bearer akash_k_secret");
  });
  it("surfaces Retry-After and turns codes into actionable sentences", async () => {
    const e = await new HttpApi(base, "akash_k_secret").searchObject("x").catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect((e as ApiError).retryAfter).toBe(7);
    expect(explain(e)).toMatch(/7 seconds/);
  });
  it("explains an unreachable server without a stack trace", async () => {
    const e = await new HttpApi("http://127.0.0.1:1", "k").me().catch((x: unknown) => x);
    expect(explain(e)).toMatch(/Could not reach the AKASH API/);
  });
  it("streams events over fetch, tolerating frames split across chunks", async () => {
    const api = new HttpApi(base, "akash_k_secret"), got: number[] = [];
    const res = await follow(api, "abc", (e) => got.push(e.seq), new AbortController().signal, 1);
    expect(got).toEqual([1, 2, 3]);
    expect(res).toBe("done");
  });
});
