import type { DiagnosisMessage, IssueDiagnosisRequest } from './issueDiagnosis'

export function buildFollowUpRequest(
  baseRequest: IssueDiagnosisRequest,
  conversation: DiagnosisMessage[],
  question: string,
): IssueDiagnosisRequest {
  return {
    ...baseRequest,
    conversation_history: [
      ...conversation,
      { role: 'user', content: question.trim() },
    ],
  }
}
