# chainlit_integration.py

from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from urllib.parse import urlparse, parse_qs
from chainlit.data import get_data_layer
from chainlit.logger import logger
from chainlit.auth import create_jwt
from chainlit.config import config as cl_config
from chainlit import User  # Ensure this import works based on your chainlit package structure
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import MutableHeaders

def add_chainlit_routes(app):
    """
    Adds the Chainlit login adapter endpoint, middleware, and mounts Chainlit
    to the provided FastAPI app.
    """
    # Use a prefix matching our authentication routes; here it's "chat"
    app_root_path = "chat"
    
    @app.get(f"/{app_root_path}/header-auth")
    async def header_auth(request: Request):
        # Parse the query parameters from the request URL
        query = urlparse(str(request.url)).query
        params = parse_qs(query)
        email = params.get("email", [None])[0]
        print(email)
        if not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No email provided")
        
        # Create a Chainlit user with the given email
        user = User(identifier=email, metadata={"role": "admin", "provider": "query"})
        # Create a JWT access token for the user
        access_token = create_jwt(user)
        
        # If a data layer is configured, attempt to create the user
        if data_layer := get_data_layer():
            try:
                await data_layer.create_user(user)
            except Exception as e:
                logger.error(f"Error creating user: {e}")
        
        # Redirect to the Chainlit login callback with the access token
        redirect_url = f"/chainlit/web/login/callback?access_token={access_token}"
        response = RedirectResponse(redirect_url, status_code=307)
        response.set_cookie(
            key="x-user-id",
            value=email,
            httponly=True,
            secure=False,         # Set True in production with HTTPS
            samesite="Lax",
            path="/",
            domain="localhost"    # In production, update this to your domain
        )
        return response

    # Middleware to inject the "x-user-id" header for any routes that start with "/chainlit"
    class InjectUserHeaderMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path.startswith("/chainlit"):
                email = request.cookies.get("x-user-id")
                print("==========================")
                print(email)
                if email:
                    mutable_headers = MutableHeaders(request.headers)
                    mutable_headers["x-user-id"] = email
            response = await call_next(request)
            return response

    app.add_middleware(InjectUserHeaderMiddleware)

    # Use Chainlit’s utility function to mount Chainlit under the desired path.
    # Ensure that "cl.py" is the correct target for Chainlit in your setup.
    from chainlit.utils import mount_chainlit
    mount_chainlit(app=app, target="chainlit/cl.py", path="/chainlit")
