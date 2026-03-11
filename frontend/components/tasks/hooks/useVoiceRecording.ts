import { useCallback, useEffect, useRef, useState } from 'react'
import { getVoiceWsUrl } from '@/lib/api-config'
import { getErrorMessage } from '@/lib/utils'

interface UseVoiceRecordingOptions {
  onTranscription: (text: string) => void
}

export function useVoiceRecording({
  onTranscription,
}: UseVoiceRecordingOptions) {
  const [isRecording, setIsRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const voiceWsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)

  const stopStream = useCallback((stream: MediaStream) => {
    stream.getTracks().forEach((track) => track.stop())
  }, [])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stop()
      stopStream(mediaRecorderRef.current.stream)
      mediaRecorderRef.current = null
    }

    if (voiceWsRef.current) {
      voiceWsRef.current.close()
      voiceWsRef.current = null
    }

    setIsRecording(false)
  }, [stopStream])

  const startRecording = useCallback(async () => {
    try {
      setError(null)
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

      const voiceUrl = getVoiceWsUrl()
      if (!voiceUrl) {
        stopStream(stream)
        setError('Voice service not configured')
        return
      }

      const voiceWs = new WebSocket(voiceUrl)
      voiceWsRef.current = voiceWs

      voiceWs.onopen = () => {
        setIsRecording(true)
      }

      voiceWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'transcription' && data.text) {
            onTranscription(data.text)
          }
        } catch (err) {
          setError(getErrorMessage(err, 'Received invalid voice response'))
        }
      }

      voiceWs.onerror = () => {
        setError('Voice connection error')
        stopRecording()
      }

      voiceWs.onclose = () => {
        setIsRecording(false)
      }

      const mediaRecorder = new MediaRecorder(stream)
      mediaRecorderRef.current = mediaRecorder

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0 && voiceWs.readyState === WebSocket.OPEN) {
          voiceWs.send(event.data)
        }
      }

      mediaRecorder.start(250)
    } catch (err) {
      setError(getErrorMessage(err, 'Microphone access denied'))
    }
  }, [onTranscription, stopRecording, stopStream])

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }, [isRecording, startRecording, stopRecording])

  useEffect(() => {
    return () => {
      stopRecording()
    }
  }, [stopRecording])

  return {
    isRecording,
    error,
    toggleRecording,
  }
}
