export type Profile = "B0" | "B1" | "B2" | "B3";
export type DocumentId =
  | "campus_wifi_clean"
  | "campus_wifi_poisoned_a07"
  | "campus_wifi_poisoned_a08"
  | "campus_wifi_poisoned_a09"
  | "campus_wifi_poisoned_c05"
  | "campus_wifi_poisoned_c06"
  | "campus_wifi_poisoned_c07"
  | "campus_wifi_poisoned_c08";
export interface AttackExample {
  case_id: string;
  title: string;
  message: string;
  document_id: DocumentId;
  entry: "message" | "document";
  explanation: string;
  document_text: string;
  payload_text: string;
}
export async function getExamples(): Promise<AttackExample[]> {
  const response = await fetch("/api/examples", {
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error("挑战样例暂不可用，请检查后端版本。");
  return (await response.json()).examples;
}
export interface ChatInput {
  message: string;
  document_id: DocumentId;
  defense_profile: Profile;
}
export interface ChatResult {
  request_id: string;
  answer: string;
  defense_profile: Profile;
  document_id: DocumentId;
  model: string;
  latency_ms: number;
  technical_status: string;
  security_events: { stage: string; rule_id: string; source: string }[];
}
export interface Health {
  status: string;
  configured: boolean;
  model: string;
  provider: string;
}

export async function getHealth(): Promise<Health> {
  const response = await fetch("/health", {
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error("无法连接后端");
  return response.json();
}

export async function sendChat(input: ChatInput): Promise<ChatResult> {
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal: AbortSignal.timeout(70000),
  });
  const body = await response.json();
  // Upstream failures use the same public result shape so technical status stays visible.
  if (body.request_id && typeof body.answer === "string") return body;
  throw new Error(
    typeof body.detail === "string"
      ? body.detail
      : "请求未完成，请检查后端状态。",
  );
}
