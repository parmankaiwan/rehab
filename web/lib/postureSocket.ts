import { ConnectionState, POSTURE_STATES, PostureSnapshot } from "@/types/posture";

type Listener = (snapshot: PostureSnapshot) => void;
type StateListener = (state: ConnectionState) => void;

export function isPostureSnapshot(value: unknown): value is PostureSnapshot {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.timestamp === "number" && typeof v.overall_state === "string" && POSTURE_STATES.includes(v.overall_state as never) && typeof v.ready === "boolean" && typeof v.ready_progress === "number" && !!v.components && typeof v.components === "object" && Array.isArray(v.feedback);
}

export class PostureSocket {
  private socket?: WebSocket;
  private timer?: ReturnType<typeof setTimeout>;
  private stopped = false;
  private attempts = 0;
  constructor(private url: string, private onData: Listener, private onState: StateListener) {}
  connect() {
    this.stopped = false; this.onState(this.attempts ? "CONNECTING" : "CONNECTING");
    try {
      this.socket = new WebSocket(this.url);
      this.socket.onopen = () => { this.attempts = 0; this.onState("CONNECTED"); };
      this.socket.onmessage = (event) => { try { const parsed: unknown = JSON.parse(String(event.data)); if (isPostureSnapshot(parsed)) this.onData(parsed); } catch { /* malformed packets are ignored */ } };
      this.socket.onerror = () => this.onState("ERROR");
      this.socket.onclose = () => { if (!this.stopped) { this.onState("DISCONNECTED"); this.schedule(); } };
    } catch { this.onState("ERROR"); this.schedule(); }
  }
  private schedule() { const delay = Math.min(1000 * 2 ** this.attempts++, 8000); clearTimeout(this.timer); this.timer = setTimeout(() => this.connect(), delay); }
  reconnect() { this.disconnect(); this.attempts = 0; this.connect(); }
  disconnect() { this.stopped = true; clearTimeout(this.timer); this.socket?.close(); }
}
