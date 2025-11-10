// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type {
  ChatEvent,
  InterruptEvent,
  MessageChunkEvent,
  ToolCallChunksEvent,
  ToolCallResultEvent,
  ToolCallsEvent,
} from "../api";
import { deepClone } from "../utils/deep-clone";

import type { Message } from "./types";

export function mergeMessage(message: Message, event: ChatEvent) {
  if (event.type === "message_chunk") {
    mergeTextMessage(message, event);
  } else if (event.type === "tool_calls" || event.type === "tool_call_chunks") {
    mergeToolCallMessage(message, event);
  } else if (event.type === "tool_call_result") {
    mergeToolCallResultMessage(message, event);
  } else if (event.type === "interrupt") {
    mergeInterruptMessage(message, event);
  }
  // 安全处理finish_reason和toolCalls解析
  if (event.data?.finish_reason) {
    message.finishReason = event.data.finish_reason;
    message.isStreaming = false;
    if (message.toolCalls && Array.isArray(message.toolCalls)) {
      message.toolCalls.forEach((toolCall) => {
        if (toolCall.argsChunks && Array.isArray(toolCall.argsChunks) && toolCall.argsChunks.length > 0) {
          try {
            // 添加try-catch避免JSON解析错误导致整个应用崩溃
            const argsJson = toolCall.argsChunks.join("");
            if (argsJson.trim()) { // 确保不为空字符串
              toolCall.args = JSON.parse(argsJson);
            }
            delete toolCall.argsChunks;
          } catch (error) {
            console.error('Failed to parse tool call args JSON:', error, toolCall.argsChunks);
            // 解析失败时使用空对象作为fallback
            toolCall.args = {};
            delete toolCall.argsChunks;
          }
        }
      });
    }
  }
  return deepClone(message);
}

function mergeTextMessage(message: Message, event: MessageChunkEvent) {
  if (event.data.content) {
    message.content += event.data.content;
    message.contentChunks.push(event.data.content);
  }
  if (event.data.reasoning_content) {
    message.reasoningContent = (message.reasoningContent ?? "") + event.data.reasoning_content;
    message.reasoningContentChunks = message.reasoningContentChunks ?? [];
    message.reasoningContentChunks.push(event.data.reasoning_content);
  }
}
function convertToolChunkArgs(args: string) {
  // Convert escaped characters in args
  if (!args) return "";
  return args.replace(/&#91;/g, "[").replace(/&#93;/g, "]").replace(/&#123;/g, "{").replace(/&#125;/g, "}");
}
function mergeToolCallMessage(
  message: Message,
  event: ToolCallsEvent | ToolCallChunksEvent,
) {
  // 安全处理tool_calls事件
  if (event.type === "tool_calls" && event.data?.tool_calls && Array.isArray(event.data.tool_calls) && event.data.tool_calls[0]?.name) {
    message.toolCalls = event.data.tool_calls.map((raw) => ({
      id: raw.id || '',
      name: raw.name || '',
      args: raw.args || {},
      result: undefined,
    }));
  }

  message.toolCalls ??= [];
  
  // 确保event.data.tool_call_chunks存在且为数组
  const toolCallChunks = event.data?.tool_call_chunks && Array.isArray(event.data.tool_call_chunks) ? event.data.tool_call_chunks : [];
  for (const chunk of toolCallChunks) {
    if (!chunk) continue; // 跳过null或undefined的chunk
    
    const convertedArgs = convertToolChunkArgs(chunk.args || '');
    
    // 跳过空的或无效的chunks
    if (!convertedArgs || convertedArgs.trim() === '') {
      continue;
    }
    
    if (chunk.id) {
      const toolCall = message.toolCalls.find(
        (toolCall) => toolCall.id === chunk.id,
      );
      if (toolCall) {
        // 对于有id的chunk，直接设置为新的argsChunks
        toolCall.argsChunks = [convertedArgs];
      }
    } else {
      // 先查找现有的streaming tool call
      let streamingToolCall = message.toolCalls.find(
        (toolCall) => toolCall.argsChunks?.length,
      );
      
      // 如果没有找到现有的streaming tool call，创建一个新的
      if (!streamingToolCall) {
        streamingToolCall = {
          id: '',
          name: '',
          args: {}, // 使用空对象替代undefined以符合Record<string, unknown>类型
          argsChunks: [convertedArgs],
          result: undefined,
        };
        message.toolCalls.push(streamingToolCall);
      } else {
        // 优化：合并连续的chunk到同一个数组元素
        // 这对于处理单个字符的Unicode序列（如"8", "\u", "4", "f", "5"）特别重要
        streamingToolCall.argsChunks ??= [];
        
        // 总是将当前chunk追加到最后一个chunk上，避免单个字符渲染
        const lastChunk = streamingToolCall.argsChunks[streamingToolCall.argsChunks.length - 1] ?? '';
        streamingToolCall.argsChunks[streamingToolCall.argsChunks.length - 1] = lastChunk + convertedArgs;
      }
    }
  }
}

function mergeToolCallResultMessage(
  message: Message,
  event: ToolCallResultEvent,
) {
  // 添加完整的空值检查
  if (message.toolCalls && Array.isArray(message.toolCalls) && event.data?.tool_call_id) {
    const toolCall = message.toolCalls.find(
      (toolCall) => toolCall.id === event.data.tool_call_id,
    );
    if (toolCall) {
      toolCall.result = event.data.content ?? '';
    }
  }
}

function mergeInterruptMessage(message: Message, event: InterruptEvent) {
  message.isStreaming = false;
  // 安全设置options，确保event.data存在
  if (event.data) {
    message.options = event.data.options || {};
  }
}
