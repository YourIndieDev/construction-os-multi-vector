import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { TFunction } from 'i18next'
import {
  agentStepI18nKey,
  type AgUiEvent,
} from '@/lib/ag-ui/events'
import {
  formatAgentProgressLogLine,
  formatAgentProgressStatus,
  parseAgentProgressEvent,
} from '@/lib/ag-ui/progress'
import {
  parseMcpToolCallEvent,
  upsertMcpToolCall,
} from '@/lib/ag-ui/mcp-tool-calls'
import { parseA2uiEvent } from '@/lib/ag-ui/a2ui'
import { parseDrawingRetrievalDebugEvent } from '@/lib/ag-ui/drawing-retrieval'
import { isA2uiChatEnabled } from '@/lib/a2ui/constants'
import { useA2uiSurfaceStore } from '@/lib/a2ui/surface-store'
import { useDrawingRetrievalStore } from '@/lib/stores/drawing-retrieval-store'
import type { ChatToolCall } from '@/lib/types/mcp'
import { attachHtmlToChatContent } from '@/lib/utils/extract-html-from-chat'

export const HTML_TEMPLATE_OUTPUT_EVENT = 'html_template_output'

export interface ChatStreamMessage {
  id: string
  type: 'human' | 'ai'
  content: string
  timestamp?: string
}

export interface ParsedHtmlTemplateOutputEvent {
  messageId: string | null
  templateId: string | null
  html: string
}

export function parseHtmlTemplateOutputEvent(
  event: AgUiEvent
): ParsedHtmlTemplateOutputEvent | null {
  if (event.name !== HTML_TEMPLATE_OUTPUT_EVENT) {
    return null
  }
  const value = event.value
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const record = value as Record<string, unknown>
  if (typeof record.html !== 'string' || !record.html.trim()) {
    return null
  }
  return {
    messageId:
      typeof record.messageId === 'string'
        ? record.messageId
        : typeof event.messageId === 'string'
          ? event.messageId
          : null,
    templateId:
      typeof record.templateId === 'string' ? record.templateId : null,
    html: record.html,
  }
}

export interface AgUiSseHandlerDeps<TMessage extends ChatStreamMessage> {
  aiMessageIdRef: MutableRefObject<string | null>
  streamContentRef: MutableRefObject<Map<string, string>>
  streamRafRef: MutableRefObject<number | null>
  setMessages: Dispatch<SetStateAction<TMessage[]>>
  setStreamStatus: Dispatch<SetStateAction<string | null>>
  setActivityLog: Dispatch<SetStateAction<string[]>>
  setLiveMcpToolCalls: Dispatch<SetStateAction<ChatToolCall[]>>
  appendStreamingDelta: (messageId: string, delta: string) => void
  flushStreamingContent: () => void
  clearStreamingBuffers: () => void
  t: TFunction
  createAiMessage: (id: string, content: string) => TMessage
}

export interface AgUiSseHandlerOptions {
  onCustomEvent?: (event: AgUiEvent) => void
  onToolCallUpdate?: (toolCall: ChatToolCall) => void
  onStateSnapshot?: (snapshot: unknown) => void
  flushOnTextMessageEnd?: boolean
  clearBuffersOnRunFinished?: boolean
}

export function extractAgUiTextDelta(event: AgUiEvent): string {
  if (typeof event.delta === 'string') {
    return event.delta
  }
  if (typeof event.content === 'string') {
    return event.content
  }
  return ''
}

export function resolveAgUiMessageId(
  event: AgUiEvent,
  fallbackPrefix = 'ai'
): string {
  return (event.messageId as string) || `${fallbackPrefix}-${Date.now()}`
}

function bindDrawingDebugToMessage(messageId: string) {
  const store = useDrawingRetrievalStore.getState()
  store.bindPendingDebug(messageId)
  const next = useDrawingRetrievalStore.getState()
  if (
    !next.debugByMessageId[messageId] &&
    next.request.projectId &&
    next.request.mode === 'existing'
  ) {
    next.hydrateMessageDebug(messageId, {
      message_id: messageId,
      requested_mode: 'existing',
      mode_used: 'existing',
      project_id: next.request.projectId,
      requested_source_ids: [],
      existing: null,
      multi_vector: null,
      vision: null,
      evidence: [],
      fallback_reason: null,
    })
  }
}

export function createAgUiChatSseHandler<TMessage extends ChatStreamMessage>(
  deps: AgUiSseHandlerDeps<TMessage>,
  options: AgUiSseHandlerOptions = {}
): (event: AgUiEvent) => void {
  const {
    aiMessageIdRef,
    streamContentRef,
    streamRafRef,
    setMessages,
    setStreamStatus,
    setActivityLog,
    setLiveMcpToolCalls,
    appendStreamingDelta,
    flushStreamingContent,
    clearStreamingBuffers,
    t,
    createAiMessage,
  } = deps

  const {
    onCustomEvent,
    onToolCallUpdate,
    onStateSnapshot,
    flushOnTextMessageEnd = false,
    clearBuffersOnRunFinished = false,
  } = options

  return (event: AgUiEvent) => {
    switch (event.type) {
      case 'STEP_STARTED': {
        if (typeof event.stepName === 'string') {
          setStreamStatus(t(agentStepI18nKey(event.stepName)))
        }
        break
      }
      case 'STEP_FINISHED': {
        break
      }
      case 'CUSTOM': {
        const progress = parseAgentProgressEvent(event)
        if (progress) {
          const status = formatAgentProgressStatus(progress, t)
          if (status) {
            setStreamStatus(status)
          }
          const logLine = formatAgentProgressLogLine(progress, t)
          if (logLine) {
            setActivityLog((prev) => [...prev, logLine])
          }
        }
        const toolCallUpdate = parseMcpToolCallEvent(event)
        if (toolCallUpdate) {
          setLiveMcpToolCalls((prev) => upsertMcpToolCall(prev, toolCallUpdate))
          onToolCallUpdate?.(toolCallUpdate)
        }
        if (isA2uiChatEnabled()) {
          const a2ui = parseA2uiEvent(event)
          if (a2ui) {
            const store = useA2uiSurfaceStore.getState()
            const boundMessageId = a2ui.messageId || aiMessageIdRef.current
            store.applyMessages(boundMessageId, a2ui.messages)
          }
        }
        const htmlOutput = parseHtmlTemplateOutputEvent(event)
        if (htmlOutput) {
          const boundMessageId = htmlOutput.messageId || aiMessageIdRef.current
          if (boundMessageId) {
            const currentContent =
              streamContentRef.current.get(boundMessageId) ?? ''
            const nextContent = attachHtmlToChatContent(
              currentContent,
              htmlOutput.html
            )
            streamContentRef.current.set(boundMessageId, nextContent)
            setMessages((prev) => {
              let found = false
              const updated = prev.map((message) => {
                if (message.id !== boundMessageId) {
                  return message
                }
                found = true
                return { ...message, content: nextContent }
              })
              return found
                ? updated
                : [...updated, createAiMessage(boundMessageId, nextContent)]
            })
          }
        }
        const drawingDebug = parseDrawingRetrievalDebugEvent(event)
        if (drawingDebug) {
          useDrawingRetrievalStore.getState().captureDebug(
            drawingDebug,
            drawingDebug.message_id || event.messageId || aiMessageIdRef.current
          )
        }
        onCustomEvent?.(event)
        break
      }
      case 'TEXT_MESSAGE_START': {
        const messageId = resolveAgUiMessageId(event)
        aiMessageIdRef.current = messageId
        bindDrawingDebugToMessage(messageId)
        streamContentRef.current.set(messageId, '')
        setMessages((prev) => [...prev, createAiMessage(messageId, '')])
        if (isA2uiChatEnabled()) {
          useA2uiSurfaceStore.getState().attachPendingToMessage(messageId)
        }
        break
      }
      case 'TEXT_MESSAGE_CONTENT':
      case 'TEXT_MESSAGE_CHUNK': {
        const delta = extractAgUiTextDelta(event)
        if (!delta) {
          break
        }
        if (!aiMessageIdRef.current) {
          const messageId = resolveAgUiMessageId(event)
          aiMessageIdRef.current = messageId
          bindDrawingDebugToMessage(messageId)
          streamContentRef.current.set(messageId, delta)
          setMessages((prev) => [...prev, createAiMessage(messageId, delta)])
        } else {
          appendStreamingDelta(aiMessageIdRef.current, delta)
        }
        break
      }
      case 'TEXT_MESSAGE_END': {
        if (!flushOnTextMessageEnd) {
          break
        }
        if (streamRafRef.current != null) {
          cancelAnimationFrame(streamRafRef.current)
          streamRafRef.current = null
        }
        flushStreamingContent()
        setStreamStatus(null)
        break
      }
      case 'STATE_SNAPSHOT': {
        onStateSnapshot?.(event.snapshot)
        break
      }
      case 'RUN_FINISHED': {
        if (clearBuffersOnRunFinished) {
          flushStreamingContent()
          clearStreamingBuffers()
        }
        setStreamStatus(null)
        break
      }
      case 'RUN_ERROR': {
        throw new Error(
          typeof event.message === 'string' ? event.message : 'Stream error'
        )
      }
      default:
        break
    }
  }
}
