from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DATA_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
REQUEST_TIMEOUT = (5, 20)


def build_session() -> requests.Session:
    """Build an HTTP session that retries transient read-only requests."""
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update({"User-Agent": "bond-calendar-notify/1.1"})
    session.mount("https://", adapter)
    return session


def get_bond_calendar(session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Fetch the latest convertible-bond calendar from Eastmoney."""
    params = {
        "sortColumns": "PUBLIC_START_DATE,SECURITY_CODE",
        "sortTypes": "-1,-1",
        "pageSize": "50",
        "pageNumber": "1",
        "reportName": "RPT_BOND_CB_LIST",
        "columns": "ALL",
        "quoteType": "0",
        "source": "WEB",
        "client": "WEB",
    }
    client = session or build_session()
    response = client.get(DATA_URL, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("东方财富接口没有返回有效 JSON") from exc

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("东方财富接口响应缺少 result 字段")

    bonds = result.get("data")
    if not isinstance(bonds, list):
        raise RuntimeError("东方财富接口的 result.data 不是列表")

    print(f"已获取 {len(bonds)} 条可转债记录")
    return bonds


def get_today_date(now: datetime | None = None) -> str:
    """Return today's date in the Asia/Shanghai timezone."""
    current = now or datetime.now(BEIJING_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TIMEZONE)
    else:
        current = current.astimezone(BEIJING_TIMEZONE)
    return current.strftime("%Y-%m-%d")


def bonds_for_date(
    bonds: list[dict[str, Any]], field: str, target_date: str
) -> list[dict[str, Any]]:
    """Select bonds whose named date field matches ``target_date``."""
    selected = []
    for bond in bonds:
        value = bond.get(field)
        if value and str(value).split()[0] == target_date:
            selected.append(bond)
    return selected


def format_bond(bond: dict[str, Any]) -> str:
    return f"- {bond.get('SECURITY_NAME_ABBR', '-')}（{bond.get('SECURITY_CODE', '-')}）"


def build_daily_message(
    subscription_bonds: list[dict[str, Any]],
    result_bonds: list[dict[str, Any]],
) -> tuple[str, str] | None:
    """Build one non-duplicated Server Chan message for today's bond events."""
    sections: list[str] = []

    if subscription_bonds:
        subscription_lines = ["## 今日可申购新债"]
        subscription_lines.extend(format_bond(bond) for bond in subscription_bonds)
        subscription_lines.append("请在交易时间内通过券商 App 完成申购。")
        sections.append("\n".join(subscription_lines))

    if result_bonds:
        result_lines = ["## 今日公布中签结果"]
        result_lines.extend(format_bond(bond) for bond in result_bonds)
        result_lines.append("请打开券商 App 查询中签结果；如中签，请确保账户有足额认购资金。")
        sections.append("\n".join(result_lines))

    if not sections:
        return None

    return "📅 今日新债提醒", "\n\n".join(sections)


def send_to_wechat(
    title: str,
    content: str,
    *,
    server_key: str | None = None,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Send a Server Chan notification and fail on rejected responses."""
    key = server_key if server_key is not None else os.getenv("SERVERCHAN_API_KEY")
    if not key:
        raise RuntimeError("未设置 SERVERCHAN_API_KEY")

    client = session or build_session()
    response = client.post(
        f"https://sctapi.ftqq.com/{key}.send",
        data={"title": title, "desp": content},
        timeout=REQUEST_TIMEOUT,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError:
        # Do not include the request URL in the exception because it contains SendKey.
        raise RuntimeError(
            f"Server 酱 HTTP 请求失败（status={response.status_code}）"
        ) from None

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("Server 酱没有返回有效 JSON") from exc

    if not isinstance(result, dict):
        raise RuntimeError("Server 酱返回了无法识别的响应")

    result_code = result.get("code", result.get("errno"))
    if result_code is not None and str(result_code) != "0":
        message = result.get("message", result.get("errmsg", "未知错误"))
        raise RuntimeError(f"Server 酱推送失败：{message}（code={result_code}）")

    print("Server 酱推送成功")
    return result


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} 必须是 true 或 false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推送今日可申购及公布中签结果的新债")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只抓取并显示结果，不发送 Server 酱通知",
    )
    args = parser.parse_args(argv)

    today = get_today_date()
    bonds = get_bond_calendar()
    subscription_bonds = bonds_for_date(bonds, "PUBLIC_START_DATE", today)
    result_bonds = bonds_for_date(bonds, "BOND_START_DATE", today)
    message = build_daily_message(subscription_bonds, result_bonds)

    print(
        f"北京时间 {today}，找到 {len(subscription_bonds)} 只可申购新债，"
        f"{len(result_bonds)} 只公布中签结果的新债"
    )

    if args.dry_run:
        if message:
            print(message[0])
            print(message[1])
        else:
            print("今日无可申购或公布中签结果的新债")
        print("dry-run 完成，未发送微信通知")
        return 0

    if message:
        send_to_wechat(*message)
    elif env_flag("NOTIFY_WHEN_EMPTY"):
        send_to_wechat("📅 今日新债提醒", "今天没有可申购或公布中签结果的新债。")
    else:
        print("今日没有需要推送的新债事件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
