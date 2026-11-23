from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit

from .contracts import DataSourceDialect, DataSourceDraft, DataSourceSslMode


class UnsafeConnectionTarget(ValueError):
    pass


@dataclass(frozen=True)
class ConnectionPolicy:
    """Validate control-plane inputs before a driver or DNS resolver sees them."""

    allowed_hosts: frozenset[str] = frozenset()
    allow_sqlite: bool = True

    _SCHEMES = {
        DataSourceDialect.MYSQL: frozenset({"mysql", "mysql+pymysql"}),
        DataSourceDialect.POSTGRESQL: frozenset({"postgresql", "postgresql+psycopg", "postgres"}),
        DataSourceDialect.SQLITE: frozenset({"sqlite", "sqlite+pysqlite"}),
    }

    def validate(self, draft: DataSourceDraft) -> None:
        try:
            ssl_mode = DataSourceSslMode(draft.ssl_mode)
        except (TypeError, ValueError) as exc:
            raise UnsafeConnectionTarget("不支持的数据源 TLS 模式") from exc
        parsed = urlsplit(draft.connection_url)
        if parsed.scheme not in self._SCHEMES[draft.dialect]:
            raise UnsafeConnectionTarget("连接 URL 协议与所选数据库类型不匹配")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeConnectionTarget("URL 不得包含账号或密码，请使用独立字段")
        if parsed.query or parsed.fragment:
            raise UnsafeConnectionTarget("连接 URL 不接受 query/fragment 参数")
        if not 1 <= draft.query_timeout_seconds <= 120:
            raise UnsafeConnectionTarget("查询超时必须在 1 到 120 秒之间")
        if not 1 <= draft.max_rows <= 10_000:
            raise UnsafeConnectionTarget("最大行数必须在 1 到 10000 之间")
        if not draft.selected_database.strip():
            raise UnsafeConnectionTarget("必须选择数据库")
        if draft.dialect is DataSourceDialect.SQLITE:
            if not self.allow_sqlite:
                raise UnsafeConnectionTarget("当前环境禁止 SQLite 数据源")
            if ssl_mode is not DataSourceSslMode.DISABLE:
                raise UnsafeConnectionTarget("SQLite 仅支持 disable TLS 模式")
            return
        if not parsed.hostname:
            raise UnsafeConnectionTarget("连接 URL 必须包含主机名")
        host = parsed.hostname.lower().rstrip(".")
        if self.allowed_hosts and host not in self.allowed_hosts:
            raise UnsafeConnectionTarget("目标主机不在数据源 allowlist")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return
        if address.is_loopback and not draft.allow_private_network:
            raise UnsafeConnectionTarget("默认禁止回环地址；仅受控开发环境可显式开启")
        if address.is_link_local or address.is_multicast or address.is_unspecified:
            raise UnsafeConnectionTarget("禁止链路本地、多播或未指定地址")
        if address.is_private and not draft.allow_private_network:
            raise UnsafeConnectionTarget("私网数据源需要显式启用并经过管理员审核")
