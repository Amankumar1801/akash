import type { Interpretation } from "../lib/nlquery";
import type {
  AskAnswer, DiscoveryPage, FeedQuery, SkyOut, Experiment, ExperimentConfig, LabelRow, ReportFile, ReviewLabel,
  EvidenceRow, InvestigationDetail, InvestigationRequest, Job, JobEvent, LightCurveData, Me,
  ImageRequest, ImageResult, ModelOut, ModelDetail, ObjectOut, ObservationOut, ProvGraph, SpectrumRequest, SpectrumResult, VariabilityResult,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string,
    public requestId?: string, public retryAfter?: number) {
    super(message);
  }
}

/** Everything the UI needs. HttpApi talks to the service; DemoApi (demo.ts) fakes it locally. */
export interface AkashApi {
  readonly kind: "live" | "demo";
  me(): Promise<Me>;
  searchObject(query: string): Promise<ObjectOut>;
  getObject(id: string): Promise<ObjectOut>;
  observations(objectId: string): Promise<ObservationOut[]>;
  observationData(obsId: string, maxPoints: number): Promise<LightCurveData>;
  createInvestigation(req: InvestigationRequest): Promise<Job>;
  listInvestigations(): Promise<Job[]>;
  getInvestigation(id: string): Promise<InvestigationDetail>;
  cancelInvestigation(id: string): Promise<Job>;
  evidence(id: string): Promise<EvidenceRow[]>;
  provenance(id: string): Promise<ProvGraph>;
  models(): Promise<ModelOut[]>;
  modelDetail(name: string, version: string): Promise<ModelDetail>;
  analyzeSpectrum(req: SpectrumRequest): Promise<SpectrumResult>;
  analyzeImage(req: ImageRequest): Promise<ImageResult>;
  variability(obsId: string): Promise<VariabilityResult>;
  ask(id: string, question: string): Promise<AskAnswer>;
  createExperiment(c: ExperimentConfig): Promise<Experiment>;
  getExperiment(id: string): Promise<Experiment>;
  cancelExperiment(id: string): Promise<Experiment>;
  addLabel(id: string, label: ReviewLabel, note?: string): Promise<LabelRow>;
  listLabels(id: string): Promise<LabelRow[]>;
  discoveries(q: FeedQuery): Promise<DiscoveryPage>;
  interpretQuery(nl: string): Promise<Interpretation>;
  sky(): Promise<SkyOut>;
  report(id: string, format: "markdown" | "html"): Promise<ReportFile>;
  /** Ordered events after `after`; ends when the job reaches a terminal state. */
  events(id: string, after: number, signal: AbortSignal): AsyncGenerator<JobEvent>;
}

export class HttpApi implements AkashApi {
  readonly kind = "live" as const;
  constructor(private base: string, private key: string) {}

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return { Accept: "application/json", ...(this.key ? { Authorization: `Bearer ${this.key}` } : {}),
      ...extra };
  }

  private async req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    let res: Response;
    try {
      res = await fetch(this.base + path, {
        method, signal, headers: this.headers(body ? { "Content-Type": "application/json" } : {}),
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") throw e;
      throw new ApiError(0, "unreachable",
        "Could not reach the AKASH API. Check the address in Settings, or switch to demo data.");
    }
    if (!res.ok) throw await toApiError(res);
    return (await res.json()) as T;
  }

  me = () => this.req<Me>("GET", "/v1/me");
  searchObject = (query: string) => this.req<ObjectOut>("POST", "/v1/objects/search", { query });
  getObject = (id: string) => this.req<ObjectOut>("GET", `/v1/objects/${id}`);
  observations = (id: string) => this.req<ObservationOut[]>("GET", `/v1/objects/${id}/observations`);
  observationData = (id: string, maxPoints: number) =>
    this.req<LightCurveData>("GET", `/v1/observations/${id}/data?max_points=${maxPoints}`);
  createInvestigation = (r: InvestigationRequest) => this.req<Job>("POST", "/v1/investigations", r);
  listInvestigations = () => this.req<Job[]>("GET", "/v1/investigations?limit=50");
  getInvestigation = (id: string) => this.req<InvestigationDetail>("GET", `/v1/investigations/${id}`);
  cancelInvestigation = (id: string) => this.req<Job>("DELETE", `/v1/investigations/${id}`);
  evidence = (id: string) => this.req<EvidenceRow[]>("GET", `/v1/investigations/${id}/evidence`);
  provenance = (id: string) => this.req<ProvGraph>("GET", `/v1/investigations/${id}/provenance`);
  interpretQuery = (nl: string) =>
    this.req<Interpretation>("GET", `/v1/discoveries/interpret?nl=${encodeURIComponent(nl)}`);
  models = () => this.req<ModelOut[]>("GET", "/v1/models");
  modelDetail = (name: string, version: string) =>
    this.req<ModelDetail>("GET", `/v1/models/${encodeURIComponent(name)}/${encodeURIComponent(version)}`);
  analyzeImage = (req: ImageRequest) => this.req<ImageResult>("POST", "/v1/images/analyze", req);
  analyzeSpectrum = (req: SpectrumRequest) => this.req<SpectrumResult>("POST", "/v1/spectra/analyze", req);
  variability = (obsId: string) => this.req<VariabilityResult>("GET", `/v1/observations/${obsId}/variability`);
  createExperiment = (c: ExperimentConfig) => this.req<Experiment>("POST", "/v1/experiments", c);
  getExperiment = (id: string) => this.req<Experiment>("GET", `/v1/experiments/${id}`);
  cancelExperiment = (id: string) => this.req<Experiment>("DELETE", `/v1/experiments/${id}`);
  addLabel = (id: string, label: ReviewLabel, note?: string) =>
    this.req<LabelRow>("POST", `/v1/investigations/${id}/labels`, note ? { label, note } : { label });
  listLabels = (id: string) => this.req<LabelRow[]>("GET", `/v1/investigations/${id}/labels`);
  discoveries = (q: FeedQuery) => {
    const p = new URLSearchParams();
    for (const c of q.category ?? []) p.append("category", c);
    if (q.exclude_known) p.set("exclude_known", "true");
    if (q.min_anomaly_percentile !== undefined) p.set("min_anomaly_percentile", String(q.min_anomaly_percentile));
    if (q.min_snr !== undefined) p.set("min_snr", String(q.min_snr));
    if (q.reviewed && q.reviewed !== "any") p.set("reviewed", q.reviewed);
    if (q.q) p.set("q", q.q);
    p.set("sort", q.sort ?? "triage"); p.set("limit", String(q.limit ?? 25)); p.set("offset", String(q.offset ?? 0));
    return this.req<DiscoveryPage>("GET", `/v1/discoveries?${p.toString()}`);
  };
  sky = () => this.req<SkyOut>("GET", "/v1/sky");
  report = async (id: string, format: "markdown" | "html"): Promise<ReportFile> => {
    let res: Response;
    try {
      res = await fetch(this.base + "/v1/reports", { method: "POST",
        headers: this.headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({ investigation_id: id, format }) });
    } catch {
      throw new ApiError(0, "unreachable", "Could not reach the AKASH API. Check the address in Settings, or switch to demo data.");
    }
    if (!res.ok) throw await toApiError(res);
    return { text: await res.text(), filename: `akash-report-${id.slice(0, 8)}.${format === "html" ? "html" : "md"}`,
      mime: format === "html" ? "text/html" : "text/markdown" };
  };
  ask = (id: string, question: string) =>
    this.req<AskAnswer>("POST", `/v1/investigations/${id}/ask`, { question });

  /** SSE over fetch (EventSource cannot send an Authorization header). */
  async *events(id: string, after: number, signal: AbortSignal): AsyncGenerator<JobEvent> {
    const res = await fetch(`${this.base}/v1/investigations/${id}/events?after=${after}`, {
      signal, headers: this.headers({ Accept: "text/event-stream" }),
    });
    if (!res.ok || !res.body) throw await toApiError(res);
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += value;
      let cut: number;
      while ((cut = buf.indexOf("\n\n")) >= 0) {
        const ev = parseSseBlock(buf.slice(0, cut));
        buf = buf.slice(cut + 2);
        if (ev) yield ev;
      }
    }
  }
}

export function parseSseBlock(block: string): JobEvent | null {
  let id = "", kind = "message", data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // keepalive comment
    if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("event:")) kind = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!id || kind === "end" || kind === "timeout") return null;
  try {
    const parsed = JSON.parse(data || "{}") as Record<string, unknown>;
    const ts = typeof parsed.ts === "number" ? parsed.ts : Date.now() / 1000;
    return { seq: Number(id), ts, kind, data: parsed };
  } catch { return null; }
}

async function toApiError(res: Response): Promise<ApiError> {
  const ra = Number(res.headers.get("retry-after")) || undefined;
  try {
    const j = (await res.json()) as { error?: { code?: string; message?: string; request_id?: string } };
    const e = j.error ?? {};
    return new ApiError(res.status, e.code ?? "error", e.message ?? res.statusText, e.request_id, ra);
  } catch {
    return new ApiError(res.status, "error", res.statusText || "Request failed", undefined, ra);
  }
}

/** Plain-language message for an error the user can act on. */
export function explain(e: unknown): string {
  if (e instanceof ApiError) {
    switch (e.code) {
      case "unauthenticated": return "The API key is missing or wrong. Add a valid key in Settings.";
      case "forbidden": return "This key can view results but not start investigations.";
      case "ambiguous_identity": return "That name matches more than one object. Use a catalog ID such as TIC 261136679.";
      case "object_not_found": return "No object matched. Try a catalog ID such as TIC 261136679 or KIC 8462852.";
      case "rate_limited": return `Too many requests. Try again in ${e.retryAfter ?? 30} seconds.`;
      case "upstream_error": return "An archive did not respond. Try again in a minute.";
      default: return e.message;
    }
  }
  return e instanceof Error ? e.message : "Something went wrong.";
}
