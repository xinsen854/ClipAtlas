from dataclasses import dataclass
from urllib.parse import urlsplit

_COMPATIBLE_SUFFIX = "/compatible-mode/v1"
_NATIVE_SUFFIX = "/api/v1"


@dataclass(frozen=True, slots=True)
class BailianEndpoints:
    openai_compatible: str
    dashscope_api_root: str


def is_aliyun_bailian_url(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and bool(hostname)
        and (hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com"))
    )


def derive_bailian_endpoints(value: str) -> BailianEndpoints:
    raw = value.strip().rstrip("/")
    if not is_aliyun_bailian_url(raw):
        raise ValueError("Bailian Base URL must use an aliyuncs.com endpoint")

    parsed = urlsplit(raw)
    if parsed.query or parsed.fragment:
        raise ValueError("Bailian Base URL must not contain query or fragment")

    path = parsed.path.rstrip("/")
    if path.endswith(_COMPATIBLE_SUFFIX):
        prefix = path[: -len(_COMPATIBLE_SUFFIX)]
    elif path.endswith(_NATIVE_SUFFIX):
        prefix = path[: -len(_NATIVE_SUFFIX)]
    elif not path:
        prefix = ""
    else:
        raise ValueError(
            "Bailian Base URL must be a workspace root, /compatible-mode/v1, or /api/v1"
        )

    origin = f"{parsed.scheme}://{parsed.netloc}{prefix}"
    return BailianEndpoints(
        openai_compatible=f"{origin}{_COMPATIBLE_SUFFIX}",
        dashscope_api_root=f"{origin}{_NATIVE_SUFFIX}",
    )
