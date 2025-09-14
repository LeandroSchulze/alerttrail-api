import ipaddress
from fastapi import Request

def get_client_ip(request: Request) -> str:
    for header in ("x-forwarded-for", "cf-connecting-ip", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            ip = value.split(",")[0].strip()
            try:
                ipaddress.ip_address(ip)
                return ip
            except Exception:
                pass
    return request.client.host if request.client else "0.0.0.0"
