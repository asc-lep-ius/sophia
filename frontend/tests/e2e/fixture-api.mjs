/**
 * Deterministic stand-in for the Sophia API, for end-to-end runs only.
 *
 * The study surface is measured here — latency budgets, pacing floors,
 * keyboard flow — and those numbers only mean something against a fixed
 * dataset. A real API would fold model-generation time and database variance
 * into every measurement.
 *
 * It answers the same shapes the generated OpenAPI client expects, including
 * the per-question engagement policy, so the app exercises its real code
 * paths: nothing in `src/` knows this exists.
 */
import { createServer } from "node:http";

const PORT = Number(process.env.SOPHIA_FIXTURE_PORT ?? 8788);
const CSRF_TOKEN = "e2e-csrf-token";
const LEARNING_PATH_ID = 12;

/** Session 1 is paced like production; session 2 is the latency deck. */
const PACED_POLICY = {
  kind: "elaboration",
  required_event_types: [
    "prompt_shown",
    "prediction_made",
    "elaboration_written",
  ],
  min_elaboration_chars: 80,
  min_prompt_dwell_ms: 5000,
};

/**
 * The latency deck carries an ungated policy on purpose: the 50 ms budget is
 * a navigation-interaction budget, and measuring it through a 5-second dwell
 * floor 50 times would measure the floor. `study-pacing.spec.ts` is what holds
 * the floors themselves.
 */
const UNGATED_POLICY = {
  kind: "elaboration",
  required_event_types: [],
  min_elaboration_chars: 0,
  min_prompt_dwell_ms: 0,
};

const SELF_RATING_SCORES = { 1: 0, 2: 0.3, 3: 0.7, 4: 1 };

const PACED_SESSION_LIMIT = 100;
const DEFAULT_DECK_SIZE = 51;
const EXTEND_DECK_SIZE = 2;
const EXTEND_SESSION_ID = 501;

const state = {
  sessions: new Map(),
  questions: new Map(),
  attempts: new Map(),
  predictions: new Map(),
  nextSessionId: 900,
};

/**
 * Sessions appear on first use, so every test can own one.
 *
 * The fixture is one process shared by parallel workers: a test that grades a
 * card would otherwise shorten the deck another test is asserting a card count
 * against. The id picks the policy — under 100 is paced like production, 100
 * and over is ungated for the tests that measure navigation rather than
 * friction — so a spec chooses its behaviour by choosing an id. One id gets a
 * two-card deck, for the test that drains a queue and extends it.
 */
function ensureSession(id) {
  if (state.sessions.has(id)) {
    return;
  }
  const paced = id < PACED_SESSION_LIMIT;
  addSession(state.sessions, state.questions, {
    id,
    topic: paced ? "Graphs" : "Latency",
    cards: id === EXTEND_SESSION_ID ? EXTEND_DECK_SIZE : DEFAULT_DECK_SIZE,
    policy: paced ? PACED_POLICY : UNGATED_POLICY,
  });
}

function addSession(sessions, questions, { id, topic, cards, policy }) {
  sessions.set(id, {
    id,
    learning_path_id: LEARNING_PATH_ID,
    topic,
    pre_test_score: null,
    post_test_score: null,
    started_at: "2026-09-04T10:00:00Z",
    completed_at: null,
    improvement: null,
  });
  questions.set(
    id,
    Array.from({ length: cards }, (_unused, index) => ({
      id: `s${id}-q${index}`,
      kind: "open_response",
      topic,
      prompt: `Card ${index + 1}: explain ${topic} in your own words.`,
      difficulty: "explain",
      content_language: "en",
      translations: [],
      provenance: {
        origin: "lms",
        generated_by: "model",
        generator_ref: "fixture-model",
        generated_at: "2026-09-04T10:00:00Z",
        verified_by: null,
        verified_at: null,
        source_spans: [],
      },
      engagement_policy: policy,
    })),
  );
}

const routes = [
  ["GET", /^\/api\/auth\/session$/, sessionResponse],
  ["GET", /^\/api\/ready$/, () => ({ status: "ready" })],
  [
    "POST",
    /^\/api\/metrics\/web-vitals$/,
    () => ({ status: "accepted", code: "metrics.web_vitals.accepted" }),
  ],
  ["GET", /^\/api\/study\/pacing$/, pacingResponse],
  ["GET", /^\/api\/study\/sessions$/, listSessions],
  ["POST", /^\/api\/study\/sessions$/, startSession],
  ["POST", /^\/api\/study\/sessions\/(\d+)\/complete$/, completeSession],
  ["GET", /^\/api\/study\/sessions\/(\d+)\/summary$/, sessionSummary],
  ["GET", /^\/api\/study\/sessions\/(\d+)\/questions$/, sessionQuestions],
  ["POST", /^\/api\/study\/questions$/, generateQuestions],
  ["POST", /^\/api\/study\/attempts$/, submitAttempt],
  ["POST", /^\/api\/study\/predictions$/, recordPrediction],
  ["POST", /^\/api\/study\/reflections$/, recordReflection],
  ["POST", /^\/api\/events\/batch$/, ingestEvents],
];

function sessionResponse() {
  return {
    authenticated: true,
    csrf_token: CSRF_TOKEN,
    user: {
      id: "e2e-learner",
      display_name: "E2E Learner",
      email: "e2e@example.test",
    },
    tenant: {
      org_id: "local",
      learning_path_id: String(LEARNING_PATH_ID),
      cohort_id: null,
      role: "student",
    },
    settings: {
      theme: "light",
      locale: "en",
      selected_learning_path_id: String(LEARNING_PATH_ID),
    },
  };
}

function pacingResponse() {
  return {
    reflection_min_seconds: Number(
      process.env.SOPHIA_FIXTURE_REFLECTION_SECONDS ?? 30,
    ),
    elaboration_min_chars: PACED_POLICY.min_elaboration_chars,
    prompt_min_dwell_ms: PACED_POLICY.min_prompt_dwell_ms,
  };
}

function listSessions() {
  return {
    learning_path_id: LEARNING_PATH_ID,
    sessions: [...state.sessions.values()],
  };
}

function sessionAttemptsFor(sessionId) {
  return [...state.attempts.values()].filter(
    (attempt) => attempt.session_id === sessionId,
  );
}

function startSession(_match, body) {
  const id = state.nextSessionId++;
  addSession(state.sessions, state.questions, {
    id,
    topic: body.topic ?? "Graphs",
    cards: 3,
    policy: PACED_POLICY,
  });
  return { session: state.sessions.get(id) };
}

function sessionQuestions(match) {
  const sessionId = Number(match[1]);
  ensureSession(sessionId);
  return {
    session_id: sessionId,
    learning_path_id: LEARNING_PATH_ID,
    questions: state.questions.get(sessionId) ?? [],
    attempted_question_ids: sessionAttemptsFor(sessionId).map(
      (attempt) => attempt.question_id,
    ),
  };
}

function generateQuestions(_match, body) {
  const sessionId = Number(body.session_id ?? 0);
  if (sessionId > 0) {
    ensureSession(sessionId);
  }
  const existing = state.questions.get(sessionId) ?? [];
  const template = existing[0] ?? (state.questions.get(1) ?? [])[0];
  const added = Array.from({ length: body.count ?? 3 }, (_unused, index) => ({
    ...template,
    id: `s${sessionId}-gen${existing.length + index}`,
    prompt: `Generated card ${existing.length + index + 1}.`,
  }));
  state.questions.set(sessionId, [...existing, ...added]);
  return {
    learning_path_id: LEARNING_PATH_ID,
    topic: body.topic ?? "Graphs",
    content_language: "en",
    questions: added,
  };
}

function submitAttempt(_match, body) {
  const key = `${body.session_id}:${body.request_id}`;
  const existing = state.attempts.get(key);
  if (existing) {
    return { attempt: existing };
  }

  const attempt = {
    id: state.attempts.size + 1,
    learning_path_id: LEARNING_PATH_ID,
    session_id: body.session_id,
    question_id: body.question_id,
    answer_text: body.answer_text,
    confidence: body.confidence ?? null,
    self_rating: body.self_rating,
    score: SELF_RATING_SCORES[body.self_rating] ?? 0,
    phase: body.phase ?? "practice",
    submitted_at: "2026-09-04T10:05:00Z",
  };
  state.attempts.set(key, attempt);
  return { attempt };
}

function recordPrediction(_match, body) {
  state.predictions.set(body.session_id, (body.rating - 1) / 4);
  return {
    prediction: {
      learning_path_id: LEARNING_PATH_ID,
      topic: body.topic,
      predicted: (body.rating - 1) / 4,
      rated_at: "2026-09-04T10:01:00Z",
    },
  };
}

function recordReflection(_match, body) {
  return {
    reflection: {
      id: 1,
      session_id: body.session_id,
      learning_path_id: LEARNING_PATH_ID,
      prompt: body.prompt,
      reflection_text: body.reflection_text,
      created_at: "2026-09-04T10:40:00Z",
    },
  };
}

function ingestEvents(_match, body) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    accepted: body.events?.length ?? 0,
    duplicate: 0,
  };
}

/** Mirrors the server: pre and post are the means of the phased attempts. */
function completeSession(match) {
  const sessionId = Number(match[1]);
  ensureSession(sessionId);
  const session = state.sessions.get(sessionId);
  if (!session) {
    return null;
  }
  session.pre_test_score = phaseMean(sessionId, "pre_test");
  session.post_test_score = phaseMean(sessionId, "post_test");
  session.completed_at = "2026-09-04T10:45:00Z";
  session.improvement =
    session.pre_test_score === null || session.post_test_score === null
      ? null
      : session.post_test_score - session.pre_test_score;
  return { session_id: sessionId, completed: true, session };
}

function sessionSummary(match) {
  const sessionId = Number(match[1]);
  ensureSession(sessionId);
  const session = state.sessions.get(sessionId);
  if (!session) {
    return null;
  }
  const predicted = state.predictions.get(sessionId) ?? null;
  const practice = phaseMean(sessionId, "practice");
  const measured = session.post_test_score ?? practice;
  return {
    session,
    attempts: {
      pre_test: phaseCount(sessionId, "pre_test"),
      practice: phaseCount(sessionId, "practice"),
      post_test: phaseCount(sessionId, "post_test"),
    },
    practice_score: practice,
    predicted,
    measured,
    calibration_delta:
      predicted === null || measured === null ? null : measured - predicted,
    band: band(predicted, measured),
    legacy_scored: false,
  };
}

function band(predicted, measured) {
  if (predicted === null || measured === null) {
    return "unknown";
  }
  const error = predicted - measured;
  if (Math.abs(error) <= 0.1) {
    return "well_calibrated";
  }
  return error > 0 ? "overconfident" : "underconfident";
}

function sessionAttempts(sessionId, phase) {
  return [...state.attempts.values()].filter(
    (attempt) => attempt.session_id === sessionId && attempt.phase === phase,
  );
}

function phaseCount(sessionId, phase) {
  return sessionAttempts(sessionId, phase).length;
}

function phaseMean(sessionId, phase) {
  const scores = sessionAttempts(sessionId, phase).map(
    (attempt) => attempt.score,
  );
  if (scores.length === 0) {
    return null;
  }
  return scores.reduce((total, score) => total + score, 0) / scores.length;
}

function streamEvents(response) {
  response.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache, no-transform",
    connection: "keep-alive",
  });
  response.write("event: heartbeat\ndata: {}\n\n");
  const heartbeat = setInterval(() => {
    response.write("event: heartbeat\ndata: {}\n\n");
  }, 1000);
  response.on("close", () => clearInterval(heartbeat));
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://127.0.0.1");

  if (
    request.method === "GET" &&
    /^\/api\/study\/\d+\/events$/.test(url.pathname)
  ) {
    streamEvents(response);
    return;
  }

  readBody(request).then((body) => {
    for (const [method, pattern, handler] of routes) {
      const match = pattern.exec(url.pathname);
      if (request.method === method && match) {
        const payload = handler(match, body, url);
        send(response, payload === null ? 404 : 200, payload ?? notFound());
        return;
      }
    }
    send(response, 404, notFound());
  });
});

function notFound() {
  return { detail: { code: "http.not_found", params: {} } };
}

function send(response, status, payload) {
  const serialized = JSON.stringify(payload);
  response.writeHead(status, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(serialized),
  });
  response.end(serialized);
}

async function readBody(request) {
  if (request.method === "GET" || request.method === "HEAD") {
    return {};
  }
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

server.listen(PORT, "127.0.0.1", () => {
  process.stdout.write(`fixture api listening on ${PORT}\n`);
});
