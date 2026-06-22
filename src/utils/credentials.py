"""
環境変数から認証情報を設定ファイルに上書きするユーティリティ。
Cloud Run では GCP Secret Manager から環境変数として注入される。
"""
import os

_ENV_MAP = {
    ("api", "jquants", "api_key"): "JQUANTS_API_KEY",
    ("api", "jquants", "email"): "JQUANTS_EMAIL",
    ("api", "jquants", "password"): "JQUANTS_PASSWORD",
    ("api", "gemini", "api_key"): "GEMINI_API_KEY",
    ("api", "line", "channel_access_token"): "LINE_CHANNEL_ACCESS_TOKEN",
    ("api", "line", "user_id"): "LINE_USER_ID",
}


def override_credentials(cfg: dict) -> None:
    """環境変数が設定されていれば settings.yaml の認証情報を上書きする"""
    for keys, env_var in _ENV_MAP.items():
        val = os.environ.get(env_var)
        if val:
            node = cfg
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = val
