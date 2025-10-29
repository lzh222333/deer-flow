// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useEffect, useRef, useState } from "react";

import { env } from "~/env";

import type { DeerFlowConfig } from "../config";
import type { Conversation } from "../messages";
import { useReplay } from "../replay";

import { fetchReplayTitle } from "./chat";
import { queryConversations } from "./conversations";
import { resolveServiceURL } from "./resolve-service-url";

export function useReplayMetadata() {
  const { isReplay } = useReplay();
  const [title, setTitle] = useState<string | null>(null);
  const isLoading = useRef(false);
  const [error, setError] = useState<boolean>(false);
  useEffect(() => {
    if (!isReplay) {
      return;
    }
    if (title || isLoading.current) {
      return;
    }
    isLoading.current = true;
    fetchReplayTitle()
      .then((title) => {
        setError(false);
        setTitle(title ?? null);
        if (title) {
          document.title = `${title} - 国寿投资深度研究智能体平台`;
        }
      })
      .catch(() => {
        setError(true);
        setTitle("Error: the replay is not available.");
        document.title = "国寿投资深度研究智能体平台";
      })
      .finally(() => {
        isLoading.current = false;
      });
  }, [isLoading, isReplay, title]);
  return { title, isLoading, hasError: error };
}

const DEFAULT_CONFIG: DeerFlowConfig = {
  rag: { provider: "" },
  models: { basic: [], reasoning: [] },
};

export function useConfig(): {
  config: DeerFlowConfig;
  loading: boolean;
} {
  const [loading, setLoading] = useState(true);
  const [config, setConfig] = useState<DeerFlowConfig>(DEFAULT_CONFIG);

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY) {
      setLoading(false);
      return;
    }

    const fetchConfigWithRetry = async () => {
      const maxRetries = 2;
      let lastError: Error | null = null;

      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          const res = await fetch(resolveServiceURL("./config"), {
            signal: AbortSignal.timeout(5000), // 5 second timeout
          });

          if (!res.ok) {
            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
          }

          const configData = await res.json();
          setConfig(configData);
          setLoading(false);
          return; // Success, exit retry loop
        } catch (err) {
          lastError = err instanceof Error ? err : new Error(String(err));

          // Log attempt details
          if (attempt === 0) {
            const apiUrl = resolveServiceURL("./config");
            console.warn(
              `[Config] Failed to fetch from ${apiUrl}: ${lastError.message}`,
            );
          }

          // Wait before retrying (exponential backoff: 100ms, 500ms)
          if (attempt < maxRetries) {
            const delay = Math.pow(2, attempt) * 100;
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }
      }

      // All retries failed, use default config
      console.warn(
        `[Config] Using default config after ${maxRetries + 1} attempts. Last error: ${lastError?.message ?? "Unknown"}`,
      );
      setConfig(DEFAULT_CONFIG);
      setLoading(false);
    };

    void fetchConfigWithRetry();
  }, []);

  return { config, loading };
}

export function useConversations(): {
  results: Conversation[] | null;
  loading: boolean;
} {
  const [results, setResults] = useState<Array<Conversation>>([]);
  const [loading, setLoading] = useState(true);
  const hasInitialized = useRef(false);
  const maxRetries = useRef(3);

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY) {
      setLoading(false);
      return;
    }
    // Prevent multiple calls
    if (hasInitialized.current || maxRetries.current <= 0) {
      return;
    }

    queryConversations()
      .then((data) => {
        setResults(data);
        setLoading(false);
        hasInitialized.current = true;
        maxRetries.current = 0; // Reset retries after successful fetch
      })
      .catch((error) => {
        console.error("Failed to fetch replays", error);
        setLoading(false);
        if (maxRetries.current > 0) {
          maxRetries.current -= 1;
          console.warn(`Retrying... (${3 - maxRetries.current} attempts left)`);
        }
      });

    return () => {
      hasInitialized.current = false;
      maxRetries.current = 3; // Reset retries on unmount
    };
  }, []);

  return { results, loading };
}