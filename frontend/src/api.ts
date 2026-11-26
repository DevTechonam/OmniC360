export type Env = 'dev' | 'qa' | 'prod';
export type Status = 'open' | 'in_progress' | 'resolved' | 'closed';
export type Priority = 'low' | 'normal' | 'high' | 'urgent';
export type Customer = {id: string; name: string};
export type Operator = {id: number; name: string};
export type Session = {operator: Operator & {email: string}; customers: Customer[]};
export type Ticket = {id: string; subject: string; priority: Priority; status: Status; source: 'chatbot' | 'ivr'; assignee_id: number | null; assignee_name: string | null; created_at: string; updated_at: string};
export type Activity = {id: number; kind: string; body: string; created_at: string; actor: string | null};
export type Detail = Ticket & {description: string; contact: string | null; external_reference: string | null; environment: Env; activity: Activity[]};
export type Queue = {items: Ticket[]; total: number; counts: Partial<Record<Status, number>>};
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {credentials: 'same-origin', ...options, headers: { Accept: 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers }});
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof error.detail === 'string' ? error.detail : Array.isArray(error.detail) ? error.detail.map((field: {msg: string}) => field.msg).join('; ') : 'Request failed. Please try again.');
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}
export const labels = {dev: 'Development', qa: 'QA', prod: 'Production', open: 'Open', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed', low: 'Low', normal: 'Normal', high: 'High', urgent: 'Urgent', chatbot: 'Chatbot', ivr: 'IVR'};
export const statuses: Status[] = ['open', 'in_progress', 'resolved', 'closed'];
export const priorities: Priority[] = ['low', 'normal', 'high', 'urgent'];
