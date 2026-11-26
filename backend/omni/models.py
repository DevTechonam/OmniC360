from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

Env = Literal['dev', 'qa', 'prod']
Status = Literal['open', 'in_progress', 'resolved', 'closed']
Priority = Literal['low', 'normal', 'high', 'urgent']
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(StrictModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=254)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class Intake(StrictModel):
    source: Literal['chatbot', 'ivr']
    subject: Text
    description: LongText
    priority: Priority = 'normal'
    contact: Text | None = None
    external_reference: Text | None = None


class UpdateTicket(StrictModel):
    status: Status | None = None
    assignee_id: int | None = None

    @model_validator(mode='after')
    def valid_change(self):
        if not self.model_fields_set or ('status' in self.model_fields_set and self.status is None):
            raise ValueError('Supply status or assignee_id; status cannot be null')
        return self


class AddNote(StrictModel):
    body: NoteText


class Receipt(BaseModel):
    id: str
    environment: Env
    created_at: str
