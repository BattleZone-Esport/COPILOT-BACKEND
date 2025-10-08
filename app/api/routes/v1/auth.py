from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from app.core.config import Settings
from app.core.security import create_access_token, create_refresh_token, encrypt_oauth_token
from app.db.mongo import get_db
from app.repositories.user_repository import get_user_by_email, create_user, touch_last_login, update_user
from datetime import datetime, timezone
import uuid
import json

router = APIRouter(prefix="/v1/auth", tags=["auth"])

def build_oauth(settings: Settings):
    oauth = OAuth()
    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        oauth.register(
            name="google",
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    if settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET:
        oauth.register(
            name="github",
            client_id=settings.GITHUB_CLIENT_ID,
            client_secret=settings.GITHUB_CLIENT_SECRET,
            access_token_url="https://github.com/login/oauth/access_token",
            authorize_url="https://github.com/login/oauth/authorize",
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "read:user user:email"},
        )
    return oauth

@router.get("/google/login")
async def google_login(settings: Settings = Depends(Settings)):
    oauth = build_oauth(settings)
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(redirect_uri)

@router.get("/google/callback")
async def google_callback(request: Request, settings: Settings = Depends(Settings), db=Depends(get_db)):
    oauth = build_oauth(settings)
    token = await oauth.google.authorize_access_token()
    userinfo = await oauth.google.parse_id_token(token)
    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email not provided")
    user = await get_user_by_email(db, email)
    if not user:
        user = await create_user(db, {
            "user_id": str(uuid.uuid4()),
            "email": email,
            "name": userinfo.get("name"),
            "avatar_url": userinfo.get("picture"),
            "provider": "google",
            "providers": {"google": {}},
            "created_at": datetime.now(timezone.utc),
        })
    enc = encrypt_oauth_token(json.dumps(token), settings.JWT_SECRET_KEY)
    await update_user(db, user["user_id"], {"providers.google": {"tokens": enc}})
    await touch_last_login(db, user["user_id"])
    access = create_access_token({"sub": user["user_id"]}, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh = create_refresh_token({"sub": user["user_id"]}, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM, settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return JSONResponse({"access_token": access, "refresh_token": refresh, "token_type": "bearer"})

@router.get("/github/login")
async def github_login(settings: Settings = Depends(Settings)):
    oauth = build_oauth(settings)
    redirect_uri = settings.GITHUB_REDIRECT_URI
    return await oauth.github.authorize_redirect(redirect_uri)

@router.get("/github/callback")
async def github_callback(request: Request, settings: Settings = Depends(Settings), db=Depends(get_db)):
    oauth = build_oauth(settings)
    token = await oauth.github.authorize_access_token()
    # get primary email
    resp = await oauth.github.get("user")
    profile = resp.json()
    email_resp = await oauth.github.get("user/emails")
    emails = email_resp.json()
    primary_email = next((e["email"] for e in emails if e.get("primary")), None) or (emails[0]["email"] if emails else None)
    if not primary_email:
        raise HTTPException(status_code=400, detail="Email not provided")
    user = await get_user_by_email(db, primary_email)
    if not user:
        user = await create_user(db, {
            "user_id": str(uuid.uuid4()),
            "email": primary_email,
            "name": profile.get("name") or profile.get("login"),
            "avatar_url": profile.get("avatar_url"),
            "provider": "github",
            "providers": {"github": {}},
            "created_at": datetime.now(timezone.utc),
        })
    enc = encrypt_oauth_token(json.dumps(token), settings.JWT_SECRET_KEY)
    await update_user(db, user["user_id"], {"providers.github": {"tokens": enc}})
    await touch_last_login(db, user["user_id"])
    access = create_access_token({"sub": user["user_id"]}, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh = create_refresh_token({"sub": user["user_id"]}, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM, settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return JSONResponse({"access_token": access, "refresh_token": refresh, "token_type": "bearer"})
