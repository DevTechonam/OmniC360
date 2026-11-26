import {StrictMode, useCallback, useEffect, useState, type FormEvent} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowLeft, ArrowRight, BookOpenText, Bot, CheckCircle2, ChevronRight, CircleDot, Headset, Inbox, Layers3, LogOut, Phone, RefreshCw, Search, ShieldCheck, Ticket as TicketIcon, X} from 'lucide-react';
import {api, ApiError, labels, priorities, statuses, type Customer, type Detail, type Env, type Operator, type Priority, type Queue, type Session, type Status} from './api';
import './styles.css';

const date = (stamp: string) => new Date(stamp).toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong.';
const initials = (name: string) => name.trim().split(/\s+/).slice(0, 2).map(word => word[0]?.toUpperCase()).join('') || '?';
const pageSize = 25;

function Brand() {return <div className="brand"><span className="brand-mark"><Headset size={21}/></span><div>OmniC360<small>SUPPORT OPERATIONS</small></div></div>}
function Pill({value}: {value: Status | Priority}) {return <span className={`pill ${value}`}><span/>{labels[value]}</span>}
function Source({value}: {value: 'chatbot' | 'ivr'}) {const Icon = value === 'ivr' ? Phone : Bot; return <span className="source"><Icon size={15}/>{labels[value]}</span>}
function ErrorBanner({message}: {message: string}) {return message && <p role="alert" className="error">{message}</p>}

function SignIn({onSignIn}: {onSignIn: () => Promise<void>}) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError('');
    try {
      await api('/session', {method: 'POST', body: JSON.stringify({email: form.get('email'), password: form.get('password')})});
      await onSignIn();
    } catch (error) {setError(errorText(error));} finally {setBusy(false);}
  }
  return <main className="login"><aside><Brand/><div className="pitch"><span className="eyebrow">AGENT WORKSPACE</span><h1>Customer escalations, in one queue.</h1><p>Review issues from your chatbots and IVR, route them to the right owner, and keep the next action clear.</p></div><div className="login-foot"><ShieldCheck size={17}/> Customer and environment scoped</div></aside><div className="login-body"><form onSubmit={submit}><div className="login-icon"><TicketIcon size={25}/></div><h2>Sign in</h2><p>Use your operator account to open the escalation console.</p><ErrorBanner message={error}/><label>Work email<input type="email" name="email" required maxLength={254} autoComplete="username" placeholder="agent@company.com"/></label><label>Password<input type="password" name="password" required maxLength={256} autoComplete="current-password"/></label><button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'} <ArrowRight size={16}/></button></form></div></main>;
}

function Workspace({session, onExpired}: {session: Session; onExpired: () => void}) {
  const [customer, setCustomer] = useState(session.customers[0]?.id ?? '');
  const [env, setEnv] = useState<Env>('dev');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const selected = session.customers.find(c => c.id === customer);
  async function logout() {
    setBusy(true); setError('');
    try {await api('/session', {method: 'DELETE'}); onExpired();}
    catch (error) {if (error instanceof ApiError && error.status === 401) onExpired(); else setError(errorText(error));}
    finally {setBusy(false);}
  }
  return <div className="shell"><aside className="rail"><Brand/><div className="rail-main"><div className="rail-label">WORKSPACE</div><div className="rail-active"><Inbox size={17}/> <span>Escalation queue</span></div><a href="/api/docs" target="_blank" rel="noreferrer"><BookOpenText size={17}/> <span>API reference</span></a></div><div className="rail-profile"><div className="avatar">{initials(session.operator.name)}</div><div className="profile-text"><b>{session.operator.name}</b><small>Operator</small></div><button className="icon" onClick={logout} disabled={busy} aria-label="Sign out" title="Sign out"><LogOut size={17}/></button></div></aside><div className="workspace"><header className="top"><span className="crumb"><Layers3 size={16}/> Workspace <ChevronRight size={14}/> <b>Escalations</b></span><div className="scope"><label><span>Customer</span><select value={customer} onChange={e => {setCustomer(e.target.value);setEnv('dev');}} disabled={!session.customers.length} aria-label="Customer">{session.customers.length ? session.customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>) : <option value="">No customers</option>}</select></label><label><span>Environment</span><select className={`environment ${env}`} value={env} onChange={e => setEnv(e.target.value as Env)} aria-label="Environment">{(['dev','qa','prod'] as const).map(value => <option key={value} value={value}>{labels[value]}</option>)}</select></label></div></header><main className="main"><ErrorBanner message={error}/>{selected ? <QueueView key={`${selected.id}/${env}`} customer={selected} env={env} onExpired={onExpired}/> : <div className="empty panel"><Inbox size={28}/><b>No customer workspaces yet</b><span>Ask your administrator to assign you to a customer.</span></div>}</main></div></div>;
}

function QueueView({customer, env, onExpired}: {customer: Customer; env: Env; onExpired: () => void}) {
  const [q, setQ] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<Status | ''>('');
  const [priority, setPriority] = useState<Priority | ''>('');
  const [page, setPage] = useState(0);
  const [version, setVersion] = useState(0);
  const [data, setData] = useState<Queue | null>(null);
  const [detail, setDetail] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const root = `/customers/${encodeURIComponent(customer.id)}`;
  const endpoint = `${root}/tickets`;
  const refresh = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    const timeout = window.setTimeout(() => {setSearch(q.trim()); setPage(0);}, 225);
    return () => window.clearTimeout(timeout);
  }, [q]);
  useEffect(() => {
    const abort = new AbortController();
    const params = new URLSearchParams({q: search, limit: String(pageSize), offset: String(page * pageSize)});
    if (status) params.set('status', status);
    if (priority) params.set('priority', priority);
    setLoading(true); setError(''); setData(null);
    api<Queue>(`${endpoint}?${params}`, {signal: abort.signal, headers: {'X-Environment': env}}).then(result => {
      if (abort.signal.aborted) return;
      if (page && page * pageSize >= result.total) setPage(Math.max(0, Math.ceil(result.total / pageSize) - 1));
      else setData(result);
    }).catch(error => {
      if (abort.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) onExpired();
      else setError(errorText(error));
    }).finally(() => {if (!abort.signal.aborted) setLoading(false);});
    return () => abort.abort();
  }, [endpoint, env, onExpired, page, priority, search, status, version]);
  const metrics = [['open', CircleDot], ['in_progress', Activity], ['resolved', CheckCircle2], ['closed', Inbox]] as const;
  return <>
    <div className="heading"><div><div className="eyebrow">OPERATOR CONSOLE</div><h1>Escalation queue</h1><p>Review and resolve issues sent from chat and voice integrations.</p></div><button className="secondary" onClick={refresh} disabled={loading}><RefreshCw size={15}/> Refresh</button></div>
    <div className="metrics">{metrics.map(([key, Icon]) => <button key={key} className={`metric ${status === key ? 'active' : ''}`} onClick={() => {setStatus(status === key ? '' : key);setPage(0);}} aria-pressed={status === key}><div><span>{labels[key]}</span><strong>{data ? data.counts[key] ?? 0 : '—'}</strong></div><span className={`metric-icon ${key}`}><Icon size={17}/></span></button>)}</div>
    <section className="panel" aria-label="Escalation tickets" aria-busy={loading}><div className="panel-title"><h2>Tickets</h2><span className="context">{customer.name} / {labels[env]}</span></div><div className="filters"><label className="search"><Search size={17}/><input aria-label="Search tickets" placeholder="Search ticket ID, subject, or reference…" value={q} maxLength={160} onChange={e => setQ(e.target.value)}/></label><select value={status} aria-label="Filter by status" onChange={e => {setStatus(e.target.value as Status | '');setPage(0);}}><option value="">All statuses</option>{statuses.map(key => <option key={key} value={key}>{labels[key]}</option>)}</select><select value={priority} aria-label="Filter by priority" onChange={e => {setPriority(e.target.value as Priority | '');setPage(0);}}><option value="">All priorities</option>{priorities.map(key => <option key={key} value={key}>{labels[key]}</option>)}</select></div>
    {error ? <div className="panel-error"><ErrorBanner message={error}/></div> : loading ? <div className="empty" role="status">Loading tickets…</div> : data?.items.length ? <div className="table-scroll"><table><thead><tr><th>Ticket</th><th>Priority</th><th>Status</th><th>Source</th><th>Assignee</th><th>Updated</th><th aria-label="Open ticket"/></tr></thead><tbody>{data.items.map(ticket => <tr key={ticket.id} onClick={() => setDetail(ticket.id)}><td><button className="ticket-link" onClick={event => {event.stopPropagation();setDetail(ticket.id);}}>{ticket.subject}</button><small className="ticket-id">{ticket.id}</small></td><td><Pill value={ticket.priority}/></td><td><Pill value={ticket.status}/></td><td><Source value={ticket.source}/></td><td>{ticket.assignee_name ?? 'Unassigned'}</td><td className="no-wrap">{date(ticket.updated_at)}</td><td><ChevronRight size={16}/></td></tr>)}</tbody></table></div> : <div className="empty"><Inbox size={28}/><b>{q || status || priority ? 'No matching tickets' : 'No tickets yet'}</b><span>{q || status || priority ? 'Try another search or clear a filter.' : `Escalations sent to ${labels[env]} will appear here.`}</span></div>}
    <footer className="table-foot"><span>{data?.total ? `Showing ${page * pageSize + 1}–${page * pageSize + data.items.length} of ${data.total}` : data ? '0 tickets' : '—'}</span><div><button className="secondary icon" aria-label="Previous page" disabled={!page || loading} onClick={() => setPage(p => p - 1)}><ArrowLeft size={16}/></button><button className="secondary icon" aria-label="Next page" disabled={!data || (page + 1) * pageSize >= data.total || loading} onClick={() => setPage(p => p + 1)}><ArrowRight size={16}/></button></div></footer></section>
    {detail && <TicketDetail key={detail} env={env} root={root} endpoint={`${endpoint}/${encodeURIComponent(detail)}`} onClose={() => setDetail('')} onUpdate={refresh} onExpired={onExpired}/>}
  </>;
}

function TicketDetail({env, root, endpoint, onClose, onUpdate, onExpired}: {env: Env; root: string; endpoint: string; onClose: () => void; onUpdate: () => void; onExpired: () => void}) {
  const [ticket, setTicket] = useState<Detail | null>(null);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [dialog, setDialog] = useState<HTMLDialogElement | null>(null);
  const fail = useCallback((error: unknown) => {if (error instanceof ApiError && error.status === 401) onExpired(); else setError(errorText(error));}, [onExpired]);
  useEffect(() => {if (dialog && !dialog.open) dialog.showModal();}, [dialog]);
  useEffect(() => {
    const abort = new AbortController();
    Promise.all([api<Detail>(endpoint,{signal:abort.signal, headers: {'X-Environment': env}}), api<Operator[]>(`${root}/operators`,{signal:abort.signal})]).then(([detail,list]) => {if (!abort.signal.aborted) {setTicket(detail);setOperators(list);}}).catch(error => {if (!abort.signal.aborted) fail(error);});
    return () => abort.abort();
  }, [endpoint, env, fail, root]);
  async function mutate(path: string, method: string, body: object, clearNote = false) {
    setBusy(true); setError('');
    try {await api(`${endpoint}${path}`, {method, headers: {'X-Environment': env}, body: JSON.stringify(body)}); if (clearNote) setNote(''); onUpdate();setTicket(await api<Detail>(endpoint, {headers: {'X-Environment': env}}));}
    catch (error) {fail(error);} finally {setBusy(false);}
  }
  return <dialog ref={setDialog} className="drawer" aria-labelledby="details-title" onCancel={onClose} onClick={event => {if (event.currentTarget === event.target) {const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();}}}>
    <header><div><span className="eyebrow">TICKET DETAILS</span><h2 id="details-title">{ticket?.subject ?? 'Escalation details'}</h2>{ticket && <span className="ticket-id">{ticket.id} · {labels[ticket.environment]}</span>}</div><button className="secondary icon" onClick={onClose} aria-label="Close ticket"><X size={18}/></button></header><div className="drawer-body"><ErrorBanner message={error}/>{!ticket ? !error && <div role="status">Loading details…</div> : <><div className="detail-pills"><Pill value={ticket.priority}/><Source value={ticket.source}/></div><div className="edit-grid"><label>Status<select disabled={busy} value={ticket.status} onChange={e => void mutate('', 'PATCH', {status: e.target.value})}>{statuses.map(key => <option key={key} value={key}>{labels[key]}</option>)}</select></label><label>Assignee<select disabled={busy} value={ticket.assignee_id ?? ''} onChange={e => void mutate('', 'PATCH', {assignee_id: e.target.value ? Number(e.target.value) : null})}><option value="">Unassigned</option>{operators.map(user => <option key={user.id} value={user.id}>{user.name}</option>)}</select></label></div><section className="detail-section"><h3>Issue description</h3><p className="body-text">{ticket.description}</p><dl><div><dt>Contact</dt><dd>{ticket.contact ?? 'Not provided'}</dd></div><div><dt>External reference</dt><dd>{ticket.external_reference ?? 'Not provided'}</dd></div><div><dt>Received</dt><dd>{date(ticket.created_at)}</dd></div></dl></section><section className="detail-section"><h3>Internal activity</h3><form onSubmit={event => {event.preventDefault(); if (note.trim()) void mutate('/notes','POST',{body: note.trim()},true);}}><textarea aria-label="Internal note" placeholder="Add a note for other operators…" value={note} maxLength={4000} onChange={e => setNote(e.target.value)} rows={3}/><button className="primary" disabled={!note.trim() || busy}>Add internal note</button></form><ol className="activity">{ticket.activity.map(item => <li key={item.id}><b>{item.actor ?? 'Integration'}</b><time dateTime={item.created_at}>{date(item.created_at)}</time><p>{item.body}</p></li>)}</ol></section></>}</div>
  </dialog>;
}

function App() {
  const [session, setSession] = useState<Session | undefined | null>(undefined);
  const [error, setError] = useState('');
  const signedOut = useCallback(() => setSession(null), []);
  const reload = useCallback(async (signal?: AbortSignal) => {
    const current = await api<Session>('/session', {signal});
    if (!signal?.aborted) setSession(current);
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    reload(abort.signal).catch(error => {if (!abort.signal.aborted) {if (!(error instanceof ApiError && error.status === 401)) setError(errorText(error)); signedOut();}});
    return () => abort.abort();
  }, [reload, signedOut]);
  if (session === undefined) return <main className="empty full" role="status">Loading OmniC360…</main>;
  return session ? <Workspace session={session} onExpired={signedOut}/> : <>{error && <ErrorBanner message={error}/>}<SignIn onSignIn={() => reload()}/></>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>);
