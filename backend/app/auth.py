import os
import httpx
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel
from typing import Optional, Dict, Any

# Environment variables
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
# For Google, we fetch public keys from their endpoint
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

security = HTTPBearer()

class User(BaseModel):
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    # We can add efficient role/org checking here later
    # role: str = "user" 

async def get_google_public_keys() -> Dict[str, Any]:
    """Fetch Google's public keys for verifying JWTs"""
    async with httpx.AsyncClient() as client:
        response = await client.get(GOOGLE_CERTS_URL)
        return response.json()

async def verify_google_token(token: str) -> Dict[str, Any]:
    """Verify the Google JWT token"""
    try:
        # Get public keys
        jwks = await get_google_public_keys()
        
        # Verify and decode
        # Note: audience check is crucial
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=GOOGLE_CLIENT_ID,
            options={"verify_at_hash": False} # Sometimes needed for Google tokens
        )
        return payload
    except JWTError as e:
        error_msg = str(e)
        print(f"JWT Verification Error: {error_msg}")
        
        # provide more descriptive detail for common errors
        detail = "Invalid authentication credentials"
        if "exp" in error_msg.lower() or "expired" in error_msg.lower():
            detail = "Token expired. Please refresh your session."
        elif "aud" in error_msg.lower() or "audience" in error_msg.lower():
            detail = "Token audience mismatch. Check GOOGLE_CLIENT_ID."
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Dependency to get the current authenticated user.
    Validates JWT token from Authorization header.
    """
    token = credentials.credentials
    
    if not GOOGLE_CLIENT_ID:
        print("DEBUG AUTH: GOOGLE_CLIENT_ID is None")
        # Don't fail here, verify_google_token will fail with a better error if needed
    
    try:
        payload = await verify_google_token(token)
        print(f"DEBUG AUTH: Payload extracted for {payload.get('email')}")
    except HTTPException as e:
         # Re-raise HTTPExceptions as-is to preserve details
         raise e
    except Exception as e:
         print(f"DEBUG AUTH: Unexpected verification error: {str(e)}")
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {str(e)}",
        )

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing email")

    # Domain restriction check (redundant with frontend but good for security)
    if not email.endswith("@appointy.com"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access restricted to @appointy.com users (found {email})"
        )

    return User(
        email=email,
        name=payload.get("name"),
        picture=payload.get("picture")
    )
