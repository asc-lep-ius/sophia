"""Study session page — 5-step stepper with adaptive difficulty."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final

import structlog
from nicegui import app, ui

from sophia.domain.models import DifficultyLevel
from sophia.gui.components.confidence_rating import confidence_rating
from sophia.gui.components.flashcard import flashcard
from sophia.gui.components.loading import loading_spinner, skeleton_card
from sophia.gui.components.math_input import math_input
from sophia.gui.services.study_service import (
    check_novel_topic,
    complete_session,
    compute_score,
    finalize_calibration,
    format_improvement,
    get_posttest_questions,
    get_pretest_questions,
    get_study_material,
    save_study_flashcard,
    select_interleave_topics,
    start_session,
)
from sophia.gui.state.session_store import SessionState, SessionStore
from sophia.gui.state.storage_map import GENERAL_APP_CONTAINER
from sophia.gui.state.study_state import (
    get_active_topic as _get_active_topic,
)
from sophia.gui.state.study_state import (
    get_course_id as _get_course_id,
)
from sophia.gui.state.study_state import (
    get_insight as _get_insight,
)
from sophia.gui.state.study_state import (
    get_interleaved as _get_interleaved,
)
from sophia.gui.state.study_state import (
    get_novel_topic as _get_novel_topic,
)
from sophia.gui.state.study_state import (
    get_post_answers as _get_post_answers,
)
from sophia.gui.state.study_state import (
    get_post_confidence as _get_post_confidence,
)
from sophia.gui.state.study_state import (
    get_pre_answers as _get_pre_answers,
)
from sophia.gui.state.study_state import (
    get_pre_confidence as _get_pre_confidence,
)
from sophia.gui.state.study_state import (
    get_reflection as _get_reflection,
)
from sophia.gui.state.study_state import (
    get_session_id as _get_session_id,
)
from sophia.gui.state.study_state import (
    get_session_ids as _get_session_ids,
)
from sophia.gui.state.study_state import (
    get_step_index as _get_step_index,
)
from sophia.gui.state.study_state import (
    get_timer_remaining as _get_timer_remaining,
)
from sophia.gui.state.study_state import (
    get_topics as _get_topics,
)
from sophia.gui.state.study_state import (
    reset_session_state as _reset_session_state,
)
from sophia.gui.state.study_state import (
    set_insight as _set_insight,
)
from sophia.gui.state.study_state import (
    set_interleaved as _set_interleaved,
)
from sophia.gui.state.study_state import (
    set_novel_topic as _set_novel_topic,
)
from sophia.gui.state.study_state import (
    set_post_answers as _set_post_answers,
)
from sophia.gui.state.study_state import (
    set_post_confidence as _set_post_confidence,
)
from sophia.gui.state.study_state import (
    set_pre_answers as _set_pre_answers,
)
from sophia.gui.state.study_state import (
    set_pre_confidence as _set_pre_confidence,
)
from sophia.gui.state.study_state import (
    set_reflection as _set_reflection,
)
from sophia.gui.state.study_state import (
    set_session_id as _set_session_id,
)
from sophia.gui.state.study_state import (
    set_session_ids as _set_session_ids,
)
from sophia.gui.state.study_state import (
    set_step_index as _set_step_index,
)
from sophia.gui.state.study_state import (
    set_timer_remaining as _set_timer_remaining,
)
from sophia.gui.state.study_state import (
    set_topics as _set_topics,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# --- Constants ---------------------------------------------------------------

_AUTOSAVE_INTERVAL_SECONDS: Final = 10
_PRETEST_COUNT: Final = 3
_POSTTEST_COUNT: Final = 3
_MIN_INTERLEAVE_TOPICS: Final = 2
_MAX_INTERLEAVE_TOPICS: Final = 4

_DIFFICULTY_BADGE_COLORS: Final[dict[DifficultyLevel, str]] = {
    DifficultyLevel.CUED: "red",
    DifficultyLevel.EXPLAIN: "orange",
    DifficultyLevel.TRANSFER: "green",
}

_METACOGNITIVE_PROMPTS: Final = [
    "Which question was hardest?",
    "Where were you uncertain?",
    "What will you review?",
]

_STEP_LABELS: Final = [
    "Pre-Test",
    "Study",
    "Post-Test",
    "Reflection",
    "Flashcards",
]


def _questions_complete(answers: dict[str, str], confidence: dict[str, int], *, count: int) -> bool:
    """All questions answered (non-blank) and confidence-rated."""
    if count == 0:
        return True
    for i in range(count):
        key = str(i)
        if key not in answers or not answers[key].strip():
            return False
        if key not in confidence:
            return False
    return True


def _build_session_id(course_id: int, topics: list[str], *, interleaved: bool) -> str:
    """Deterministic session ID — single topic or interleaved hash."""
    if not interleaved:
        return f"{course_id}:{topics[0]}"
    digest = hashlib.sha256(":".join(sorted(topics)).encode()).hexdigest()[:12]
    return f"{course_id}:interleaved:{digest}"


def _render_difficulty_badge(difficulty: DifficultyLevel) -> None:
    color = _DIFFICULTY_BADGE_COLORS[difficulty]
    ui.badge(difficulty.value.upper(), color=color).classes("text-xs")


def study_content() -> None:
    """Main study page entry point — called by app_shell + error_boundary."""
    _render_header()
    _study_session()  # pyright: ignore[reportUnusedCoroutine]


def _render_header() -> None:
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Study Session").classes("text-2xl font-bold")

        def _toggle_interleaved(e: object) -> None:
            _set_interleaved(not _get_interleaved())
            _study_session.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

        ui.switch("Interleaved Mode", value=_get_interleaved(), on_change=_toggle_interleaved)


def _render_resume_prompt(
    session_id: str,
    state: SessionState,
    *,
    on_resume: object,
    on_discard: object,
) -> None:
    with ui.card().classes("w-full max-w-lg mx-auto p-6"):
        ui.label("Resume Session?").classes("text-xl font-bold")
        step_display = state.step_index + 1
        ui.label(f"In-progress session for '{state.topic}' (step {step_display}/5).")
        with ui.row().classes("mt-4 gap-2"):
            ui.button("Resume", on_click=on_resume).props("color=primary")  # pyright: ignore[reportArgumentType]
            ui.button("Start Fresh", on_click=on_discard).props("color=negative outline")  # pyright: ignore[reportArgumentType]


# --- Core session stepper ----------------------------------------------------


@ui.refreshable  # type: ignore[misc]
async def _study_session() -> None:
    """Fetch data and render the 5-step study stepper."""
    container: AppContainer | None = app.storage.general.get(GENERAL_APP_CONTAINER)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAssignmentType]
    if not container:
        loading_spinner(text="Connecting...")
        return

    course_id = _get_course_id()
    topic = _get_active_topic()
    if not course_id or not topic:
        with ui.column().classes("w-full items-center py-12"):
            ui.icon("school", color="gray").classes("text-6xl")
            ui.label("Select a course and topic first.").classes("text-gray-500 mt-4")
            ui.link("Dashboard", "/").classes("mt-2")
        return

    interleaved = _get_interleaved()

    # Resolve topics
    if interleaved:
        try:
            available = await select_interleave_topics(container, course_id)  # pyright: ignore[reportUnknownArgumentType]
        except Exception:
            log.exception("interleave_topic_fetch_failed")
            available = [topic]
        if len(available) < _MIN_INTERLEAVE_TOPICS:
            available = [topic]
            _set_interleaved(False)
            interleaved = False
    else:
        available = [topic]

    topics = _get_topics() or available
    if topics != _get_topics():
        _set_topics(topics)

    session_id = _build_session_id(course_id, topics, interleaved=interleaved)

    # Check for existing session to resume
    store = SessionStore(app.storage.user)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    existing = store.load_state(session_id)
    if existing and not _get_session_id():

        def _resume() -> None:
            _set_session_id(session_id)
            _set_step_index(existing.step_index)
            _study_session.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

        def _discard() -> None:
            store.discard_session(session_id)
            _reset_session_state()
            _set_session_id(session_id)
            _study_session.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

        _render_resume_prompt(session_id, existing, on_resume=_resume, on_discard=_discard)
        return

    # Ensure session_id is set
    if not _get_session_id():
        _set_session_id(session_id)

    # Start backend session if at step 0 with no DB session yet
    step = _get_step_index()
    try:
        if step == 0 and not existing:
            session_ids: dict[str, int] = {}
            for t in topics:
                sess = await start_session(container, course_id, t)  # pyright: ignore[reportUnknownArgumentType]
                session_ids[t] = sess.id
            _set_session_ids(session_ids)
    except Exception:
        log.exception("session_start_failed", course_id=course_id, topics=topics)

    # Autosave timer
    def _autosave() -> None:
        _save_current_state(store, session_id, course_id, topics, interleaved)

    ui.timer(_AUTOSAVE_INTERVAL_SECONDS, _autosave)

    # Render stepper
    try:
        await _render_stepper(container, course_id, topics, interleaved)  # pyright: ignore[reportUnknownArgumentType]
    except Exception:
        log.exception("study_session_render_failed")
        skeleton_card()


def _save_current_state(
    store: SessionStore,
    session_id: str,
    course_id: int,
    topics: list[str],
    interleaved: bool,
) -> None:
    """Serialize current tab state into session store."""
    pre_answers = {f"pre_{k}": v for k, v in _get_pre_answers().items()}
    post_answers = {f"post_{k}": v for k, v in _get_post_answers().items()}
    post_score = _compute_post_score(topics) if _get_step_index() >= 3 else None
    state = SessionState(
        topic=topics[0],
        course_id=course_id,
        mode="interleaved" if interleaved else "single",
        step_index=_get_step_index(),
        answers={**pre_answers, **post_answers},
        pre_test_score=_compute_pre_score(topics),
        post_test_score=post_score,
    )
    store.save_state(session_id, state)


def _compute_pre_score(topics: list[str]) -> float | None:
    """Compute pre-test score if answers exist, else None."""
    answers = _get_pre_answers()
    if not answers:
        return None
    count = len(topics) * _PRETEST_COUNT
    return compute_score(answers, [""] * count)


def _compute_post_score(topics: list[str]) -> float | None:
    """Compute post-test score if answers exist, else None."""
    answers = _get_post_answers()
    if not answers:
        return None
    count = len(topics) * _POSTTEST_COUNT
    return compute_score(answers, [""] * count)


async def _render_stepper(
    container: AppContainer,
    course_id: int,
    topics: list[str],
    interleaved: bool,
) -> None:
    step = _get_step_index()

    # Aria-live step announcer for screen readers
    step_announcer = (
        ui.label(f"Step {step + 1} of {len(_STEP_LABELS)}: {_STEP_LABELS[step]}")
        .classes("sr-only")
        .props('aria-live="polite"')
    )

    with ui.stepper().props("header-nav=false").classes("w-full") as stepper:
        with ui.step(_STEP_LABELS[0]):
            await _render_pretest(stepper, container, course_id, topics)
        with ui.step(_STEP_LABELS[1]):
            await _render_study_phase(stepper, container, course_id, topics)
        with ui.step(_STEP_LABELS[2]):
            await _render_posttest(stepper, container, course_id, topics)
        with ui.step(_STEP_LABELS[3]):
            _render_reflection(stepper)
        with ui.step(_STEP_LABELS[4]):
            await _render_flashcard_step(stepper, container, course_id, topics, interleaved)

    # Advance stepper to current step (NiceGUI steppers default to step 0)
    for _ in range(step):
        stepper.next()

    # Ctrl+Enter keyboard shortcut to advance step
    def _on_ctrl_enter(e: object) -> None:
        key = getattr(e, "key", "")
        action = getattr(e, "action", False)
        modifiers = getattr(e, "modifiers", None) or {}  # pyright: ignore[reportUnknownVariableType]
        if action and key == "Enter" and getattr(modifiers, "ctrl", False):  # pyright: ignore[reportUnknownArgumentType]
            current = _get_step_index()
            if current < len(_STEP_LABELS) - 1:
                if not _can_advance_from_step(current, num_topics=len(topics)):
                    ui.notify("Complete the current step first", type="warning")
                    return
                _advance_step(stepper, current + 1)
                step_announcer.text = (
                    f"Step {current + 2} of {len(_STEP_LABELS)}: {_STEP_LABELS[current + 1]}"
                )

    ui.keyboard(on_key=_on_ctrl_enter)


# --- Step renderers ----------------------------------------------------------


async def _render_pretest(
    stepper: ui.stepper,
    container: AppContainer,
    course_id: int,
    topics: list[str],
) -> None:
    all_questions: list[tuple[str, str, DifficultyLevel]] = []
    for t in topics:
        try:
            questions, difficulty = await get_pretest_questions(
                container,
                course_id,
                t,
                count=_PRETEST_COUNT,
            )
        except Exception:
            log.exception("pretest_fetch_failed", topic=t)
            questions, difficulty = [f"Explain {t}"] * _PRETEST_COUNT, DifficultyLevel.EXPLAIN
        if _get_novel_topic():
            difficulty = DifficultyLevel.CUED
        for q in questions:
            all_questions.append((t, q, difficulty))

    # Novel topic check (only for single-topic mode)
    if len(topics) == 1:
        try:
            is_novel = await check_novel_topic(container, course_id, topics[0])
        except Exception:
            log.exception("novel_check_failed", topic=topics[0])
            is_novel = False
        if is_novel:

            def _mark_novel() -> None:
                _set_novel_topic(True)
                log.info("novel_topic_marked", topic=topics[0], course_id=course_id)

            ui.button(
                "I haven't encountered this yet",
                on_click=_mark_novel,
                icon="new_releases",
            ).props("outline color=warning").classes("mb-4")

    answers = _get_pre_answers()
    conf = _get_pre_confidence()
    total = len(all_questions)

    for idx, (topic_name, question, difficulty) in enumerate(all_questions):
        key = str(idx)
        with ui.card().classes("w-full p-4 mb-2"):
            with ui.row().classes("items-center gap-2 mb-2"):
                _render_difficulty_badge(difficulty)
                if len(topics) > 1:
                    ui.badge(topic_name).classes("text-xs")
            ui.markdown(question)

            def _make_answer_handler(k: str) -> Callable[[str], None]:
                def _on_change(text: str) -> None:
                    a = _get_pre_answers()
                    a[k] = text
                    _set_pre_answers(a)

                return _on_change

            math_input(
                value=answers.get(key, ""),
                label=f"Answer {idx + 1}",
                on_change=_make_answer_handler(key),
            )

            def _make_confidence_handler(k: str) -> Callable[[int], None]:
                def _on_rate(rating: int) -> None:
                    c = _get_pre_confidence()
                    c[k] = rating
                    _set_pre_confidence(c)

                return _on_rate

            confidence_rating(on_rate=_make_confidence_handler(key))

    # Score display + next button
    complete = _questions_complete(answers, conf, count=total)
    if complete and total > 0:
        score = compute_score(answers, [q for _, q, _ in all_questions])
        ui.label(f"Pre-test score: {score:.0%}").classes("text-lg font-bold mt-4")

    with ui.stepper_navigation():
        ui.button("Next", on_click=lambda: _advance_step(stepper, 1)).props(
            "color=primary" + ("" if complete else " disable"),
        ).bind_enabled_from(
            target_object={"v": complete},
            target_name="v",
        ) if not complete else ui.button(
            "Next",
            on_click=lambda: _advance_step(stepper, 1),
        ).props("color=primary")


async def _render_study_phase(
    stepper: ui.stepper,
    container: AppContainer,
    course_id: int,
    topics: list[str],
) -> None:
    is_novel = _get_novel_topic()
    for t in topics:
        try:
            material = await get_study_material(container, course_id, t)
        except Exception:
            log.exception("study_material_fetch_failed", topic=t)
            material = f"*Could not load material for {t}.*"
        if len(topics) > 1:
            ui.label(t).classes("text-xl font-bold mt-4 mb-2")
        if is_novel:
            _render_difficulty_badge(DifficultyLevel.CUED)
        ui.markdown(material).classes("w-full")

    ui.label("What was the key insight?").classes("text-lg font-semibold mt-6")

    def _on_insight_change(text: str) -> None:
        _set_insight(text)

    insight = _get_insight()
    ui.textarea(
        value=insight,
        label="Key insight",
        on_change=lambda e: _on_insight_change(e.value),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    ).classes("w-full")

    has_insight = bool(insight.strip()) if insight else False

    with ui.stepper_navigation():
        ui.button("Back", on_click=lambda: _retreat_step(stepper, 0)).props("flat")
        if has_insight:
            ui.button("Next", on_click=lambda: _advance_step(stepper, 2)).props("color=primary")
        else:
            ui.button("Next").props("color=primary disable")


async def _render_posttest(
    stepper: ui.stepper,
    container: AppContainer,
    course_id: int,
    topics: list[str],
) -> None:
    all_questions: list[tuple[str, str, DifficultyLevel]] = []
    for t in topics:
        try:
            questions, difficulty = await get_posttest_questions(
                container,
                course_id,
                t,
                count=_POSTTEST_COUNT,
            )
        except Exception:
            log.exception("posttest_fetch_failed", topic=t)
            questions, difficulty = [f"Explain {t}"] * _POSTTEST_COUNT, DifficultyLevel.EXPLAIN
        for q in questions:
            all_questions.append((t, q, difficulty))

    answers = _get_post_answers()
    conf = _get_post_confidence()
    total = len(all_questions)

    for idx, (topic_name, question, difficulty) in enumerate(all_questions):
        key = str(idx)
        with ui.card().classes("w-full p-4 mb-2"):
            with ui.row().classes("items-center gap-2 mb-2"):
                _render_difficulty_badge(difficulty)
                if len(topics) > 1:
                    ui.badge(topic_name).classes("text-xs")
            ui.markdown(question)

            def _make_answer_handler(k: str) -> Callable[[str], None]:
                def _on_change(text: str) -> None:
                    a = _get_post_answers()
                    a[k] = text
                    _set_post_answers(a)

                return _on_change

            math_input(
                value=answers.get(key, ""),
                label=f"Answer {idx + 1}",
                on_change=_make_answer_handler(key),
            )

            def _make_confidence_handler(k: str) -> Callable[[int], None]:
                def _on_rate(rating: int) -> None:
                    c = _get_post_confidence()
                    c[k] = rating
                    _set_post_confidence(c)

                return _on_rate

            confidence_rating(on_rate=_make_confidence_handler(key))

    # Improvement summary
    complete = _questions_complete(answers, conf, count=total)
    if complete and total > 0:
        pre_answers = _get_pre_answers()
        pre_score = compute_score(pre_answers, [""] * len(pre_answers)) if pre_answers else 0.0
        post_score = compute_score(answers, [q for _, q, _ in all_questions])
        improvement = format_improvement(pre_score, post_score)
        ui.label(f"Improvement: {improvement}").classes("text-lg font-bold mt-4")

    with ui.stepper_navigation():
        ui.button("Back", on_click=lambda: _retreat_step(stepper, 1)).props("flat")
        if complete:
            ui.button("Next", on_click=lambda: _advance_step(stepper, 3)).props("color=primary")
        else:
            ui.button("Next").props("color=primary disable")


def _render_reflection(stepper: ui.stepper) -> None:
    remaining = _get_timer_remaining()

    ui.label("Reflection").classes("text-xl font-bold mb-4")
    timer_label = ui.label(f"Time remaining: {remaining}s").classes("text-lg font-semibold")

    def _tick() -> None:
        r = _get_timer_remaining()
        if r > 0:
            r -= 1
            _set_timer_remaining(r)
            timer_label.text = f"Time remaining: {r}s"

    ui.timer(1, _tick)

    # Metacognitive prompts
    for prompt in _METACOGNITIVE_PROMPTS:
        ui.label(prompt).classes("text-sm text-gray-600 mt-2 italic")

    ui.label("Write your reflection:").classes("text-lg font-semibold mt-4")

    def _on_reflection_change(e: object) -> None:
        _set_reflection(getattr(e, "value", ""))  # pyright: ignore[reportUnknownArgumentType]

    ui.textarea(
        value=_get_reflection(),
        label="Reflection",
        on_change=_on_reflection_change,
    ).classes("w-full")

    timer_done = remaining <= 0
    has_reflection = bool(_get_reflection().strip())

    with ui.stepper_navigation():
        ui.button("Back", on_click=lambda: _retreat_step(stepper, 2)).props("flat")
        if timer_done and has_reflection:
            ui.button("Next", on_click=lambda: _advance_step(stepper, 4)).props("color=primary")
        else:
            ui.button("Next").props("color=primary disable")


async def _render_flashcard_step(
    stepper: ui.stepper,
    container: AppContainer,
    course_id: int,
    topics: list[str],
    interleaved: bool,
) -> None:
    ui.label("Create Flashcards").classes("text-xl font-bold mb-4")
    if interleaved:
        ui.label("Create at least one flashcard per topic.").classes("text-sm text-gray-500 mb-2")

    for t in topics:
        if len(topics) > 1:
            ui.label(t).classes("text-lg font-semibold mt-4")

        front_val: dict[str, str] = {"v": ""}
        back_val: dict[str, str] = {"v": ""}

        @ui.refreshable  # type: ignore[misc]
        def _card_preview(fv: dict[str, str] = front_val, bv: dict[str, str] = back_val) -> None:
            flashcard(front=fv.get("v", ""), back=bv.get("v", ""))

        def _make_front_handler(d: dict[str, str]) -> Callable[[str], None]:
            def _h(text: str) -> None:
                d["v"] = text
                _card_preview.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

            return _h

        def _make_back_handler(d: dict[str, str]) -> Callable[[str], None]:
            def _h(text: str) -> None:
                d["v"] = text
                _card_preview.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

            return _h

        math_input(label="Front (question)", on_change=_make_front_handler(front_val))
        math_input(label="Back (answer)", on_change=_make_back_handler(back_val))

        # Live preview
        with ui.expansion("Preview", icon="visibility").classes("w-full mt-2"):
            _card_preview()

        async def _save_card(
            topic: str = t,
            front: dict[str, str] = front_val,
            back: dict[str, str] = back_val,
        ) -> None:
            f, b = front["v"].strip(), back["v"].strip()
            if not f or not b:
                ui.notify("Both front and back are required.", type="warning")
                return
            try:
                await save_study_flashcard(container, course_id, topic, f, b)
                ui.notify(f"Flashcard saved for {topic}!", type="positive")
            except Exception:
                log.exception("flashcard_save_failed", topic=topic)
                ui.notify("Failed to save flashcard.", type="negative")

        ui.button("Save Flashcard", on_click=_save_card, icon="save").props(  # pyright: ignore[reportArgumentType]
            "color=primary outline",
        ).classes("mt-2")

    ui.separator().classes("my-6")

    async def _finish_session() -> None:
        await _complete_study_session(container, course_id, topics)
        _reset_session_state()
        # Discard persisted session
        store = SessionStore(app.storage.user)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        store.discard_session(_get_session_id())
        _study_session.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

    with ui.stepper_navigation():
        ui.button("Back", on_click=lambda: _retreat_step(stepper, 3)).props("flat")
        ui.button("Finish Session", on_click=_finish_session, icon="check_circle").props(  # pyright: ignore[reportArgumentType]
            "color=positive",
        )


async def _complete_study_session(
    container: AppContainer,
    course_id: int,
    topics: list[str],
) -> None:
    """Complete the study session — record scores and calibration for each topic."""
    pre_answers = _get_pre_answers()
    post_answers = _get_post_answers()
    pre_count = len(topics) * _PRETEST_COUNT
    post_count = len(topics) * _POSTTEST_COUNT

    pre_score = compute_score(pre_answers, [""] * pre_count) if pre_answers else 0.0
    post_score = compute_score(post_answers, [""] * post_count) if post_answers else 0.0

    session_ids = _get_session_ids()
    for t in topics:
        try:
            sid = session_ids.get(t)
            if sid is None:
                sess = await start_session(container, course_id, t)
                sid = sess.id
            await complete_session(
                container,
                session_id=sid,
                pre_score=pre_score,
                post_score=post_score,
            )
            await finalize_calibration(container, course_id, t, post_score)
        except Exception:
            log.exception("session_complete_failed", topic=t)

    ui.notify("Session complete!", type="positive")
    ui.navigate.to("/")


def _can_advance_from_step(step: int, *, num_topics: int) -> bool:
    """Check whether the current step's completion criteria are satisfied."""
    if step == 0:
        return _questions_complete(
            _get_pre_answers(),
            _get_pre_confidence(),
            count=num_topics * _PRETEST_COUNT,
        )
    if step == 1:
        insight = _get_insight()
        return bool(insight and insight.strip())
    if step == 2:
        return _questions_complete(
            _get_post_answers(),
            _get_post_confidence(),
            count=num_topics * _POSTTEST_COUNT,
        )
    if step == 3:
        return _get_timer_remaining() <= 0 and bool(_get_reflection().strip())
    return False


def _advance_step(stepper: ui.stepper, target: int) -> None:
    _set_step_index(target)
    stepper.next()


def _retreat_step(stepper: ui.stepper, target: int) -> None:
    _set_step_index(target)
    stepper.previous()
