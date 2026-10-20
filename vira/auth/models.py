from pydantic import BaseModel

class SetupRequest(BaseModel):
    username: str
    password: str
    confirm_password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class ForgotRequest(BaseModel):
    username: str
    recovery_code: str
    new_password: str
    confirm_password: str