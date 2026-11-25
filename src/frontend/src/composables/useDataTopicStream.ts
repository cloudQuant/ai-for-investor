import { type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import { dataTopicsApi } from '@/api/dataTopics'

function detachSocketHandlers(target: WebSocket | null) {
  if (!target) return
  target.onopen = null
  target.onmessage = null
  target.onclose = null
  target.onerror = null
}

/**
 * Manages the WebSocket lifecycle for DataTopicsPage with stale-socket guards.
 */
export function useDataTopicStream(options: {
  selectedTopic: Ref<string>
  topicPattern: Ref<string>
  wsConnected: Ref<boolean>
  liveEvents: Ref<Array<Record<string, unknown>>>
  latestValue: Ref<unknown>
  missingTokenMessage: () => string
}) {
  let socket: WebSocket | null = null

  function disconnectStream() {
    const activeSocket = socket
    socket = null
    options.wsConnected.value = false
    if (activeSocket) {
      detachSocketHandlers(activeSocket)
      activeSocket.close()
    }
  }

  function connectStream() {
    disconnectStream()
    if (typeof window === 'undefined') {
      return
    }
    const protocols = dataTopicsApi.getWebSocketProtocols()
    if (protocols.length === 0) {
      ElMessage.error(options.missingTokenMessage())
      return
    }
    const url = options.selectedTopic.value
      ? dataTopicsApi.buildTopicStreamUrl(options.selectedTopic.value)
      : dataTopicsApi.buildPatternStreamUrl(options.topicPattern.value)
    const currentSocket = new window.WebSocket(url, protocols)
    socket = currentSocket
    currentSocket.onopen = () => {
      if (socket !== currentSocket) return
      options.wsConnected.value = true
    }
    currentSocket.onmessage = (event: MessageEvent) => {
      if (socket !== currentSocket) return
      try {
        const payload = JSON.parse(String(event.data)) as Record<string, unknown>
        options.liveEvents.value = [payload, ...options.liveEvents.value].slice(0, 10)
        if (payload.type === 'topic_update' || payload.type === 'snapshot') {
          options.latestValue.value = payload.value
        }
      } catch {
        options.liveEvents.value = [
          { type: 'raw', data: String(event.data) },
          ...options.liveEvents.value,
        ].slice(0, 10)
      }
    }
    currentSocket.onclose = () => {
      detachSocketHandlers(currentSocket)
      if (socket !== currentSocket) return
      options.wsConnected.value = false
      socket = null
    }
    currentSocket.onerror = () => {
      if (socket !== currentSocket) return
      options.wsConnected.value = false
    }
  }

  return { disconnectStream, connectStream }
}
