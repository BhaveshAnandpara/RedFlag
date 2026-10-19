"""The setup chat, files, examples, skipping and the two contexts.

Added to the setup router by `build_setup_router`. Everything here is owner-only (the router's
dependency) and nothing here ever sees the endpoint key.
"""

import asyncio
import re
import secrets
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from redflag_backend.settings import Settings
from redflag_backend.setups.interviewer import (
    INTERVIEWER_SYSTEM,
    InterviewerAnswer,
    apply_updates,
)
from redflag_backend.setups.interviewer import build_prompt as interviewer_prompt
from redflag_backend.setups.llm import ModelFailure, SetupLLM
from redflag_backend.setups.models import (
    ChatTurn,
    Contexts,
    Example,
    JudgeContext,
    SetupData,
    Tagged,
    TesterContext,
    ToolSpec,
    UploadedFile,
    required_status,
)
from redflag_backend.setups.store import NoSuchSetup, SetupStore
from redflag_backend.setups.supervisor import SUPERVISOR_SYSTEM, SupervisorAnswer, build_contexts
from redflag_backend.setups.supervisor import build_prompt as supervisor_prompt

ALLOWED_EXTENSIONS = (".txt", ".md", ".markdown", ".json")
FILE_NAME = re.compile(r"^[A-Za-z0-9._ -]{1,80}$")
LIMIT_REPLY = (
    "We have reached the limit for this chat. Everything so far is saved in the panel, where you "
    "can still edit any field before you review the rules."
)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class SkipBody(BaseModel):
    topic: str = Field(min_length=1, max_length=200)


class FileBody(BaseModel):
    name: str
    content: str


class ExampleBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    label: Literal["bad_reply", "good_reply", "conversation"] = "conversation"


class ContextEdit(BaseModel):
    value: Any


def _error(status: int, kind: str, message: str | None = None) -> JSONResponse:
    body: dict[str, Any] = {"kind": kind}
    if message:
        body["message"] = message
    return JSONResponse(status_code=status, content={"error": body})


def add_chat_routes(
    router: APIRouter, settings: Settings, store: SetupStore, llm: SetupLLM
) -> None:
    async def load(setup_id: int) -> SetupData:
        try:
            data, _, _ = await asyncio.to_thread(store.get_draft, setup_id)
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing
        return data

    async def change(setup_id: int, apply: Any) -> Any:
        try:
            return await asyncio.to_thread(store.update_draft, setup_id, apply)
        except NoSuchSetup as missing:
            raise HTTPException(status_code=404, detail="no such setup") from missing

    @router.post("/setups/{setup_id}/chat", response_model=None)
    async def chat(setup_id: int, body: ChatBody) -> dict[str, Any] | JSONResponse:
        data = await load(setup_id)
        cap = settings.setup_chat_max_messages
        if data.user_messages >= cap:
            return {"reply": LIMIT_REPLY, "asking": None, "limit_reached": True, "messages_left": 0}
        unmet = [name for name, met in required_status(data).items() if name != "ready" and not met]
        prompt = interviewer_prompt(data, body.message, unmet, settings.setup_max_followups)
        try:
            answer = await llm.ask(
                setup_id, "interviewer", INTERVIEWER_SYSTEM, prompt, InterviewerAnswer
            )
        except ModelFailure as failure:
            return _error(failure.status, failure.kind)

        def apply(draft: SetupData) -> str | None:
            asking = answer.asking
            if asking and draft.followups_asked < settings.setup_max_followups:
                draft.followups_asked += 1
            else:
                asking = None
            apply_updates(draft, answer.updates)
            draft.chat += [
                ChatTurn(role="user", content=body.message),
                ChatTurn(role="assistant", content=answer.reply),
            ]
            draft.user_messages += 1
            return asking

        asking = await change(setup_id, apply)
        return {
            "reply": answer.reply,
            "asking": asking,
            "limit_reached": False,
            "messages_left": cap - data.user_messages - 1,
        }

    @router.post("/setups/{setup_id}/skip")
    async def skip(setup_id: int, body: SkipBody) -> dict[str, Any]:
        def apply(draft: SetupData) -> None:
            topic = body.topic.strip()
            if topic and topic not in draft.fields.unclear:
                draft.fields.unclear.append(topic)

        await change(setup_id, apply)
        data = await load(setup_id)
        return {"unclear": data.fields.unclear}

    @router.post("/setups/{setup_id}/examples", status_code=201)
    async def add_example(setup_id: int, body: ExampleBody) -> dict[str, Any]:
        example = Example(id=f"e-{secrets.token_hex(3)}", text=body.text, label=body.label)

        def apply(draft: SetupData) -> None:
            draft.fields.examples.append(example)

        await change(setup_id, apply)
        return example.model_dump()

    @router.post("/setups/{setup_id}/files", status_code=201, response_model=None)
    async def add_file(setup_id: int, body: FileBody) -> dict[str, Any] | JSONResponse:
        name = body.name.strip()
        if not FILE_NAME.fullmatch(name) or not name.lower().endswith(ALLOWED_EXTENSIONS):
            return _error(
                422,
                "file_type",
                "Only text, markdown and JSON files with a plain name are accepted.",
            )
        if len(body.content.encode("utf-8")) > settings.setup_file_max_bytes:
            return _error(413, "file_too_large", "That file is too large.")

        def apply(draft: SetupData) -> bool:
            others = [f for f in draft.files if f.name != name]
            if len(others) >= settings.setup_file_max_count:
                return False
            draft.files = [*others, UploadedFile(name=name, content=body.content)]
            return True

        if not await change(setup_id, apply):
            return _error(422, "too_many_files", "That is too many files for one setup.")
        return {"name": name, "bytes": len(body.content.encode("utf-8"))}

    @router.delete("/setups/{setup_id}/files/{name}", status_code=204, response_model=None)
    async def delete_file(setup_id: int, name: str) -> Response:
        def apply(draft: SetupData) -> None:
            draft.files = [f for f in draft.files if f.name != name]

        await change(setup_id, apply)
        return Response(status_code=204)

    @router.post("/setups/{setup_id}/contexts", response_model=None)
    async def make_contexts(setup_id: int) -> dict[str, Any] | JSONResponse:
        data = await load(setup_id)
        try:
            answer = await llm.ask(
                setup_id, "supervisor", SUPERVISOR_SYSTEM, supervisor_prompt(data), SupervisorAnswer
            )
        except ModelFailure as failure:
            return _error(failure.status, failure.kind)

        def apply(draft: SetupData) -> dict[str, Any]:
            draft.contexts = build_contexts(draft, answer)
            return draft.contexts.model_dump()

        return {"contexts": await change(setup_id, apply)}

    @router.put("/setups/{setup_id}/contexts/{which}/{name}", response_model=None)
    async def edit_context(
        setup_id: int, which: Literal["tester", "judge"], name: str, body: ContextEdit
    ) -> dict[str, Any] | JSONResponse:
        editable: dict[str, set[str]] = {
            "tester": {"purpose", "tools", "weak_spots", "what_to_try", "notes"},
            "judge": {"purpose", "rules", "limits", "protected_data", "tools", "notes"},
        }
        if name not in editable[which]:
            return _error(422, "not_editable", "That part of the context cannot be edited here.")

        def apply(draft: SetupData) -> bool:
            contexts = draft.contexts or Contexts()
            target: TesterContext | JudgeContext = getattr(contexts, which)
            try:
                if name in {"purpose", "notes"}:
                    value: Any = str(body.value)
                elif name == "tools":
                    value = [ToolSpec.model_validate(item) for item in body.value]
                else:
                    value = [Tagged.model_validate(item) for item in body.value]
            except (ValueError, TypeError):
                return False
            setattr(target, name, value)
            key = f"{which}.{name}"
            if key not in contexts.locked:
                contexts.locked.append(key)
            draft.contexts = contexts
            return True

        if not await change(setup_id, apply):
            return _error(422, "bad_value", "That value does not fit this part of the context.")
        data = await load(setup_id)
        return {"contexts": data.contexts.model_dump() if data.contexts else None}
