from pydantic import BaseModel


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
