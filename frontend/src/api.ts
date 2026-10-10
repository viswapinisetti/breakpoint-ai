/** Typed client for the Breakpoint API.
 *
 * Identity is carried in a header, mirroring the backend's auth adapter: when
 * real NxtWave SSO lands, only this file and `app/deps.py` change.
 */

export type Difficulty = '1' | '2' | '3' | '4' | '5'

export interface Tool {
  key: string
  label: string
  icon: string
}

/** One registered topic, from the backend topic registry
 *  (`app/subjects/topics.py`). Subjects list every registered topic in
 *  curriculum order, including topics with no published challenges yet. */
export interface SubjectTopic {
  key: string
  number: number
  /** Exactly what a challenge's `topic` field holds. */
  name: string
  challenge_count: number
  /** Sum of its investigations' estimates, computed by the backend
   *  (`app/engine/duration.py`) from each one's difficulty and mode. */
  estimated_minutes: number
}

export interface Subject {
  key: string
  number: number
  name: string
  tagline: string
  tier: string
  topics: SubjectTopic[]
  tools: Tool[]
  evidence_types: string[]
  failure_categories: string[]
  challenge_count: number
  estimated_minutes: number
  has_deterministic_validator: boolean
  accent: string
}

export interface ChallengeCard {
  id: string
  subject: string
  topic: string
  subtopic: string
  difficulty: Difficulty
  challenge_mode: string
  artifact_type: string
  question: string
  simulated_confidence: number
  estimated_minutes: number
  attempted: boolean
  completed: boolean
}

/** What the student is allowed to see before judging. Note the absence of
 *  anything about correctness - that is enforced server-side. */
export interface StudentChallenge {
  id: string
  subject: string
  topic: string
  subtopic: string
  difficulty: Difficulty
  challenge_mode: string
  question: string
  artifact_type: string
  /** Free-form, subject-owned payload. Values may be strings, lists or
   *  nested tables; ArtifactView renders by shape. */
  artifact: Record<string, unknown>
  ai_claim: string
  ai_solution: { index: number; text: string }[]
  ai_final_answer: string
  simulated_confidence: number
  hint_count: number
  /** Which verdicts this challenge's mode accepts. The server rejects
   *  anything outside this set, so the UI renders exactly these. */
  allowed_judgments: JudgmentValue[]
  /** Mode G only: two rival solutions, both shown in full and neither
   *  marked. Empty for every other mode. */
  competing: CompetingSolution[]
  /** Mode F only: the call shape and the tests that already pass. */
  test_gap: TestGap | null
}

/** One of two rival solutions in Which-AI-Is-Wrong (Mode G). */
export interface CompetingSolution {
  label: string
  persona: string
  ai_claim: string
  ai_solution: { index: number; text: string }[]
  ai_final_answer: string
  simulated_confidence: number
}

/** Mode F: what the student's test has to look like, and what the shipped
 *  suite already covers. The reference implementation is never sent. */
export interface TestGap {
  entry_point: string
  signature: string
  arity: number
  existing_tests: string[]
  input_guidance: string
}

export interface StartAttempt {
  attempt_id: number
  challenge: StudentChallenge
  tools: Tool[]
  evidence_types: string[]
  max_debate_turns: number
  hints_used: number
  resumed: boolean
}

export type TruthState = 'flawed' | 'valid' | 'insufficient_information'
export type TrustJudgment = 'challenge' | 'approve' | 'insufficient_information'
export type ComparisonJudgment =
  | 'a_correct'
  | 'b_correct'
  | 'both_correct'
  | 'neither_correct'
  | 'underdetermined'
export type JudgmentValue = TrustJudgment | ComparisonJudgment
export type OutcomeTask = 'repair' | 'justify' | 'clarify' | 'break_tests'

export interface JudgeResult {
  correct: boolean
  truth_state: TruthState
  located_first_failure: boolean
  message: string
  requires_evidence: boolean
  outcome_task: OutcomeTask
  /** Echoed back as recorded; null when the client sent none. */
  confidence: number | null
  /** The confidence badge the artifact displayed, for the comparison. */
  ai_confidence: number
  /** One line about the student's certainty rather than their answer. */
  calibration_note: string
}

/** Accuracy within one confidence band, for the reliability chart. */
export interface CalibrationBand {
  label: string
  low: number
  high: number
  count: number
  mean_confidence: number | null
  accuracy: number | null
}

/** Confidence calibration (backend app/engine/calibration.py). Rates are null
 *  below `min_sample`; the counts are always real. */
export interface Calibration {
  judged: number
  mean_confidence: number | null
  accuracy: number | null
  /** Mean confidence minus accuracy: positive is overconfident. */
  gap: number | null
  brier: number | null
  over_trust: number
  under_trust: number
  believed_confident_ai: number
  bands: CalibrationBand[]
  recent_days: number
  recent_judged: number
  recent_over_trust: number
  recent_believed_confident_ai: number
  min_sample: number
}

/** One typed Evidence Board card (PRD v0.2 section 6.4). */
export interface EvidenceCardDraft {
  type: string
  reference: string
  references_step: number | null
  why_supports: string
  expression: string
  value: string
  unit: string
  reference_b: string
  conflict: string
  input: string
  expected: string
  observed: string
  rule: string
  replacement: string
}

export interface DeterministicCheck {
  card_index: number
  check: string
  status: 'passed' | 'failed' | 'not_applicable'
  reason_code: string
  detail: string
  computed: string | null
}

export type EvaluationStatus =
  | 'supported'
  | 'needs_revision'
  | 'review_pending'
  | 'technical_error'

export interface EvidenceResult {
  revision: number
  status: EvaluationStatus
  accepted: boolean
  strength: number
  feedback: string
  missing: string
  reason_code: string
  dimensions: Record<string, number>
  checks: DeterministicCheck[]
  /** Deterministic checks only. Distinct from `accepted`, which is whether the
   *  evidence actually supports the judgment (PRD v0.2 section 6.4). */
  checks_passed: boolean
  replayed: boolean
}

export interface TransferResult {
  correct: boolean
  expected: string
  message: string
}

export interface AppealResult {
  id: number
  status: string
  message: string
}

export interface HintResult {
  level: number
  kind: string
  text: string
  hints_used: number
  hints_remaining: number
}

export interface DebateResult {
  reply: string
  turn: number
  turns_remaining: number
  conceded: boolean
  exhausted: boolean
}

export interface RepairResult {
  accepted: boolean
  strength: number
  feedback: string
  reference_repair: string
}

/** One Break-the-Tests submission (Mode F). A rejected input is still
 *  informative, so `message` matters as much as `accepted`. */
export interface BreakTestResult {
  accepted: boolean
  reason_code:
    | 'suite_broken'
    | 'no_divergence'
    | 'already_covered'
    | 'unparseable_input'
    | 'execution_error'
  message: string
  normalised_input: string
  shipped_result: string
  correct_result: string
  submissions: number
}

export interface Autopsy {
  challenge_id: string
  truth_state: TruthState
  missing_information: string
  resolving_scenarios: string[]
  assisted: boolean
  answer_coincidentally_correct: boolean
  failure_category: string
  failure_label: string
  failure_location: number | null
  misconception: string
  why_convincing: string
  first_failure_step: number | null
  replay: { index: number; text: string; status: string; solution: string }[]
  canonical_solution: string
  canonical_answer: string
  ai_final_answer: string
  repair: string
  debrief: string
  counterexamples: string[]
  score: Record<string, number | boolean>
  hints_used: number
  debate_turns: number
  counterfactual: string
  transfer_question: string
  /** Mode G. Empty for every other mode. */
  comparison_verdict: '' | ComparisonJudgment
  divergence_step: number | null
  comparison_explanation: string
  /** Mode F. Empty for every other mode. */
  test_input: string
  test_submissions: number
  test_broke_suite: boolean
}

export interface JudgmentMatrixRow {
  truth_state: TruthState
  total: number
  judgments: Record<JudgmentValue, number>
}

export interface Stats {
  claims_investigated: number
  resolved_mixed_mode: number
  failures_found: number
  correct_approvals: number
  correct_insufficient: number
  false_alarms: number
  missed_failures: number
  strong_evidence: number
  /** null when the sample is below `min_sample` - show "Not enough evidence yet". */
  first_judgment_accuracy: number | null
  false_alarm_rate: number | null
  missed_failure_rate: number | null
  judgment_matrix: JudgmentMatrixRow[]
  min_sample: number
  investigation_score: number
  score_components: Record<string, number>
  assisted_attempts: number
  independent_completions: number
  streak_days: number
  verification_skills: Record<string, number>
  failure_categories: Record<string, number>
  achievements: string[]
  calibration: Calibration
}

/** Who the caller is. `signed_in: false` is an answer, not an error: in
 *  header mode nobody signs in and the app still works. */
export interface AuthProfile {
  signed_in: boolean
  name: string
  email: string
  /** password | google | header | oidc */
  provider: string
  external_id: string
}

/** What sign-in this server offers, so the screen renders only what works. */
export interface AuthProviders {
  mode: string
  password: boolean
  google: boolean
  /** Why Google is missing, when it is - shown rather than hidden. */
  google_unavailable: string
  sign_in_required: boolean
}

export interface HistoryEntry {
  attempt_id: number
  challenge_id: string
  subject: string
  topic: string
  subtopic: string
  difficulty: Difficulty
  question: string
  status: string
  judgment: string | null
  judged_correctly: boolean | null
  score: number
}

export interface DebateTurn {
  turn: number
  role: string
  message: string
  conceded: boolean
}

/* --- Challenge Studio (staff) ------------------------------------------- */

export interface AdminChallengeRow {
  challenge_id: string
  subject: string
  topic: string
  subtopic: string
  difficulty: Difficulty
  artifact_type: string
  status: string
  truth_state: TruthState
  failure_category: string
  failure_label: string
  quality_score: number
  version: number
  question: string
  reports: number
  failed_validators: number
  reviewed_by: string
  updated_at: string
}

export interface AdminChallengeDetail {
  row: AdminChallengeRow
  body: Record<string, unknown>
  student_view: StudentChallenge
  validations: { validator: string; passed: boolean; detail: string }[]
  critic_summary: Record<string, unknown>
  versions: {
    seq: number
    body_version: number
    status: string
    note: string
    author: string
    created_at: string
  }[]
  reports: { reason: string; detail: string; created_at: string }[]
  allowed_transitions: string[]
}

export interface ReviewItem {
  kind: 'appeal' | 'evaluation'
  id: number
  attempt_id: number
  challenge_id: string
  subject: string
  question: string
  truth_state: TruthState
  learner_judgment: string
  reason: string
  evaluator_feedback: string
  cards: {
    ordinal: number
    type: string
    references_step: number | null
    payload: Record<string, string>
    why_supports: string
  }[]
  created_at: string
}

export interface QueueCounts {
  by_status: Record<string, number>
  in_review: number
  published: number
  reports: number
  reviews: number
  ai_configured: boolean
  ai_provider: string
  ai_models: Record<string, string>
}

export interface GenerationJob {
  id: number
  status: string
  params: Record<string, unknown>
  requested: number
  survived: number
  rejected: number
  funnel: {
    index: number
    stage: string
    reasons: string[]
    challenge_id?: string
    quality?: number
  }[]
  error: string
  created_by: string
  created_at: string
  finished_at: string | null
}

export interface Template {
  key: string
  name: string
  description: string
  desired_failure: string
  difficulty: string
  make_correct: boolean
  applicable_subjects: string[]
}

export interface StudioAnalytics {
  published: number
  subjects_with_content: number
  total_subjects: number
  challenges: {
    challenge_id: string
    subject: string
    subtopic: string
    difficulty: string
    failure_label: string
    attempts: number
    completion_rate: number
    detection_rate: number
    avg_hints: number
    abandonment_rate: number
  }[]
  evidence_submitted: number
  evidence_acceptance_rate: number
  failure_distribution: Record<string, number>
  model_calls: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
}

export interface StudioReport {
  id: number
  challenge_id: string
  subject: string
  status: string
  reason: string
  detail: string
  question: string
  created_at: string
}

export class ApiError extends Error {
  readonly status: number
  /** Per-field errors from a 422, so the board can show them next to the
   *  cards rather than as one opaque sentence. */
  readonly fieldErrors: string[] | null

  constructor(status: number, message: string, fieldErrors: string[] | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

const STUDENT_ID = 'demo-student'
/** The name shown in header mode, where there is no account to read one from.
 *  In accounts mode the signed-in profile supplies it instead. */
export const STUDENT_NAME = 'NxtWave Learner'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      // The session cookie is the credential in accounts mode. The student
      // headers stay for header mode, where they are the credential; the
      // server ignores them once accounts are on.
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-Student-Id': STUDENT_ID,
        'X-Student-Name': STUDENT_NAME,
        ...(init?.headers ?? {}),
      },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the Breakpoint API. Is the backend running?')
  }

  if (!response.ok) {
    // A 502/504 without a JSON body comes from the dev proxy, not the API: the
    // backend is not listening on its port, usually because it is not running
    // or is still starting up.
    let detail =
      response.status === 502 || response.status === 504
        ? 'Cannot reach the Breakpoint API. The backend is not running, or is still starting - try again in a moment.'
        : `Request failed (${response.status})`
    let fieldErrors: string[] | null = null
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') {
        detail = body.detail
      } else if (body?.detail && typeof body.detail === 'object') {
        // Structured 422 from the evidence endpoint.
        if (typeof body.detail.message === 'string') detail = body.detail.message
        if (Array.isArray(body.detail.errors)) fieldErrors = body.detail.errors
      } else if (Array.isArray(body?.detail)) {
        // FastAPI's own validation shape.
        fieldErrors = body.detail
          .map((d: { msg?: string }) => d?.msg)
          .filter((m: unknown): m is string => typeof m === 'string')
        detail = 'This submission is not valid.'
      }
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(response.status, detail, fieldErrors)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export const auth = {
  providers: () => request<AuthProviders>('/auth/providers'),
  me: () => request<AuthProfile>('/auth/me'),
  signUp: (email: string, password: string, name: string) =>
    post<AuthProfile>('/auth/signup', { email, password, name }),
  signIn: (email: string, password: string) =>
    post<AuthProfile>('/auth/login', { email, password }),
  signOut: () => post<void>('/auth/logout'),
  /** A full-page navigation, not fetch: the browser has to follow Google's
   *  redirects and come back with the session cookie set. */
  googleUrl: '/api/auth/google/start',
}

export const api = {
  health: () => request<{ status: string; ai_configured: boolean }>('/health'),
  subjects: () => request<Subject[]>('/subjects'),
  subject: (key: string) => request<Subject>(`/subjects/${key}`),
  challenges: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString()
    return request<ChallengeCard[]>(`/challenges${q ? `?${q}` : ''}`)
  },
  daily: () => request<ChallengeCard | null>('/challenges/daily'),
  continueList: () => request<ChallengeCard[]>('/challenges/continue'),
  start: (id: string) => post<StartAttempt>(`/challenges/${id}/start`),
  judge: (
    attempt: number,
    judgment: JudgmentValue,
    located_step: number | null,
    /** How sure the student said they were, before the verdict resolved. */
    confidence: number | null,
  ) =>
    post<JudgeResult>(`/attempts/${attempt}/judge`, {
      judgment,
      located_step,
      confidence,
    }),
  evidence: (
    attempt: number,
    cards: EvidenceCardDraft[],
    idempotencyKey: string,
  ) =>
    post<EvidenceResult>(`/attempts/${attempt}/evidence`, {
      cards,
      idempotency_key: idempotencyKey,
    }),
  transfer: (attempt: number, answer: string) =>
    post<TransferResult>(`/attempts/${attempt}/transfer`, { answer }),
  appeal: (attempt: number, reason: string) =>
    post<AppealResult>(`/attempts/${attempt}/appeal`, { reason }),
  hint: (attempt: number) => post<HintResult>(`/attempts/${attempt}/hint`),
  debate: (attempt: number, message: string) =>
    post<DebateResult>(`/attempts/${attempt}/debate`, { message }),
  debateHistory: (attempt: number) =>
    request<DebateTurn[]>(`/attempts/${attempt}/debate`),
  repair: (attempt: number, repair: string) =>
    post<RepairResult>(`/attempts/${attempt}/repair`, { repair }),
  breakTests: (attempt: number, test_input: string, rationale: string) =>
    post<BreakTestResult>(`/attempts/${attempt}/test`, {
      test_input,
      rationale,
    }),
  complete: (attempt: number) => post<Autopsy>(`/attempts/${attempt}/complete`),
  report: (id: string, reason: string, detail: string) =>
    post<{ status: string }>(`/challenges/${id}/report`, { reason, detail }),
  stats: () => request<Stats>('/stats'),
  history: () => request<HistoryEntry[]>('/history'),
}

/** Staff identity for the Challenge Studio. Swap for real role-based SSO
 *  alongside the student adapter — both live behind one header each. */
const STAFF_NAME = 'Content Developer'

/* The Studio's shared secret (BREAKPOINT_ADMIN_TOKEN on the backend).
 *
 * It is typed in by staff and kept for the browser tab only. It is never
 * compiled into the bundle: anything in the bundle is readable by every
 * visitor, which would defeat the token. sessionStorage can throw (blocked
 * storage, private windows), so every access is guarded and the in-memory
 * copy keeps the Studio working for the page's lifetime regardless. */
const STAFF_TOKEN_KEY = 'breakpoint.staffToken'
let staffToken: string = (() => {
  try {
    return sessionStorage.getItem(STAFF_TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
})()

export const staffAuth = {
  hasToken: () => staffToken !== '',
  setToken(token: string) {
    staffToken = token.trim()
    try {
      sessionStorage.setItem(STAFF_TOKEN_KEY, staffToken)
    } catch {
      /* the in-memory copy still applies */
    }
  },
  clearToken() {
    staffToken = ''
    try {
      sessionStorage.removeItem(STAFF_TOKEN_KEY)
    } catch {
      /* nothing stored */
    }
  },
}

const staffHeaders = (): Record<string, string> =>
  staffToken
    ? { 'X-Staff-Name': STAFF_NAME, 'X-Admin-Token': staffToken }
    : { 'X-Staff-Name': STAFF_NAME }

const staffGet = <T>(path: string) =>
  request<T>(path, { headers: staffHeaders() })

const staffSend = <T>(path: string, method: string, body?: unknown) =>
  request<T>(path, {
    method,
    headers: staffHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  })

export const studio = {
  counts: () => staffGet<QueueCounts>('/admin/counts'),
  queue: (status?: string) =>
    staffGet<AdminChallengeRow[]>(
      `/admin/queue${status ? `?status=${status}` : ''}`,
    ),
  detail: (id: string) => staffGet<AdminChallengeDetail>(`/admin/challenges/${id}`),
  transition: (id: string, status: string, note: string) =>
    staffSend<AdminChallengeRow>(
      `/admin/challenges/${id}/transition`,
      'POST',
      { status, note },
    ),
  edit: (id: string, body: Record<string, unknown>, note: string) =>
    staffSend<AdminChallengeDetail>(`/admin/challenges/${id}`, 'PATCH', {
      body,
      note,
    }),
  generate: (payload: Record<string, unknown>) =>
    staffSend<GenerationJob>('/admin/generate', 'POST', payload),
  jobs: () => staffGet<GenerationJob[]>('/admin/jobs'),
  job: (id: number) => staffGet<GenerationJob>(`/admin/jobs/${id}`),
  templates: () => staffGet<Template[]>('/admin/templates'),
  analytics: () => staffGet<StudioAnalytics>('/admin/analytics'),
  reports: () => staffGet<StudioReport[]>('/admin/reports'),
  reviews: () => staffGet<ReviewItem[]>('/admin/reviews'),
  resolveReview: (
    kind: string,
    id: number,
    outcome: string,
    note: string,
  ) =>
    staffSend<{ status: string; outcome: string }>(
      `/admin/reviews/${kind}/${id}/resolve`,
      'POST',
      { outcome, note },
    ),
}
