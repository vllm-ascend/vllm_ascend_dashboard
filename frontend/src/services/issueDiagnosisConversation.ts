import type { DiagnosisMessage, IssueDiagnosisRequest } from './issueDiagnosis'

export const MAX_CONVERSATION_MESSAGES = 50

export function canAskFollowUp(conversation: DiagnosisMessage[]): boolean {
  const completeMessages = conversation.filter(message => message.content.trim())
  return completeMessages.length < MAX_CONVERSATION_MESSAGES - 1
}

export function buildFollowUpRequest(
  baseRequest: IssueDiagnosisRequest,
  conversation: DiagnosisMessage[],
  question: string,
): IssueDiagnosisRequest {
  return {
    ...baseRequest,
    conversation_history: [
      ...conversation.filter(message => message.content.trim()),
      { role: 'user', content: question.trim() },
    ],
  }
}
