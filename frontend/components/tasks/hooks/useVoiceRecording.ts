import { useCallback, useEffect, useRef, useState } from 'react'
import { getVoiceWsUrl } from '@/lib/api-config'

interface UseVoiceRecordingOptions {
  onTranscription: (text: string) => void
}

export function useVoiceRecording({ onTranscription }: UseVoiceRecordingOptions) {
  const [isRecording, setIsRecording] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const voiceWsRef = useRef<WebSocket | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.stop()
      mediaRecorderRef.current.stream.getTracks().forEach((track) => track.stop())
      mediaRecorderRef.current = null
    }

    if (voiceWsRef.current) {
      voiceWsRef.current.close()
      voiceWsRef.current = null
    }

    setIsRecording(false)
  }, [])

  const startRecording = useCallback(async () => {
    try {
      setError(null)
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

      const voiceUrl = getVoiceWsUrl()
      if (!voiceUrl) {
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
          console.error('Failed to parse voice response:', err)
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
      console.error('Failed to start voice recording:', err)
      setError('Microphone access denied')
    }
  }, [onTranscription, stopRecording])

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
