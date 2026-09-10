"""Authentication endpoints for user login, registration, and token management."""

from datetime import datetime, timezone
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Organization, User, UserRole
from ..schemas import (
    LoginRequest,
    MFASetup,
    PasswordChange,
    Token,
    TokenRefresh,
    UserRead,
    UserRegister,
)
from ..security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_mfa_secret,
    get_current_user,
    get_password_hash,
    verify_mfa_code,
    verify_password,
)

router = APIRouter(prefix="/v1/auth", tags=["Authentication"])


@router.post("/register", response_model=UserRead, status_code=201)
def register_user(payload: UserRegister, db: Session = Depends(get_db)) -> UserRead:
    """
    Register a new user with an organization.
    Creates both the organization and the user as OWNER.
    """
    # Check if email already exists
    existing_user = db.scalar(select(User).where(User.email == payload.email))
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )
    
    # Create organization
    org = Organization(name=payload.organization_name)
    db.add(org)
    db.flush()  # Get org ID before creating user
    
    # Create user as OWNER
    user = User(
        organization_id=org.id,
        email=payload.email,
        password_hash=get_password_hash(payload.password),
        full_name=payload.full_name,
        role=UserRole.OWNER,
        is_active=True,
        email_verified=False,  # Should send verification email in production
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> Token:
    """
    Authenticate user and return access/refresh tokens.
    If MFA is enabled, mfa_code is required.
    """
    # Find user by email
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check MFA if enabled
    if user.mfa_enabled:
        if not payload.mfa_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA code required"
            )
        if not user.mfa_secret or not verify_mfa_code(user.mfa_secret, payload.mfa_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MFA code",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    
    # Generate tokens
    token_data = {"sub": user.id, "email": user.email, "org_id": user.organization_id}
    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)
    
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer"
    )


@router.post("/refresh", response_model=Token)
def refresh_token(payload: TokenRefresh, db: Session = Depends(get_db)) -> Token:
    """
    Refresh access token using a valid refresh token.
    """
    token_payload = decode_token(payload.refresh_token)
    if not token_payload or token_payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = token_payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Generate new tokens
    token_data = {"sub": user.id, "email": user.email, "org_id": user.organization_id}
    access_token = create_access_token(token_data)
    new_refresh_token = create_refresh_token(token_data)
    
    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer"
    )


@router.get("/me", response_model=UserRead)
def get_current_user_info(current_user: User = Depends(get_current_user)) -> User:
    """
    Get current authenticated user information.
    """
    return current_user


@router.post("/mfa/setup")
def setup_mfa(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Setup MFA for the current user.
    Returns the MFA secret and QR code provisioning URI.
    """
    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA already enabled"
        )
    
    mfa_secret = generate_mfa_secret()
    current_user.mfa_secret = mfa_secret
    db.commit()
    
    # Return secret and provisioning URI for QR code generation
    return {
        "mfa_secret": mfa_secret,
        "provisioning_uri": f"otpauth://totp/Projet%20Facturation:{current_user.email}?secret={mfa_secret}&issuer=Projet%20Facturation"
    }


@router.post("/mfa/enable")
def enable_mfa(
    payload: MFASetup,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enable MFA after verifying the first code.
    """
    if not current_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA not setup. Call /mfa/setup first."
        )
    
    if not verify_mfa_code(current_user.mfa_secret, payload.mfa_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA code"
        )
    
    current_user.mfa_enabled = True
    db.commit()
    
    return {"message": "MFA enabled successfully"}


@router.post("/mfa/disable")
def disable_mfa(
    payload: MFASetup,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Disable MFA by verifying the current code.
    """
    if not current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA not enabled"
        )
    
    if not verify_mfa_code(current_user.mfa_secret, payload.mfa_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA code"
        )
    
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    db.commit()
    
    return {"message": "MFA disabled successfully"}


@router.post("/password/change")
def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Change the current user's password.
    """
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password"
        )
    
    current_user.password_hash = get_password_hash(payload.new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}
