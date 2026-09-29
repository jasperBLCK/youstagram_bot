from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.admin.deps import check_credentials, f_str
from app.admin.routes.common import back, render

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/") -> HTMLResponse:
    return render(request, "login.html", next=next if next.startswith("/") else "/")


@router.post("/login", response_model=None)
async def login(request: Request) -> RedirectResponse | HTMLResponse:
    form = await request.form()
    username, password = f_str(form, "username"), f_str(form, "password")
    nxt = f_str(form, "next", "/")
    if not check_credentials(username, password):
        return render(request, "login.html", next=nxt, error="Неверный логин или пароль")
    request.session["admin"] = username
    return back(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return back("/login")
