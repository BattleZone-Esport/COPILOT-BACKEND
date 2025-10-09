from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth
from app.core.config import get_settings, Settings
from app.db.mongo import get_db
from app.repositories.user_repository import get_user_by_email, create_user, touch_last_login, update_user
from app.core.security import generate_csrf_token
from datetime import datetime, timezone
import uuid
import json

router = APIRouter(tags=["auth"])  # prefix will be added in main.py
templates = Jinja2Templates(directory="templates")

def build_oauth(settings: Settings):
    oauth = OAuth()
    if settings.AUTH_GOOGLE_CLIENT_ID and settings.AUTH_GOOGLE_CLIENT_SECRET:
        oauth.register(
            name='google',
            client_id=settings.AUTH_GOOGLE_CLIENT_ID,
            client_secret=settings.AUTH_GOOGLE_CLIENT_SECRET,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'}
        )
    # Assuming you might add Github later, leaving the structure in
    # if settings.AUTH_GITHUB_CLIENT_ID and settings.AUTH_GITHUB_CLIENT_SECRET:
    #     oauth.register(...) 
    return oauth

@router.get('/login')
async def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "user": request.session.get('user')})


@router.get('/logout')
async def logout(request: Request):
    request.session.pop('user', None)
    request.session.pop('csrf_token', None)
    return RedirectResponse(url='/')

@router.get('/csrf')
async def get_csrf_token(request: Request):
    """Get or generate a CSRF token for the current session."""
    csrf_token = request.session.get('csrf_token')
    if not csrf_token:
        csrf_token = generate_csrf_token()
        request.session['csrf_token'] = csrf_token
    return {"csrf_token": csrf_token}

@router.get('/me')
async def get_current_user(request: Request):
    """Get the current authenticated user from session."""
    user = request.session.get('user')
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

@router.get('/google/login')
async def google_login(request: Request, settings: Settings = Depends(get_settings)):
    redirect_uri = request.url_for('google_callback')
    oauth = build_oauth(settings)
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get('/google/callback')
async def google_callback(request: Request, settings: Settings = Depends(get_settings), db=Depends(get_db)):
    oauth = build_oauth(settings)
    token = await oauth.google.authorize_access_token(request)
    userinfo = await oauth.google.parse_id_token(request, token)
    
    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email not provided")

    user = await get_user_by_email(db, email)
    if not user:
        user_details = {
            "user_id": str(uuid.uuid4()),
            "email": email,
            "name": userinfo.get("name"),
            "avatar_url": userinfo.get("picture"),
            "provider": "google",
            "providers": {"google": {}},
            "created_at": datetime.now(timezone.utc),
        }
        user = await create_user(db, user_details)
    
    # Storing essential user info in session
    request.session['user'] = {
        'name': user['name'],
        'email': user['email'],
        'picture': user.get('avatar_url')
    }

    csrf_token = generate_csrf_token()
    request.session['csrf_token'] = csrf_token
    
    await touch_last_login(db, user["user_id"])
    return RedirectResponse(url='/')

# You can add the github routes here later if needed following the same pattern
