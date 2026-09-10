"""User management endpoints with RBAC."""

import math
from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Organization, User, UserRole
from ..schemas import (
    InviteUser,
    InvitationCreate,
    InvitationRead,
    PaginatedUsers,
    UserRead,
    UserUpdate,
)
from ..security import (
    check_role,
    get_current_user,
    get_password_hash,
)

router = APIRouter(prefix="/v1", tags=["Users"])


@router.get("/users/me", response_model=UserRead)
def get_my_profile(current_user: User = Depends(get_current_user)) -> User:
    """Get current user's profile."""
    return current_user


@router.patch("/users/me", response_model=UserRead)
def update_my_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """Update current user's profile."""
    update_data = payload.model_dump(exclude_unset=True)
    
    # Prevent self-deactivation
    if "is_active" in update_data and not update_data["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account"
        )
    
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/users", response_model=PaginatedUsers)
def list_users(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    role_filter: Optional[str] = Query(default=None, alias="role"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> PaginatedUsers:
    """
    List users in the current user's organization.
    Only OWNER and ADMIN can list all users.
    """
    # Check permissions
    user_role = UserRole(current_user.role)
    if user_role not in [UserRole.OWNER, UserRole.ADMIN]:
        # Non-admin users can only see themselves
        users = [current_user]
        total = 1
        items = users
        pages = 1
        return PaginatedUsers(items=items, total=total, page=page, per_page=per_page, pages=pages)
    
    offset = (page - 1) * per_page
    
    stmt = select(User).where(User.organization_id == current_user.organization_id)
    if role_filter:
        try:
            role_enum = UserRole(role_filter)
            stmt = stmt.where(User.role == role_enum.value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Valid roles: {[r.value for r in UserRole]}"
            )
    
    count_query = select(func.count()).select_from(User).where(
        User.organization_id == current_user.organization_id
    )
    if role_filter:
        count_query = count_query.where(User.role == role_enum.value)
    
    total = db.scalar(count_query) or 0
    pages = math.ceil(total / per_page) if total > 0 else 1
    
    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    items = list(db.scalars(stmt))
    
    return PaginatedUsers(items=items, total=total, page=page, per_page=per_page, pages=pages)


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(
    user_id: str,
    current_user: User = Depends(check_role([UserRole.OWNER, UserRole.ADMIN])),
    db: Session = Depends(get_db)
) -> User:
    """
    Get a specific user by ID.
    Only OWNER and ADMIN can view other users.
    """
    user = db.scalar(select(User).where(
        User.id == user_id,
        User.organization_id == current_user.organization_id
    ))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users/invite", response_model=InvitationRead, status_code=201)
def invite_user(
    payload: InviteUser,
    current_user: User = Depends(check_role([UserRole.OWNER, UserRole.ADMIN])),
    db: Session = Depends(get_db)
):
    """
    Invite a new user to the organization.
    Only OWNER and ADMIN can invite users.
    Note: In production, this would send an email with an invitation link.
    """
    # Check if email already exists in organization
    existing = db.scalar(select(User).where(
        User.email == payload.email,
        User.organization_id == current_user.organization_id
    ))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists in the organization"
        )
    
    # For now, create the user directly (in production, create pending invitation)
    user = User(
        organization_id=current_user.organization_id,
        email=payload.email,
        password_hash=get_password_hash(secrets.token_urlsafe(32)),  # Random password
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Return as invitation format (simplified)
    return InvitationRead(
        id=user.id,
        organization_id=user.organization_id,
        email=user.email,
        role=user.role,
        invited_by_id=current_user.id,
        invited_by_email=current_user.email,
        status="accepted",  # Auto-accepted for now
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        created_at=user.created_at,
    )


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: str,
    payload: UserUpdate,
    current_user: User = Depends(check_role([UserRole.OWNER, UserRole.ADMIN])),
    db: Session = Depends(get_db)
) -> User:
    """
    Update a user's profile.
    Only OWNER and ADMIN can update other users.
    OWNER can change roles, ADMIN cannot promote to ADMIN/OWNER.
    """
    user = db.scalar(select(User).where(
        User.id == user_id,
        User.organization_id == current_user.organization_id
    ))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    
    # Role change restrictions
    if "role" in update_data:
        new_role = update_data["role"]
        current_role = UserRole(current_user.role)
        target_role = UserRole(new_role)
        
        # Only OWNER can assign OWNER or ADMIN roles
        if target_role in [UserRole.OWNER, UserRole.ADMIN] and current_role != UserRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only OWNER can assign OWNER or ADMIN roles"
            )
        
        # Cannot demote the last OWNER
        if user.role == UserRole.OWNER.value and target_role != UserRole.OWNER:
            owner_count = db.scalar(select(func.count()).select_from(User).where(
                User.organization_id == current_user.organization_id,
                User.role == UserRole.OWNER.value
            ))
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove the last OWNER in the organization"
                )
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    current_user: User = Depends(check_role([UserRole.OWNER, UserRole.ADMIN])),
    db: Session = Depends(get_db)
):
    """
    Delete a user from the organization.
    Only OWNER and ADMIN can delete users.
    Cannot delete the last OWNER.
    """
    user = db.scalar(select(User).where(
        User.id == user_id,
        User.organization_id == current_user.organization_id
    ))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Cannot delete yourself
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )
    
    # Cannot delete the last OWNER
    if user.role == UserRole.OWNER.value:
        owner_count = db.scalar(select(func.count()).select_from(User).where(
            User.organization_id == current_user.organization_id,
            User.role == UserRole.OWNER.value
        ))
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete the last OWNER in the organization"
            )
    
    db.delete(user)
    db.commit()
