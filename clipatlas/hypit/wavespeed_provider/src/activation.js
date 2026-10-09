import {
  createRuntimeEndpointAdapterFacet,
  runtimeConfigCredentialRef,
  runtimeConfigExact,
  runtimeConfigObject,
  runtimeConfigPositiveInteger,
  runtimeConfigString,
} from "@hypit/runtime-kit";

import { createWaveSpeedProvider, diagnoseWaveSpeedProvider } from "./provider.js";

const adapter = createRuntimeEndpointAdapterFacet({
  use: "@hypit/provider-wavespeed",
  activate(context) {
    if (context.pool === undefined) throw new Error("WaveSpeed Provider Pool is required");
    const config = runtimeConfigObject(context.config, "WaveSpeed");
    runtimeConfigExact(config, ["baseUrl", "apiKey", "selectedModel", "pollIntervalMs"], "WaveSpeed");
    const baseUrl = runtimeConfigString(config.baseUrl, "WaveSpeed baseUrl") ?? "https://api.wavespeed.ai/api/v3";
    const apiKey = runtimeConfigCredentialRef(config.apiKey, "WaveSpeed apiKey");
    const selectedModel = runtimeConfigString(config.selectedModel, "WaveSpeed selectedModel") ?? "seedance-2";
    const pollIntervalMs = runtimeConfigPositiveInteger(config.pollIntervalMs, "WaveSpeed pollIntervalMs") ?? 5000;
    if (apiKey === undefined) throw new Error("WaveSpeed apiKey CredentialRef is required");
    const url = new URL(baseUrl);
    if (url.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(url.hostname)) {
      throw new Error("WaveSpeed baseUrl must use HTTPS or loopback HTTP");
    }
    const options = {
      instance: context.instance,
      pool: context.pool,
      baseUrl,
      apiKey,
      selectedModel,
      pollIntervalMs,
    };
    return {
      endpoint: createWaveSpeedProvider(options),
      diagnose: async (doctor) => await diagnoseWaveSpeedProvider(options, doctor),
    };
  },
});

export default {
  format: "hypit.node-package@1",
  hostFacets: [adapter],
};
