import ChatPanel from './ChatPanel.jsx'

// Voice mode is the chat pipeline with a big mic button and answers read aloud by default.
export default function VoicePanel({ onResult }) {
  return <ChatPanel onResult={onResult} voiceFirst />
}
