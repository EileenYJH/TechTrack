from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    title: str
    source_name: str
    source_url: str
    event_url: str
    category: str
    country: str
    description: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    deadline: Optional[datetime] = None
    location: str = ""
    organizer: str = ""
    tags: list[str] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=datetime.now)

    @property
    def date_display(self) -> str:
        if self.start_date:
            if self.end_date and self.end_date.date() != self.start_date.date():
                return f"{self.start_date.strftime('%d %b %Y')} – {self.end_date.strftime('%d %b %Y')}"
            return self.start_date.strftime("%d %b %Y")
        return "Date TBA"

    @property
    def deadline_display(self) -> str:
        if self.deadline:
            return self.deadline.strftime("%d %b %Y")
        return "—"

    @property
    def is_upcoming(self) -> bool:
        if self.start_date:
            return self.start_date >= datetime.now()
        return True  # keep TBA events visible

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "event_url": self.event_url,
            "category": self.category,
            "country": self.country,
            "description": self.description,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "location": self.location,
            "organizer": self.organizer,
            "tags": ",".join(self.tags),
            "scraped_at": self.scraped_at.isoformat(),
        }
