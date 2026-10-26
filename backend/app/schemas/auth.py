import re

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


def check_password(v: str) -> str:
    if len(v.encode()) > 72:
        raise ValueError("Пароль задовгий: не більше 72 байтів (приблизно 36 літер кирилицею)")
    if len(v) < 8 or not re.search(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", v) or not re.search(r"\d", v):
        raise ValueError("Пароль: щонайменше 8 символів, літера й цифра")
    return v


class RegisterIn(BaseModel):
    full_name: str
    email: EmailStr
    password: str

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not 2 <= len(v) <= 100:
            raise ValueError("Ім'я має містити від 2 до 100 символів")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password(v)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return check_password(v)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # password_hash та інше службове в схемі відсутнє
    id: int
    email: str
    full_name: str
    telegram_linked: bool = False
    notify_min_severity: str


class ProfileIn(BaseModel):
    notify_min_severity: Literal["warning", "critical"]


class TelegramLinkOut(BaseModel):
    code: str
    url: str | None
    expires_in_s: int
