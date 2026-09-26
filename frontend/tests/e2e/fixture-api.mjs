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
/** A session whose generation failed: the predict route must be able to recover it. */
const EMPTY_SESSION_ID = 502;
/**
 * The sessions a spec walks through the predict route, whose pre-test is still
 * open. Every other seeded session starts with its anchor answered, because
 * the act route sends a session without a pre-test back to predict (#107) and
 * the specs that open act directly are measuring the cards, not that step.
 */
const PREDICT_WALK_SESSION_IDS = new Set([1, 13, 16]);

const MS_PER_DAY = 86_400_000;

/**
 * A fixed review schedule, expressed in days from now.
 *
 * Relative rather than absolute so the dashboard's week-ahead figure has the
 * same shape whenever the suite runs; the one long German compound is there
 * for the 320 px overflow gate.
 */
const REVIEW_TOPICS = [
  { topic: "Graphs", dayOffset: 0, isDue: true },
  { topic: "Sorting", dayOffset: 0, isDue: true },
  { topic: "Hashing", dayOffset: 2, isDue: false },
  { topic: "Dynamische Programmierungsaufgaben", dayOffset: 4, isDue: false },
];

/**
 * Calibration rows, including one the retired scorer touched.
 *
 * The dashboard has to keep that row out of its figure and say so, which it
 * can only be tested for against a fixture that has one.
 */
const CALIBRATION_RATINGS = [
  { topic: "Graphs", predicted: 0.9, actual: 0.4, legacy_scored: false },
  { topic: "Sorting", predicted: 0.5, actual: 0.6, legacy_scored: false },
  { topic: "Hashing", predicted: 0.8, actual: 1, legacy_scored: true },
  { topic: "Kombinatorik", predicted: 0.7, actual: null, legacy_scored: false },
];

const QUICKSTART_TOPICS = [
  "Graphs",
  "Sorting",
  "Dynamische Programmierungsaufgaben",
];

/**
 * The learning path is examined in German while the chrome stays English.
 *
 * That pairing is the whole point of the content-language contract, so the
 * fixture has to be the awkward case rather than the matching one.
 */
const CONTENT_LANGUAGE = "de";

const CONTENT_SOURCES = [
  {
    id: 12,
    external_ref: "series-12",
    title: "Algorithmen und Datenstrukturen",
  },
];

/** One finished item and one still in the pipeline, so both states render. */
const CONTENT_ITEMS = [
  {
    id: "item-1",
    title: "Graphen und Suchverfahren",
    download_status: "completed",
    skip_reason: null,
    transcription_status: "completed",
    index_status: "completed",
    sequence_number: 1,
    missed_at: null,
  },
  {
    id: "item-2",
    title: "Dynamische Programmierungsaufgaben",
    download_status: "completed",
    skip_reason: null,
    transcription_status: "pending",
    index_status: "pending",
    sequence_number: 2,
    missed_at: null,
  },
];

/**
 * Deadlines placed relative to the request, so the due phrases are fixed.
 *
 * The offsets are half-days on purpose. The relative phrase floors the elapsed
 * days, so a deadline exactly N days out sits on the boundary between two
 * phrasings and would flip on a slow machine; half a day past the boundary
 * pins each one to a single sentence.
 */
const DEADLINES = [
  {
    id: "dl-overdue",
    name: "Abgabe 1: Graphen",
    deadline_type: "assignment",
    // Floored, so a day and a half past reads as two days overdue.
    dayOffset: -1.5,
    grade_weight: 0.25,
    submission_status: "not_submitted",
  },
  {
    id: "dl-today",
    name: "Quiz 3",
    deadline_type: "quiz",
    dayOffset: 0.5,
    grade_weight: null,
    submission_status: null,
  },
  {
    id: "dl-week",
    name: "Pruefung: Dynamische Programmierungsaufgaben",
    deadline_type: "exam",
    dayOffset: 5.5,
    grade_weight: 0.5,
    submission_status: null,
  },
];

/** One reflected on and one not, so both history outcomes render. */
const PAST_DEADLINES = [
  {
    id: "past-reflected",
    name: "Abgabe 0: Sortieren",
    deadline_type: "assignment",
    dayOffset: -12.5,
    grade_weight: 0.1,
    submission_status: "submitted",
    reflected: true,
  },
  {
    id: "past-missed",
    name: "Kreuzerlübung 2",
    deadline_type: "checkmark",
    dayOffset: -20.5,
    grade_weight: null,
    submission_status: null,
    reflected: false,
  },
];

/** One domain with enough finished deadlines to read, one without. */
const EFFORT_CALIBRATION = [
  {
    domain: "assignment",
    sample_count: 4,
    mean_error: 1.25,
    mean_absolute_error: 1.5,
  },
  {
    domain: "exam",
    sample_count: 1,
    mean_error: -0.5,
    mean_absolute_error: 0.5,
  },
];

const TISS_SEMESTER = "2026W";
const TISS_COURSE_NUMBER = "123.ABC";

const TISS_FAVORITES = [
  {
    course_number: TISS_COURSE_NUMBER,
    title: "Algorithmen und Datenstrukturen",
    course_type: "VU",
    semester: TISS_SEMESTER,
    hours: 4,
    ects: 6,
    lva_registered: true,
    group_registered: false,
    exam_registered: false,
  },
];

const TISS_GROUPS = [
  {
    group_id: "grp-1",
    name: "Gruppe A",
    day: "Mo",
    time_start: "10:00",
    time_end: "12:00",
    location: "Freihaus HS 1",
    capacity: 30,
    enrolled: 12,
    status: "open",
  },
  {
    group_id: "grp-2",
    name: "Gruppe B",
    day: "Do",
    time_start: "14:00",
    time_end: "16:00",
    location: "Freihaus HS 2",
    capacity: 30,
    enrolled: 30,
    status: "full",
  },
];

/**
 * Search answers, keyed by what the page asks for.
 *
 * `nichts` returns nothing so the empty state is reachable, and any other
 * query returns the same two passages: the debounce and out-of-order tests
 * care about how many requests arrive and in what order, not about relevance.
 */
const SEARCH_RESULTS = [
  {
    content_item_id: "item-1",
    title: "Graphen und Suchverfahren",
    chunk_text: "Ein Graph besteht aus Knoten und Kanten.",
    start_time: 65,
    end_time: 128,
    score: 0.82,
    source: "transcript",
  },
  {
    content_item_id: "item-2",
    title: "Dynamische Programmierungsaufgaben",
    chunk_text: "Teilprobleme werden einmal geloest und wiederverwendet.",
    start_time: 3725,
    end_time: 3800,
    score: 0.51,
    source: "document",
  },
];

/** Requests the fixture is asked to fail, so error states are reachable. */
const FAIL_COOKIE = "sophia-e2e-fail";

const CATALOG_TOPICS = [
  { topic: "Graphs", source: "transcript" },
  { topic: "Sorting", source: "quiz" },
  { topic: "Dynamische Programmierungsaufgaben", source: "manual" },
];

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
function deckSizeFor(id) {
  if (id === EXTEND_SESSION_ID) {
    return EXTEND_DECK_SIZE;
  }
  return id === EMPTY_SESSION_ID ? 0 : DEFAULT_DECK_SIZE;
}

function ensureSession(id) {
  if (state.sessions.has(id)) {
    return;
  }
  const paced = id < PACED_SESSION_LIMIT;
  addSession(state.sessions, state.questions, {
    id,
    topic: paced ? "Graphs" : "Latency",
    cards: deckSizeFor(id),
    policy: paced ? PACED_POLICY : UNGATED_POLICY,
  });
  const anchor = state.questions.get(id)?.[0];
  if (anchor && !PREDICT_WALK_SESSION_IDS.has(id)) {
    submitAttempt(null, {
      session_id: id,
      request_id: "seeded-pre-test",
      question_id: anchor.id,
      answer_text: "Answered on the predict route before this spec began.",
      self_rating: 2,
      phase: "pre_test",
    });
  }
}

function buildQuestion({ id, sessionId, topic, position, policy }) {
  return {
    id,
    kind: "open_response",
    topic,
    prompt: `Card ${position + 1}: explain ${topic} in your own words.`,
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
      // What the card reveals. Shaped like a lecture chunk the real generator
      // records: located by episode and time, carrying the transcript text.
      source_spans: [
        {
          content_item_id: "fixture-episode",
          start_char: null,
          end_char: null,
          start_ms: 12_500,
          end_ms: 27_000,
          excerpt: `In the lecture on ${topic}, the worked example traces each step before generalising it.`,
        },
      ],
    },
    engagement_policy: policy,
    session_id: sessionId,
  };
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
    Array.from({ length: cards }, (_unused, index) =>
      buildQuestion({
        id: `s${id}-q${index}`,
        sessionId: id,
        topic,
        position: index,
        policy,
      }),
    ),
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
  ["GET", /^\/api\/review\/due$/, dueReviews],
  ["GET", /^\/api\/review\/upcoming$/, upcomingReviews],
  ["POST", /^\/api\/review\/complete$/, completeReview],
  ["GET", /^\/api\/calibration\/ratings$/, calibrationRatings],
  ["GET", /^\/api\/quickstart\/overview$/, quickstartOverview],
  ["POST", /^\/api\/quickstart\/manual-topics$/, saveManualTopics],
  ["POST", /^\/api\/quickstart\/confidence$/, saveConfidence],
  ["GET", /^\/api\/content-sources$/, listContentSources],
  ["POST", /^\/api\/content-sources\/discover$/, discoverContentSources],
  ["GET", /^\/api\/content-sources\/(\d+)\/content-items$/, listContentItems],
  ["GET", /^\/api\/learning-paths\/(\d+)\/topics$/, listTopics],
  [
    "GET",
    /^\/api\/learning-paths\/(\d+)\/topics\/confidence$/,
    listTopicConfidence,
  ],
  [
    "GET",
    /^\/api\/learning-paths\/(\d+)\/content-language$/,
    readContentLanguage,
  ],
  ["POST", /^\/api\/search$/, searchContent],
  ["GET", /^\/api\/deadlines$/, listDeadlines],
  ["GET", /^\/api\/deadlines\/workload$/, deadlineWorkload],
  ["POST", /^\/api\/deadlines\/sync$/, syncDeadlines],
  ["POST", /^\/api\/deadlines\/([^/]+)\/complete$/, completeDeadline],
  ["GET", /^\/api\/deadline-history$/, listPastDeadlines],
  ["GET", /^\/api\/deadline-history\/calibration$/, effortCalibration],
  ["GET", /^\/api\/deadline-history\/([^/]+)\/reflection$/, deadlineReflection],
  [
    "GET",
    /^\/api\/integrations\/tiss\/registration\/favorites$/,
    tissFavorites,
  ],
  [
    "GET",
    /^\/api\/integrations\/tiss\/registration\/targets\/([^/]+)$/,
    tissTarget,
  ],
  [
    "GET",
    /^\/api\/integrations\/tiss\/registration\/targets\/([^/]+)\/groups$/,
    tissGroups,
  ],
  [
    "GET",
    /^\/api\/integrations\/tiss\/registration\/targets\/([^/]+)\/exam-dates$/,
    tissExamDates,
  ],
  ["POST", /^\/api\/integrations\/tiss\/registration\/attempts$/, tissAttempt],
];

function deadlineResponse(entry) {
  return {
    id: entry.id,
    name: entry.name,
    learning_path_id: LEARNING_PATH_ID,
    learning_path_name: "Algorithmen und Datenstrukturen",
    deadline_type: entry.deadline_type,
    due_at: new Date(Date.now() + entry.dayOffset * MS_PER_DAY).toISOString(),
    grade_weight: entry.grade_weight,
    submission_status: entry.submission_status,
    url: null,
    extra: {},
  };
}

function listDeadlines(_match, _body, url) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    horizon_days: Number(url?.searchParams.get("horizon_days") ?? 14),
    deadlines: DEADLINES.map(deadlineResponse),
  };
}

function deadlineWorkload(_match, _body, url) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    horizon_days: Number(url?.searchParams.get("horizon_days") ?? 14),
    total_estimated_hours: 9.5,
    total_tracked_hours: 4,
    remaining_hours: 5.5,
    deadline_count: DEADLINES.length,
    per_day: [],
  };
}

function syncDeadlines() {
  return {
    synced_count: DEADLINES.length,
    deadlines: DEADLINES.map(deadlineResponse),
  };
}

function completeDeadline(match) {
  return {
    deadline_id: match[1],
    predicted_hours: 3,
    actual_hours: 4,
    feedback: "Vier Stunden statt drei.",
    completed: true,
  };
}

function listPastDeadlines(_match, _body, url) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    limit: Number(url?.searchParams.get("limit") ?? 50),
    deadlines: PAST_DEADLINES.map(deadlineResponse),
  };
}

function effortCalibration() {
  return { learning_path_id: LEARNING_PATH_ID, metrics: EFFORT_CALIBRATION };
}

/**
 * 404 for a deadline nobody reflected on, which is what the real route does.
 *
 * The history surface classifies an outcome from exactly this distinction, so
 * a fixture that answered 200 for everything would make every past deadline
 * look reflected on and the outcome filter untestable.
 */
function deadlineReflection(match) {
  const past = PAST_DEADLINES.find((entry) => entry.id === match[1]);
  if (!past?.reflected) {
    return null;
  }
  return {
    deadline_id: match[1],
    reflection: {
      predicted_hours: 3,
      actual_hours: 4.5,
      reflection_text: "Die Beispiele haben laenger gedauert als gedacht.",
      reflected_at: "2026-09-01T10:00:00Z",
    },
  };
}

function searchContent(_match, body) {
  const query = String(body.query ?? "");
  return {
    results: query.toLowerCase().includes("nichts") ? [] : SEARCH_RESULTS,
  };
}

function tissConnection(url) {
  return url?.searchParams.get("connection") ?? "connected";
}

function tissFavorites(_match, _body, url) {
  return {
    connection: tissConnection(url),
    semester: TISS_SEMESTER,
    favorites: TISS_FAVORITES,
  };
}

function tissTarget(match) {
  return {
    connection: "connected",
    course_number: match[1],
    semester: TISS_SEMESTER,
    target: {
      course_number: match[1],
      semester: TISS_SEMESTER,
      registration_type: "group",
      title: "Algorithmen und Datenstrukturen",
      // Far enough out that the countdown never flips to "open" mid-run.
      registration_start: "31.12.2099 08:00",
      registration_end: "31.12.2099 20:00",
      status: "open",
      groups: TISS_GROUPS,
    },
  };
}

function tissGroups(match) {
  return {
    connection: "connected",
    course_number: match[1],
    semester: TISS_SEMESTER,
    groups: TISS_GROUPS,
  };
}

function tissExamDates(match) {
  return {
    course_number: match[1],
    exams: [
      {
        exam_id: "exam-1",
        course_number: match[1],
        title: "1. Pruefungstermin",
        date_start: "15.01.2027 09:00",
        date_end: "15.01.2027 11:00",
        registration_start: "01.12.2026 08:00",
        registration_end: "10.01.2027 23:59",
        mode: "written",
      },
    ],
  };
}

/**
 * Refuses the full group and accepts the open one.
 *
 * The refusal is a 200 carrying `success: false`, not an HTTP error: TISS
 * answering "that group is full" is a successful call, and a surface that
 * rendered it as a transport failure would tell the learner to try again.
 */
function tissAttempt(_match, body) {
  const group = TISS_GROUPS.find((entry) => entry.group_id === body.group_id);
  const success = group?.status === "open";
  return {
    connection: "connected",
    course_number: body.course_number,
    semester: TISS_SEMESTER,
    result: {
      course_number: body.course_number,
      registration_type: "group",
      success,
      group_name: group?.name ?? "",
      message: success ? "Platz in Gruppe A erhalten" : "Gruppe ist voll",
      attempted_at: "2026-09-12T10:00:00Z",
    },
  };
}

/**
 * Which upstream call this run wants to fail, carried by a cookie.
 *
 * The frontend forwards the browser's cookie header to the API verbatim, so a
 * cookie is the only channel a Playwright test has into this process. Every
 * migrated surface has an error state that is otherwise unreachable from a
 * fixture that always succeeds.
 */
function failedPath(request, pathname) {
  const cookies = request.headers.cookie ?? "";
  const match = new RegExp(`${FAIL_COOKIE}=([^;]+)`).exec(cookies);
  const target = match?.[1] ? decodeURIComponent(match[1]) : "";
  return target !== "" && pathname.includes(target);
}

function listContentSources() {
  return { sources: CONTENT_SOURCES };
}

function discoverContentSources() {
  return {
    sources: [
      {
        id: 12,
        title: "Vorlesungsaufzeichnungen",
        learning_path_title: "Algorithmen und Datenstrukturen",
        learning_path_short_title: "AlgoDat",
        content_item_count: CONTENT_ITEMS.length,
      },
    ],
  };
}

function listContentItems(match) {
  return {
    content_source_id: Number(match[1]),
    items: CONTENT_ITEMS,
  };
}

function catalogTopic({ topic, source }) {
  return {
    topic,
    learning_path_id: LEARNING_PATH_ID,
    source,
    frequency: 2,
  };
}

function listTopics(match) {
  return {
    learning_path_id: Number(match[1]),
    topics: CATALOG_TOPICS.map(catalogTopic),
  };
}

/** Only the first topic is rated, so the unrated filter has something to find. */
function listTopicConfidence(match) {
  return {
    learning_path_id: Number(match[1]),
    ratings: [
      {
        topic: CATALOG_TOPICS[0].topic,
        learning_path_id: LEARNING_PATH_ID,
        predicted: 0.9,
        actual: null,
        rated_at: "2026-09-04T10:00:00Z",
        calibration_error: null,
        is_blind_spot: false,
      },
    ],
  };
}

/**
 * Mirrors the server's fallback ladder: an explicit `?lang=` wins, otherwise
 * the learning path's own language answers. The UI locale is never consulted,
 * here or there.
 */
function readContentLanguage(match, _body, url) {
  const override = url?.searchParams.get("lang");
  const language = override === "de" || override === "en" ? override : null;
  return {
    learning_path_id: Number(match[1]),
    content_language: language ?? CONTENT_LANGUAGE,
    resolved_from: language === null ? "learning_path" : "override",
    available_translations: [],
  };
}

function reviewSchedule({ topic, dayOffset, isDue }) {
  return {
    topic,
    learning_path_id: LEARNING_PATH_ID,
    interval_index: 1,
    interval_days: Math.max(dayOffset, 1),
    last_reviewed_at: null,
    next_review_at: new Date(Date.now() + dayOffset * MS_PER_DAY).toISOString(),
    score_at_last_review: null,
    difficulty: 0.3,
    stability: 1.5,
    review_count: 1,
    is_due: isDue,
  };
}

function dueReviews() {
  return {
    learning_path_id: LEARNING_PATH_ID,
    reviews: REVIEW_TOPICS.filter((entry) => entry.isDue).map(reviewSchedule),
  };
}

function upcomingReviews(_match, _body, url) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    days_ahead: Number(url?.searchParams.get("days_ahead") ?? 3),
    reviews: REVIEW_TOPICS.map(reviewSchedule),
  };
}

/**
 * Mirrors the server: the surface sends the button that was pressed and the
 * schedule comes back. Nothing about the next date is computed in the browser,
 * so nothing about it is asserted there either.
 */
function completeReview(_match, body) {
  return {
    schedule: reviewSchedule({
      topic: body.topic ?? "Graphs",
      dayOffset: (body.self_rating ?? 1) + 1,
      isDue: false,
    }),
  };
}

function calibrationRatings() {
  return {
    learning_path_id: LEARNING_PATH_ID,
    ratings: CALIBRATION_RATINGS.map((rating) => ({
      ...rating,
      learning_path_id: LEARNING_PATH_ID,
      rated_at: "2026-09-04T10:00:00Z",
      calibration_error:
        rating.actual === null ? null : rating.predicted - rating.actual,
      is_blind_spot:
        rating.actual !== null && rating.predicted - rating.actual > 0.2,
      difficulty_level: "transfer",
    })),
  };
}

function quickstartTopic(topic) {
  return {
    topic,
    learning_path_id: LEARNING_PATH_ID,
    source: "transcript",
    frequency: 2,
  };
}

function quickstartOverview() {
  return {
    learning_path_id: LEARNING_PATH_ID,
    learning_paths: [
      {
        id: LEARNING_PATH_ID,
        title: "Algorithmen und Datenstrukturen",
        short_title: "AlgoDat",
        url: null,
      },
    ],
    topics: QUICKSTART_TOPICS.map(quickstartTopic),
    nearest_deadline: null,
    completed_session_count: 2,
  };
}

function saveManualTopics(_match, body) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    topics: (body.topics ?? []).map(quickstartTopic),
  };
}

function saveConfidence(_match, body) {
  return {
    learning_path_id: LEARNING_PATH_ID,
    saved_count: Object.keys(body.ratings ?? {}).length,
  };
}

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
  const topic = body.topic ?? "Graphs";
  // Built from scratch rather than cloned from an existing card: a session
  // that never had one is exactly the case the recovery path exists for.
  const policy =
    existing[0]?.engagement_policy ??
    (sessionId < PACED_SESSION_LIMIT ? PACED_POLICY : UNGATED_POLICY);
  const added = Array.from({ length: body.count ?? 3 }, (_unused, index) =>
    buildQuestion({
      id: `s${sessionId}-gen${existing.length + index}`,
      sessionId,
      topic,
      position: existing.length + index,
      policy,
    }),
  );
  state.questions.set(sessionId, [...existing, ...added]);
  return {
    learning_path_id: LEARNING_PATH_ID,
    topic,
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

/**
 * The one multipart route, kept out of the JSON table.
 *
 * Everything else here answers a JSON body; this answers a `multipart/form-data`
 * one, and the shared reader would only ever see an unparseable string. The
 * fields are read out of the raw body with a regex rather than a real parser:
 * the fixture only has to prove the browser's own form post reaches the API
 * intact, which is what the no-JavaScript upload path rests on.
 */
function acceptUpload(raw) {
  const title = /name="title"\r?\n\r?\n([\s\S]*?)\r?\n--/.exec(raw)?.[1] ?? "";
  const filename = /name="file"; filename="([^"]*)"/.exec(raw)?.[1] ?? "";
  if (!title.trim() || !filename) {
    return { reason: "file_required" };
  }
  // The one check worth mirroring from the real boundary: the part body has
  // to start the way its extension claims. Without it the browser suite could
  // not tell an accepted upload from a disguised one, because the client-side
  // pre-check never sees the bytes.
  const body =
    /name="file";[^\r\n]*\r?\n(?:[^\r\n]+\r?\n)*\r?\n([\s\S]*?)\r?\n--/.exec(
      raw,
    )?.[1];
  if (!body?.startsWith("%PDF-")) {
    return { reason: "content_mismatch" };
  }
  return {
    accepted: {
      id: "e2e-upload-1",
      title: title.trim(),
      media_type: "application/pdf",
      byte_size: Buffer.byteLength(raw),
      state: "queued",
    },
  };
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

  if (
    request.method === "POST" &&
    url.pathname === "/api/content-sources/uploads"
  ) {
    readRawBody(request).then((raw) => {
      const result = acceptUpload(raw);
      if (result.reason) {
        send(response, 422, {
          detail: {
            code: "content.upload_rejected",
            params: { reason: result.reason },
          },
        });
        return;
      }
      send(response, 201, result.accepted);
    });
    return;
  }

  if (failedPath(request, url.pathname)) {
    send(response, 503, {
      detail: { code: "http.unavailable", params: {} },
    });
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

async function readRawBody(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function readBody(request) {
  if (request.method === "GET" || request.method === "HEAD") {
    return {};
  }
  const raw = await readRawBody(request);
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
