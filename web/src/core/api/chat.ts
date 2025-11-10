// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { env } from "~/env";

import type { MCPServerMetadata } from "../mcp";
import type { Resource } from "../messages";
import { extractFromSearchParams } from "../replay/get-replay-id";
import { fetchStream } from "../sse";
import { sleep } from "../utils";

import { queryConversationByPath } from "./conversations";
import { resolveServiceURL } from "./resolve-service-url";
import type { ChatEvent } from "./types";

function getLocaleFromCookie(): string {
  if (typeof document === "undefined") return "en-US";
  
  // Map frontend locale codes to backend locale format
  // Frontend uses: "en", "zh"
  // Backend expects: "en-US", "zh-CN"
  const LOCALE_MAP = { "en": "en-US", "zh": "zh-CN" } as const;
  
  // Initialize to raw locale format (matches cookie format)
  let rawLocale = "zh";
  
  // Read from cookie
  const cookies = document.cookie.split(";");
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split("=");
    if (name === "NEXT_LOCALE" && value) {
      rawLocale = decodeURIComponent(value);
      break;
    }
  }
  
  // Map raw locale to backend format, fallback to en-US if unmapped
  return LOCALE_MAP[rawLocale as keyof typeof LOCALE_MAP] ?? "en-US";
}

export async function* chatStream(
  userMessage: string,
  params: {
    thread_id: string;
    resources?: Array<Resource>;
    auto_accepted_plan: boolean;
    enable_clarification?: boolean;
    max_clarification_rounds?: number;
    max_plan_iterations: number;
    max_step_num: number;
    max_search_results?: number;
    interrupt_feedback?: string;
    enable_deep_thinking?: boolean;
    enable_background_investigation: boolean;
    report_style?: "academic" | "popular_science" | "news" | "social_media" | "strategic_investment";
    mcp_settings?: {
      servers: Record<
        string,
        MCPServerMetadata & {
          enabled_tools: string[];
          add_to_agents: string[];
        }
      >;
    };
  },
  options: { abortSignal?: AbortSignal } = {},
) {
  if (
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY ||
    location.search.includes("mock") ||
    location.search.includes("replay=") ||
    location.search.includes("thread_id=")
  )
    return yield* chatReplayStream(userMessage, params, options);

  try {
    const locale = getLocaleFromCookie();
    const stream = fetchStream(resolveServiceURL("chat/stream"), {
      body: JSON.stringify({
        messages: [{ role: "user", content: userMessage }],
        locale,
        ...params,
      }),
      signal: options.abortSignal,
    });

    for await (const event of stream) {
      yield {
        type: event.event,
        data: JSON.parse(event.data),
      } as ChatEvent;
    }
  } catch (e) {
    console.error(e);
  }
}

async function* chatReplayStream(
  userMessage: string,
  params: {
    thread_id: string;
    auto_accepted_plan: boolean;
    max_plan_iterations: number;
    max_step_num: number;
    max_search_results?: number;
    interrupt_feedback?: string;
  } = {
      thread_id: "__mock__",
      auto_accepted_plan: false,
      max_plan_iterations: 3,
      max_step_num: 1,
      max_search_results: 3,
      interrupt_feedback: undefined,
    },
  options: { abortSignal?: AbortSignal } = {},
): AsyncIterable<ChatEvent> {
  const urlParams = new URLSearchParams(window.location.search);
  let replayFilePath = "";
  if (urlParams.has("mock")) {
    if (urlParams.get("mock")) {
      replayFilePath = `/mock/${urlParams.get("mock")!}.txt`;
    } else {
      if (params.interrupt_feedback === "accepted") {
        replayFilePath = "/mock/final-answer.txt";
      } else if (params.interrupt_feedback === "edit_plan") {
        replayFilePath = "/mock/re-plan.txt";
      } else {
        replayFilePath = "/mock/first-plan.txt";
      }
    }
    fastForwardReplaying = true;
  } else if (urlParams.has("thread_id")) {
    const threadId = extractFromSearchParams(window.location.search, "thread_id");
    if (threadId) {
      replayFilePath = `/api/conversation/${threadId}`;
    } else {
      // Fallback to a default replay
      replayFilePath = `/replay/eiffel-tower-vs-tallest-building.txt`;
    }
    fastForwardReplaying = true;
  } else {
    const replayId = extractFromSearchParams(window.location.search, "replay");
    if (replayId) {
      replayFilePath = `/replay/${replayId}.txt`;
    } else {
      // Fallback to a default replay
      replayFilePath = `/replay/eiffel-tower-vs-tallest-building.txt`;
    }
  }
  const text = replayFilePath.startsWith("/api/conversation") ? await queryConversationByPath(replayFilePath, {
    abortSignal: options.abortSignal,
  }) : await fetchReplay(replayFilePath, {
    abortSignal: options.abortSignal,
  });
  const normalizedText = text.replace(/\r\n/g, "\n");
  const chunks = normalizedText.split("\n\n");
  for (const chunk of chunks) {
    const [eventRaw, dataRaw] = chunk.split("\n") as [string, string];
    const [, event] = eventRaw.split("event: ", 2) as [string, string];
    const [, data] = dataRaw.split("data: ", 2) as [string, string];

    try {
        const chatEvent = {
          type: event,
          data: JSON.parse(data),
        } as ChatEvent;
        
        // 为不同类型的事件添加适当的延迟
        if (chatEvent.type === "message_chunk") {
          if (!chatEvent.data.finish_reason) {
            // 根据内容长度动态调整延迟，单个字符使用较小延迟，较长内容使用标准延迟
            const contentLength = chatEvent.data.content ? chatEvent.data.content.length : 0;
            const delayMs = contentLength <= 1 ? 20 : 50;
            await sleepInReplay(delayMs);
          }
        } else if (chatEvent.type === "tool_call_result") {
          await sleepInReplay(500);
        } else if (chatEvent.type === "tool_call_chunks") {
          // 为tool_call_chunks添加适当的延迟，对于单个字符的Unicode序列使用较小延迟
          const argsLength = chatEvent.data.tool_call_chunks?.[0]?.args ? chatEvent.data.tool_call_chunks[0].args.length : 0;
          const delayMs = argsLength <= 1 ? 10 : 30;
          await sleepInReplay(delayMs);
        } else if (chatEvent.type === "tool_calls") {
          // 为tool_calls添加前置延迟
          await sleepInReplay(100);
        }
        
        yield chatEvent;
        
        // 事件生成后的延迟
        if (chatEvent.type === "tool_call_result") {
          await sleepInReplay(800);
        } else if (chatEvent.type === "message_chunk") {
          if (chatEvent.data.role === "user") {
            await sleepInReplay(500);
          }
        } else if (chatEvent.type === "tool_calls") {
          // 工具调用后的延迟
          await sleepInReplay(300);
        }
        // 为连续的tool_call_chunks事件添加额外的缓冲时间
        else if (chatEvent.type === "tool_call_chunks") {
          // 当检测到可能是Unicode字符序列时，添加较小的延迟
          const argsLength = chatEvent.data.tool_call_chunks?.[0]?.args ? chatEvent.data.tool_call_chunks[0].args.length : 0;
          if (argsLength <= 1) {
            await sleepInReplay(5);
          }
        }
      } catch (e) {
        console.error(e);
        // 更好的错误处理，避免因为单个事件解析错误而影响整个回放
        // 可以考虑生成一个错误消息事件，而不是默默忽略
      }
  }
}

const replayCache = new Map<string, string>();
export async function fetchReplay(
  url: string,
  options: { abortSignal?: AbortSignal } = {},
) {
  if (replayCache.has(url)) {
    return replayCache.get(url)!;
  }
  const res = await fetch(url, {
    signal: options.abortSignal,
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch replay: ${res.statusText}`);
  }
  const text = await res.text();
  replayCache.set(url, text);
  return text;
}

export async function fetchReplayTitle() {
  const res = chatReplayStream(
    "",
    {
      thread_id: "__mock__",
      auto_accepted_plan: false,
      max_plan_iterations: 3,
      max_step_num: 1,
      max_search_results: 3,
    },
    {},
  );
  for await (const event of res) {
    if (event.type === "message_chunk") {
      return event.data.content;
    }
  }
}

export async function sleepInReplay(ms: number) {
  if (fastForwardReplaying) {
    await sleep(0);
  } else {
    await sleep(ms);
  }
}

let fastForwardReplaying = false;
export function fastForwardReplay(value: boolean) {
  fastForwardReplaying = value;
}
