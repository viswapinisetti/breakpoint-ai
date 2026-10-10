"""AI Debate (PRD sections 30, 46.8).

The hero experience. The agent defends its solution and concedes only to real
evidence, so the constraints that matter are enforced server-side: turns are
bounded (PRD section 110, risk 5) and the concession decision is stored rather
than inferred by the client.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.agents.client import AgentError
from app.agents.runtime import debate_reply
from app.config import settings
from app.deps import SessionDep, UserDep
from app.models import AnalyticsEvent, Attempt, ChallengeRecord, DebateTurn
from app.engine.contracts import Challenge
from app.schemas import DebateRequest, DebateResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["debate"])


@router.get("/attempts/{attempt_id}/debate", response_model=list[dict])
def debate_history(
    attempt_id: int, session: SessionDep, user: UserDep
) -> list[dict]:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="attempt not found")
    turns = session.scalars(
        select(DebateTurn)
        .where(DebateTurn.attempt_id == attempt_id)
        .order_by(DebateTurn.turn, DebateTurn.id)
    )
    return [
        {
            "turn": t.turn,
            "role": t.role,
            "message": t.message,
            "conceded": t.conceded,
        }
        for t in turns
    ]


@router.post("/attempts/{attempt_id}/debate", response_model=DebateResponse)
def post_debate_turn(
    attempt_id: int, body: DebateRequest, session: SessionDep, user: UserDep
) -> DebateResponse:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None or attempt.user_id != user.id:
        raise HTTPException(status_code=404, detail="attempt not found")
    if attempt.judgment is None:
        raise HTTPException(
            status_code=409, detail="record a judgment before opening a debate"
        )

    existing = list(
        session.scalars(
            select(DebateTurn)
            .where(DebateTurn.attempt_id == attempt_id)
            .order_by(DebateTurn.turn, DebateTurn.id)
        )
    )
    if any(t.conceded for t in existing):
        raise HTTPException(status_code=409, detail="this debate is already settled")

    turn = attempt.debate_turns + 1
    if turn > settings.max_debate_turns:
        raise HTTPException(
            status_code=409,
            detail=(
                "Debate turn limit reached. Submit your evidence to the Evidence "
                "Board and complete the investigation."
            ),
        )

    record = session.get(ChallengeRecord, attempt.challenge_pk)
    if record is None:
        raise HTTPException(status_code=404, detail="challenge missing")
    challenge = Challenge.model_validate(record.body)

    history = [{"role": t.role, "message": t.message} for t in existing]
    try:
        reply, conceded = debate_reply(
            challenge=challenge,
            history=history,
            student_message=body.message,
            turn=turn,
        )
    except AgentError as exc:
        logger.warning("debate unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Breakpoint AI is unavailable right now. Please try again shortly.",
        ) from exc

    session.add(
        DebateTurn(
            attempt_id=attempt_id, turn=turn, role="student", message=body.message
        )
    )
    session.add(
        DebateTurn(
            attempt_id=attempt_id,
            turn=turn,
            role="ai",
            message=reply,
            conceded=conceded,
        )
    )
    attempt.debate_turns = turn
    session.add(
        AnalyticsEvent(
            user_id=user.id,
            name="debate_turn",
            payload={
                "challenge_id": challenge.id,
                "turn": turn,
                "conceded": conceded,
            },
        )
    )
    session.commit()

    remaining = max(0, settings.max_debate_turns - turn)
    return DebateResponse(
        reply=reply,
        turn=turn,
        turns_remaining=remaining,
        conceded=conceded,
        exhausted=remaining == 0 and not conceded,
    )
