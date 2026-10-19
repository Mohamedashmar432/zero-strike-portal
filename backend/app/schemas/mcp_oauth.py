from datetime import datetime

from pydantic import BaseModel


class ConsentRequestResponse(BaseModel):
    request_id: str
    client_name: str  # display text chosen by the registrant, never trusted
    redirect_host: str  # where the code will be sent: the part the user must judge
    scopes: list[str]
    account_email: str
    expires_at: datetime


class ConsentDecisionResponse(BaseModel):
    redirect_to: str


class ConnectedAppResponse(BaseModel):
    id: str
    client_name: str
    redirect_host: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
