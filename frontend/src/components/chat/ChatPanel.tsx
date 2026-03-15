import { useChatStore } from '../../stores/chatStore';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import TurnProgress from './TurnProgress';
import ApprovalBanner from './ApprovalBanner';

export default function ChatPanel() {
  const { activeSessionId, sendMessage } = useChatStore();

  if (!activeSessionId) {
    return (
      <div
        style={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          opacity: 0.45,
          fontSize: 14,
        }}
      >
        Select or create a session to start chatting.
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <MessageList />
      <TurnProgress />
      <ApprovalBanner />
      <MessageInput onSend={sendMessage} />
    </div>
  );
}
