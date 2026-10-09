import { canonicalize } from "@hypit/protocol";
import { defineEndpointPackage, wakeAfter } from "@hypit/endpoint-kit";
import {
  compileWireRequest,
  generationTypes,
  sealGeneratedVideoSet,
  selectWireModelForRequest,
} from "@hypit/generation";

const moduleRef = { name: "@hypit/provider-wavespeed", version: "1" };
const seedanceModule = { name: "@hypit/seedance", version: "1" };
const MODEL_VERSIONS = { "seedance-2": "2.0", "seedance-2.5": "2.5" };

const mapping = (name) => ({
  capability: { module: seedanceModule, name },
  result: "video",
  routes: [{ model: name }],
  fields: {
    prompt: { as: "value", field: "prompt" },
    referenceImage: { as: "urlArray", field: "reference_images" },
    referenceVideo: { as: "urlArray", field: "reference_videos" },
    referenceAudio: { as: "urlArray", field: "reference_audios" },
    firstFrame: { as: "url", field: "first_frame" },
    lastFrame: { as: "url", field: "last_frame" },
    resolution: { as: "value", field: "resolution" },
    aspectRatio: { as: "value", field: "aspect_ratio" },
    duration: { as: "value", field: "duration" },
    generateAudio: { as: "value", field: "generate_audio" },
    webSearch: { as: "value", field: "enable_web_search" },
  },
});

const mappings = [mapping("seedance-2"), mapping("seedance-2.5")];

function object(value, subject = "WaveSpeed response") {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${subject} must be an object`);
  }
  return value;
}

function text(value, subject) {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${subject} is missing`);
  return value;
}

function secret(credentials) {
  return text(credentials.apiKey?.secret, "WaveSpeed API key");
}

function support(selectedModel, mappingValue, request) {
  if (mappingValue.capability.name !== selectedModel) {
    return { status: "unsupported", reason: `WaveSpeed is configured for ${selectedModel}` };
  }
  const ports = request.constraints.ports ?? {};
  const images = ports.referenceImage?.length ?? 0;
  const videos = ports.referenceVideo?.length ?? 0;
  const audios = ports.referenceAudio?.length ?? 0;
  const frames = ports.firstFrame?.length ?? 0;
  if (videos > 1 || frames > 1 || (videos === 0 && frames === 0 && images > 1)) {
    return { status: "unsupported", reason: "WaveSpeed accepts one source video or one opening image per Seedance request" };
  }
  if (audios > 0 && videos === 0) {
    return { status: "unsupported", reason: "WaveSpeed reference audio requires a source video edit" };
  }
  return { status: "supported" };
}

function operation(version, input) {
  const videos = Array.isArray(input.reference_videos) ? input.reference_videos : [];
  const images = Array.isArray(input.reference_images) ? input.reference_images : [];
  const payload = { ...input };
  delete payload.reference_videos;
  delete payload.reference_images;
  delete payload.first_frame;
  delete payload.last_frame;
  if (videos.length > 0) {
    payload.video = videos[0];
    if (images.length > 0) payload.reference_images = images;
    if (version === "2.5") {
      delete payload.duration;
      delete payload.aspect_ratio;
      delete payload.enable_web_search;
    }
    return { path: `bytedance/seedance-${version}/video-edit`, payload };
  }
  const first = input.first_frame ?? images[0];
  if (typeof first === "string") {
    payload.image = first;
    if (typeof input.last_frame === "string") payload.last_image = input.last_frame;
    if (version === "2.5") delete payload.aspect_ratio;
    return { path: `bytedance/seedance-${version}/image-to-video`, payload };
  }
  delete payload.reference_audios;
  return { path: `bytedance/seedance-${version}/text-to-video`, payload };
}

function extension(mediaType) {
  return ({
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    "video/mp4": "mp4", "video/webm": "webm", "audio/mpeg": "mp3", "audio/wav": "wav",
  })[mediaType] ?? "bin";
}

function createClient(baseUrl, fetcher) {
  const base = new URL(baseUrl).href.replace(/\/$/u, "");
  async function json(path, apiKey, init = {}) {
    const response = await fetcher(`${base}/${path.replace(/^\//u, "")}`, {
      ...init,
      headers: { authorization: `Bearer ${apiKey}`, ...init.headers },
      signal: AbortSignal.timeout(60_000),
    });
    if (!response.ok) {
      const requestId = response.headers.get("x-request-id");
      let detail = "";
      try {
        const payload = object(await response.json());
        detail = typeof payload.message === "string" ? `: ${payload.message}` : "";
      } catch { /* HTTP status remains sufficient public evidence. */ }
      throw new Error(`WaveSpeed ${init.method ?? "GET"} ${path} returned HTTP ${response.status}${detail}`
        + (requestId === null ? "" : `; request=${requestId}`));
    }
    return object(await response.json());
  }
  return { base, json };
}

async function upload(client, apiKey, artifact, resources, fetcher) {
  const bytes = await resources.get(artifact.resource);
  if (bytes === undefined) throw new Error("WaveSpeed reference media is unavailable");
  const ticketPayload = await client.json("media/uploads", apiKey, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      filename: `reference.${extension(artifact.mediaType)}`,
      size: bytes.byteLength,
      content_type: artifact.mediaType,
    }),
  });
  const ticket = object(ticketPayload.data, "WaveSpeed upload ticket");
  const target = object(ticket.upload, "WaveSpeed upload target");
  const response = await fetcher(text(target.url, "WaveSpeed upload URL"), {
    method: typeof target.method === "string" ? target.method : "PUT",
    headers: object(target.headers ?? {}, "WaveSpeed upload headers"),
    body: new Uint8Array(bytes),
    signal: AbortSignal.timeout(300_000),
  });
  if (!response.ok) throw new Error(`WaveSpeed media upload returned HTTP ${response.status}`);
  return text(ticket.download_url, "WaveSpeed download URL");
}

function taskData(payload) {
  return object(payload.data, "WaveSpeed task data");
}

function failed(data) {
  return data.status === "failed" || data.status === "cancelled" || data.status === "timeout";
}

function outputs(data) {
  return Array.isArray(data.outputs) ? data.outputs.filter((item) => typeof item === "string") : [];
}

export function createWaveSpeedProvider(options) {
  if (!(options.selectedModel in MODEL_VERSIONS)) throw new Error("WaveSpeed model must be seedance-2 or seedance-2.5");
  const fetcher = options.fetch ?? globalThis.fetch;
  const client = createClient(options.baseUrl, fetcher);
  const interval = options.pollIntervalMs ?? 5000;
  const capabilities = mappings.map((mappingValue) => {
    const supports = (request) => support(options.selectedModel, mappingValue, request);
    const endpoint = {
      async start(context) {
        const supported = supports(context.need);
        if (supported.status === "unsupported") throw new Error(supported.reason);
        const apiKey = secret(context.credentials);
        const authored = context.need.constraints;
        selectWireModelForRequest(mappingValue, authored);
        const input = await compileWireRequest(mappingValue, authored,
          async (artifact) => await upload(client, apiKey, artifact, context.resources, fetcher));
        const selected = operation(MODEL_VERSIONS[mappingValue.capability.name], input.input);
        await context.reportProgress?.({ phase: `Submitting WaveSpeed ${mappingValue.capability.name}` });
        const response = taskData(await client.json(selected.path, apiKey, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(selected.payload),
        }));
        const id = text(response.id, "WaveSpeed task id");
        const handle = { id, model: mappingValue.capability.name, outputs: outputs(response) };
        const receipt = { id };
        await context.checkpoint?.({ handle: canonicalize(handle), receipt });
        if (failed(response)) return { status: "failed", receipt, failure: { code: "WAVESPEED_TASK_FAILED", message: `WaveSpeed task ${id} failed` } };
        if (response.status === "completed") return { status: "ready", handle: canonicalize(handle), receipt };
        return { ...wakeAfter(canonicalize(handle), interval), receipt };
      },
      async poll(context) {
        const handle = object(context.handle, "WaveSpeed handle");
        const apiKey = secret(context.credentials);
        const response = taskData(await client.json(`predictions/${encodeURIComponent(text(handle.id, "WaveSpeed task id"))}/result`, apiKey));
        if (failed(response)) return { status: "failed", receipt: { id: handle.id }, failure: { code: "WAVESPEED_TASK_FAILED", message: `WaveSpeed task ${handle.id} failed` } };
        const next = { ...handle, outputs: outputs(response) };
        return response.status === "completed"
          ? { status: "ready", handle: canonicalize(next), receipt: { id: handle.id } }
          : wakeAfter(canonicalize(next), interval, Date.now(), { phase: String(response.status ?? "processing") });
      },
      async collect(context) {
        const handle = object(context.handle, "WaveSpeed handle");
        let urls = Array.isArray(handle.outputs) ? handle.outputs : [];
        if (urls.length === 0) {
          const response = taskData(await client.json(`predictions/${encodeURIComponent(text(handle.id, "WaveSpeed task id"))}/result`, secret(context.credentials)));
          urls = outputs(response);
        }
        const url = text(urls[0], "WaveSpeed video output");
        const response = await fetcher(url, { signal: AbortSignal.timeout(300_000) });
        if (!response.ok) throw new Error(`WaveSpeed video download returned HTTP ${response.status}`);
        const mediaType = response.headers.get("content-type")?.split(";")[0] || "video/mp4";
        if (!mediaType.startsWith("video/")) throw new Error("WaveSpeed returned a non-video output");
        const artifact = await context.resources.put(new Uint8Array(await response.arrayBuffer()), mediaType);
        return { status: "completed", result: { value: {
          kind: "inline",
          value: canonicalize(sealGeneratedVideoSet({ videos: [artifact] })),
        } } };
      },
    };
    return {
      capability: mappingValue.capability,
      returns: generationTypes.videoSet,
      lifecycle: "asynchronous",
      supports,
      endpoint,
    };
  });
  return defineEndpointPackage({
    module: moduleRef,
    facet: "videos",
    instance: options.instance,
    pool: options.pool,
    credentials: { apiKey: options.apiKey },
    credentialInputs: { apiKey: { label: "WaveSpeed API key" } },
    defaultConcurrency: 2,
    actionLimits: { submit: { concurrency: 2 }, poll: { concurrency: 8 }, collect: { concurrency: 2 } },
    pricing: { kind: "page", url: "https://wavespeed.ai/pricing" },
    capabilities,
  });
}

export async function diagnoseWaveSpeedProvider(options, context) {
  const apiKey = secret(context.credentials);
  const client = createClient(options.baseUrl, options.fetch ?? globalThis.fetch);
  try {
    const response = await client.json("models", apiKey);
    if (!Array.isArray(response.data)) throw new Error("WaveSpeed model catalogue has no data array");
    return [];
  } catch (error) {
    return [{
      severity: "error",
      code: "WAVESPEED_CONNECTION_FAILED",
      message: error instanceof Error ? error.message : String(error),
    }];
  }
}
