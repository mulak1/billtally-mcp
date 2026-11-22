"""
Public SEO, Documentation, Legal, Analytics & Vertical Destination Routes (`APIRouter`) for BillTally.
Extracted from `app/main.py` so `main.py` stays cleanly under the 500-line soft cap.
"""

import os
from typing import Any, Dict

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.analytics import build_chatgpt_openapi, get_analytics_snapshot, render_analytics_html
from app.studio_pages import render_about_html, render_docs_html, render_privacy_html, render_terms_html
from app.vertical_pages import render_robots_txt, render_sitemap_xml, render_vertical_page_html

router = APIRouter()


def resolve_public_origin(request: Request) -> str:
    env_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if env_url:
        return env_url
    base = str(request.base_url).rstrip("/")
    if "testserver" in base:
        return "http://localhost:8791"
    if (request.headers.get("x-forwarded-proto") == "https" or "railway.app" in base) and base.startswith("http://"):
        base = "https://" + base[len("http://") :]
    return base


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page() -> HTMLResponse:
    return HTMLResponse(content=render_analytics_html(), headers={"X-Robots-Tag": "noindex, nofollow"})


@router.get("/api/analytics")
def api_analytics() -> Dict[str, Any]:
    return get_analytics_snapshot()


@router.get("/chatgpt-openapi.json")
def chatgpt_openapi_spec(request: Request) -> Dict[str, Any]:
    return build_chatgpt_openapi(base_url=resolve_public_origin(request))


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request) -> HTMLResponse:
    return HTMLResponse(content=render_about_html(public_base_url=resolve_public_origin(request)))


@router.get("/docs", response_class=HTMLResponse)
@router.get("/documentation", response_class=HTMLResponse)
def public_docs_page(request: Request) -> HTMLResponse:
    return HTMLResponse(content=render_docs_html(public_base_url=resolve_public_origin(request)))


@router.get("/privacy", response_class=HTMLResponse)
def privacy_policy(request: Request) -> HTMLResponse:
    return HTMLResponse(content=render_privacy_html(public_base_url=resolve_public_origin(request)))


@router.get("/terms", response_class=HTMLResponse)
def terms_of_service(request: Request) -> HTMLResponse:
    return HTMLResponse(content=render_terms_html(public_base_url=resolve_public_origin(request)))


def _render_vertical(slug: str, request: Request) -> HTMLResponse:
    return HTMLResponse(
        content=render_vertical_page_html(
            slug,
            public_base_url=resolve_public_origin(request),
            csp_nonce=getattr(request.state, "csp_nonce", ""),
            query_string=request.url.query,
        )
    )


@router.get("/convert/bank-statement-to-qbo-csv", response_class=HTMLResponse)
def vertical_bank_to_qbo(request: Request) -> HTMLResponse:
    return _render_vertical("bank-statement-to-qbo-csv", request)


@router.get("/check/supplier-invoice", response_class=HTMLResponse)
def vertical_supplier_invoice(request: Request) -> HTMLResponse:
    return _render_vertical("supplier-invoice", request)


@router.get("/check/contractor-invoice", response_class=HTMLResponse)
def vertical_contractor_invoice(request: Request) -> HTMLResponse:
    return _render_vertical("contractor-invoice", request)


@router.get("/check/cam-reconciliation", response_class=HTMLResponse)
def vertical_cam_reconciliation(request: Request) -> HTMLResponse:
    return _render_vertical("cam-reconciliation", request)


@router.get("/sitemap.xml")
def sitemap_xml(request: Request) -> Response:
    return Response(content=render_sitemap_xml(resolve_public_origin(request)), media_type="application/xml")


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(content=render_robots_txt(resolve_public_origin(request)))
