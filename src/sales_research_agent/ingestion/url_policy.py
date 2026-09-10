"""公网 URL 的 SSRF 防护策略。"""

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

Resolver = Callable[[str], Iterable[str]]


class UnsafeUrlError(ValueError):
    """URL 不满足公网获取安全边界时抛出。"""


class UrlPolicy:
    """验证协议、主机和 DNS 解析结果均可安全访问。"""

    def __init__(self, resolver: Resolver | None = None) -> None:
        self._resolver = resolver or _resolve_addresses

    def validate(self, url: str) -> str:
        """验证 URL，并返回未经重写的已验证 URL。"""
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise UnsafeUrlError("only http and https URLs are allowed")
        if not parsed.hostname:
            raise UnsafeUrlError("URL must contain a host")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrlError("URL userinfo is not allowed")
        try:
            _ = parsed.port
        except ValueError as error:
            raise UnsafeUrlError("URL contains an invalid port") from error

        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost":
            raise UnsafeUrlError("localhost is not a public target")

        try:
            literal_address = ipaddress.ip_address(host)
        except ValueError:
            self._validate_resolved_addresses(host)
        else:
            self._validate_global_address(literal_address)
        return url

    def _validate_resolved_addresses(self, host: str) -> None:
        try:
            addresses = list(self._resolver(host))
        except (OSError, ValueError) as error:
            raise UnsafeUrlError("host resolution failed") from error
        if not addresses:
            raise UnsafeUrlError("host resolution returned no addresses")
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError as error:
                raise UnsafeUrlError("host resolution returned an invalid address") from error
            self._validate_global_address(parsed)

    @staticmethod
    def _validate_global_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        if not address.is_global:
            raise UnsafeUrlError("URL resolves to a non-public address")


def validate_public_url(url: str, resolver: Resolver | None = None) -> str:
    """使用默认或注入的解析器验证单个公网 URL。"""
    return UrlPolicy(resolver=resolver).validate(url)


def _resolve_addresses(host: str) -> list[str]:
    """解析主机的所有地址，避免只校验 DNS 返回的首个地址。"""
    results = socket.getaddrinfo(host, 0, type=socket.SOCK_STREAM)
    return [str(item[4][0]) for item in results]
